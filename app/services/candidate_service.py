"""Candidate clip generation service."""

import logging

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.models.candidate_model import CandidateModel
from app.models.video_model import VideoModel
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.job_repository import JobRepository
from app.repositories.video_repository import VideoRepository
from app.models.clip_model import ClipModel
from app.models.subtitle_model import SubtitleModel
from app.services.score_engine import ScoreEngine

logger = logging.getLogger(__name__)


class CandidateService:
    """Generate candidate clips from scored segments."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.db = db
        self.video_repo = VideoRepository(db)
        self.job_repo = JobRepository(db)
        self.candidate_repo = CandidateRepository(db)
        self.score_engine = ScoreEngine(db)

    def generate_candidates(self, job_id: int, num_clips: int = 5) -> list[CandidateModel]:
        """Generate top-N candidate clips based on scores.

        Returns list of candidates with:
        - start_time, end_time
        - final_score
        - hook_text (if any)
        - status: 'candidate'
        """
        job = self.job_repo.get(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        video = self.video_repo.get(job.video_id)
        if video is None:
            raise ValueError(f"Video {job.video_id} not found")

        # Run score engine to populate candidate scores
        self.score_engine.calculate_for_job(job_id)

        # select_top_n menangani pemilihan top-N non-overlap (bukan slice manual)
        candidates = self.score_engine.select_top_n(job_id, num_clips)

        logger.info("Generated %d candidates for job %d", len(candidates), job_id)
        return candidates

    def get_candidate(self, candidate_id: int) -> CandidateModel:
        """Get a single candidate by ID."""
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        return candidate

    def get_candidates(self, job_id: int, limit: int = 10) -> list[CandidateModel]:
        """Get candidates for a job."""
        return self.candidate_repo.get_by_job(job_id)[:limit]

    def list_by_video(self, video_id: int) -> list[CandidateModel]:
        """Return all candidates for a specific video, sorted by score desc.

        Candidate dari job_type="training_ingest" DIKECUALIKAN.
        """
        from app.models.job_model import JobModel

        candidates = list(
            self.db.query(CandidateModel)
            .join(JobModel, CandidateModel.job_id == JobModel.id)
            .filter(
                CandidateModel.video_id == video_id,
                JobModel.job_type != "training_ingest",
            )
            .order_by(CandidateModel.final_score.desc())
            .all()
        )
        # Refresh tiap object supaya semua kolom termasuk label_source ter-load
        for c in candidates:
            self.db.refresh(c)
        return candidates

    def get_video_summaries(self) -> list[dict]:
        """Return per-video summary: video info + candidate counts + top score."""
        from app.models.job_model import JobModel
        from app.models.video_model import VideoModel

        videos = self.db.query(VideoModel).order_by(VideoModel.id.desc()).all()
        result = []
        for video in videos:
            candidates = (
                self.db.query(CandidateModel)
                .join(JobModel, CandidateModel.job_id == JobModel.id)
                .filter(
                    CandidateModel.video_id == video.id,
                    JobModel.job_type != "training_ingest",
                )
                .all()
            )
            if not candidates:
                continue
            top_score = max((c.final_score or 0.0) for c in candidates)
            liked = sum(1 for c in candidates if c.label_source == "user_liked")
            disliked = sum(1 for c in candidates if c.label_source == "user_disliked")
            clips_done = sum(1 for c in candidates if c.status in ("selected",))
            result.append({
                "video": video,
                "candidate_count": len(candidates),
                "top_score": round(top_score, 2),
                "liked": liked,
                "disliked": disliked,
                "clips_done": clips_done,
            })
        return result

    def get_completed_clips(self, candidate_ids: list[int]) -> dict[int, ClipModel]:
        """Map candidate_id -> completed clip for the given candidates."""
        if not candidate_ids:
            return {}
        clips = self.db.query(ClipModel).filter(
            ClipModel.candidate_id.in_(candidate_ids),
            ClipModel.status == "completed",
        ).all()
        return {clip.candidate_id: clip for clip in clips}

    def select_candidate(self, candidate_id: int) -> CandidateModel:
        """Mark a candidate as selected for clipping."""
        candidate = self.candidate_repo.update_status(candidate_id, "selected")
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        return candidate

    def reject_candidate(self, candidate_id: int) -> CandidateModel:
        """Mark a candidate as rejected."""
        candidate = self.candidate_repo.update_status(candidate_id, "rejected")
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        return candidate

    def categorize(self, candidate_id: int, category_id: int) -> CandidateModel:
        """Tandai candidate sebagai contoh POSITIF untuk kategori tertentu."""
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        candidate.actual_score = settings.LIKED_CLIP_DEFAULT_SCORE
        candidate.is_training_example = True
        candidate.label_source = "user_liked"
        candidate.category_id = category_id
        self.db.commit()
        self.db.refresh(candidate)
        logger.info("Candidate %d ditandai contoh kategori %d", candidate_id, category_id)
        return candidate

    def uncategorize(self, candidate_id: int) -> CandidateModel:
        """Batalkan penandaan kategori — kembalikan ke kondisi bukan training example."""
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        if candidate.label_source == "user_liked":
            candidate.actual_score = None
            candidate.is_training_example = False
            candidate.label_source = None
            candidate.category_id = None
            self.db.commit()
            self.db.refresh(candidate)
        return candidate

    def mark_as_disliked(self, candidate_id: int) -> CandidateModel:
        """Tandai candidate sebagai clip JELEK — cuma penanda kualitas, TIDAK
        dipakai sebagai data training (beda dari desain lama). Cukup untuk
        menyembunyikan/menandai, fokus training murni dari kategori positif.
        """
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        candidate.label_source = "user_disliked"
        # is_training_example & actual_score SENGAJA tidak diisi — dislike
        # tidak lagi berkontribusi ke data training sama sekali.
        self.db.commit()
        self.db.refresh(candidate)
        logger.info("Candidate %d ditandai jelek (bukan data training)", candidate_id)
        return candidate

    def unmark_disliked(self, candidate_id: int) -> CandidateModel:
        """Batalkan status disliked — kembalikan ke kondisi bukan training example."""
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        if candidate.label_source == "user_disliked":
            candidate.actual_score = None
            candidate.is_training_example = False
            candidate.label_source = None
            self.db.commit()
            self.db.refresh(candidate)
        return candidate

    def delete_candidate(self, candidate_id: int) -> None:
        """Delete a candidate dan clip terkait (FK-safe)."""
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        # Hapus subtitle + clip dari candidate ini (FK-safe order)
        clip_ids = [c.id for c in self.db.query(ClipModel).filter(ClipModel.candidate_id == candidate_id).all()]
        if clip_ids:
            self.db.query(SubtitleModel).filter(SubtitleModel.clip_id.in_(clip_ids)).delete(synchronize_session=False)
            self.db.query(ClipModel).filter(ClipModel.id.in_(clip_ids)).delete(synchronize_session=False)
        else:
            self.db.query(ClipModel).filter(ClipModel.candidate_id == candidate_id).delete(synchronize_session=False)

        self.db.delete(candidate)
        self.db.commit()
        logger.info("Deleted candidate %d", candidate_id)
