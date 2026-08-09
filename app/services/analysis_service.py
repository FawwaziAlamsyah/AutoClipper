"""Analysis service: run validators on transcript windows, persist results, build candidates.

This is the real "review" layer. For each candidate window we run all
text-based validators (hook, story, emotion, educational, viral, context,
ending, keyword boost, penalty) and store both the raw per-analyzer scores
(analysis_results) and the final weighted candidate with score_breakdown
including human-readable reasons.
"""

import logging

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.models.analysis_result_model import AnalysisResult
from app.models.candidate_model import Candidate
from app.models.history_model import History
from app.models.transcript_model import Transcript
from app.repositories.analysis_result_repository import AnalysisResultRepository
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.transcript_repository import (
    TranscriptRepository,
    TranscriptSegmentRepository,
)
from app.services.validators import run_all_validators

logger = logging.getLogger(__name__)

WEIGHTS = {
    "hook": settings.SCORE_WEIGHT_HOOK,
    "story": settings.SCORE_WEIGHT_STORY,
    "llm_content": settings.SCORE_WEIGHT_LLM_CONTENT,
    "voice_emotion": settings.SCORE_WEIGHT_VOICE_EMOTION,
    "face_emotion": settings.SCORE_WEIGHT_FACE_EMOTION,
    "gesture": settings.SCORE_WEIGHT_GESTURE,
    "eye_contact": settings.SCORE_WEIGHT_EYE_CONTACT,
    "scene": settings.SCORE_WEIGHT_SCENE,
    "audio": settings.SCORE_WEIGHT_AUDIO,
    "context": settings.SCORE_WEIGHT_CONTEXT,
    "ending": settings.SCORE_WEIGHT_ENDING,
    "keyword_boost": 0.0,
}


class AnalysisService:
    """Slice transcript into windows, validate, score, and persist."""

    def __init__(self, db: Session) -> None:
        """Initialize repos."""
        self.db = db
        self.transcript_repo = TranscriptRepository(db)
        self.segment_repo = TranscriptSegmentRepository(db)
        self.analysis_repo = AnalysisResultRepository(db)
        self.candidate_repo = CandidateRepository(db)

    def analyze_job(
        self,
        job_id: int,
        video_id: int,
        transcript: Transcript,
        num_clips: int = 5,
        min_duration: int | None = None,
        max_duration: int | None = None,
        keywords: list[str] | None = None,
        skip_keywords: list[str] | None = None,
        analyze_start_time: float | None = None,
        analyze_end_time: float | None = None,
    ) -> list[Candidate]:
        """Slice transcript into windows, validate, and create candidates."""
        min_dur = min_duration or settings.DEFAULT_MIN_CLIP_DURATION
        max_dur = max_duration or settings.DEFAULT_MAX_CLIP_DURATION
        keywords = keywords or []
        skip_keywords = skip_keywords or []

        segments = self.segment_repo.get_by_transcript(transcript.id)
        if not segments:
            logger.warning("No segments for transcript %d", transcript.id)
            return []

        if analyze_start_time is not None or analyze_end_time is not None:
            start = analyze_start_time if analyze_start_time is not None else -1.0
            end = analyze_end_time if analyze_end_time is not None else float("inf")
            segments = [s for s in segments if s.end_time >= start and s.start_time <= end]
            if not segments:
                logger.warning("Analyze range memfilter semua segmen untuk transcript %d", transcript.id)
                return []

        windows = self._build_windows(segments, num_clips, min_dur, max_dur)

        candidates = []
        for window in windows:
            text = " ".join(seg.text for seg in window["segments"])
            scores = run_all_validators(text, keywords, skip_keywords)
            final_score, breakdown = self._merge_scores(scores)

            for analyzer_type, payload in scores.items():
                self.analysis_repo.add(AnalysisResult(
                    video_id=video_id,
                    job_id=job_id,
                    analyzer_type=analyzer_type,
                    start_time=window["start"],
                    end_time=window["end"],
                    score=payload["score"],
                    result_data={"reason": payload["reason"]},
                ))

            candidate = self.candidate_repo.add(Candidate(
                video_id=video_id,
                job_id=job_id,
                start_time=window["start"],
                end_time=window["end"],
                final_score=final_score,
                score_breakdown=breakdown,
                hook_text=window["segments"][0].text.strip()[:120],
                status="candidate",
            ))
            candidates.append(candidate)

        logger.info("Created %d candidates for job %d", len(candidates), job_id)
        return candidates

    def _build_windows(
        self,
        segments: list,
        num_clips: int,
        min_dur: float,
        max_dur: float,
    ) -> list[dict]:
        """Group transcript segments into candidate time windows.

        Simple sliding-window: pick the N segments-sets spread across the
        transcript, each sized to the target duration.
        """
        total_duration = segments[-1].end_time - segments[0].start_time
        if total_duration <= 0:
            total_duration = 60.0

        target = min(max_dur, max(min_dur, total_duration / max(num_clips, 1)))
        windows = []
        cursor = segments[0].start_time

        while len(windows) < num_clips and cursor < segments[-1].end_time:
            win_start = cursor
            win_end = min(cursor + target, segments[-1].end_time)
            win_segments = [
                s for s in segments
                if s.start_time >= win_start and s.start_time < win_end
            ]
            if win_segments:
                windows.append({
                    "start": win_start,
                    "end": win_end,
                    "segments": win_segments,
                })
            cursor = win_end

        return windows

    def _merge_scores(self, scores: dict[str, dict]) -> tuple[float, dict]:
        """Weighted merge of validator scores into 0-100 final score."""
        breakdown: dict[str, dict] = {}
        total = 0.0
        weight_sum = 0.0

        for name, payload in scores.items():
            weight = WEIGHTS.get(name, 0.0)
            contribution = payload["score"] * weight
            breakdown[name] = {
                "score": payload["score"],
                "reason": payload["reason"],
                "weight": weight,
                "contribution": round(contribution, 2),
            }
            total += contribution
            weight_sum += weight

        # keyword boost & penalty handled inside validators; add raw bonus
        if "keyword_boost" in scores:
            bonus = (scores["keyword_boost"]["score"] - 5.0) * 0.02
            total += bonus
        if "penalty" in scores:
            total += scores["penalty"]["score"] * 0.1

        final = max(0.0, min(100.0, total * 10.0))
        return round(final, 2), breakdown
