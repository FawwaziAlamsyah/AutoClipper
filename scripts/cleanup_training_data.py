"""
Script to cleanly delete all data downloaded from the bulk CSV training import.
Deletes physical video files from disk and removes all corresponding database entries.
Keeps all normal user videos (non-training_ingest) intact.
"""

import sys
from pathlib import Path
from datetime import datetime

# Set UTF-8 encoding
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from app.db.session import SessionLocal
from app.models.job_model import JobModel
from app.models.video_model import VideoModel
from app.services.video_service import VideoService

def cleanup():
    db = SessionLocal()
    video_service = VideoService(db)

    print("=== STARTING CLEANUP OF CSV TRAINING DATA ===")

    # 1. Identify all videos associated with training_ingest jobs
    ingest_jobs = db.query(JobModel).filter(JobModel.job_type == "training_ingest").all()
    ingest_video_ids = sorted(list(set([j.video_id for j in ingest_jobs])))
    print(f"Identified {len(ingest_video_ids)} training_ingest videos in database.")

    deleted_count = 0
    freed_bytes = 0

    for vid in ingest_video_ids:
        video = db.query(VideoModel).filter(VideoModel.id == vid).first()
        if not video:
            continue

        # Measure file size before deletion
        if video.file_path:
            p = Path(video.file_path)
            if p.exists() and p.is_file():
                try:
                    freed_bytes += p.stat().st_size
                except Exception:
                    pass

        try:
            # hard_delete removes physical file, clips, candidates, analysis, jobs, and video row
            video_service.hard_delete(vid)
            deleted_count += 1
        except Exception as e:
            print(f"Error hard-deleting video {vid}: {e}")

    # 2. Check for any orphan files in data/uploads created after 21:00 today matching windah/shorts
    uploads_dir = Path("data/uploads")
    orphan_deleted = 0
    if uploads_dir.exists():
        cutoff = datetime(2026, 10, 18, 21, 0, 0)
        for f in uploads_dir.glob("*.*"):
            if f.is_file():
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime >= cutoff and ("windah" in f.name.lower() or "shorts" in f.name.lower() or "klip" in f.name.lower()):
                        # Check if it belongs to any remaining video in DB
                        exists_in_db = db.query(VideoModel).filter(VideoModel.file_path == str(f.resolve())).first()
                        if not exists_in_db:
                            freed_bytes += f.stat().st_size
                            f.unlink(missing_ok=True)
                            orphan_deleted += 1
                except Exception as e:
                    print(f"Error deleting orphan file {f.name}: {e}")

    db.close()

    print("\n=== CLEANUP COMPLETED ===")
    print(f"Total videos hard-deleted from DB: {deleted_count}")
    print(f"Additional orphan files removed: {orphan_deleted}")
    print(f"Total disk space freed: {freed_bytes / (1024 * 1024):.2f} MB ({freed_bytes / (1024 ** 3):.2f} GB)")

if __name__ == "__main__":
    cleanup()
