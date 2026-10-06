# AUDIT — human-counter (Fase 0, 2026-10-07)

Status: **Fase 0 selesai.** Semua temuan diverifikasi: [TERBUKTI-JALAN] = dibuktikan
dengan tes yang dijalankan (lihat `tests/test_audit_fase0.py`); [DARI-BACAAN] =
dari pemeriksaan kode, akan dibuktikan dengan tes yang gagal di fase berikutnya.

## Kritis — merusak keakuratan hitungan

| Tag | Status | Bukti |
|---|---|---|
| **K1** Dedup lapis-2 menggabungkan ORANG BERBEDA (IoU bbox ≥ 0,5 dalam 10 menit) → undercount sistematis di titik piksel ramai | **TERBUKTI (MERAH)** | `pytest tests/test_audit_fase0.py::TestK1` → "1 is not None : BUG K1 TERBUKTI" — dua orang berbeda (bbox [100,100,200,400] vs [105,105,205,405], 2 menit) digabung jadi satu |
| **K2** "Hari ini" salah pada 00:00–07:00 WIB | **TERVERIFIKASI FIX** (hijau) | `pytest ...::TestK2` PASSED setelah refactor `today_boundary_utc_iso()` — batas tengah malam WIB diekstrak dari fix 2026-10-07 |
| **K3** Semantik "melewati" salah: mencatat saat pertama muncul, bukan saat melintasi garis virtual; tanpa arah masuk/keluar, tanpa ROI/zona abaikan, tanpa filter jitter | DARI-BACAAN | `counter_server.py` hanya menerima bbox dari klien; tak ada konsep garis/arah |
| **K4** Deteksi hanya berjalan saat tab browser terbuka; tidak ada penghitungan 24/7 | DARI-BACAAN | `static/tracker.js` berjalan dalam `setInterval` halaman |
| **K5** Model & pelacak lemah: COCO-SSD lite + IoU greedy tanpa prediksi gerak; JEDA_HIDUP 4 dtk → fragmentasi → overcount; oklusi >4 dtk → ganda | DARI-BACAAN | `tracker.js` |
| **K6** Tidak ada deteksi stream beku/hitam/basi | DARI-BACAAN | tidak ada perbandingan antar-bingkai di ingest |

## Penting — keandalan & kebenaran data

| Tag | Status | Bukti |
|---|---|---|
| **P1** `detector_server.py`: generator `stream=True` diiterasi DI LUAR `_infer_lock` → inferensi berjalan tanpa lock pada ThreadingHTTPServer (race) | **TERBUKTI (kode)** | baris 83-84 `with _infer_lock: results = model(...)` lalu baris 94 `for result in results:` di luar blok |
| **P2** Heartbeat menaikkan `frames` pada event yang sudah digabung (event_key tak ada) → no-op diam-diam | DARI-BACAAN | `counter_server.py` UPDATE by event_key tanpa cek hasil |
| **P3** Proxy HLS: body dibaca penuh ke memori; HTTPError hulu dipukul rata jadi 502; tanpa deteksi hulu mati | DARI-BACAAN | rute `/api/stream/*`, `/api/media/*` |
| **P4** Satu koneksi SQLite global + RLock, tanpa WAL, tanpa migrasi/retensi/rollup | DARI-BACAAN | `counter_server.py` awal |
| **P5** Dependensi runtime dari CDN tanpa pin patch/SRI | DARI-BACAAN | `static/index.html` |
| **P6** `camera.name` dimasukkan ke `innerHTML` tanpa escape (XSS dari hulu) | DARI-BACAAN | `static/app.js::buildGrid` |
| **P7** Tanpa tes counter, tanpa requirements.txt, tanpa health per-kamera, tanpa rate-limit/validasi input | DARI-BACAAN | — (sebagian tertutup: `tests/` + `pytest` kini ada untuk audit) |
| **P8** Counter bergantung wajib pada GEV :4173 padahal daftar URL HLS sudah ada lokal | DARI-BACAAN | `counter_server.py::list_cameras` |

## Rencana perbaikan (peta fase)

- **Fase 1** — backend baru: FastAPI + uvicorn, ingest worker per kamera (10 kamera,
  reconnect+backoff, deteksi beku/hitam), SQLite WAL + skema berversi, UTC epoch +
  agregasi WIB, `/api/v1` + SSE. Memperbaiki K2 permanen, P1-P8.
- **Fase 2** — mesin hitung: YOLOv8s + ByteTrack server-side (perbaiki K4/K5),
  garis virtual + arah + histeresis (perbaiki K3), hapus dedup lapis-2 bermasalah
  (perbaiki K1 — pengganti: idempotensi via (camera, session, track, line, direction)),
  deteksi stream beku (K6). 10 kamera.
- **Fase 3** — evaluasi & penyetelan (ground truth, MAPE/F1, laporan akurasi jujur).
- **Fase 4** — frontend baru (Vite+React+TS, tanpa CDN runtime, XSS-aman).
- **Fase 5** — ketahanan, chaos/soak, CI, dokumentasi, satu perintah jalan.

## Keputusan awal (akan dikonfirmasi sebelum Fase 1)

- 10 kamera pilot dipilih dari pengukuran YOLOv8s nyata (terbanyak orang) —
  lihat `cameras.json`. Garis hitung tiap kamera dikosongkan; akan diatur lewat
  editor garis di dashboard (Fase 2) dengan pratinjau bingkai, karena posisi garis
  adalah keputusan per-kamera yang butuh mata manusia.
- Backend counter baru **tidak lagi bergantung wajib pada GEV** (P8): daftar kamera
  dari `cameras.json` (URL HLS langsung). GEV tetap jalan sebagai konsol opsinya.
