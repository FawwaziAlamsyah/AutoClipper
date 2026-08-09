"""Score engine: aggregate analyzer scores into weighted final score."""

import logging

from app.core.config.settings import settings
from app.models.candidate_model import CandidateModel
from app.models.clip_model import ClipModel
from app.repositories.analysis_result_repository import AnalysisResultRepository
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.job_repository import JobRepository
from app.repositories.video_repository import VideoRepository

logger = logging.getLogger(__name__)


class ScoreEngine:
    """Aggregate and weight scores from various analyzers."""

    def __init__(self, db):
        """Initialize with DB session and repos."""
        self.db = db
        self.video_repo = VideoRepository(db)
        self.job_repo = JobRepository(db)
        self.analysis_repo = AnalysisResultRepository(db)
        self.candidate_repo = CandidateRepository(db)

    def calculate_for_job(self, job_id: int) -> float:
        """Calculate weighted score for all candidates in a job.

        Weights (configurable via settings):
        - LLM Content: 30%
        - Hook: 10%
        - Story: 15%
        - Voice Emotion: 10%
        - Face Emotion: 8%
        - Gesture: 5%
        - Eye Contact: 3%
        - Scene: 4%
        - Audio: 5%
        - Context: 5%
        - Ending: 5%
        """
        job = self.job_repo.get(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        candidates = self.candidate_repo.get_by_job(job_id)
        if not candidates:
            logger.warning("No candidates found for job %d", job_id)
            return 0.0

        for candidate in candidates:
            breakdown = self._calculate_score_breakdown(job_id, candidate)
            final_score = sum(v["contribution"] for v in breakdown.values())

            candidate.final_score = final_score
            candidate.score_breakdown = breakdown

        self.db.commit()
        return candidates[0].final_score if candidates else 0.0

    def select_top_n(self, job_id: int, n: int) -> list:
        """Simpan top-n candidate dengan final_score tertinggi, TANPA overlap satu
        sama lain (non-max suppression berbasis waktu), hapus sisanya.

        Window yang overlap satu sama lain (hasil sliding window Task 1) bisa
        punya konten nyaris sama — suppression memastikan top-N adalah momen
        berbeda, bukan geser beberapa detik. Return selected (sorted desc).
        """
        candidates = self.candidate_repo.get_by_job(job_id)
        if not candidates:
            return []

        ranked = sorted(candidates, key=lambda c: c.final_score or 0.0, reverse=True)

        selected: list = []
        for cand in ranked:
            overlaps = any(
                cand.start_time < kept.end_time and cand.end_time > kept.start_time
                for kept in selected
            )
            if not overlaps:
                selected.append(cand)
            if len(selected) >= n:
                break

        drop = [c for c in candidates if c not in selected]
        drop_ids = [c.id for c in drop]
        if drop_ids:
            self.db.query(ClipModel).filter(ClipModel.candidate_id.in_(drop_ids)).delete(synchronize_session=False)
            self.db.query(CandidateModel).filter(CandidateModel.id.in_(drop_ids)).delete(synchronize_session=False)
            self.db.commit()
            logger.info(
                "Dropped %d overlapping/low-score candidate(s) dari job %d, simpan top %d",
                len(drop_ids), job_id, len(selected),
            )

        return selected

    def _calculate_score_breakdown(self, job_id: int, candidate) -> dict[str, dict]:
        """Calculate weighted score components for a candidate.

        Setiap analyzer jadi dict: {score, weight, contribution, reason}.
        Analyzer dengan bobot 0 dilewati. Analyzer yang TIDAK PERNAH menghasilkan
        result di seluruh job dianggap tidak aktif — bobotnya di-exclude.

        PENTING: analysis difilter per window candidate (start_time range) —
        bukan rata-rata seluruh job. Tanpa filter ini, semua candidate dapat skor
        identik (rata-rata global) — persis bug skor seragam.
        """
        analysis = self.analysis_repo.get_by_job(job_id)

        # Analyzer yang sama sekali tidak punya result di seluruh job ini dianggap
        # tidak aktif untuk job ini — bobotnya di-exclude, bukan 0.5 ke semua window.
        active_types = {a.analyzer_type for a in analysis}

        weights = {
            "llm_content": settings.SCORE_WEIGHT_LLM_CONTENT,
            "hook": settings.SCORE_WEIGHT_HOOK,
            "story": settings.SCORE_WEIGHT_STORY,
            "voice_emotion": settings.SCORE_WEIGHT_VOICE_EMOTION,
            "face_emotion": settings.SCORE_WEIGHT_FACE_EMOTION,
            "gesture": settings.SCORE_WEIGHT_GESTURE,
            "eye_contact": settings.SCORE_WEIGHT_EYE_CONTACT,
            "scene": settings.SCORE_WEIGHT_SCENE,
            "audio": settings.SCORE_WEIGHT_AUDIO,
            "context": settings.SCORE_WEIGHT_CONTEXT,
            "ending": settings.SCORE_WEIGHT_ENDING,
        }

        # Filter analysis ke window candidate ini saja (overlap check).
        cand_analysis = [
            a for a in analysis
            if (a.start_time is None or a.start_time < candidate.end_time)
            and (a.end_time is None or a.end_time > candidate.start_time)
        ]

        breakdown = {}
        for analyzer_type, weight in weights.items():
            if weight <= 0 or analyzer_type not in active_types:
                continue
            score = self._get_analyzer_score(cand_analysis, analyzer_type)
            breakdown[analyzer_type] = {
                "score": score,
                "weight": weight,
                "contribution": round(score * weight, 2),
                "reason": self._get_reason(cand_analysis, analyzer_type),
            }

        # Penalty for skip keywords (simplified: subtract 0.5 per keyword match)
        penalty = self._calculate_penalty(cand_analysis)
        if penalty > 0:
            breakdown["penalty"] = {
                "score": penalty,
                "weight": 0.0,
                "contribution": round(-abs(penalty), 2),
                "reason": self._get_reason(cand_analysis, "penalty") or "Konten spam/CTA terdeteksi",
            }

        return breakdown

    def _get_reason(self, analysis: list, analyzer_type: str) -> str:
        """Ambil reason dari result_data analysis terakhir untuk analyzer type."""
        reason = ""
        for a in analysis:
            if a.analyzer_type == analyzer_type and a.result_data:
                reason = a.result_data.get("reason", "")
        return reason

    def _get_analyzer_score(self, analysis: list, analyzer_type: str) -> float:
        """Extract average score from analyzer results (per-window, sudah di-filter)."""
        results = [a for a in analysis if a.analyzer_type == analyzer_type]
        if not results:
            return 0.5  # Default neutral score

        return sum(r.score or 0 for r in results) / len(results)

    def _calculate_penalty(self, analysis: list) -> float:
        """Calculate penalty for skip keywords."""
        penalties = {
            "sponsor": 0.5,
            "intro": 0.5,
            "outro": 0.5,
            "cta": 0.3,
            "dead air": 0.2,
            "silence": 0.2,
        }

        total_penalty = 0.0
        for a in analysis:
            result_data = a.result_data or {}
            if "keyword" in result_data:
                for kw, val in penalties.items():
                    if kw in result_data["keyword"].lower():
                        total_penalty += val

        return total_penalty
