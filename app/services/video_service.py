"""Upload & video management service."""

import hashlib
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import NotFoundException, ValidationException
from app.models.cache_entry_model import CacheEntryModel
from app.models.clip_model import ClipModel
from app.models.video_model import VideoModel
from app.repositories.video_repository import VideoRepository
from app.services.history_service import HistoryService

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = set(settings.ALLOWED_VIDEO_EXTENSIONS)


class VideoService:
    """Handles video upload, validation, and metadata."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.repo = VideoRepository(db)
        self.history_service = HistoryService(db)
        self.db = db

    def upload(self, filename: str, file_bytes: bytes) -> VideoModel:
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

        logger.debug("Import process: simpan file %s ke disk", dest.name)
        dest.write_bytes(file_bytes)
        logger.info("Video saved: %s (%d bytes)", dest, len(file_bytes))
        logger.debug("Import process: success - video tersimpan ke disk")

        video = VideoModel(
            original_filename=filename,
            source_type="upload",
            file_path=str(dest),
            file_size_bytes=len(file_bytes),
            status="uploaded",
        )
        video = self.repo.add(video)

        self.history_service.log(
            action="video_uploaded",
            description=f"Uploaded {filename}",
            video_id=video.id,
        )
        self.db.commit()

        return video

    def begin_upload(self, filename: str) -> VideoModel:
        """Create an 'uploading' video record so the upload survives page navigation."""
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValidationException(
                f"Format '{ext}' tidak didukung. Gunakan: {', '.join(ALLOWED_EXTENSIONS)}"
            )
        video = VideoModel(
            original_filename=filename,
            source_type="upload",
            file_path="",
            status="uploading",
        )
        video = self.repo.add(video)
        logger.info("Begin upload: video %d", video.id)
        return video

    def finish_upload(self, video_id: int, file) -> VideoModel:
        """Stream an upload to disk and mark the video as uploaded."""
        video = self.get(video_id)
        if video.status == "uploaded":
            return video

        filename = video.original_filename
        ext = Path(filename).suffix.lower()
        upload_dir: Path = settings.UPLOAD_DIR
        upload_dir.mkdir(parents=True, exist_ok=True)

        safe_name = f"vid_{video_id}_{Path(filename).stem}{ext}"
        dest = upload_dir / safe_name

        with open(dest, "wb") as out:
            shutil.copyfileobj(file, out, 1024 * 1024)

        size = dest.stat().st_size
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if size > max_bytes:
            dest.unlink(missing_ok=True)
            self.delete(video_id)
            raise ValidationException(
                f"Ukuran file melebihi batas {settings.MAX_UPLOAD_SIZE_MB} MB"
            )

        video.file_path = str(dest)
        video.file_size_bytes = size
        self.repo.update_status(video_id, "uploaded")
        self.history_service.log(
            action="video_uploaded",
            description=f"Uploaded {filename}",
            video_id=video.id,
        )
        self.db.commit()
        logger.info("Video saved: %s (%d bytes)", dest, size)
        return video

    def mark_stale_uploading_failed(self) -> int:
        """Mark videos stuck in 'uploading' as failed (orphaned after restart)."""
        stale = self.db.query(VideoModel).filter(VideoModel.status == "uploading").all()
        for video in stale:
            video.status = "failed"
        if stale:
            self.db.commit()
            logger.info("Marked %d stale uploading video(s) as failed", len(stale))
        return len(stale)

    def get(self, video_id: int) -> VideoModel:
        """Get video by ID or raise NotFoundException."""
        video = self.repo.get(video_id)
        if video is None:
            raise NotFoundException(f"Video {video_id} tidak ditemukan")
        return video

    def list_all(self) -> list[VideoModel]:
        """Return all videos."""
        return self.repo.list()

    def delete(self, video_id: int) -> None:
        """Archive video: hapus file fisik, TAPI simpan semua baris database.

        Nama method "delete" dipertahankan (dipanggil dari video_router.py) tapi
        perilakunya sekarang archive — video yang sudah dianalisis tidak pernah
        hard-delete dari DB, supaya data training/candidate tidak pernah hilang.
        """
        video = self.get(video_id)
        if video.is_archived:
            logger.info("Video %d sudah diarsipkan sebelumnya, skip", video_id)
            return

        self._delete_video_files(video_id, video.file_path)
        # _delete_related_rows() TIDAK dipanggil — candidates, analysis_results,
        # transcripts, dll semua TETAP di database.

        video.is_archived = True
        video.archived_at = datetime.now(UTC)
        self.history_service.log(
            action="video_archived",
            description="File dihapus untuk hemat storage, data training tetap tersimpan",
            video_id=video.id,
        )
        self.db.commit()
        logger.info("Video %d diarsipkan (file dihapus, data DB tetap ada)", video_id)

    def _delete_video_files(self, video_id: int, source_path: str) -> None:
        """Delete source, cache, and output files for a video."""
        paths = [source_path]
        paths += [c.file_path for c in self.db.query(ClipModel).filter(ClipModel.video_id == video_id).all() if c.file_path]
        paths += [c.file_path for c in self.db.query(CacheEntryModel).filter(CacheEntryModel.video_id == video_id).all() if c.file_path]

        for raw_path in paths:
            path = Path(raw_path)
            if path.exists() and path.is_file():
                try:
                    path.unlink()
                    logger.info("Deleted file: %s", path)
                except PermissionError:
                    # Windows: file terkunci proses lain (browser masih streaming
                    # preview <video>). Skip hapus fisik — DB record tetap dihapus.
                    logger.warning(
                        "File terkunci (dipakai proses lain), lewati hapus fisik: %s", path
                    )

    def hard_delete(self, video_id: int) -> None:
        """Hard-delete video beserta SEMUA data terkait dari database.

        Dipakai saat ingin benar-benar menghapus segalanya — file, candidates,
        training labels, transcripts, analysis_results, jobs, dst.
        Operasi ini TIDAK BISA di-undo.
        """
        from app.models.analysis_result_model import AnalysisResultModel
        from app.models.candidate_model import CandidateModel
        from app.models.job_model import JobModel
        from app.models.job_step_model import JobStepModel
        from app.models.speaker_model import SpeakerModel
        from app.models.subtitle_model import SubtitleModel
        from app.models.transcript_model import TranscriptModel
        from app.models.transcript_segment_model import TranscriptSegmentModel

        video = self.get(video_id)

        # 1. Hapus file fisik dulu
        self._delete_video_files(video_id, video.file_path)

        # 2. Hapus semua baris DB terkait (FK-safe order)
        job_ids = [j.id for j in self.db.query(JobModel).filter(JobModel.video_id == video_id).all()]
        transcript_ids = [t.id for t in self.db.query(TranscriptModel).filter(TranscriptModel.video_id == video_id).all()]
        candidate_ids = [c.id for c in self.db.query(CandidateModel).filter(CandidateModel.video_id == video_id).all()]
        clip_ids = [c.id for c in self.db.query(ClipModel).filter(ClipModel.video_id == video_id).all()]
        speaker_ids = [s.id for s in self.db.query(SpeakerModel).filter(SpeakerModel.video_id == video_id).all()]

        if clip_ids:
            self.db.query(SubtitleModel).filter(SubtitleModel.clip_id.in_(clip_ids)).delete(synchronize_session=False)
        if transcript_ids:
            self.db.query(TranscriptSegmentModel).filter(TranscriptSegmentModel.transcript_id.in_(transcript_ids)).delete(synchronize_session=False)
        if speaker_ids:
            self.db.query(TranscriptSegmentModel).filter(TranscriptSegmentModel.speaker_id.in_(speaker_ids)).update({TranscriptSegmentModel.speaker_id: None}, synchronize_session=False)
        if candidate_ids:
            self.db.query(ClipModel).filter(ClipModel.candidate_id.in_(candidate_ids)).delete(synchronize_session=False)

        self.db.query(ClipModel).filter(ClipModel.video_id == video_id).delete(synchronize_session=False)
        self.db.query(CandidateModel).filter(CandidateModel.video_id == video_id).delete(synchronize_session=False)
        self.db.query(AnalysisResultModel).filter(AnalysisResultModel.video_id == video_id).delete(synchronize_session=False)
        self.db.query(TranscriptModel).filter(TranscriptModel.video_id == video_id).delete(synchronize_session=False)
        self.db.query(SpeakerModel).filter(SpeakerModel.video_id == video_id).delete(synchronize_session=False)
        self.db.query(CacheEntryModel).filter(CacheEntryModel.video_id == video_id).delete(synchronize_session=False)
        self.db.query(HistoryModel).filter(HistoryModel.video_id == video_id).delete(synchronize_session=False)

        if job_ids:
            self.db.query(JobStepModel).filter(JobStepModel.job_id.in_(job_ids)).delete(synchronize_session=False)
            self.db.query(JobModel).filter(JobModel.id.in_(job_ids)).delete(synchronize_session=False)

        # 3. Hapus row video itu sendiri
        self.repo.delete(video_id)
        self.db.commit()
        logger.info("Hard-deleted video %d dan semua data terkait", video_id)
