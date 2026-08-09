"""Upload & video management service."""

import hashlib
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import NotFoundException, ValidationException
from app.models.analysis_result_model import AnalysisResult
from app.models.cache_entry_model import CacheEntry
from app.models.candidate_model import Candidate
from app.models.clip_model import Clip
from app.models.history_model import History
from app.models.job_model import Job
from app.models.job_step_model import JobStep
from app.models.speaker_model import Speaker
from app.models.subtitle_model import Subtitle
from app.models.transcript_model import Transcript
from app.models.transcript_segment_model import TranscriptSegment
from app.models.video_model import Video
from app.repositories.video_repository import VideoRepository

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = set(settings.ALLOWED_VIDEO_EXTENSIONS)


class VideoService:
    """Handles video upload, validation, and metadata."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.repo = VideoRepository(db)
        self.db = db

    def upload(self, filename: str, file_bytes: bytes) -> Video:
        """Validate, save to disk, and persist a new video record."""
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValidationException(
                f"Format '{ext}' tidak didukung. Gunakan: {', '.join(ALLOWED_EXTENSIONS)}"
            )

        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise ValidationException(
                f"Ukuran file melebihi batas {settings.MAX_UPLOAD_SIZE_MB} MB"
            )

        upload_dir: Path = settings.UPLOAD_DIR
        upload_dir.mkdir(parents=True, exist_ok=True)

        file_hash = hashlib.md5(file_bytes[:8192]).hexdigest()[:8]
        safe_name = f"{file_hash}_{Path(filename).stem}{ext}"
        dest = upload_dir / safe_name

        dest.write_bytes(file_bytes)
        logger.info("Video saved: %s (%d bytes)", dest, len(file_bytes))

        video = Video(
            original_filename=filename,
            source_type="upload",
            file_path=str(dest),
            file_size_bytes=len(file_bytes),
            status="uploaded",
        )
        video = self.repo.add(video)

        self.db.add(History(
            video_id=video.id,
            action="video_uploaded",
            description=f"Uploaded {filename}",
        ))
        self.db.commit()

        return video

    def get(self, video_id: int) -> Video:
        """Get video by ID or raise NotFoundException."""
        video = self.repo.get(video_id)
        if video is None:
            raise NotFoundException(f"Video {video_id} tidak ditemukan")
        return video

    def list_all(self) -> list[Video]:
        """Return all videos."""
        return self.repo.list()

    def delete(self, video_id: int) -> None:
        """Delete a video, related records, and generated files."""
        video = self.get(video_id)
        self._delete_video_files(video_id, video.file_path)
        self._delete_related_rows(video_id)
        self.repo.delete(video_id)
        logger.info("Deleted video record: %d", video_id)

    def _delete_video_files(self, video_id: int, source_path: str) -> None:
        """Delete source, cache, and output files for a video."""
        paths = [source_path]
        paths += [c.file_path for c in self.db.query(Clip).filter(Clip.video_id == video_id).all() if c.file_path]
        paths += [c.file_path for c in self.db.query(CacheEntry).filter(CacheEntry.video_id == video_id).all() if c.file_path]

        for raw_path in paths:
            path = Path(raw_path)
            if path.exists() and path.is_file():
                path.unlink()
                logger.info("Deleted file: %s", path)

    def _delete_related_rows(self, video_id: int) -> None:
        """Delete related rows in FK-safe order."""
        job_ids = [j.id for j in self.db.query(Job).filter(Job.video_id == video_id).all()]
        transcript_ids = [t.id for t in self.db.query(Transcript).filter(Transcript.video_id == video_id).all()]
        candidate_ids = [c.id for c in self.db.query(Candidate).filter(Candidate.video_id == video_id).all()]
        clip_ids = [c.id for c in self.db.query(Clip).filter(Clip.video_id == video_id).all()]
        speaker_ids = [s.id for s in self.db.query(Speaker).filter(Speaker.video_id == video_id).all()]

        if clip_ids:
            self.db.query(Subtitle).filter(Subtitle.clip_id.in_(clip_ids)).delete(synchronize_session=False)
        if transcript_ids:
            self.db.query(TranscriptSegment).filter(TranscriptSegment.transcript_id.in_(transcript_ids)).delete(synchronize_session=False)
        if speaker_ids:
            self.db.query(TranscriptSegment).filter(TranscriptSegment.speaker_id.in_(speaker_ids)).update({TranscriptSegment.speaker_id: None}, synchronize_session=False)
        if candidate_ids:
            self.db.query(Clip).filter(Clip.candidate_id.in_(candidate_ids)).delete(synchronize_session=False)

        self.db.query(Clip).filter(Clip.video_id == video_id).delete(synchronize_session=False)
        self.db.query(Candidate).filter(Candidate.video_id == video_id).delete(synchronize_session=False)
        self.db.query(AnalysisResult).filter(AnalysisResult.video_id == video_id).delete(synchronize_session=False)
        self.db.query(Transcript).filter(Transcript.video_id == video_id).delete(synchronize_session=False)
        self.db.query(Speaker).filter(Speaker.video_id == video_id).delete(synchronize_session=False)
        self.db.query(CacheEntry).filter(CacheEntry.video_id == video_id).delete(synchronize_session=False)
        self.db.query(History).filter(History.video_id == video_id).delete(synchronize_session=False)

        if job_ids:
            self.db.query(JobStep).filter(JobStep.job_id.in_(job_ids)).delete(synchronize_session=False)
            self.db.query(Job).filter(Job.id.in_(job_ids)).delete(synchronize_session=False)

        self.db.commit()
