"""Debug script: log setiap frame timestamp ke txt file.

Usage:
    python debug_frame_logger.py <video_path> [output.txt]

Contoh:
    python debug_frame_logger.py data/uploads/video.mp4
    python debug_frame_logger.py data/uploads/video.mp4 debug_frames.txt
"""

import sys
import subprocess
import json
from pathlib import Path


def get_frame_timestamps(video_path: str) -> list[dict]:
    """Ambil semua frame timestamps via ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "frame=pts_time,pict_type",
        "-of", "json",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return []
    data = json.loads(result.stdout)
    return data.get("frames", [])


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    video_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "debug_frames.txt"

    if not Path(video_path).exists():
        print(f"File tidak ditemukan: {video_path}")
        sys.exit(1)

    print(f"Scanning frames: {video_path}")
    frames = get_frame_timestamps(video_path)
    print(f"Ditemukan {len(frames)} frames")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# Frame timestamps: {video_path}\n")
        f.write(f"# Total frames: {len(frames)}\n")
        f.write(f"# {'Frame':>6}  {'Timestamp':>12}  {'Type':>4}\n")
        f.write("-" * 40 + "\n")
        for i, frame in enumerate(frames):
            pts = frame.get("pts_time", "?")
            pict = frame.get("pict_type", "?")
            line = f"  {i:>6}  {float(pts):>12.4f}s  {pict:>4}"
            f.write(line + "\n")

    print(f"Tersimpan ke: {output_path}")


if __name__ == "__main__":
    main()
