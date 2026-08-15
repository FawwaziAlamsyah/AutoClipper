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
