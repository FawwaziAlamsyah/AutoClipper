"""AI Discovery Service — 'Analys by AI' pipeline orchestration.

Runs end-to-end full video curation via LLM (Gemini 3.8 Flash / 9Router)
without running sliding-window scoring or analyzer passes.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.ai_modules.llm_analysis.ai_curator import AICurator, AICuratorError
from app.core.exceptions.base import NotFoundException
from app.models.candidate_model import CandidateModel
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.category_repository import CategoryRepository
from app.repositories.transcript_repository import TranscriptSegmentRepository
from app.repositories.video_repository import VideoRepository
from app.services.audio_spike_detector_service import AudioSpikeDetectorService
from app.services.ffmpeg_service import FFmpegService
from app.services.history_service import HistoryService
from app.services.job_service import JobService
from app.services.storyboard_service import StoryboardService
from app.services.transcript_service import TranscriptService

logger = logging.getLogger(__name__)


class AIDiscoveryService:
    """Service untuk menjalankan pipeline kurasi video 'Analys by AI'."""

    def __init__(
        self,
        db: Session,
        ffmpeg: FFmpegService | None = None,
        transcript_service: TranscriptService | None = None,
        storyboard_service: StoryboardService | None = None,
        audio_spike_service: AudioSpikeDetectorService | None = None,
        ai_curator: AICurator | None = None,
    ) -> None:
        self.db = db
        self.video_repo = VideoRepository(db)
        self.job_service = JobService(db)
        self.category_repo = CategoryRepository(db)
        self.candidate_repo = CandidateRepository(db)
        self.segment_repo = TranscriptSegmentRepository(db)
        self.history_service = HistoryService(db)

        self.ffmpeg = ffmpeg or FFmpegService()
        self.transcript_service = transcript_service or TranscriptService(db, ffmpeg=self.ffmpeg)
        self.storyboard_service = storyboard_service or StoryboardService()
        self.audio_spike_service = audio_spike_service or AudioSpikeDetectorService()
        self.ai_curator = ai_curator or AICurator()

    def create_job(
        self,
        video_id: int,
        category_text: str = "",
        scan_visual: bool = True,
        content_brief: str | None = None,
    ) -> int:
        """Buat job pipeline ai_discovery dan simpan parameter AI."""
        video = self.video_repo.get(video_id)
        if video is None:
            raise NotFoundException(f"Video {video_id} tidak ditemukan")

        # Cek apakah teks kategori cocok dengan salah satu kategori yang sudah ada
        matched_cat = None
        clean_cat = (category_text or "").strip()
        if clean_cat:
            matched_cat = self.category_repo.get_by_name(clean_cat)
            if not matched_cat:
                for cat in self.category_repo.get_all():
                    if cat.name.lower() == clean_cat.lower():
                        matched_cat = cat
                        break

        job = self.job_service.create(
            video_id=video_id,
            pipeline_name="ai_discovery_v1",
            job_type="ai_discovery",
            category_id=matched_cat.id if matched_cat else None,
        )
        job.ai_category_text = clean_cat or "Umum / Menarik"
        job.ai_scan_visual = scan_visual
        job.ai_content_brief = (content_brief or "").strip() or None
        self.db.commit()

        logger.info(
            "Created ai_discovery job %d for video %d (category='%s', scan_visual=%s, has_brief=%s)",
            job.id, video_id, job.ai_category_text, scan_visual, bool(job.ai_content_brief),
        )
        return job.id

    def process_ai_video(
        self,
        video_id: int,
        job_id: int | None = None,
        category_text: str = "",
        scan_visual: bool = True,
        content_brief: str | None = None,
    ) -> dict[str, Any]:
        """Jalankan pipeline AI Discovery penuh untuk satu video."""
        video = self.video_repo.get(video_id)
        if video is None:
            raise NotFoundException(f"Video {video_id} tidak ditemukan")

        if job_id:
            job = self.job_service.get(job_id)
            if category_text:
                job.ai_category_text = category_text.strip()
            job.ai_scan_visual = scan_visual
            if content_brief is not None:
                job.ai_content_brief = (content_brief or "").strip() or None
            self.db.commit()
        else:
            j_id = self.create_job(video_id, category_text=category_text, scan_visual=scan_visual, content_brief=content_brief)
            job = self.job_service.get(j_id)

        cat_name = job.ai_category_text or category_text or "Umum / Viral"
        visual_enabled = bool(job.ai_scan_visual if job.ai_scan_visual is not None else scan_visual)
        active_brief = job.ai_content_brief or (content_brief.strip() if content_brief else None)

        logger.info("Mulai AI Discovery pipeline untuk video %d (job %d)", video_id, job.id)
        self.video_repo.update_status(video_id, "processing")

        try:
            # Step 1: Ekstraksi Audio & Transkripsi (Whisper)
            transcript = self.transcript_service.transcribe(video_id, job_id=job.id)
            segments = self.segment_repo.get_by_transcript(transcript.id)

            # Guard: Video tanpa audio dan Scan Visual OFF
            if not segments and not visual_enabled:
                raise AICuratorError(
                    "Tidak ada ucapan/dialog yang terdeteksi pada video ini. "
                    "Silakan aktifkan opsi 'Scan Visual' agar AI dapat mendeteksi momen aksi dari video."
                )

            # Step 2: Sinyal Audio (Spikes timeline)
            self.job_service.start_step(job.id, "signals")
            audio_spikes = self.audio_spike_service.detect_timeline_spikes(video.file_path)
            self.job_service.finish_step(job.id, "signals", success=True)

            # Step 3: Storyboard & Scene Cuts (Scan Visual)
            self.job_service.start_step(job.id, "storyboard")
            storyboard_images: list[str] = []
            scene_cuts: list[float] = []

            if visual_enabled:
                try:
                    storyboard_images, scene_cuts = self.storyboard_service.generate_storyboard(video.file_path)
                except Exception as e:
                    logger.warning("Storyboard generation gagal: %s. Melanjutkan tanpa visual.", e)
            self.job_service.finish_step(job.id, "storyboard", success=True)

            # Step 4: AI Curation (1 LLM Multimodal Request)
            self.job_service.start_step(job.id, "ai_curate")
            try:
                curation_result = self.ai_curator.curate(
                    category_name=cat_name,
                    duration_seconds=float(video.duration_seconds or 60.0),
                    segments=segments,
                    audio_spikes=audio_spikes,
                    scene_cuts=scene_cuts,
                    storyboard_images=storyboard_images,
                    scan_visual=visual_enabled,
                    content_brief=active_brief,
                )
                self.job_service.finish_step(job.id, "ai_curate", success=True)
            except AICuratorError as e:
                self.job_service.finish_step(job.id, "ai_curate", success=False, error=e.message)
                raise
            except Exception as e:
                err_msg = f"Kegagalan sistem AI: {str(e)}"
                self.job_service.finish_step(job.id, "ai_curate", success=False, error=err_msg)
                raise AICuratorError(err_msg, original_error=e)

            # Step 5: Validasi, Boundary Snapping, dan Simpan Candidates
            self.job_service.ensure_step(job.id, "complete")
            self.job_service.start_step(job.id, "complete")

            candidates = self._validate_and_persist_candidates(
                video=video,
                job=job,
                curation_result=curation_result,
                segments=segments,
                scene_cuts=scene_cuts,
            )

            self.job_service.complete_job(job.id)
            self.job_service.finish_step(job.id, "complete", success=True)
            self.video_repo.update_status(video_id, "ready")

            log_desc = f"AI Discovery menghasilkan {len(candidates)} kandidat klip viral (kategori='{cat_name}')"
            self.history_service.log(
                action="ai_candidate_generated",
                description=log_desc,
                video_id=video_id,
                job_id=job.id,
            )
            self.db.commit()

            return {
                "video_id": video_id,
                "job_id": job.id,
                "candidates_count": len(candidates),
                "candidates": [
                    {
                        "id": c.id,
                        "start_time": c.start_time,
                        "end_time": c.end_time,
                        "final_score": c.final_score,
                        "title": c.hook_text,
                        "source": c.source,
                        "score_breakdown": c.score_breakdown or {},
                    }
                    for c in candidates
                ],
            }

        except Exception as e:
            logger.error("AI Discovery process gagal untuk video %d: %s", video_id, e, exc_info=True)
            self.video_repo.update_status(video_id, "ready")
            self.db.commit()
            raise

    def _validate_and_persist_candidates(
        self,
        video: Any,
        job: Any,
        curation_result: dict[str, Any],
        segments: list[Any],
        scene_cuts: list[float],
    ) -> list[CandidateModel]:
        """Validasi hasil kurasi AI, snap boundaries ke batas kalimat/scene, dan simpan."""
        raw_candidates = curation_result.get("candidates", [])
        cat_interp = curation_result.get("category_interpretation", "")
        video_dur = float(video.duration_seconds or 36000.0)

        # Map segments by ID untuk pencarian O(1)
        seg_map = {getattr(s, "id", None) or s.get("id"): s for s in segments if s}

        validated_moments: list[dict[str, Any]] = []

        for cand in raw_candidates:
            start_seg_id = cand.get("start_seg")
            end_seg_id = cand.get("end_seg")
            cand_start = cand.get("start_time")
            cand_end = cand.get("end_time")

            raw_start: float | None = None
            raw_end: float | None = None

            # 1. Resolusi waktu dari segmen transcript
            if start_seg_id in seg_map and end_seg_id in seg_map:
                s_seg = seg_map[start_seg_id]
                e_seg = seg_map[end_seg_id]
                s_t = getattr(s_seg, "start_time", 0.0) if hasattr(s_seg, "start_time") else s_seg.get("start_time", 0.0)
                e_t = getattr(e_seg, "end_time", 0.0) if hasattr(e_seg, "end_time") else e_seg.get("end_time", 0.0)
                raw_start = float(s_t)
                raw_end = float(e_t)
            # 2. Resolusi waktu langsung jika momen visual
            elif cand_start is not None and cand_end is not None:
                try:
                    raw_start = float(cand_start)
                    raw_end = float(cand_end)
                except (ValueError, TypeError):
                    continue

            if raw_start is None or raw_end is None or raw_end <= raw_start:
                continue

            # Durasi guard: minimal 5 detik, maksimal 180 detik (batas short-form)
            duration = raw_end - raw_start
            if duration < 5.0 or duration > 180.0:
                continue

            # Boundary snapping (melebar keluar, tidak pernah menyempit agar puncak momen aman)
            snapped_start = max(0.0, raw_start - 0.75)
            # Cek apakah ada scene cut terdekat sebelum start (dalam 2.5s)
            nearby_cuts_before = [c for c in scene_cuts if (raw_start - 2.5) <= c <= raw_start]
            if nearby_cuts_before:
                snapped_start = max(0.0, nearby_cuts_before[-1])

            snapped_end = min(video_dur, raw_end + 0.6)
            # Cek apakah ada scene cut terdekat setelah end (dalam 2.5s)
            nearby_cuts_after = [c for c in scene_cuts if raw_end <= c <= (raw_end + 2.5)]
            if nearby_cuts_after:
                snapped_end = min(video_dur, nearby_cuts_after[0])

            confidence = min(max(float(cand.get("confidence", 7.0)), 0.0), 10.0)
            if confidence < 6.5:
                continue

            title = str(cand.get("title") or "Momen Viral Pilihan AI").strip()[:140]
            archetype = str(cand.get("archetype") or "highlight").strip().lower()
            why_viral = str(cand.get("why_viral") or "").strip()

            # Hook moment (cold-open teaser)
            hook_data = cand.get("hook") or {}
            h_time = hook_data.get("moment_time")
            hook_caption = (hook_data.get("caption") or title)[:80]
            hook_type = hook_data.get("type") or "shock"

            hook_start: float | None = None
            hook_end: float | None = None
            hook_conf: float | None = None

            if h_time is not None:
                try:
                    h_val = float(h_time)
                    # Hook harus berada di dalam rentang klip dan setidaknya 1.0s setelah awal
                    if (snapped_start + 1.0) <= h_val <= snapped_end:
                        hook_start = round(h_val, 2)
                        hook_end = round(min(hook_start + 2.5, snapped_end), 2)
                        hook_conf = round(min(max(confidence / 10.0, 0.6), 1.0), 2)
                except (ValueError, TypeError):
                    pass

            validated_moments.append({
                "start_time": round(snapped_start, 2),
                "end_time": round(snapped_end, 2),
                "confidence": round(confidence, 1),
                "title": title,
                "archetype": archetype,
                "why_viral": why_viral,
                "hook_start": hook_start,
                "hook_end": hook_end,
                "hook_type": hook_type,
                "hook_caption": hook_caption,
                "hook_conf": hook_conf,
            })

        # Overlap filtering: sort by confidence descending, singkirkan yang overlap > 50%
        validated_moments.sort(key=lambda m: m["confidence"], reverse=True)
        selected_moments: list[dict[str, Any]] = []

        for m in validated_moments:
            overlap = False
            for s in selected_moments:
                inter_start = max(m["start_time"], s["start_time"])
                inter_end = min(m["end_time"], s["end_time"])
                if inter_end > inter_start:
                    inter_dur = inter_end - inter_start
                    m_dur = m["end_time"] - m["start_time"]
                    if m_dur > 0 and (inter_dur / m_dur) > 0.50:
                        overlap = True
                        break
            if not overlap:
                selected_moments.append(m)

        # Urutkan berdasarkan waktu mulai video ascending agar rapi
        selected_moments.sort(key=lambda m: m["start_time"])

        created_candidates: list[CandidateModel] = []
        for m in selected_moments:
            score_breakdown = {
                "source": "ai",
                "title": m["title"],
                "archetype": m["archetype"],
                "why_viral": m["why_viral"],
                "confidence": m["confidence"],
                "category_interpretation": cat_interp,
                "has_campaign_brief": bool(getattr(job, "ai_content_brief", None)),
            }

            candidate_obj = CandidateModel(
                video_id=video.id,
                job_id=job.id,
                category_id=job.category_id,
                start_time=m["start_time"],
                end_time=m["end_time"],
                final_score=m["confidence"],
                score_breakdown=score_breakdown,
                hook_text=m["title"],
                hook_moment_start=m["hook_start"],
                hook_moment_end=m["hook_end"],
                hook_type=m["hook_type"],
                hook_caption=m["hook_caption"],
                hook_confidence=m["hook_conf"],
                source="ai",
                status="candidate",
            )
            saved = self.candidate_repo.add(candidate_obj)
            created_candidates.append(saved)

        logger.info(
            "AI Discovery: Berhasil memvalidasi dan menyimpan %d candidate clips untuk video %d",
            len(created_candidates), video.id,
        )
        return created_candidates
