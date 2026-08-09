"""Transcript orchestration: extract audio → whisper → persist + cache."""

import hashlib
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import NotFoundException
from app.models.cache_entry_model import CacheEntryModel
from app.models.history_model import HistoryModel
from app.models.transcript_model import TranscriptModel
from app.models.transcript_segment_model import TranscriptSegmentModel
from app.models.video_model import VideoModel
from app.repositories.cache_entry_repository import CacheEntryRepository
from app.repositories.transcript_repository import (
    TranscriptRepository,
    TranscriptSegmentRepository,
)
from app.ai_modules.registry import get_analyzer
from app.ai_modules.speech_to_text.whisper_analyzer import WhisperAnalyzer
from app.repositories.video_repository import VideoRepository
from app.services.ffmpeg_service import FFmpegService
from app.services.job_service import JobService

logger = logging.getLogger(__name__)


class TranscriptService:
    """Orchestrates extract + transcribe for a video."""

    def __init__(
        self,
        db: Session,
        ffmpeg: FFmpegService | None = None,
        whisper: WhisperAnalyzer | None = None,
    ) -> None:
        """Initialize with DB and optional tool services (injectable for tests)."""
        self.db = db
        self.video_repo = VideoRepository(db)
        self.transcript_repo = TranscriptRepository(db)
        self.segment_repo = TranscriptSegmentRepository(db)
        self.cache_repo = CacheEntryRepository(db)
        self.job_service = JobService(db)
        self.ffmpeg = ffmpeg or FFmpegService()
        self.whisper = whisper or get_analyzer("whisper")

    def transcribe(
        self,
        video_id: int,
        job_id: int | None = None,
        language: str | None = None,
        force: bool = False,
    ) -> TranscriptModel:
        """Run extract + STT pipeline for a video.

        Uses cache key video:{id}:transcribe to skip re-whisper when possible.
        """
        video = self.video_repo.get(video_id)
        if video is None:
            raise NotFoundException(f"Video {video_id} tidak ditemukan")

        if not force:
            cached = self.transcript_repo.get_by_video(video_id)
            if cached is not None:
                logger.debug("Transcript process: pakai cache transcript %d", cached.id)
                return cached

        job = self.job_service.get(job_id) if job_id else self.job_service.create(video_id)
        logger.debug("Transcript process: mulai untuk video %d (job %d)", video_id, job.id)

        try:
            self._extract_and_update_metadata(video, job.id)
            transcript = self._run_transcribe(video, job.id, language)
            self.job_service.finish_step(job.id, "transcribe", success=True)

            self.db.add(HistoryModel(
                video_id=video_id,
                job_id=job.id,
                action="transcript_completed",
                description=f"Transcript {transcript.id} language={transcript.language}",
            ))
            self.db.commit()
            return transcript
        except Exception as e:
            self.job_service.finish_step(job.id, "transcribe", success=False, error=str(e))
            raise

    def get_by_video(self, video_id: int) -> TranscriptModel:
        """Get latest transcript for video."""
        t = self.transcript_repo.get_by_video(video_id)
        if t is None:
            raise NotFoundException(f"Transcript untuk video {video_id} tidak ditemukan")
        return t

    def get_by_job(self, job_id: int) -> TranscriptModel:
        """Get transcript for a job."""
        t = self.transcript_repo.get_by_job(job_id)
        if t is None:
            raise NotFoundException(f"Transcript untuk job {job_id} tidak ditemukan")
        return t

    def _extract_and_update_metadata(self, video: VideoModel, job_id: int) -> Path:
        """Extract audio WAV; update video metadata from ffprobe."""
        self.job_service.start_step(job_id, "extract")

        try:
            meta = self.ffmpeg.extract_metadata(video.file_path)
            video.duration_seconds = meta.get("duration_seconds")
            video.width = meta.get("width")
            video.height = meta.get("height")
            video.fps = meta.get("fps")
            video.status = "processing"
            self.db.commit()

            audio_path = self._audio_path_for(video)
            cache_key = f"video:{video.id}:audio"

            existing = self.cache_repo.get_by_key(cache_key)
            if existing and existing.file_path and Path(existing.file_path).exists():
                logger.info("Using cached audio: %s", existing.file_path)
                self.job_service.finish_step(job_id, "extract", success=True)
                return Path(existing.file_path)

            self.ffmpeg.extract_audio(video.file_path, str(audio_path))

            if existing is None:
                self.cache_repo.add(CacheEntryModel(
                    cache_key=cache_key,
                    video_id=video.id,
                    step_name="extract",
                    file_path=str(audio_path),
                ))
            else:
                existing.file_path = str(audio_path)
                self.db.commit()

            self.job_service.finish_step(job_id, "extract", success=True)
            return audio_path
        except Exception as e:
            self.job_service.finish_step(job_id, "extract", success=False, error=str(e))
            raise

    def _run_transcribe(self, video: VideoModel, job_id: int, language: str | None) -> TranscriptModel:
        """Run Whisper and persist transcript + segments."""
        self.job_service.start_step(job_id, "transcribe")

        audio_path = self._audio_path_for(video)
        if not audio_path.exists():
            # extract may have been skipped via cache with different path
            cache = self.cache_repo.get_by_key(f"video:{video.id}:audio")
            if cache and cache.file_path:
                audio_path = Path(cache.file_path)
            else:
                audio_path = self._extract_and_update_metadata(video, job_id)

        result = self.whisper.analyze(
            {"audio_path": str(audio_path), "language": language}
        )
        data = result.result_data

        transcript = TranscriptModel(
            video_id=video.id,
            job_id=job_id,
            engine=f"faster-whisper-{settings.WHISPER_MODEL}",
            language=data.get("language"),
            full_text=data.get("full_text", ""),
        )
        transcript = self.transcript_repo.add(transcript)

        for seg in data.get("segments", []):
            conf = None
            words = seg.get("words") or []
            if words:
                conf = sum(w.get("probability", 0) for w in words) / len(words)

            self.segment_repo.add(TranscriptSegmentModel(
                transcript_id=transcript.id,
                start_time=float(seg["start"]),
                end_time=float(seg["end"]),
                text=seg["text"].strip(),
                confidence=conf,
            ))

        self.cache_repo.add(CacheEntryModel(
            cache_key=f"video:{video.id}:transcribe",
            video_id=video.id,
            step_name="transcribe",
            file_path=None,
        ))

        video.status = "ready"
        self.db.commit()
        self.db.refresh(transcript)
        logger.info("Saved transcript %d with %d segments", transcript.id, len(data.get("segments", [])))
        return transcript

    def _audio_path_for(self, video: VideoModel) -> Path:
        """Deterministic cache path for extracted audio."""
        stem = Path(video.file_path).stem
        digest = hashlib.md5(str(video.id).encode()).hexdigest()[:8]
        cache_dir = settings.CACHE_DIR / "audio"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{digest}_{stem}.wav"
