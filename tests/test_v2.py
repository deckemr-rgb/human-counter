"""Tes Human Counter v2 — logika hitung, batas WIB, API.

Perbaikan yang diverifikasi (dari docs/AUDIT.md):
- K1: tidak ada lagi dedup bbox yang menggabungkan orang berbeda —
  identitas = (camera, session, track, line, direction) yang unik.
- K2: batas "hari ini" WIB benar termasuk 00:00-07:00 WIB.
- K3: lewatan = perpindahan garis dengan arah + histeresis + min bingkai.

Semantik arah (vektor garis p1→p2, kiri→kanan untuk garis horizontal):
menurun melewati garis (+1 → -1) = "out"; menaik (-1 → +1) = "in".
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.counting import LineSpec, Track, update_track_side  # noqa: E402

WIB = timezone(timedelta(hours=7))


class TestGarisVirtual(unittest.TestCase):
    def setUp(self):
        # garis horizontal di 50% tinggi, p1 kiri → p2 kanan
        self.line = LineSpec(1, "garis-tengah", (0.1, 0.5), (0.9, 0.5))
        self.lines = [self.line]
        self.hyst = config.HYSTERESIS  # fraksi
        self.track = Track(7)

    def jalankan(self, ys):
        hasil = []
        for y in ys:
            hasil += update_track_side(
                self.track, (0.5, y), self.lines,
                self.hyst, config.MIN_DISPLACEMENT, config.MIN_TRACK_FRAMES,
            )
        return hasil

    def test_orang_turun_arah_out(self):
        hasil = self.jalankan((0.2, 0.3, 0.4, 0.55, 0.65, 0.75))
        self.assertEqual([h[2] for h in hasil], ["out"])

    def test_orang_naik_arah_in(self):
        self.track = Track(8)
        hasil = self.jalankan((0.8, 0.7, 0.6, 0.45, 0.3, 0.2))
        self.assertEqual([h[2] for h in hasil], ["in"])

    def test_orang_berdiri_di_garis_tidak_menghitung(self):
        hasil = self.jalankan((0.49, 0.51, 0.49, 0.51, 0.49, 0.51, 0.49, 0.51))
        self.assertEqual(len(hasil), 0, "jitter di garis tidak boleh menghitung")

    def test_jejak_pendek_tidak_menghitung(self):
        self.track.note((0.5, 0.2))
        hasil = self.jalankan((0.8,))
        self.assertEqual(len(hasil), 0, "jejak 2 bingkai belum sah")

    def test_bolak_balik_hanya_sekali_per_arah(self):
        # aturan idempotensi spec: UNIQUE(track, garis, arah) — jejak yang sama
        # pada garis & arah yang sama hanya dihitung SEKALI, walau bolak-balik.
        hasil = self.jalankan((0.2, 0.4, 0.8, 0.6, 0.3, 0.5, 0.85))
        self.assertEqual([h[2] for h in hasil], ["out", "in"])


class TestBatasHariWIB(unittest.TestCase):
    def test_tengah_malam_wib(self):
        from app.db import wib_day_bounds_utc
        start, end = wib_day_bounds_utc("2026-10-07")
        pukul_0030_wib = datetime(2026, 10, 7, 0, 30, tzinfo=WIB)
        ts = int(pukul_0030_wib.timestamp())
        self.assertTrue(start <= ts < end, "00:30 WIB harus masuk 2026-10-07 WIB")
        self.assertEqual(
            datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M"),
            "2026-10-06T17:30",
        )

    def test_batas_hari_fungsi_sinkron_dengan_konversi(self):
        from app.db import date_str_wib, wib_day_bounds_utc
        start, _ = wib_day_bounds_utc("2026-10-07")
        self.assertEqual(date_str_wib(start), "2026-10-07")


if __name__ == "__main__":
    unittest.main()
