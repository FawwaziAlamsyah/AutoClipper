"""A/B regression test — VideoVisionPass (single-pass) vs legacy analyzers.

Bandingkan skor PER WINDOW untuk 4 analyzer visual (face_emotion, eye_contact,
gesture, scene) pada VIDEO ASLI yang sama. Formula seharusnya identik; beda
menandakan regression dari jalur single-pass.

Jalankan w/o DB:
    python -m scripts.ab_vision "data/uploads/<file>.mp4"

Output: per-window score legacy vs single-pass + delta, lalu ranking top-N
overlap. Exit code 0 = lolos gate (semua delta <= tolerance).
"""

import glob
import math
import os
import sys

from app.ai_modules.registry import get_analyzer
from app.ai_modules.video_vision_pass import VideoVisionPass

# Analyzer visual + bobot kiblat saat ini (untuk ranking)
VISUAL = {
    "face_emotion": 0.15,
    "gesture": 0.20,
    "eye_contact": 0.04,
    "scene": 0.06,
}

# Toleransi beda skor (absolut). Formula identik → harus ~0.
SCORE_TOLERANCE = 0.5

# Window yang di-scan [start, end] detik (sample, bukan seluruh durasi biar cepat)
WINDOWS = [(0, 60), (30, 90), (60, 120), (120, 180)]


def pick_video() -> str:
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        return sys.argv[1]
    env = os.environ.get("AB_VIDEO")
    if env and os.path.exists(env):
        return env
    vids = sorted(glob.glob("data/uploads/*.mp4"))
    if not vids:
        raise SystemExit("Tidak ada video .mp4 di data/uploads/")
    return vids[0]


def run_legacy(path: str, start: float, end: float) -> dict:
    out = {}
    for atype in VISUAL:
        analyzer = get_analyzer(atype)
        result = analyzer.analyze({"video_path": path, "start": start, "end": end})
        out[atype] = result.score
    return out


def run_single(path: str, start: float, end: float) -> dict:
    vvp = VideoVisionPass()
    res = vvp.analyze_window(path, start, end)
    return {atype: r.score for atype, r in res.items() if atype in VISUAL}


def rank(per_window_scores: dict) -> list:
    # {window_idx: {atype: score}} → final = weighted sum (bobot kiblat),
    # sort desc → ranking top windows.
    scored = []
    for w, a in per_window_scores.items():
        total = sum(v * VISUAL[k] for k, v in a.items())
        scored.append((w, total))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [w for w, _ in scored]


def overlap(a: list, b: list) -> float:
    if not a:
        return 0.0
    return len(set(a) & set(b)) / len(set(a)) * 100.0


def main() -> int:
    path = pick_video()
    print(f"=== A/B Vision: legacy vs single-pass ===")
    print(f"video: {path}\n")

    legacy = {}
    single = {}
    worst = 0.0
    worst_pair = None

    for start, end in WINDOWS:
        leg = run_legacy(path, start, end)
        sg = run_single(path, start, end)
        legacy[(start, end)] = leg
        single[(start, end)] = sg

        print(f"window [{start}-{end}]s")
        for atype in VISUAL:
            l = leg.get(atype)
            s = sg.get(atype)
            delta = abs((s or 0.0) - (l or 0.0))
            flag = "  <-- DRIFT" if delta > SCORE_TOLERANCE else ""
            print(f"  {atype:14s} legacy={l} single={s} delta={delta:.2f}{flag}")
            if delta > worst:
                worst = delta
                worst_pair = (atype, start, end)
        print()

    # Ranking overlap top-N
    leg_rank = rank(legacy)
    sg_rank = rank(single)
    print("=== RANKING (bobot kiblat) ===")
    print(f"legacy order  : {leg_rank}")
    print(f"single order  : {sg_rank}")
    for n in (1, 2):
        ov = overlap(leg_rank[:n], sg_rank[:n])
        print(f"top-{n} overlap: {ov:.0f}%")

    print(f"\nworst per-analyzer delta: {worst:.2f} "
          f"({'di ' + str(worst_pair) if worst_pair else ''})")
    if worst > SCORE_TOLERANCE:
        print(f"FAIL: ada drift > {SCORE_TOLERANCE}")
        return 1
    print(f"PASS: semua delta <= {SCORE_TOLERANCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
