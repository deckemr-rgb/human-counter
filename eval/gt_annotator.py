"""eval/gt_annotator.py — alat anotasi ground truth lewatan (operator).

Putar klip; setiap kali SEORANG orang melewati garis putih (dari kiri ke
kanan = 'in', kanan ke kiri = 'out'), tekan:
    SPACE = lewatan 'in'     B = lewatan 'out'     ESC = simpan & keluar

Output: eval/ground_truth/<nama-klip>.json — berisi daftar timestamp detik
dan arah. Dibandingkan run_eval --gt oleh perhitungan precision/recall.
"""

import json
import sys
import time
from pathlib import Path

import cv2

def main():
    if len(sys.argv) < 2:
        print("pemakaian: python eval/gt_annotator.py <klip.mp4>")
        sys.exit(1)
    clip = Path(sys.argv[1])
    cap = cv2.VideoCapture(str(clip))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    events = []
    paused = False
    print("SPACE=in  B=out  P=pause  ESC=simpan")
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        cv2.putText(frame, f"t={t:6.1f}s  in={sum(1 for e in events if e['direction']=='in')}"
                    f" out={sum(1 for e in events if e['direction']=='out')}",
                    (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imshow("GT annotator", frame)
        wait = 0 if paused else max(1, int(1000 / fps))
        key = cv2.waitKey(wait) & 0xFF
        if key == ord(" "):
            events.append({"ts": round(t, 2), "direction": "in"})
        elif key == ord("b"):
            events.append({"ts": round(t, 2), "direction": "out"})
        elif key == ord("p"):
            paused = not paused
        elif key == 27:
            break
    cap.release()
    cv2.destroyAllWindows()
    out_dir = Path(__file__).resolve().parent / "ground_truth"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{clip.stem}.json"
    out.write_text(json.dumps({"clip": clip.name, "fps": fps, "events": events}, indent=1),
                   encoding="utf-8")
    print(f"disimpan: {out} ({len(events)} lewatan)")

if __name__ == "__main__":
    main()
