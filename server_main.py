"""Human Counter v2 — FastAPI backend + SSE + statis + ingest 10 kamera.

Menjalankan: python server_main.py  (atau uvicorn server_main:app)
"""

import asyncio
import json
import queue
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config
from app.db import Database, load_cameras, wib_day_bounds_utc
from app.ingest import CameraWorker

BASE = Path(__file__).resolve().parent
STATIC_DIR = BASE / "static"

app = FastAPI(title="Human Counter", version="2.0")
db = Database(BASE / "counter.db")
session_id = uuid.uuid4().hex[:12]
workers: dict[str, CameraWorker] = {}

# ---------------- event bus (SSE) ----------------

_subscribers: set[queue.Queue] = set()
_bus_lock = threading.Lock()


class Bus:
    def publish(self, event: dict):
        with _bus_lock:
            for q in list(_subscribers):
                try:
                    q.put_nowait(event)
                except Exception:
                    pass


bus = Bus()


def start_workers():
    cameras = load_cameras(config.CAMERAS_FILE)
    for cam in cameras:
        if cam["id"] in workers:
            continue
        lines = db.execute(
            "SELECT id, name, p1x, p1y, p2x, p2y FROM count_lines WHERE camera_id = ?",
            (cam["id"],),
        ).fetchall()
        worker = CameraWorker(
            cam,
            [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "p1": [r["p1x"], r["p1y"]],
                    "p2": [r["p2x"], r["p2y"]],
                }
                for r in lines
            ],
            db,
            bus,
            session_id,
        )
        worker.start()
        workers[cam["id"]] = worker


# ---------------- models ----------------

class LineIn(BaseModel):
    name: str = Field(default="", max_length=60)
    p1: list[float] = Field(min_length=2, max_length=2)
    p2: list[float] = Field(min_length=2, max_length=2)


class LinesIn(BaseModel):
    lines: list[LineIn] = Field(max_length=6)


# ---------------- helpers ----------------

def camera_rows():
    return db.execute("SELECT * FROM cameras ORDER BY name").fetchall()


def sync_cameras_table():
    """Registry cameras.json → tabel cameras (idempoten)."""
    for cam in load_cameras(config.CAMERAS_FILE):
        db.execute(
            "INSERT OR IGNORE INTO cameras (id, name, city, lat, lon, url, enabled)"
            " VALUES (?,?,?,?,?,?,?)",
            (cam["id"], cam["name"], cam.get("city", ""), cam.get("lat"),
             cam.get("lon"), cam["url"], 1 if cam.get("enabled", True) else 0),
        )
    db.commit()


# ---------------- routes ----------------

@app.on_event("startup")
def _startup():
    sync_cameras_table()
    threading.Thread(target=start_workers, daemon=True, name="worker-starter").start()


@app.get("/api/health")
def health():
    return {"ok": True, "version": "2.0", "tz": config.TZ_LABEL,
            "workers": len(workers), "sessionId": session_id}


@app.get("/api/v1/cameras")
def cameras():
    rows = camera_rows()
    out = []
    for r in rows:
        w = workers.get(r["id"])
        lines = db.execute(
            "SELECT id, name, p1x, p1y, p2x, p2y FROM count_lines WHERE camera_id = ?",
            (r["id"],),
        ).fetchall()
        out.append({
            "id": r["id"], "name": r["name"], "city": r["city"],
            "enabled": bool(r["enabled"]),
            "status": w.status if w else "starting",
            "fps": round(w.fps, 2) if w else 0,
            "avgConf": round(w.avg_conf, 2) if w else 0,
            "inCount": w.in_count if w else 0,
            "outCount": w.out_count if w else 0,
            "boxes": w.latest_boxes if w else [],
            "lines": [dict(l) for l in lines],
            "streamUrl": f"/api/stream/{r['id']}",
            "lastError": w.last_error if w else "",
        })
    return {"cameras": out}


