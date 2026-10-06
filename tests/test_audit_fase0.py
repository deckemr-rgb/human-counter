"""Tes Fase 0 — membuktikan temuan audit dengan kode yang dijalankan.

Tes di sini MENYATAKAN PERILAKU YANG BENAR (hasil akhir yang diinginkan).
Saat ini beberapa dari mereka MERAH karena bug-nya memang masih ada — itu
buktinya (lihat docs/AUDIT.md). Mereka akan hijau setelah Fase 1-2.
"""

import json
import sqlite3
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import counter_server as cs  # noqa: E402

CAM = "kamera-uji"


class AuditTestBase(unittest.TestCase):
    """DB uji terpisah untuk tiap tes — tidak menyentuh counter.db produksi."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        cs.DB = self.conn
        cs.DB.executescript(cs._SCHEMA_SQL)
        cs._camera_cache["sources"] = [
            {"id": CAM, "name": "Kamera Uji", "city": "Jakarta", "feedType": "hls"}
        ]

    def tearDown(self):
        self.conn.close()


class TestK1DedupMenggabungkanOrangBeda(AuditTestBase):
    """K1: dua ORANG BERBEDA lewat titik piksel yang sama dalam 10 menit —
    backend harus mencatat mereka sebagai DUA lewatan, bukan satu."""

    def test_dua_orang_bbox_mirip_tercatat_dua(self):
        now = __import__("time").time()
        # Orang A lewat
        cs.DB.execute(
            "INSERT INTO events (event_key, camera_id, camera_name, first_seen,"
            " last_seen, frames, max_conf, bbox_first, bbox_last)"
            " VALUES ('k-a', ?, 'Kamera Uji', ?, ?, 5, 0.8, ?, ?)",
            (CAM, cs.now_iso(), cs.now_iso(), "[100,100,200,400]", "[100,100,200,400]"),
        )
        self.conn.commit()
        # Orang B lewat 2 menit kemudian di titik piksel yang hampir sama
        dup = cs.find_duplicate(CAM, [105, 105, 205, 405], now - 120)
        # PERILAKU BENAR: TIDAK boleh dianggap duplikat (dua orang berbeda)
        self.assertIsNone(
            dup,
            "BUG K1 TERBUKTI: orang berbeda dengan bbox mirip digabung menjadi "
            "satu catatan (undercount sistematis di titik piksel ramai)",
        )


class TestK2StatistikHariIniWIB(AuditTestBase):
    """K2: orang tercatat 01:30 WIB hari ini harus dihitung 'HARI INI',
    meskipun dalam UTC ia jatuh pada 18:30 tanggal kemarin."""

    def test_event_0130_wib_dihitung_hari_ini(self):
        from datetime import datetime, timedelta, timezone

        # 01:30 WIB hari ini → epoch & ISO UTC
        wib = timezone(timedelta(hours=7))
        now_wib = datetime.now(wib)
        pukul_0130_wib = now_wib.replace(hour=1, minute=30, second=0, microsecond=0)
        if pukul_0130_wib > now_wib:  # 01:30 belum terjadi hari ini → kemarin
            pukul_0130_wib -= timedelta(days=1)
        iso_utc = pukul_0130_wib.astimezone(timezone.utc).isoformat(timespec="seconds")
        cs.DB.execute(
            "INSERT INTO events (event_key, camera_id, camera_name, first_seen,"
            " last_seen, frames, max_conf) VALUES ('k-wib', ?, 'Kamera Uji', ?, ?, 1, 0.9)",
            (CAM, iso_utc, iso_utc),
        )
        self.conn.commit()
        stats = self._call_stats()
        self.assertEqual(
            stats["today"], 1,
            f"BUG K2: event {iso_utc} (01:30 WIB) tidak terhitung hari ini "
            f"— stats['today'] = {stats['today']}",
        )

    def _call_stats(self):
        """Panggil logika statistik /api/stats lewat handler yang di-stub."""
        captured = {}

        class FakeWriter:
            def write(self, body):
                captured["body"] = json.loads(body)

        handler = cs.CounterHandler.__new__(cs.CounterHandler)
        handler._send_json = lambda status, payload: captured.update(body=payload, status=status)
        # handler do_GET menulis via wfile — stub minimal
        original = cs.CounterHandler.do_GET
        # Panggil hanya bagian /api/stats: ekstrak ke fungsi agar teruji →
        # untuk Fase 0, jalankan query yang sama persis seperti di handler.
        now = __import__("time").time()
        with cs._db_lock:
            hour_ago = datetime.fromtimestamp(now - 3600, timezone.utc).isoformat(timespec="seconds")
            captured["body"] = {
                "total": cs.DB.execute("SELECT COUNT(*) c FROM events").fetchone()["c"],
                "today": cs.DB.execute(
                    "SELECT COUNT(*) c FROM events WHERE first_seen >= ?",
                    (cs.today_boundary_utc_iso(),),
                ).fetchone()["c"]
                if hasattr(cs, "today_boundary_utc_iso")
                else cs.DB.execute(
                    "SELECT COUNT(*) c FROM events WHERE first_seen >= date('now','localtime')",
                ).fetchone()["c"],
                "lastHour": cs.DB.execute(
                    "SELECT COUNT(*) c FROM events WHERE first_seen >= ?", (hour_ago,)
                ).fetchone()["c"],
            }
        return captured["body"]


if __name__ == "__main__":
    unittest.main()
