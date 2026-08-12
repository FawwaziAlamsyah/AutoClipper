"""Training import service: parse CSV dan enqueue bulk training_ingest jobs."""

import csv
import io
import logging
import threading
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.services.download_service import DownloadService
from app.services.process_service import ProcessService
from app.services.video_service import VideoService

logger = logging.getLogger(__name__)

# Store progress bulk import — in-memory (app lokal single-user).
# Key: import_id → {total, queued, completed, failed, jobs}
_IMPORTS: dict[str, dict] = {}


def _new_import_id() -> str:
    """Buat id unik untuk satu proses bulk import."""
    return f"imp_{uuid.uuid4().hex[:8]}"


class TrainingImportService:
    """Parse CSV dan enqueue setiap baris sebagai training_ingest job."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.db = db
        self.video_service = VideoService(db)
        self.download_service = DownloadService(db)
        self.process_service = ProcessService(db)

    async def parse_csv(self, file: UploadFile) -> list[dict]:
        """Parse CSV file dan validasi kolom source + actual_score.

        Format CSV yang diharapkan (header opsional, auto-detected):
            source,actual_score
            /path/to/clip.mp4,8.5
            https://youtu.be/xxxxx,9.0

        Return list of dicts: [{source, actual_score}, ...]
        """
        content = await file.read()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

        reader = csv.reader(io.StringIO(text))
        rows: list[dict] = []

        for line_num, row in enumerate(reader, start=1):
            # Skip baris kosong
            if not row or all(cell.strip() == "" for cell in row):
                continue

            # Skip header row jika ada (deteksi: kolom pertama bukan angka/path/URL)
            if line_num == 1 and len(row) >= 2:
                first = row[0].strip().lower()
                if first in ("source", "path", "url", "file"):
                    continue

            if len(row) < 2:
                raise ValidationException(
                    f"Baris {line_num}: format salah — butuh 2 kolom (source, actual_score)"
                )

            source = row[0].strip()
            score_str = row[1].strip()

            try:
                actual_score = float(score_str)
            except ValueError:
                raise ValidationException(
                    f"Baris {line_num}: actual_score '{score_str}' bukan angka valid"
                )

            if not (0 <= actual_score <= 10):
                raise ValidationException(
                    f"Baris {line_num}: actual_score {actual_score} harus antara 0-10"
                )

            if not source:
                raise ValidationException(f"Baris {line_num}: source tidak boleh kosong")

            rows.append({"source": source, "actual_score": actual_score})

        if not rows:
            raise ValidationException("CSV tidak memiliki baris data yang valid")

        return rows

    def enqueue_bulk_ingest(self, rows: list[dict]) -> tuple[str, list]:
        """Enqueue setiap baris sebagai background training_ingest job.

        Return (import_id, job_ids_placeholder) — job_ids diisi async
        setelah setiap baris selesai diproses.
        """
        import_id = _new_import_id()
        _IMPORTS[import_id] = {
            "total": len(rows),
            "queued": len(rows),
            "completed": 0,
            "failed": 0,
            "jobs": [],
        }

        def _run_row(row: dict) -> None:
            """Proses satu baris CSV di background thread."""
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                svc = ProcessService(db)
                video_svc = VideoService(db)
                dl_svc = DownloadService(db)

                source: str = row["source"]
                actual_score: float = row["actual_score"]

                # Tentukan apakah source adalah URL atau path lokal
                is_url = source.startswith("http://") or source.startswith("https://")

                if is_url:
                    # Reuse DownloadService yang sudah ada — jangan duplikasi logic
                    video = dl_svc.download_video(source)
                else:
                    # Path lokal: baca bytes dan upload lewat VideoService
                    file_path = Path(source)
                    if not file_path.exists():
                        raise ValidationException(f"File tidak ditemukan: {source}")
                    file_bytes = file_path.read_bytes()
                    video = video_svc.upload(file_path.name, file_bytes)

                # Buat job training_ingest dan jalankan pipeline
                job_id = svc.create_job(video.id, job_type="training_ingest")
                _IMPORTS[import_id]["jobs"].append(job_id)

                svc.process_video(
                    video.id,
                    job_id=job_id,
                    num_clips=1,
                    actual_score=actual_score,
                )

                _IMPORTS[import_id]["completed"] += 1
                logger.info(
                    "Bulk import %s: baris selesai (video %d, job %d, score %.1f)",
                    import_id, video.id, job_id, actual_score,
                )
            except Exception as e:
                _IMPORTS[import_id]["failed"] += 1
                logger.error("Bulk import %s: baris gagal (%s): %s", import_id, row["source"], e)
            finally:
                _IMPORTS[import_id]["queued"] -= 1
                db.close()

        # Jalankan tiap baris di background thread — endpoint langsung balas
        for row in rows:
            thread = threading.Thread(target=_run_row, args=(row,), daemon=True)
            thread.start()

        return import_id, []

    def get_import_progress(self, import_id: str) -> dict:
        """Baca progress bulk import aktif."""
        entry = _IMPORTS.get(import_id)
        if entry is None:
            return {"status": "unknown"}
        total = entry["total"]
        completed = entry["completed"]
        failed = entry["failed"]
        queued = entry["queued"]
        done = completed + failed
        percent = round((done / total) * 100) if total else 0
        status = "running" if queued > 0 else "finished"
        return {
            "import_id": import_id,
            "status": status,
            "total": total,
            "completed": completed,
            "failed": failed,
            "queued": queued,
            "percent": percent,
            "job_ids": entry["jobs"],
        }
