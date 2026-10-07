"""eval/run_eval.py — replay klip melalui pipa hitung asli + metrik.

Pemakaian:
    python eval/run_eval.py <klip.mp4> [--garis x1,y1,x2,y2] [--detik 60]

Metrik: bingkai diproses, deteksi/bingkai, jejak unik, rasio fragmentasi
(jejjak / orang rata-rata), lewatan per arah, fps efektif. Dipakai juga
sebagai uji determinisme: dua replay konfigurasi sama harus menghasilkan
angka identik (golden test).
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import supervision as sv
from ultralytics import YOLO

from app import config
from app.counting import LineSpec, Track, update_track_side


def run_replay(clip_path, line_spec, seconds, imgsz, conf):
    """Replay deterministik: sampling berbasis POSISI video (N-th frame),
    bukan waktu dinding — hasil identik antar-run (golden test)."""
    model = YOLO(config.MODEL_NAME)
    tracker = sv.ByteTrack(track_activation_threshold=0.25)
    cap = cv2.VideoCapture(clip_path)
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25
    step = max(1, round(video_fps / config.TARGET_FPS))
    limit = int(seconds * video_fps)
    tracks = {}
    frames = 0
    det_sum = 0
    crossings = {"in": 0, "out": 0}
    t0 = time.time()
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok or idx >= limit:
            break
        idx += 1
        if idx % step != 0:
            continue
        frames += 1
        result = model(frame, verbose=False, imgsz=imgsz, conf=conf,
                       iou=config.NMS_IOU, classes=[0])[0]
        det_sv = sv.Detections.from_ultralytics(result)
        tracked = tracker.update_with_detections(det_sv)
        det_sum += tracked.xyxy.shape[0]
        frame_h, frame_w = frame.shape[:2]
        if tracked.xyxy.shape[0]:
            ids = (tracked.tracker_id if tracked.tracker_id is not None
                   else [-1] * tracked.xyxy.shape[0])
            for box, tid, cf in zip(tracked.xyxy.tolist(), ids, tracked.confidence.tolist()):
                if tid not in tracks:
                    tracks[tid] = Track(tid)
                x1, y1, x2, y2 = box
                point = ((x1 + x2) / 2 / frame_w, (y1 + y2) / frame_h)
                for _l, _n, d in update_track_side(
                    tracks[tid], point, [line_spec],
                    config.HYSTERESIS, config.MIN_DISPLACEMENT, config.MIN_TRACK_FRAMES,
                ):
                    crossings[d] += 1
    cap.release()
    elapsed = time.time() - t0
    avg_det = det_sum / max(frames, 1)
    return {
        "frames": frames,
        "avgDetections": round(avg_det, 1),
        "uniqueTracks": len(tracks),
        "fragmentation": round(len(tracks) / max(avg_det, 1), 2),
        "crossingsIn": crossings["in"],
        "crossingsOut": crossings["out"],
        "fpsEffektif": round(frames / max(elapsed, 0.001), 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("clip")
    parser.add_argument("--garis", default="0.5,0.2,0.5,0.85",
                        help="x1,y1,x2,y2 fraksi")
    parser.add_argument("--detik", type=int, default=60)
    parser.add_argument("--imgsz", type=int, default=config.IMGSZ)
    parser.add_argument("--conf", type=float, default=config.CONF)
    args = parser.parse_args()

    x1, y1, x2, y2 = (float(v) for v in args.garis.split(","))
    line = LineSpec(1, "eval", (x1, y1), (x2, y2))

    a = run_replay(args.clip, line, args.detik, args.imgsz, args.conf)
    b = run_replay(args.clip, line, args.detik, args.imgsz, args.conf)
    # fpsEffektif adalah pengukuran waktu — bukan bagian golden.
    a.pop("fpsEffektif"); b.pop("fpsEffektif")
    deterministik = a == b
    print(json.dumps({
        "clip": args.clip,
        "garis": args.garis,
        "imgsz": args.imgsz,
        "conf": args.conf,
        "run_pertama": a,
        "replay_deterministik": deterministik,
    }, indent=1))
    if not deterministik:
        print("PERINGATAN: replay tidak deterministik — selidiki (golden test gagal)")
        sys.exit(2)


if __name__ == "__main__":
    main()
