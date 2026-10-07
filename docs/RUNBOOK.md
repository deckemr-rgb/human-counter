# RUNBOOK — Human Counter v2

## Menjalankan

```bat
:: satu perintah (membuat venv + dependensi bila belum ada):
run_counter.bat
:: atau manual:
.venv\Scripts\python.exe server_main.py
:: dashboard: http://localhost:5103
```

- Daftar kamera: `cameras.json` (10 kamera Jakarta, URL HLS publik).
- Tidak bergantung pada gods-eye-view (P8 selesai). GEV tetap bisa jalan sebagai konsol opsional.

## Operasi harian

1. **Pilih kamera** — semua 10 aktif bawaan; matikan dengan `"enabled": false` di `cameras.json`.
2. **Garis hitung** — buka kartu kamera → **atur garis** → klik dua titik pada
   bingkai → simpan. Garis vertikal cocok untuk pejalan kaki yang bergerak
   kiri↔kanan; horizontal untuk gerak naik/bawah. Garis bisa diganti kapan saja
   (penghitungan baru berlaku setelah garis disimpan).
3. **Ekspor** — tombol CSV di header (per tanggal terpilih).

## Troubleshooting

| Gejala | Sebab umum | Tindakan |
|---|---|---|
| Semua kamera "offline" | hulu (balitower) tidak terjangkau / DNS | cek internet; worker pulih otomatis (backoff 3–60 dtk) |
| Status "frozen" | bingkai hulu beku (masalah hulu) | dianggap tidak sehat dalam cakupan; pulih otomatis saat gambar bergerak |
| fps kecil (<0,5) | 10 kamera × CPU | normal (~0,25–0,7 fps/kamera pada CPU laptop); turunkan kamera aktif atau naikkan `HUMAN_DETECTOR_IMGSZ` bila akurasi > cakupan |
| Lewatan 0 lama | posisi garis tidak dilalui orang | geser garis lewat editor ke jalur pejalan kaki |
| DB besar | retensi | event mentah >90 hari bisa dihapus: `DELETE FROM crossing_events WHERE ts_utc < strftime('%s','now','-90 days')` lalu `VACUUM` |

## Backup

Salin `counter.db` (WAL — aman disalin saat berjalan; untuk konsistensi penuh,
hentikan server dulu). `checkpoint WAL` otomatis oleh SQLite.

## Privasi & kepatuhan (ringkas)

Hanya agregat "lewatan" per garis; tanpa wajah/identitas/atribut; tanpa
penyimpanan bingkai. `track_id` lokal per sesi ingest, bukan identitas.
Penggunaan operasional di luar uji coba perlu dasar hukum & izin pemilik kamera
(UU PDP). Sumber kamera: portal publik Pemprov DKI Jakarta (atribusi tampil di
video hulu).