@app.get("/api/v1/summary")
def summary(date: str | None = Query(default=None)):
    date = date or datetime.now(config.WIB).strftime("%Y-%m-%d")
    start, end = wib_day_bounds_utc(date)
    row = db.execute(
        "SELECT COUNT(*) total,"
        " SUM(direction='in') masuk, SUM(direction='out') keluar"
        " FROM crossing_events WHERE ts_utc >= ? AND ts_utc < ?",
        (start, end),
    ).fetchone()
    peak = db.execute(
        "SELECT strftime('%H', ts_utc, 'unixepoch', '+7 hours') jam, COUNT(*) c"
        " FROM crossing_events WHERE ts_utc >= ? AND ts_utc < ?"
        " GROUP BY jam ORDER BY c DESC LIMIT 1",
        (start, end),
    ).fetchone()
    online = sum(1 for w in workers.values() if w.status in ("online", "capturing"))
    # cakupan: rasio sampel health 'online/frozen' hari ini
    samples = db.execute(
        "SELECT COUNT(*) c FROM camera_health WHERE minute_utc >= ? AND minute_utc < ?",
        (start, end),
    ).fetchone()["c"]
    good = db.execute(
        "SELECT COUNT(*) c FROM camera_health WHERE minute_utc >= ? AND minute_utc < ?"
        " AND status IN ('online','capturing')",
        (start, end),
    ).fetchone()["c"]
    return {
        "date": date,
        "total": row["total"] or 0,
        "in": row["masuk"] or 0,
        "out": row["keluar"] or 0,
        "peakHour": peak["jam"] if peak else None,
        "peakCount": peak["c"] if peak else 0,
        "camerasOnline": online,
        "camerasTotal": len(workers),
        "coveragePct": round(100 * good / samples, 1) if samples else None,
    }


@app.get("/api/v1/hourly")
def hourly(date: str | None = Query(default=None), camera: str | None = Query(default=None)):
    date = date or datetime.now(config.WIB).strftime("%Y-%m-%d")
    start, end = wib_day_bounds_utc(date)
    where, params = "ts_utc >= ? AND ts_utc < ?", [start, end]
    if camera:
        where += " AND camera_id = ?"
        params.append(camera)
    rows = db.execute(
        f"SELECT strftime('%H', ts_utc, 'unixepoch', '+7 hours') jam,"
        f" SUM(direction='in') masuk, SUM(direction='out') keluar, COUNT(*) total"
        f" FROM crossing_events WHERE {where} GROUP BY jam ORDER BY jam",
        params,
    ).fetchall()
    return {"date": date, "hours": [dict(r) for r in rows]}


@app.get("/api/v1/events")
def events(limit: int = Query(default=40, le=200), camera: str | None = None):
    limit = min(limit, 200)
    if camera:
        rows = db.execute(
            "SELECT e.*, c.name AS camera_name FROM crossing_events e"
            " LEFT JOIN cameras c ON c.id = e.camera_id"
            " WHERE e.camera_id = ? ORDER BY e.ts_utc DESC, e.id DESC LIMIT ?",
            (camera, limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT e.*, c.name AS camera_name FROM crossing_events e"
            " LEFT JOIN cameras c ON c.id = e.camera_id"
            " ORDER BY e.ts_utc DESC, e.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"events": [dict(r) for r in rows]}


@app.get("/api/v1/export.csv")
def export_csv(from_d: str = Query(alias="from"), to: str | None = None, camera: str | None = None):
    start, end = wib_day_bounds_utc(to or from_d)
    end2 = wib_day_bounds_utc(to)[1] if to else end
    params: list = [start, end2]
    where = "ts_utc >= ? AND ts_utc < ?"
    if camera:
        where += " AND camera_id = ?"
        params.append(camera)
    rows = db.execute(
        f"SELECT * FROM crossing_events WHERE {where} ORDER BY ts_utc", params
    ).fetchall()
    lines = ["wib_time,camera,line_id,direction,track_id,conf"]
    for r in rows:
        wib = datetime.fromtimestamp(r["ts_utc"], config.WIB).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"{wib},{r['camera_id']},{r['line_id']},{r['direction']},{r['track_id']},{r['conf'] or ''}")
    body = ("\n".join(lines) + "\n").encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="lewatan-{from_d}.csv"'},
    )


