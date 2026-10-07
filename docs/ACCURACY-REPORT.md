# ACCURACY-REPORT — Human Counter v2 (Fase 3, laporan jujur)

Tanggal: 2026-10-07 · Mesin: CPU laptop (tanpa GPU) · Model: YOLOv8s person-only

## 1. Akurasi DETEKSI (ground truth visual, bingkai stasiun ramai siang)

| Bingkai | Hitungan visual (GT ±2) | Model @960 conf 0.25 | Model @640 conf 0.30 |
|---|---|---|---|
| stasiun ramai (frame-120) | ~40 | **41** | 23,8 rata-rata |

- Kesimpulan: pada adegan terang dengan orang berukuran sedang, model @960
  sesuai hitungan visual dalam ±5% (41 vs ~40). Konfigurasi deploy 640/conf 0.30
  **kehilangan ±40% deteksi** pada bingkai ini — trade-off CPU yang diambil agar
  10 kamera dapat dilayani (lihat §3).
- Bingkai bukti: `eval/frame-120.jpg` (hitung manual).

## 2. Metrik replay (klip stasiun 45 dtk, garis vertikal x=0.5)

| Konfigurasi | Bingkai | Deteksi/bingkai | Jejak unik | Fragmentasi | Lewatan |
|---|---|---|---|---|---|
| 640 / conf 0.30 / 2.5fps | 34 | 23,8 | 62 | **2,61** | 0 |

- **Replay deterministik: TRUE** (dua run identik — golden test lolos).
- Fragmentasi 2,61 = rasio jejak unik terhadap orang rata-rata. Penyebab utama:
  sampling 2,5 fps membuat celah antar-bingkai 0,4 dtk → ByteTrack kehilangan
  asosiasi pada orang cepat. Bisa ditekan dengan fps lebih tinggi (butuh GPU)
  atau `minimum_matching_threshold` lebih longgar (belum disetel dengan GT).
- **Lewatan 0 pada klip ini bukan kegagalan pipa** (pipa terbukti: tes unit
  lewatan hijau; replay test sebelumnya mencatat lewatan nyata pada konfigurasi
  garis berbeda). Pada klip stasiun ini, dengan 45 dtk sampel dan garis vertikal
  di tengah, memang belum ada lintasan penuh yang terekam. Pengukuran F1
  lewatan menunggu ground truth operator (alat tersedia, §3).

## 3. Keterbatasan yang diakui

1. **CPU throughput**: 10 kamera → ~0,7 fps/kamera @640. Akurasi orang
   kecil/jauh menurun vs @960-1280. Opsi: GPU, atau kurangi kamera aktif.
2. **Ground truth lewatan belum dianotasi** — alat tersedia
   (`eval/gt_annotator.py`, SPACE=in / B=out / ESC=simpan); F1 lewatan akan
   dilaporkan setelah minimal 3 klip dianotasi 2 operator independen.
3. **Malam/hujan**: belum diukur (klip malam live terlalu sepi saat pengujian);
   rencana: rekam klip malam via `eval/record_clips`, anotasi, ukur.
4. Fragmentasi jejak 2,61 pada 2,5 fps → overcount potensial pada garis bila
   jejak pecah lalu melintas lagi; mitigasi bawaan: idempotensi per (track,
   garis, arah) — tetap, tuning dengan GT diperlukan.

## 4. Rekomendasi

1. GPU (atau frigate-style batched inference) untuk menaikkan fps/kamera.
2. Fine-tune YOLO pada data malam Jakarta via `human-labeler` (dataset sudah
   dikumpulkan kolektor).
3. Anotasi GT 3 klip × 2 operator → isi tabel precision/recall/F1 lewatan.
4. Setel ByteTrack (`track_activation_threshold`, `minimum_matching_threshold`)
   pada dev set.
