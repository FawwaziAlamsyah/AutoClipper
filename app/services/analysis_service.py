"""Analysis service: run validators on transcript windows, persist results, build candidates.

Text validators (hook, story, context, ending, viral, keyword boost, penalty)
tetap dijalankan via `run_all_validators`. Analyzer AI (llm_content, face_emotion)
dipanggil lewat registry plugin — menambah analyzer baru berarti daftar di
`app/ai_modules/registry.py` + satu entry di PLUGIN_ANALYZERS di bawah ini.
"""

import logging

from sqlalchemy.orm import Session

from app.ai_modules.base.analyzer_interface import AnalyzerUnavailable
from app.ai_modules.registry import get_analyzer
from app.core.config.settings import settings
from app.models.analysis_result_model import AnalysisResultModel
from app.models.candidate_model import CandidateModel
from app.models.history_model import HistoryModel
from app.models.transcript_model import TranscriptModel
from app.repositories.analysis_result_repository import AnalysisResultRepository
from app.repositories.cache_entry_repository import CacheEntryRepository
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.transcript_repository import (
    TranscriptRepository,
    TranscriptSegmentRepository,
)
from app.repositories.video_repository import VideoRepository
from app.services.job_service import JobService
from app.services.validators import run_all_validators

logger = logging.getLogger(__name__)

# Cap jumlah window per job — sliding window video panjang bisa menghasilkan
# ratusan window; downsampled merata agar tetap men-scan seluruh durasi.
MAX_WINDOWS_PER_JOB = 150


