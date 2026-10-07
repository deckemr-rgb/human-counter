"""Ingest worker per kamera: capture tangguh + YOLOv8+ByteTrack + hitung garis.

Satu thread per kamera, satu instance model per kamera (ByteTrack butuh
state persist per kamera). API tidak pernah diblok inferensi: worker hanya
menulis hasil ke memori bersama (latest boxes + health) dan DB.
"""

import math
import threading
import time
from datetime import datetime, timezone

import cv2
import supervision as sv

from . import config, counting

import torch  # noqa: E402  — batasi thread agar 10 worker tidak saling menjatuhkan
torch.set_num_threads(2)

# Inferensi diserialisasi lintas worker: 10 YOLO CPU paralel saling
# menjatuhkan (oversubscription, ~100 dtk per kamera). Dengan satu kunci,
# tiap kamera mendapat giliran ~3 dtk. State ByteTrack tetap per kamera
# karena tiap worker punya instance modelnya sendiri.
INFER_LOCK = threading.Lock()
from .counting import LineSpec, Track


class CameraWorker(threading.Thread):
    def __init__(self, camera, lines, db, bus, session_id):
        super().__init__(daemon=True, name=f"ingest-{camera['id'][:24]}")
        self.camera = camera
        self.camera_id = camera["id"]
        self.lines = [
            LineSpec(l["id"], l.get("name", ""), tuple(l["p1"]), tuple(l["p2"]))
            for l in lines
        ]
        self.db = db
        self.bus = bus
        self.session_id = session_id
        self.stop_event = threading.Event()
        # state untuk API (dibaca tanpa lock — nilai atomik sederhana)
        self.status = "connecting"
        self.fps = 0.0
        self.avg_conf = 0.0
        self.in_count = 0
        self.out_count = 0
        self.latest_boxes = []  # [(track_id, [x,y,w,h], conf)]
        self.last_annotated = None  # JPEG bytes teranotasi (untuk dashboard)
        self.last_error = ""

    def _set_status(self, status):
        if self.status != status:
            self.status = status
            self.bus.publish({"type": "camera-status", "cameraId": self.camera_id, "status": status})

    def run(self):
        from ultralytics import YOLO

        model = YOLO(config.MODEL_NAME)
        # ByteTrack dari pustaka supervision: ID stabil & bebas dari
        # keanehan model.track() ultralytics (K5).
        tracker = sv.ByteTrack(track_activation_threshold=0.25)
        backoff = config.RECONNECT_MIN_S
        last_frames = []
        frozen_run = 0
        while not self.stop_event.is_set():
            started = time.time()
            try:
                cap = cv2.VideoCapture(self.camera["url"], cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    raise RuntimeError("cannot open stream")
                backoff = config.RECONNECT_MIN_S
                self._set_status("online")
                track_map = {}  # track_id(int) -> Track
                last_grab = 0.0
                while not self.stop_event.is_set():
                    # frame-skip: tangkap terus, proses bila saatnya tiba
                    ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError("read failed")
                    now = time.time()
                    if now - last_grab < 1.0 / config.TARGET_FPS:
                        continue
                    last_grab = now
                    if frame is None or frame.size == 0:
                        continue
                    # deteksi bingkai beku: rata-rata selisih piksel (grayscale kecil)
                    small = cv2.cvtColor(cv2.resize(frame, (96, 54)), cv2.COLOR_BGR2GRAY)
                    last_frames.append(small)
                    if len(last_frames) > 2:
                        last_frames.pop(0)
                    if len(last_frames) == 2:
                        diff = cv2.absdiff(last_frames[0], last_frames[1])
                        changed = float((diff > 25).mean())  # fraksi piksel berubah
                        if changed < 0.005:  # <0,5% piksel bergerak = beku
                            frozen_run += 1
                        else:
                            frozen_run = 0
                        if frozen_run >= 5:
                            self._set_status("frozen")
                        elif frozen_run == 0 and self.status == "frozen":
                            self._set_status("online")
                    # deteksi + ByteTrack
                    infer_t0 = time.time()
                    with INFER_LOCK:
                        result = model.predict(
                            frame, verbose=False,
                            imgsz=config.IMGSZ, conf=config.CONF, iou=config.NMS_IOU,
                            classes=[0],  # person saja
                        )[0]
                    self.fps = 1.0 / max(0.001, time.time() - infer_t0)
                    frame_h, frame_w = frame.shape[:2]
                    detections_sv = sv.Detections.from_ultralytics(result)
                    tracked = tracker.update_with_detections(detections_sv)
                    boxes = []
                    detections = []
                    if tracked.xyxy.shape[0]:
                        track_ids = (
                            tracked.tracker_id
                            if tracked.tracker_id is not None
                            else [-1] * tracked.xyxy.shape[0]
                        )
                        for box, tid, conf in zip(
                            tracked.xyxy.tolist(), track_ids, tracked.confidence.tolist(),
                        ):
                            boxes.append((int(tid), [round(v, 1) for v in box], round(float(conf), 3)))
                            detections.append((int(tid), box, float(conf)))
                    self.latest_boxes = boxes
                    if detections:
                        confs = [d[2] for d in detections]
                        self.avg_conf = sum(confs) / len(confs)
                    # hitung garis
                    lines_now = self.lines
                    if lines_now:
                        for tid, box, conf in detections:
                            track = track_map.get(tid)
                            if track is None:
                                track = Track(tid)
                                track_map[tid] = track
                            x1, y1, x2, y2 = box
                            point = ((x1 + x2) / 2 / frame_w, (y1 + y2) / frame_h)  # bottom-center, fraksi
                            track.max_conf = max(track.max_conf, conf)
                            crossings = counting.update_track_side(
                                track, point, lines_now,
                                config.HYSTERESIS, config.MIN_DISPLACEMENT,
                                config.MIN_TRACK_FRAMES,
                            )
                    for line_id, _name, direction in crossings:
                        self._register_crossing(line_id, direction, tid, conf)
                        self.in_count += direction == "in"
                        self.out_count += direction == "out"
                    # JPEG teranotasi untuk dashboard: kotak + ID + garis
                    # hitung + banner — digambar di SERVER sehingga kotak dan
                    # garis SELALU terlihat di dashboard tanpa bergantung pada
                    # pemutaran video peramban (yang rentan hulu flaky).
                    self.last_annotated = self._make_annotated_jpeg(frame, boxes)
                    self._set_status("online")
            except Exception as exc:
                self.last_error = str(exc)[:120]
                self._set_status("offline")
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, config.RECONNECT_MAX_S)
            finally:
                try:
                    cap.release()
                except Exception:
                    pass
            self.stop_event.wait(max(0.0, config.RECONNECT_MIN_S - (time.time() - started)))

    def _make_annotated_jpeg(self, frame, boxes):
        """Gambar kotak + ID + garis hitung + banner pada salinan bingkai,
        kembalikan JPEG bytes (untuk endpoint /api/v1/annotated)."""
        annotated = frame.copy()
        frame_h, frame_w = annotated.shape[:2]
        # garis hitung (kuning)
        for line in self.lines:
            p1 = (int(line.p1[0] * frame_w), int(line.p1[1] * frame_h))
            p2 = (int(line.p2[0] * frame_w), int(line.p2[1] * frame_h))
            cv2.line(annotated, p1, p2, (0, 209, 255), 2)
        # kotak + label
        for tid, box, conf in boxes:
            x1, y1, x2, y2 = (int(v) for v in box)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 229, 255), 2)
            label = f"#{tid} {int(conf * 100)}%"
            cv2.putText(annotated, label, (x1 + 2, max(12, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 229, 255), 1)
        # banner jumlah orang
        cv2.rectangle(annotated, (0, 0), (230, 34), (37, 99, 235), -1)
        cv2.putText(annotated, f"Persons: {len(boxes)}", (8, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        small = cv2.resize(annotated, (640, int(640 * frame_h / max(frame_w, 1))))
        ok, encoded = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return encoded.tobytes() if ok else None

    def _register_crossing(self, line_id, direction, track_id, conf):
        line = next((l for l in self.lines if l.line_id == line_id), None)
        name = line.name if line else f"garis-{line_id}"
        ts = int(time.time())
        try:
            self.db.execute(
                "INSERT OR IGNORE INTO crossing_events"
                " (ts_utc, camera_id, line_id, direction, track_id, session_id, conf)"
                " VALUES (?,?,?,?,?,?,?)",
                (ts, self.camera_id, line_id, direction, track_id, self.session_id, conf),
            )
            self.db.commit()
            self.bus.publish({
                "type": "crossing",
                "cameraId": self.camera_id,
                "cameraName": self.camera["name"],
                "direction": direction,
                "line": name,
                "ts": ts,
            })
        except Exception:
            pass

    def reload_lines(self, lines):
        self.lines = [
            LineSpec(l["id"], l.get("name", ""), tuple(l["p1"]), tuple(l["p2"]))
            for l in lines
        ]