@app.put("/api/v1/cameras/{camera_id}/lines")
def put_lines(camera_id: str, body: LinesIn):
    if camera_id not in workers:
        raise HTTPException(404, "kamera tidak ditemukan")
    for line in body.lines:
        for v in (*line.p1, *line.p2):
            if not 0 <= v <= 1:
                raise HTTPException(400, "koordinat harus fraksi 0..1")
    with db._lock:
        db.execute("DELETE FROM count_lines WHERE camera_id = ?", (camera_id,))
        for line in body.lines:
            db.execute(
                "INSERT INTO count_lines (camera_id, name, p1x, p1y, p2x, p2y)"
                " VALUES (?,?,?,?,?,?)",
                (camera_id, line.name, line.p1[0], line.p1[1], line.p2[0], line.p2[1]),
            )
        db.commit()
        rows = db.execute(
            "SELECT id, name, p1x, p1y, p2x, p2y FROM count_lines WHERE camera_id = ?",
            (camera_id,),
        ).fetchall()
    workers[camera_id].reload_lines([dict(r) for r in rows])
    bus.publish({"type": "lines-updated", "cameraId": camera_id})
    return {"ok": True, "lines": [dict(r) for r in rows]}


@app.get("/api/v1/annotated/{camera_id}")
def annotated(camera_id: str):
    """JPEG teranotasi terakhir (kotak + garis + banner) — digambar server,
    dijamin menampilkan deteksi tanpa bergantung pemutaran video."""
    w = workers.get(camera_id)
    if w is None or not w.last_annotated:
        raise HTTPException(404, "belum ada bingkai teranotasi")
    return StreamingResponse(
        iter([w.last_annotated]),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/v1/live")
async def live():
    q: queue.Queue = queue.Queue()
    with _bus_lock:
        _subscribers.add(q)
    async def stream():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    event = q.get_nowait()
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    await asyncio.sleep(2)
                    continue
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            with _bus_lock:
                _subscribers.discard(q)
    return StreamingResponse(stream(), media_type="text/event-stream")


# ---------------- proxy HLS langsung ke upstream terdaftar (P8) ----------------
#
# Alasan arsitektur (docs/ARCHITECTURE.md): proxy v1 meneruskan playlist GEV
# yang kadang kembali sebagai master lagi (upstream flaky) sehingga hls.js
# gagal parse. v2 menyelesaikan rantai playlist DI SERVER ini: master dari
# URL registri → tiap URI dijadikan absolut → dilayani lewat /api/upstream
# dengan allowlist host dari registry (anti-SSRF).

import urllib.parse  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402

_upstream_hosts: set[str] = set()


def refresh_upstream_hosts():
    for cam in load_cameras(config.CAMERAS_FILE):
        try:
            _upstream_hosts.add(urlsplit(cam["url"]).netloc)
        except Exception:
            pass


refresh_upstream_hosts()


def _fetch_upstream(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "human-counter/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", "application/octet-stream")


def _rewrite_playlist(body: bytes, base_url: str) -> bytes:
    """Ubah setiap URI di playlist menjadi /api/upstream?u=<absolut>.

    Hanya host yang ada di allowlist registry yang diteruskan (anti-SSRF).
    """
    out = []
    for raw in body.decode("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            out.append(raw)
            continue
        absolute = urllib.parse.urljoin(base_url, line)
        if urlsplit(absolute).netloc not in _upstream_hosts:
            out.append(raw)
            continue
        out.append("/api/upstream?u=" + urllib.parse.quote(absolute, safe=""))
    return ("\n".join(out) + "\n").encode("utf-8")


@app.get("/api/stream/{camera_id}")
def stream_v2(camera_id: str):
    cam = next((c for c in load_cameras(config.CAMERAS_FILE) if c["id"] == camera_id), None)
    if not cam:
        raise HTTPException(404, "kamera tidak ditemukan")
    try:
        body, content_type = _fetch_upstream(cam["url"])
    except Exception as exc:
        raise HTTPException(502, f"upstream gagal: {str(exc)[:120]}")
    if "mpegurl" in content_type:
        body = _rewrite_playlist(body, cam["url"])
    return StreamingResponse(
        iter([body]),
        media_type=content_type,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/upstream")
def upstream(u: str = Query(...)):
    if urlsplit(u).netloc not in _upstream_hosts:
        raise HTTPException(403, "host tidak diizinkan")
    try:
        body, content_type = _fetch_upstream(u)
    except Exception as exc:
        raise HTTPException(502, f"upstream gagal: {str(exc)[:120]}")
    if "mpegurl" in content_type:
        body = _rewrite_playlist(body, u)
    return StreamingResponse(
        iter([body]),
        media_type=content_type,
        headers={"Cache-Control": "no-store"},
    )


# ---------------- statis ----------------

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")
