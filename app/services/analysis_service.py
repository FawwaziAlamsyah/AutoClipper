"""Analysis service: run validators on transcript windows, persist results, build candidates.

Text validators (hook, story, context, ending, viral, keyword boost, penalty)
tetap dijalankan via `run_all_validators`. Analyzer AI (llm_content, face_emotion)
dipanggil lewat registry plugin — menambah analyzer baru berarti daftar di
`app/ai_modules/registry.py` + satu entry di PLUGIN_ANALYZERS di bawah ini.
"""

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai_modules.base.analyzer_interface import AnalyzerUnavailable
from app.ai_modules.registry import get_analyzer
from app.core.config.settings import settings
from app.models.analysis_result_model import AnalysisResultModel
from app.models.cache_entry_model import CacheEntryModel
from app.models.candidate_model import CandidateModel
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

# Keempat analyzer visual yang digabung dalam single-pass VideoVisionPass
_VISUAL_ANALYZER_TYPES = {"face_emotion", "eye_contact", "gesture", "scene"}


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

        # Pilih mode window berdasarkan job_type:
        # - training_ingest: satu window mencakup seluruh durasi clip (clip sudah jadi momen terbaik)
        # - discovery (default): sliding window untuk men-scan raw stream panjang
        job = self.job_service.get(job_id)
        if job.job_type == "training_ingest":
            windows = [{
                "start": segments[0].start_time,
                "end": segments[-1].end_time,
                "segments": segments,
            }]
        else:
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

        Untuk keempat analyzer visual (face_emotion, eye_contact, gesture, scene),
        bila USE_VIDEO_VISION_PASS=True digunakan VideoVisionPass — satu pass decode
        per window alih-alih 4 VideoCapture+seek terpisah (~3-4× lebih cepat).

        Jalur lama (4 VideoCapture terpisah) tetap tersedia dan dipakai bila
        USE_VIDEO_VISION_PASS=False (untuk A/B comparison).

        Untuk semua analyzer lain (llm_content, voice_emotion, audio), jalur lama
        tidak berubah.
        """
        if settings.USE_VIDEO_VISION_PASS and video_path:
            self._run_visual_analyzers_single_pass(windows, video_path, video_id, job_id)
        else:
            # Jalur lama: 4 VideoCapture terpisah per window
            self._run_visual_analyzers_legacy(windows, video_path, video_id, job_id)

        # Analyzer non-visual (llm_content, voice_emotion, audio) — tidak berubah
        non_visual_builders = {
            "llm_content": lambda w, i: {"transcript_text": window_texts[i]},
            "voice_emotion": (
                lambda w, i: {"audio_path": audio_path, "start": w["start"], "end": w["end"]}
                if audio_path else None
            ),
            "audio": (
                lambda w, i: {"audio_path": audio_path, "start": w["start"], "end": w["end"]}
                if audio_path else None
            ),
        }

        for analyzer_type, build in non_visual_builders.items():
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

    def _run_visual_analyzers_single_pass(
        self,
        windows: list[dict],
        video_path: str,
        video_id: int,
        job_id: int,
    ) -> None:
        """Jalankan 4 analyzer visual via VideoVisionPass — 1 VideoCapture per window.

        Bila USE_VISION_PROXY=True, generate proxy video 480p (atau sesuai
        VISION_PROXY_HEIGHT) terlebih dahulu. Proxy di-cache di DB agar tidak
        di-generate ulang untuk job berikutnya pada video yang sama.

        job_service start_step / finish_step tetap dipanggil per analyzer_type
        agar progress bar UI tidak berubah kontraknya.
        """
        from app.ai_modules.video_vision_pass import VideoVisionPass
        from app.services.ffmpeg_service import FFmpegService

        # ── Tentukan video yang akan di-decode (proxy atau asli) ─────────────
        decode_path = video_path

        if settings.USE_VISION_PROXY:
            proxy_cache_key = f"video:{video_id}:vision_proxy"
            existing_proxy = self.cache_repo.get_by_key(proxy_cache_key)

            if existing_proxy and existing_proxy.file_path and \
                    Path(existing_proxy.file_path).exists():
                decode_path = existing_proxy.file_path
                logger.info(
                    "Vision proxy reuse dari cache untuk video %d: %s",
                    video_id, decode_path,
                )
            else:
                # Generate proxy baru
                proxy_dir = settings.CACHE_DIR / "vision_proxy"
                proxy_dir.mkdir(parents=True, exist_ok=True)
                proxy_output = str(proxy_dir / f"video_{video_id}_proxy.mp4")

                try:
                    ffmpeg = FFmpegService()
                    ffmpeg.generate_vision_proxy(
                        video_path,
                        proxy_output,
                        height=settings.VISION_PROXY_HEIGHT,
                    )
                    decode_path = proxy_output

                    # Simpan ke cache DB
                    if existing_proxy is None:
                        self.cache_repo.add(CacheEntryModel(
                            cache_key=proxy_cache_key,
                            video_id=video_id,
                            step_name="vision_proxy",
                            file_path=proxy_output,
                        ))
                    else:
                        existing_proxy.file_path = proxy_output
                        self.db.commit()

                    logger.info(
                        "Vision proxy generated dan di-cache untuk video %d: %s",
                        video_id, proxy_output,
                    )
                except Exception as e:
                    logger.warning(
                        "Vision proxy generation gagal untuk video %d: %s. "
                        "Fallback ke video asli.",
                        video_id, e,
                    )
                    decode_path = video_path  # fallback ke video asli

        # ── Start semua 4 step sebelum loop ──────────────────────────────────
        for atype in _VISUAL_ANALYZER_TYPES:
            self.job_service.start_step(job_id, atype)

        # Satu instance VideoVisionPass per job — model MediaPipe di-build sekali
        vvp = VideoVisionPass()
        counts: dict[str, int] = {atype: 0 for atype in _VISUAL_ANALYZER_TYPES}

        for i, window in enumerate(windows):
            try:
                results = vvp.analyze_window(
                    decode_path,
                    window["start"],
                    window["end"],
                )
            except AnalyzerUnavailable as e:
                logger.warning(
                    "VideoVisionPass skip window %d [%.1f-%.1f]: %s",
                    i, window["start"], window["end"], e,
                )
                continue

            for atype, result in results.items():
                self.analysis_repo.add(AnalysisResultModel(
                    video_id=video_id,
                    job_id=job_id,
                    analyzer_type=atype,
                    start_time=window["start"],
                    end_time=window["end"],
                    score=result.score,
                    result_data=result.result_data,
                ))
                counts[atype] += 1

        for atype in _VISUAL_ANALYZER_TYPES:
            self.job_service.finish_step(job_id, atype, success=counts[atype] > 0)
            logger.info(
                "VideoVisionPass %s: %d/%d window berhasil untuk job %d",
                atype, counts[atype], len(windows), job_id,
            )

    def _run_visual_analyzers_legacy(
        self,
        windows: list[dict],
        video_path: str | None,
        video_id: int,
        job_id: int,
    ) -> None:
        """Jalur lama: 4 VideoCapture terpisah per window (untuk A/B comparison).

        Identik dengan perilaku sebelum VideoVisionPass diperkenalkan.
        """
        visual_builders = {
            atype: (
                lambda w, i, _p=video_path: {"video_path": _p, "start": w["start"], "end": w["end"]}
                if video_path else None
            )
            for atype in _VISUAL_ANALYZER_TYPES
        }

        for analyzer_type, build in visual_builders.items():
            analyzer = get_analyzer(analyzer_type)
            if analyzer is None:
                continue

            logger.debug("Analyze process (legacy): step %s start", analyzer_type)
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
                "Analyzer %s (legacy): %d/%d window berhasil untuk job %d",
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
