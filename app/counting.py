"""Logika garis hitung virtual — fungsi murni, mudah diuji.

Semantik (docs/ARCHITECTURE.md):
- Setiap jejak (track) punya titik acuan = bottom-center bbox (kaki orang).
- "Sisi" garis dihitung sebagai tanda perkalian silang terhadap vektor garis
  (p1→p2). Sisi +1 = kanan arah vektor, -1 = kiri.
- Sisi hanya DIKUNCI saat titik berjarak > histeresis dari garis (fraksi
  tinggi frame) — orang yang berdiri di atas garis tidak bolak-balik sisi.
- Lewatan sah: sisi terkunci berubah (+1↔-1), total perpindahan titik acuan
  antara dua kunci >= MIN_DISPLACEMENT, dan umur jejak >= MIN_TRACK_FRAMES.
- Arah (vektor garis p1→p2): +1 → -1 = "out" (menurun); -1 → +1 = "in" (menaik).
"""

from dataclasses import dataclass, field


@dataclass
class LineSpec:
    line_id: int
    name: str
    p1: tuple  # (x, y) fraksi 0..1
    p2: tuple


@dataclass
class Track:
    track_id: int
    frames: int = 0
    max_conf: float = 0.0
    locked_side: int = 0
    locked_point: tuple | None = None
    last_point: tuple | None = None
    crossed: dict = field(default_factory=dict)  # (line_id, direction) -> True
    history: list = field(default_factory=list)  # [(point, side)]

    def note(self, point):
        self.last_point = point
        self.frames += 1
        self.history.append((point, self.locked_side))
        if len(self.history) > 64:
            self.history.pop(0)


def side_of(point, p1, p2):
    """Tanda jarak bertanda titik terhadap garis p1→p2 (px)."""
    (x1, y1), (x2, y2) = p1, p2
    vx, vy = x2 - x1, y2 - y1
    length = (vx * vx + vy * vy) ** 0.5 or 1.0
    return ((point[0] - x1) * vy - (point[1] - y1) * vx) / length


def within_segment(point, p1, p2, margin=0.15):
    """Titik proyeksinya jatuh di sekitar segmen garis (fraksi 0..1 dari
    panjang garis, diberi margin agar orang lewat di ujung garis tetap terhitung)."""
    (x1, y1), (x2, y2) = p1, p2
    vx, vy = x2 - x1, y2 - y1
    length_sq = vx * vx + vy * vy
    if length_sq == 0:
        return False
    t = ((point[0] - x1) * vx + (point[1] - y1) * vy) / length_sq
    return -margin <= t <= 1 + margin


def update_track_side(track: Track, point, lines,
                      hysteresis_frac, min_disp, min_frames):
    """Perbarui jejak dengan titik baru (fraksi 0..1); kembalikan lewatan.

    return: [(line_id, name, direction)]
    """
    track.note(point)
    crossings = []
    for line in lines:
        p1 = (line.p1[0], line.p1[1])
        p2 = (line.p2[0], line.p2[1])
        side = side_of(point, p1, p2)
        hyst = hysteresis_frac
        if abs(side) > hyst:
            new_side = 1 if side > 0 else -1
            if track.locked_side == 0:
                track.locked_side = new_side
                track.locked_point = point
            elif new_side != track.locked_side:
                # perpindahan minimum antara titik kunci lama dan titik kini
                disp = ((point[0] - track.locked_point[0]) ** 2
                        + (point[1] - track.locked_point[1]) ** 2) ** 0.5
                direction = "in" if new_side == 1 else "out"
                already = (line.line_id, direction) in track.crossed
                if (
                    track.frames >= min_frames
                    and disp >= min_disp
                    and within_segment(point, p1, p2)
                    and not already
                ):
                    track.crossed[(line.line_id, direction)] = True
                    crossings.append((line.line_id, line.name, direction))
                track.locked_side = new_side
                track.locked_point = point
    return crossings
