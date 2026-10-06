# ARCHITECTURE — Human Counter v2 (target Fase 1-2)

Status: desain target untuk pembangunan ulang (Fase 1-2). Keputusan boleh
berubah hanya dengan alasan tertulis di dokumen ini.

## Gambar besar

```
[Sumber HLS publik ×10]  ──>  [Ingest worker per kamera]  ──>  [Detektor + ByteTrack]
        (cameras.json)              │ reconnect eksponensial        │ kelas person saja
                                    │ frame-skip → ~5-8 fps          │ garis virtual + arah
                                    │ health: online/stale/          │ event idempoten
                                    │ frozen/offline                 v
                            [Health & telemetri] ──────────> [SQLite WAL: events + rollup
                                                              jam/hari + camera_health]
                                                                      │
                                              [FastAPI :5103 /api/v1 + SSE] <┘
                                                                      │
                                              [Frontend SPA (Vite+React+TS)] ← statis dari FastAPI
```

## Keputusan & alasan

1. **Deteksi pindah ke server (Python), bukan peramban.** Alasan: penghitungan
   harian harus 24/7 (K4) dan COCO-SSD lite kehilangan orang kecil/jauh/malam
   (K5). YOLOv8s + ByteTrack (`model.track(persist=True)`) memberi ID jejak
   stabil — bahan dasar garis virtual. Biaya: proses inferensi terpisah dari API.
2. **Satu proses ingest per kamera** dengan buffer 1-bingkai (buang basi) agar
   latensi tidak menumpuk; reconnect eksponensial + jitter; hulu dihormati
   (maks. koneksi bersamaan terbatas).
3. **SQLite WAL** cukup untuk 10 kamera MVP; skema dan query ditulis agar
   migrasi ke Postgres tidak mengubah API. Retensi event mentah 90 hari;
   rollup jam/hari disimpan lama.
4. **Waktu: UTC epoch int** di DB; semua agregasi hari/jam dihitung Asia/Jakarta
   melalui satu fungsi (`wib_boundaries`) dengan tes batas tengah malam.
5. **Garis hitung per kamera** disimpan di DB + `cameras.json`; editor garis di
   dashboard dengan pratinjau bingkai. Event sah: jejak ≥5 bingkai, bottom-center
   bbox memotong garis dengan histeresis + perpindahan minimum, idempoten
   UNIQUE(camera, session, track, line, direction).
6. **Label jujur: "Lewatan"** — tanpa klaim orang unik (privasi, lihat AUDIT §9).
7. **API `/api/v1`** + SSE untuk feed live; validasi pydantic; bind 127.0.0.1 default.
8. **Frontend**: Vite + React + TypeScript + Tailwind + ECharts; hls.js terbundel
   (tanpa CDN runtime — P5); semua teks dinamis di-escape (P6).

## Skema (v1)

- `cameras(id PK, name, city, lat, lon, url, enabled)`
- `count_lines(id PK, camera_id FK, name, p1x, p1y, p2x, p2y, direction_axis)`
- `crossing_events(id PK, ts_utc INT, camera_id, line_id, direction, track_id,
   session_id, conf, UNIQUE(camera_id, session_id, track_id, line_id, direction))`
- `hourly_rollup(camera_id, hour_utc, in_count, out_count, PRIMARY KEY(camera_id, hour_utc))`
- `camera_health(camera_id, ts_utc, status, fps, avg_conf)`

## Di luar lingkup v2 awal

Re-identifikasi lintas kamera, fine-tuning model (dipertimbangkan setelah data
labeler cukup), multi-node.
