"""Repository for Transcript and TranscriptSegment models."""

from app.models.transcript_model import TranscriptModel
from app.models.transcript_segment_model import TranscriptSegmentModel
from app.repositories.base_repository import PostgresRepository


class TranscriptRepository(PostgresRepository[TranscriptModel]):
    """PostgreSQL repository for transcripts."""

    model_class = TranscriptModel

    def get_by_video(self, video_id: int) -> TranscriptModel | None:
        """Get the latest transcript for a video."""
        return (
            self.db.query(TranscriptModel)
            .filter(TranscriptModel.video_id == video_id)
            .order_by(TranscriptModel.created_at.desc())
            .first()
        )

    def get_by_job(self, job_id: int) -> TranscriptModel | None:
        """Get transcript for a specific job."""
        return self.db.query(TranscriptModel).filter(TranscriptModel.job_id == job_id).first()


class TranscriptSegmentRepository(PostgresRepository[TranscriptSegmentModel]):
    """PostgreSQL repository for transcript segments."""

    model_class = TranscriptSegmentModel

    def get_by_transcript(self, transcript_id: int) -> list[TranscriptSegmentModel]:
        """Get all segments for a transcript."""
        return list(
            self.db.query(TranscriptSegmentModel)
            .filter(TranscriptSegmentModel.transcript_id == transcript_id)
            .order_by(TranscriptSegmentModel.start_time)
            .all()
        )
