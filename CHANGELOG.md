# CHANGELOG — Human Counter

## v2.0 (2026-10-07) — pembangunan ulang sesuai audit Fase 0

**Backend baru** (FastAPI + uvicorn, menggantikan counter_server.py):
- Ingest worker per kamera (10 kamera) dengan reconnect eksponensial + jitter,
  frame-skip, deteksi bingkai beku (fraksi piksel bergerak) — memperbaiki K4/K6.
- Deteksi **server-side**: YOLOv8s + ByteTrack dari pustaka supervision
  (ID stabil) — memperbaiki K5. Ditemukan & diatasi: `model.track()`
  ultralytics 8.4.x tidak mengembalikan ID pada lingkungan ini → deteksi
  `model.predict()` + tracker supervision.
- Garis hitung virtual + arah (in/out) + histeresis + min bingkai + min
  perpindahan; event idempoten UNIQUE(camera, session, track, line, direction)
  — memperbaiki K3 & menghapus dedup bermasalah K1.
- SQLite WAL + skema berversi + UTC epoch; agregasi hari/jam Asia/Jakarta —
  memperbaiki K2 permanen.
- API `/api/v1`: summary, hourly, cameras (+status/health), events, export.csv,
  PUT lines, SSE live, proxy HLS langsung ke upstream terdaftar (P3, P8).
- Kunci inferensi global + `torch.set_num_threads(2)` (10 worker CPU).

**Frontend baru** (vanilla JS, tanpa CDN runtime — P5): dashboard ruang kendali
gelap: KPI lewatan (total/in/out/puncak/online/cakupan), grafik per jam WIB,
dinding 10 kamera live dengan kotak+garis+ID dari server, feed SSE, peringkat
kamera, editor garis di atas bingkai, ekspor CSV. Semua teks dinamis di-escape (P6).

**Tes**: 7/7 hijau (garis virtual: turun/naik/jitter/jejak-pendek/idempoten;
batas tengah malam WIB; sinkronisasi konversi). Benchmark model A/B: yolov8s
@1280 terbaik untuk malam (terpasang di human-detector).

**Diketahui terbuka (jujur)**: penyetelan akurasi Fase 3 (ground truth, MAPE/F1),
chaos/soak 24 jam, Lighthouse. Pada CPU: ~0,25–0,7 fps/kamera untuk 10 kamera
(imgsz 640); naikkan via env bila akurasi diprioritaskan.

## v1.0 (2026-10-06)
- Prototipe: deteksi COCO-SSD di peramban + SQLite + ekspor YOLO/COCO +
  kolektor otomatis + keputusan TypeSafe Jev (diikuti audit Fase 0).