class AnalysisService:
    """Slice transcript into windows, validate, score, and persist."""

    def __init__(self, db: Session) -> None:
        """Initialize repos."""
        self.db = db
        self.transcript_repo = TranscriptRepository(db)
        self.segment_repo = TranscriptSegmentRepository(db)
        self.analysis_repo = AnalysisResultRepository(db)
        self.candidate_repo = CandidateRepository(db)
        self.video_repo = VideoRepository(db)
        self.cache_repo = CacheEntryRepository(db)
        self.job_service = JobService(db)

    def analyze_job(
        self,
        job_id: int,
        video_id: int,
        transcript: TranscriptModel,
        num_clips: int = 5,
        min_duration: int | None = None,
        max_duration: int | None = None,
        keywords: list[str] | None = None,
        skip_keywords: list[str] | None = None,
        analyze_start_time: float | None = None,
        analyze_end_time: float | None = None,
    ) -> list[CandidateModel]:
        """Slice transcript into windows, validate, and create candidates."""
        min_dur = min_duration or settings.DEFAULT_MIN_CLIP_DURATION
        max_dur = max_duration or settings.DEFAULT_MAX_CLIP_DURATION
        keywords = keywords or []
        skip_keywords = skip_keywords or []

        video = self.video_repo.get(video_id)
        video_path = video.file_path if video else None

        # Audio hasil extract disimpan di cache (key sama dengan transcript_service)
        audio_entry = self.cache_repo.get_by_key(f"video:{video_id}:audio")
        audio_path = audio_entry.file_path if audio_entry else None

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

        # Sliding window menyapu SELURUH durasi video dengan overlap — semua
        # kandidat dihasilkan, lalu score_engine.select_top_n() yang memilih
        # top-N non-overlap setelah scoring.
        windows = self._build_windows(segments, min_dur, max_dur)

        # Text validators (per window) + buat candidates
        candidates = []
        window_texts = []
        for window in windows:
            text = " ".join(seg.text for seg in window["segments"])
            window_texts.append(text)
            scores = run_all_validators(text, keywords, skip_keywords)

            for analyzer_type, payload in scores.items():
                self.analysis_repo.add(AnalysisResultModel(
                    video_id=video_id,
                    job_id=job_id,
                    analyzer_type=analyzer_type,
                    start_time=window["start"],
                    end_time=window["end"],
                    score=payload["score"],
                    result_data={"reason": payload["reason"]},
                ))

            # Candidate tanpa final_score/score_breakdown — score_engine yang akan isi nanti
            candidate = self.candidate_repo.add(CandidateModel(
                video_id=video_id,
                job_id=job_id,
                start_time=window["start"],
                end_time=window["end"],
                final_score=0.0,
                score_breakdown={},
                hook_text=window["segments"][0].text.strip()[:120],
                status="candidate",
            ))
            candidates.append(candidate)

        # Plugin analyzer: tiap analyzer di-start sekali, jalankan semua windows,
        # lalu di-finish. Pencatatan job step per-analyzer.
        self._run_plugin_analyzers(windows, window_texts, video_path, audio_path, video_id, job_id)

        logger.info("Created %d candidates for job %d", len(candidates), job_id)
        return candidates

    def _run_plugin_analyzers(
        self,
        windows: list[dict],
        window_texts: list[str],
        video_path: str | None,
        audio_path: str | None,
        video_id: int,
        job_id: int,
    ) -> None:
        """Jalankan semua plugin analyzer lewat registry.

        Untuk tiap analyzer: catat start_step (job step), jalankan di semua
        window, lalu finish_step. Analyzer yang tak tersedia di-skip.
        """
        input_builders = {
            "llm_content": lambda w, i: {"transcript_text": window_texts[i]},
            "face_emotion": (
                lambda w, i: {"video_path": video_path, "start": w["start"], "end": w["end"]}
                if video_path
                else None
            ),
            "gesture": (
                lambda w, i: {"video_path": video_path, "start": w["start"], "end": w["end"]}
                if video_path
                else None
            ),
            "eye_contact": (
                lambda w, i: {"video_path": video_path, "start": w["start"], "end": w["end"]}
                if video_path
                else None
            ),
            "scene": (
                lambda w, i: {"video_path": video_path, "start": w["start"], "end": w["end"]}
                if video_path
                else None
            ),
            "voice_emotion": (
                lambda w, i: {"audio_path": audio_path, "start": w["start"], "end": w["end"]}
                if audio_path
                else None
            ),
            "audio": (
                lambda w, i: {"audio_path": audio_path, "start": w["start"], "end": w["end"]}
                if audio_path
                else None
            ),
        }

        for analyzer_type, build in input_builders.items():
            analyzer = get_analyzer(analyzer_type)
            if analyzer is None:
                continue

            logger.debug("Analyze process: step %s start", analyzer_type)
            self.job_service.start_step(job_id, analyzer_type)
            success_count = 0
            total_windows = 0

            for i, window in enumerate(windows):
                input_data = build(window, i)
                if input_data is None:
                    continue
                total_windows += 1
                try:
                    result = analyzer.analyze(input_data)
                except AnalyzerUnavailable as e:
                    logger.warning("Skip analyzer %s di window %d: %s", analyzer_type, i, e)
                    continue
                self.analysis_repo.add(AnalysisResultModel(
                    video_id=video_id,
                    job_id=job_id,
                    analyzer_type=analyzer_type,
                    start_time=window["start"],
                    end_time=window["end"],
                    score=result.score,
                    result_data=result.result_data,
                ))
                success_count += 1

            self.job_service.finish_step(job_id, analyzer_type, success=success_count > 0)
            logger.info(
                "Analyzer %s: %d/%d window berhasil untuk job %d",
                analyzer_type, success_count, total_windows, job_id,
            )

    def _build_windows(
        self,
        segments: list,
        min_dur: float,
        max_dur: float,
        stride_ratio: float = 0.5,
    ) -> list[dict]:
        """Scan seluruh transcript dengan sliding window yang overlap.

        Window duration = max_dur (durasi target terpanjang). Stride = stride_ratio
        × window duration, sehingga window saling overlap dan tidak ada bagian
        video yang terlewat hanya karena posisinya di tengah/akhir.

        Tidak dibatasi num_clips di sini — semua window kandidat dihasilkan,
        lalu score_engine.select_top_n() yang memilih & menghapus non-top setelah
        scoring. Video sangat panjang di-downsample merata ke MAX_WINDOWS_PER_JOB.
        """
        if not segments:
            return []

        video_start = segments[0].start_time
        video_end = segments[-1].end_time
        window_dur = max_dur
        stride = max(window_dur * stride_ratio, 1.0)

        windows = []
        cursor = video_start
        while cursor < video_end:
            win_start = cursor
            win_end = min(cursor + window_dur, video_end)

            # Buang window terakhir yang kepotong terlalu pendek (< min_dur),
            # kecuali itu satu-satunya window yang ada.
            if (win_end - win_start) < min_dur and windows:
                break

            win_segments = [
                s for s in segments
                if s.start_time < win_end and s.end_time > win_start
            ]
            if win_segments:
                windows.append({"start": win_start, "end": win_end, "segments": win_segments})

            cursor += stride

        # Safety limit: video panjang → banyak window. Downsample merata.
        if len(windows) > MAX_WINDOWS_PER_JOB:
            step = len(windows) / MAX_WINDOWS_PER_JOB
            windows = [windows[int(i * step)] for i in range(MAX_WINDOWS_PER_JOB)]

        return windows
