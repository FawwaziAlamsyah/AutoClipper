"""Repository for Transcript and TranscriptSegment models."""

from app.models.transcript_model import Transcript
from app.models.transcript_segment_model import TranscriptSegment
from app.repositories.base_repository import PostgresRepository


class TranscriptRepository(PostgresRepository[Transcript]):
    """PostgreSQL repository for transcripts."""

    model_class = Transcript

    def get_by_video(self, video_id: int) -> Transcript | None:
        """Get the latest transcript for a video."""
        return (
            self.db.query(Transcript)
            .filter(Transcript.video_id == video_id)
            .order_by(Transcript.created_at.desc())
            .first()
        )

    def get_by_job(self, job_id: int) -> Transcript | None:
        """Get transcript for a specific job."""
        return self.db.query(Transcript).filter(Transcript.job_id == job_id).first()


class TranscriptSegmentRepository(PostgresRepository[TranscriptSegment]):
    """PostgreSQL repository for transcript segments."""

    model_class = TranscriptSegment

    def get_by_transcript(self, transcript_id: int) -> list[TranscriptSegment]:
        """Get all segments for a transcript."""
        return list(
            self.db.query(TranscriptSegment)
            .filter(TranscriptSegment.transcript_id == transcript_id)
            .order_by(TranscriptSegment.start_time)
            .all()
        )
