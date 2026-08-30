"""All SQLAlchemy ORM models — import here so Alembic and Base.metadata see them."""

from app.models.video_model import VideoModel
from app.models.job_model import JobModel
from app.models.job_step_model import JobStepModel
from app.models.transcript_model import TranscriptModel
from app.models.transcript_segment_model import TranscriptSegmentModel
from app.models.speaker_model import SpeakerModel
from app.models.analysis_result_model import AnalysisResultModel
from app.models.candidate_model import CandidateModel
from app.models.clip_model import ClipModel
from app.models.subtitle_model import SubtitleModel
from app.models.history_model import HistoryModel
from app.models.cache_entry_model import CacheEntryModel
from app.models.training_run_model import TrainingRunModel
from app.models.category_model import CategoryModel
from app.models.tiktok_account_model import TikTokAccountModel

__all__ = [
    "VideoModel",
    "JobModel",
    "JobStepModel",
    "TranscriptModel",
    "TranscriptSegmentModel",
    "SpeakerModel",
    "AnalysisResultModel",
    "CandidateModel",
    "ClipModel",
    "SubtitleModel",
    "HistoryModel",
    "CacheEntryModel",
    "TrainingRunModel",
    "TikTokAccountModel",
]
