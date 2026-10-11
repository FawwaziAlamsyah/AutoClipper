"""Preview service for timestamp-based candidate preview."""

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.exceptions.base import NotFoundException, ValidationException
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.video_repository import VideoRepository
from app.services.ffmpeg_service import FFmpegService


class PreviewService:
    """Build lightweight preview data without rendering final clip."""

    def __init__(self, db: Session) -> None:
        """Initialize repositories."""
        self.candidate_repo = CandidateRepository(db)
        self.video_repo = VideoRepository(db)
        self.ffmpeg_service = FFmpegService()

    def get_candidate_preview(self, candidate_id: int) -> dict:
        """Return video path and timestamp range for client-side preview."""
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise NotFoundException(f"Candidate {candidate_id} tidak ditemukan")

        video = self.video_repo.get(candidate.video_id)
        if video is None:
            raise NotFoundException(f"Video {candidate.video_id} tidak ditemukan")

        return {
            "candidate_id": candidate.id,
            "video_id": video.id,
            "video_path": video.file_path,
            "start_time": candidate.start_time,
            "end_time": candidate.end_time,
            "duration": candidate.end_time - candidate.start_time,
            "score": candidate.final_score,
            "hook_text": candidate.hook_text,
        }

    def build_preview_clip_file(self, candidate_id: int, output_path: str) -> str:
        """Generate file preview trim (cached) untuk satu candidate.

        Raise ValidationException dengan pesan jelas kalau video sumbernya sudah
        diarsipkan/filenya hilang — pola sama seperti guard di ClipService.
        """
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise NotFoundException(f"Candidate {candidate_id} tidak ditemukan")

        video = self.video_repo.get(candidate.video_id)
        if video is None:
            raise NotFoundException(f"Video {candidate.video_id} tidak ditemukan")

        if getattr(video, "is_archived", False) or not Path(video.file_path).exists():
            raise ValidationException(
                f"Video dengan ID {video.id} sudah dihapus. Preview tidak tersedia, "
                "tapi data candidate tetap tersimpan untuk training."
            )

        return self.ffmpeg_service.extract_preview_clip(
            video.file_path, candidate.start_time, candidate.end_time, output_path
        )

    def build_candidate_thumbnail_file(self, candidate_id: int, output_path: str) -> str:
        """Generate thumbnail frame (cached JPEG) dari full video untuk candidate card preview."""
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise NotFoundException(f"Candidate {candidate_id} tidak ditemukan")

        video = self.video_repo.get(candidate.video_id)
        if video is None:
            raise NotFoundException(f"Video {candidate.video_id} tidak ditemukan")

        video_path = video.file_path
        if getattr(video, "is_archived", False) or not Path(video_path).exists():
            # Coba fallback ke clip rendered jika ada
            if getattr(candidate, "clips", None):
                for cl in candidate.clips:
                    c_path = getattr(cl, "edited_file_path", None) or getattr(cl, "file_path", None)
                    if c_path and Path(c_path).exists():
                        video_path = c_path
                        break
            if not Path(video_path).exists():
                raise ValidationException(
                    f"Video dengan ID {video.id} sudah dihapus atau tidak ditemukan. "
                    "Thumbnail tidak tersedia."
                )

        duration = candidate.end_time - candidate.start_time
        if duration > 1.5:
            ts = candidate.start_time + 1.0
        elif duration > 0.5:
            ts = candidate.start_time + 0.3
        else:
            ts = candidate.start_time

        # Jika fallback ke clip (bukan video asli), ts dihitung relatif dari 0
        if video_path != video.file_path:
            ts = min(1.0, max(0.0, duration / 2))

        return self.ffmpeg_service.extract_thumbnail(
            video_path, output_path, timestamp=ts
        )

    def build_video_thumbnail_file(
        self, video_id: int, output_path: str, timestamp: float | None = None
    ) -> str:
        """Generate thumbnail frame (cached JPEG) dari full video untuk video card di halaman candidates."""
        video = self.video_repo.get(video_id)
        if video is None:
            raise NotFoundException(f"Video {video_id} tidak ditemukan")

        video_path = video.file_path
        if not Path(video_path).exists():
            raise ValidationException(
                f"File video {video_id} tidak ditemukan di disk: {video_path}"
            )

        if timestamp is None:
            dur = video.duration_seconds or 10.0
            timestamp = min(3.0, max(0.5, dur / 5))

        return self.ffmpeg_service.extract_thumbnail(
            video_path, output_path, timestamp=timestamp
        )


