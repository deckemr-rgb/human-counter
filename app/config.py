"""Konfigurasi & konstanta Human Counter v2.

Zona waktu bisnis: Asia/Jakarta (WIB, UTC+7, tanpa DST). Semua waktu di DB
disimpan sebagai UTC epoch integer; agregasi hari/jam dikonversi ke WIB.
"""

from datetime import timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "counter.db"
CAMERAS_FILE = BASE_DIR / "cameras.json"

HOST = os_host = "127.0.0.1"
PORT = 5103
GEV_BASE = __import__("os").environ.get("GEV_BASE", "http://localhost:4173").rstrip("/")

WIB = timezone(timedelta(hours=7))
TZ_LABEL = "Asia/Jakarta"

# Ingest
TARGET_FPS = 2.5            # deteksi per detik per kamera (frame-skip)
FRAME_STALE_S = 3.0         # bingkai lebih tua dari ini dianggap basi
FROZEN_DIFF_EPS = 2.0       # selisih rata-rata piksel < ini = bingkai beku
FROZEN_MIN_FRAMES = 8       # bingkai beku beruntun sebelum status FROZEN
RECONNECT_MIN_S = 3.0
RECONNECT_MAX_S = 60.0

# Deteksi
MODEL_NAME = os_host_env = __import__("os").environ.get("HUMAN_DETECTOR_MODEL", "yolov8s.pt")
# 640 = realistis untuk 10 kamera di CPU (lihat AUDIT/ACCURACY);
# naikkan ke 960-1280 via env bila akurasi lebih penting daripada cakupan.
IMGSZ = int(__import__("os").environ.get("HUMAN_DETECTOR_IMGSZ", "640"))
CONF = float(__import__("os").environ.get("HUMAN_DETECTOR_CONF", "0.3"))
NMS_IOU = float(__import__("os").environ.get("HUMAN_DETECTOR_IOU", "0.6"))

# Penghitungan
MIN_TRACK_FRAMES = 3        # jejak sah minimal N deteksi (spec: ≥5 pada 5fps; di ~1fps 3 cukup)
MIN_DISPLACEMENT = 0.08    # fraksi, perpindahan minimum antar sisi
HYSTERESIS = 0.08           # jarak minimum dari garis (fraksi) sebelum sisi dikunci
DIRECTION_IN = "in"         # semantik: menyilang ke sisi +1 dari vektor garis
DIRECTION_OUT = "out"

RETENTION_DAYS = 90
