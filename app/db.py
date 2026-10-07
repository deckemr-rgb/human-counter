"""SQLite WAL: skema berversi + helper waktu WIB.

Semua timestamp disimpan UTC epoch integer. Agregasi hari/jam dilakukan di
Asia/Jakarta lewat helper di modul ini (temuan K2: pencampuran UTC/lokal
membuat 00:00-07:00 WIB salah hitung).
"""

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

WIB = config.WIB

SCHEMA_VERSION = 1

_MIGRATIONS = {
    1: """
    CREATE TABLE IF NOT EXISTS cameras (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      city TEXT DEFAULT '',
      lat REAL, lon REAL,
      url TEXT NOT NULL,
      enabled INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS count_lines (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      camera_id TEXT NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
      name TEXT DEFAULT '',
      p1x REAL NOT NULL, p1y REAL NOT NULL,
      p2x REAL NOT NULL, p2y REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS crossing_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts_utc INTEGER NOT NULL,
      camera_id TEXT NOT NULL,
      line_id INTEGER NOT NULL,
      direction TEXT NOT NULL,
      track_id INTEGER NOT NULL,
      session_id TEXT NOT NULL,
      conf REAL,
      UNIQUE(camera_id, session_id, track_id, line_id, direction)
    );
    CREATE INDEX IF NOT EXISTS idx_events_ts ON crossing_events(ts_utc);
    CREATE INDEX IF NOT EXISTS idx_events_cam_ts ON crossing_events(camera_id, ts_utc);
    CREATE TABLE IF NOT EXISTS hourly_rollup (
      camera_id TEXT NOT NULL,
      hour_utc INTEGER NOT NULL,
      in_count INTEGER DEFAULT 0,
      out_count INTEGER DEFAULT 0,
      PRIMARY KEY (camera_id, hour_utc)
    );
    CREATE TABLE IF NOT EXISTS camera_health (
      camera_id TEXT NOT NULL,
      minute_utc INTEGER NOT NULL,
      status TEXT NOT NULL,
      fps REAL,
      avg_conf REAL,
      PRIMARY KEY (camera_id, minute_utc)
    );
    CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
    """,
}


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.migrate()

    def migrate(self):
        with self._lock:
            self.conn.executescript(_MIGRATIONS[SCHEMA_VERSION])
            row = self.conn.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
            current = row["version"] if row else 0
            if current < SCHEMA_VERSION:
                self.conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)"
                    if not row
                    else "UPDATE schema_version SET version = ?",
                    (SCHEMA_VERSION,),
                )
            self.conn.commit()

    # -- helper -----------------------------------------------------------

    def execute(self, sql, params=()):
        with self._lock:
            return self.conn.execute(sql, params)

    def commit(self):
        with self._lock:
            self.conn.commit()


def wib_day_bounds_utc(date_str):
    """Batas [mulai, selesai) satu hari WIB (YYYY-MM-DD) sebagai UTC epoch int."""
    y, m, d = (int(x) for x in date_str.split("-"))
    start = datetime(y, m, d, tzinfo=WIB)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def date_str_wib(ts_utc):
    """Tanggal WIB (YYYY-MM-DD) dari epoch UTC."""
    return datetime.fromtimestamp(ts_utc, WIB).strftime("%Y-%m-%d")


def load_cameras(path: Path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [c for c in data.get("cameras", []) if c.get("enabled", True)]
