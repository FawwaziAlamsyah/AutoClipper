"""Clip generation service (final FFmpeg render)."""

import logging
import subprocess
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.models.clip_model import ClipModel
from app.repositories.clip_repository import ClipRepository
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.transcript_repository import (
    TranscriptRepository,
    TranscriptSegmentRepository,
)
from app.repositories.video_repository import VideoRepository
from app.services.ffmpeg_service import FFmpegService
from app.services.history_service import HistoryService
from app.services.job_service import JobService

logger = logging.getLogger(__name__)


class ClipService:
    """Generate final clip from candidate using FFmpeg."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session and tool services."""
        self.db = db
        self.video_repo = VideoRepository(db)
        self.candidate_repo = CandidateRepository(db)
        self.clip_repo = ClipRepository(db)
        self.transcript_repo = TranscriptRepository(db)
        self.segment_repo = TranscriptSegmentRepository(db)
        self.ffmpeg = FFmpegService()
        self.history_service = HistoryService(db)
        self.job_service = JobService(db)

    def generate_clip(
        self,
        candidate_id: int,
        aspect_ratio: str = "9:16",
        subtitle_enabled: bool = False,
        subtitle_style: str = "minimal",
        layout: str = "stacked_split",
        facecam_position: str = "auto",
    ) -> ClipModel:
        """Generate a final clip using FFmpeg from a candidate.

        Setelah _extract_clip() sukses, jalankan Auto Hook Engine (jika aktif):
        - Cari momen hook via LLM (HookMomentFinder)
        - Simpan hasil ke candidate.hook_* untuk ditampilkan di tab Hook UI
        - Render cold-open teaser + concat via HookComposerService
        Kegagalan hook engine TIDAK menggagalkan generate_clip.
        """
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise ValidationException(f"Candidate {candidate_id} not found")

        video = self.video_repo.get(candidate.video_id)
        if video is None:
            raise ValidationException(f"Video {candidate.video_id} not found")

        if video.is_archived or not Path(video.file_path).exists():
            raise ValidationException(
                f"Video dengan ID {video.id} sudah dihapus. "
                "Tidak bisa generate clip baru dari video ini — data candidate "
                "tetap tersimpan untuk training, tapi file sumbernya sudah tidak ada."
            )

        # ── Render clip biasa ─────────────────────────────────────────────────
        unique_id = str(uuid.uuid4())[:8]
        output_dir = Path("data/outputs")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"clip_{video.id}_{candidate.id}_{unique_id}.mp4"

        norm_ratio, norm_layout = self._resolve_aspect_and_layout(aspect_ratio, layout)
        job_id = candidate.job_id
        logger.debug("Generate process: render clip untuk candidate %d (%s, %s, facecam=%s)", candidate_id, norm_ratio, norm_layout, facecam_position)
        self.job_service.start_optional_step(job_id, "generate")
        try:
            self._extract_clip(
                video.file_path, str(output_path),
                candidate.start_time, candidate.end_time,
                norm_ratio,
                layout=norm_layout,
                facecam_position=facecam_position,
            )
        except Exception:
            self.job_service.finish_optional_step(job_id, "generate", success=False, error="FFmpeg render gagal")
            logger.debug("Generate process: error - FFmpeg render gagal")
            raise
        self.job_service.finish_optional_step(job_id, "generate", success=True)
        logger.debug("Generate process: success - clip %s", output_path.name)

        existing_clip = None
        try:
            res = (
                self.db.query(ClipModel)
                .filter(ClipModel.candidate_id == candidate_id)
                .first()
            )
            if isinstance(res, ClipModel):
                existing_clip = res
        except Exception:
            existing_clip = None

        if existing_clip:
            try:
                if existing_clip.file_path and existing_clip.file_path != str(output_path):
                    Path(existing_clip.file_path).unlink(missing_ok=True)
                if existing_clip.edited_file_path:
                    Path(existing_clip.edited_file_path).unlink(missing_ok=True)
            except Exception:
                pass
            existing_clip.file_path = str(output_path)
            existing_clip.edited_file_path = None
            existing_clip.aspect_ratio = aspect_ratio
            existing_clip.has_subtitle = subtitle_enabled
            existing_clip.status = "completed"
            clip = self.clip_repo.save(existing_clip)
        else:
            clip = ClipModel(
                candidate_id=candidate_id,
                video_id=candidate.video_id,
                file_path=str(output_path),
                start_time=candidate.start_time,
                end_time=candidate.end_time,
                aspect_ratio=aspect_ratio,
                has_subtitle=subtitle_enabled,
                status="completed",
            )
            clip = self.clip_repo.add(clip)

        # ── Auto Hook Engine (best-effort, TIDAK boleh raise) ─────────────────
        if settings.USE_AUTO_HOOK:
            self._run_auto_hook(clip, candidate, video, layout=norm_layout, facecam_position=facecam_position)

        # ── Auto Subtitle Engine (jika diaktifkan) ───────────────────────────
        if subtitle_enabled:
            try:
                from app.services.subtitle_service import SubtitleService
                sub_srv = SubtitleService(self.db)
                sub_srv.generate_subtitle(
                    clip.id,
                    format="ass",
                    style=subtitle_style or "tiktok",
                    burn=True,
                )
            except Exception as e:
                logger.warning("Gagal auto-burn subtitle untuk clip %d: %s", clip.id, e)

        # ── Update candidate + history ────────────────────────────────────────
        self.candidate_repo.update_status(candidate_id, "selected")
        self.history_service.log(
            action="clip_exported",
            description=f"Clip {clip.id} exported: {aspect_ratio}",
            video_id=candidate.video_id,
            job_id=candidate.job_id,
        )

        logger.info("Generated clip %d for candidate %d", clip.id, candidate_id)
        return clip

    def _run_auto_hook(
        self,
        clip: ClipModel,
        candidate,
        video,
        layout: str = "stacked_split",
        facecam_position: str = "auto",
        punch_zoom_scale: float | None = None,
        zoom_target: str | None = None,
    ) -> None:
        """Cari momen hook via LLM, simpan ke candidate, lalu compose clip.

        Semua exception di-catch di sini — generate_clip tidak boleh gagal karena hook.
        """
        try:
            from app.ai_modules.hook_analysis.hook_moment_finder import HookMomentFinder
            from app.services.hook_composer_service import HookComposerService
            from app.services.audio_spike_detector_service import AudioSpikeDetectorService

            # Ambil rentang waktu aktif klip (memperhitungkan hasil trim jika klip sudah diedit)
            effective_start = float(clip.start_time if clip.start_time is not None else candidate.start_time)
            effective_end = float(clip.end_time if clip.end_time is not None else candidate.end_time)
            window_duration = max(0.0, effective_end - effective_start)

            # Deteksi lonjakan audio / emosi (Fitur 4)
            audio_spikes = None
            if getattr(settings, "AUTO_HOOK_ENABLE_AUDIO_SPIKE", True):
                try:
                    spike_detector = AudioSpikeDetectorService()
                    audio_spikes = spike_detector.detect_spikes(
                        video.file_path,
                        start_time=effective_start,
                        end_time=effective_end,
                    )
                    # Simpan informasi audio spike ke score_breakdown candidate (JSONB)
                    if not isinstance(candidate.score_breakdown, dict):
                        candidate.score_breakdown = {}
                    candidate.score_breakdown["audio_spike"] = audio_spikes
                    self.db.commit()
                except Exception as e:
                    logger.debug("Deteksi audio spike dilewati: %s", e)

            # Ambil segments transcript
            transcript = self.transcript_repo.get_by_video(video.id)
            if not transcript:
                logger.debug("Auto Hook skip candidate %d: tidak ada transcript", candidate.id)
                clip.hook_skip_reason = "llm_unavailable"
                self.db.commit()
                return

            segments = self.segment_repo.get_by_transcript(transcript.id)
            # Filter ke window klip aktif saja (hanya segmen di dalam hasil trim)
            segs_in_window = [
                s for s in segments
                if s.end_time > effective_start and s.start_time < effective_end
            ]

            # Cari nama kategori untuk konteks LLM
            category_name = candidate.category.name if candidate.category else None

            finder = HookMomentFinder()
            hook_moment, skip_reason = finder.find(segs_in_window, category_name, audio_spikes=audio_spikes)

            if hook_moment is None:
                logger.info(
                    "Auto Hook skip candidate %d: %s (segments in window: %d, api_key_set: %s)",
                    candidate.id, skip_reason, len(segs_in_window), bool(finder.api_key),
                )
                clip.hook_skip_reason = skip_reason
                self.db.commit()
                return

            # Simpan hasil ke candidate (untuk ditampilkan di tab Hook UI)
            candidate.hook_moment_start = hook_moment.hook_moment_start
            candidate.hook_moment_end   = hook_moment.hook_moment_end
            candidate.hook_type         = hook_moment.hook_type
            candidate.hook_confidence   = hook_moment.hook_confidence
            candidate.hook_caption      = hook_moment.hook_caption
            self.db.commit()

            # Compose cold-open
            norm_ratio, norm_layout = self._resolve_aspect_and_layout(clip.aspect_ratio, layout)
            composer = HookComposerService(self.db)
            composer.compose(
                clip_id=clip.id,
                video_source_path=video.file_path,
                aspect_ratio=norm_ratio,
                hook_moment=hook_moment,
                window_duration=window_duration,
                layout=norm_layout,
                facecam_position=facecam_position,
                punch_zoom_scale=punch_zoom_scale,
                zoom_target=zoom_target,
            )

        except Exception as e:
            logger.warning(
                "Auto Hook Engine gagal untuk clip %d (clip normal tetap dipakai): %s",
                clip.id, e,
            )
            try:
                clip.hook_skip_reason = "render_failed"
                self.db.commit()
            except Exception:
                pass

    def retry_hook_search(
        self,
        clip_id: int,
        punch_zoom_scale: float | None = None,
        zoom_target: str | None = None,
    ) -> ClipModel:
        """Cari ulang momen hook dari awal via LLM — untuk kasus hook_moment_start null.

        Dipakai tombol "Cari Hook Ulang" di UI saat LLM sebelumnya tidak bisa
        dihubungi (llm_unavailable, low_confidence, dsb) sehingga hook_moment_start
        masih null. Ini menjalankan ulang seluruh pipeline _run_auto_hook dari nol.
        """
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise ValidationException(f"Clip {clip_id} tidak ditemukan")

        candidate = self.candidate_repo.get(clip.candidate_id)
        if candidate is None:
            raise ValidationException(f"Candidate untuk clip {clip_id} tidak ditemukan")

        video = self.video_repo.get(candidate.video_id)
        if video is None or not Path(video.file_path).exists():
            raise ValidationException("Video sumber sudah tidak ada.")

        # Reset skip reason supaya _run_auto_hook bisa jalan ulang bersih
        clip.hook_skip_reason = None
        self.db.commit()

        # Jalankan ulang seluruh pipeline pencarian hook + compose
        if punch_zoom_scale is not None or zoom_target is not None:
            self._run_auto_hook(
                clip, candidate, video,
                punch_zoom_scale=punch_zoom_scale,
                zoom_target=zoom_target,
            )
        else:
            self._run_auto_hook(clip, candidate, video)

        clip = self.clip_repo.get(clip_id)
        return clip

    def regenerate_hook(
        self,
        clip_id: int,
        punch_zoom_scale: float | None = None,
        zoom_target: str | None = None,
    ) -> ClipModel:
        """Render ulang hook dari momen tersimpan candidate (tanpa replay LLM).

        Dipakai tombol "Generate Ulang Hook" di UI saat render sebelumnya gagal
        (hook_skip_reason=render_failed) atau user coba lagi. Re-uses momen hook
        yang sudah tersimpan di candidate; langsung compose tanpa LLM call.
        Jika klip telah di-trim sehingga hook lama berada di luar batas klip aktif,
        otomatis panggil pencarian hook baru via LLM.
        """
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise ValidationException(f"Clip {clip_id} not found")

        candidate = self.candidate_repo.get(clip.candidate_id)
        if candidate is None:
            raise ValidationException(f"Candidate untuk clip {clip_id} tidak ditemukan")

        video = self.video_repo.get(candidate.video_id)
        if video is None or not Path(video.file_path).exists():
            raise ValidationException("Video sumber sudah tidak ada.")

        effective_start = float(clip.start_time if clip.start_time is not None else candidate.start_time)
        effective_end = float(clip.end_time if clip.end_time is not None else candidate.end_time)
        window_duration = max(0.0, effective_end - effective_start)

        # Jika candidate belum punya momen hook atau momen hook lama berada di luar rentang klip aktif (akibat trim),
        # jalankan pencarian hook otomatis pada klip aktif ini.
        if (
            candidate.hook_moment_start is None
            or candidate.hook_moment_start < effective_start
            or (candidate.hook_moment_end is not None and candidate.hook_moment_end > effective_end)
        ):
            clip.hook_skip_reason = None
            self.db.commit()
            if punch_zoom_scale is not None or zoom_target is not None:
                self._run_auto_hook(
                    clip, candidate, video,
                    punch_zoom_scale=punch_zoom_scale,
                    zoom_target=zoom_target,
                )
            else:
                self._run_auto_hook(clip, candidate, video)
            clip = self.clip_repo.get(clip_id)
            return clip

        # Baca hook_caption langsung dari DB via query fresh — bypass identity map
        # sepenuhnya supaya perubahan dari request Simpan Caption sebelumnya
        # selalu terbaca, tidak peduli state SQLAlchemy session cache.
        from app.models.candidate_model import CandidateModel as _CandidateModel
        self.db.expire_all()
        fresh = (
            self.db.query(_CandidateModel)
            .filter(_CandidateModel.id == candidate.id)
            .first()
        )
        fresh_caption = (fresh.hook_caption or "") if fresh else (candidate.hook_caption or "")

        from app.ai_modules.hook_analysis.hook_moment_finder import HookMoment
        from app.services.hook_composer_service import HookComposerService

        hook_moment = HookMoment(
            hook_moment_start=candidate.hook_moment_start,
            hook_moment_end=candidate.hook_moment_end,
            hook_type=candidate.hook_type or "hook",
            hook_confidence=candidate.hook_confidence or 0.0,
            hook_caption=fresh_caption,
            best_idx=0,
        )

        norm_ratio, norm_layout = self._resolve_aspect_and_layout(clip.aspect_ratio)
        composer = HookComposerService(self.db)
        composer.regenerate_from_candidate(
            clip_id=clip.id,
            video_source_path=video.file_path,
            aspect_ratio=norm_ratio,
            hook_moment=hook_moment,
            window_duration=window_duration,
            layout=norm_layout,
            punch_zoom_scale=punch_zoom_scale,
            zoom_target=zoom_target,
        )
        clip = self.clip_repo.get(clip_id)
        return clip

    def snap_hook_to_audio_spike(
        self,
        clip_id: int,
        punch_zoom_scale: float | None = None,
        zoom_target: str | None = None,
    ) -> ClipModel:
        """Snap momen hook ke titik lonjakan emosi/teriakan tertinggi audio spike lalu render ulang."""
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise ValidationException(f"Clip {clip_id} tidak ditemukan")

        candidate = self.candidate_repo.get(clip.candidate_id)
        if candidate is None:
            raise ValidationException(f"Candidate untuk clip {clip_id} tidak ditemukan")

        video = self.video_repo.get(candidate.video_id)
        if video is None or not Path(video.file_path).exists():
            raise ValidationException("Video sumber sudah tidak ada.")

        effective_start = float(clip.start_time if clip.start_time is not None else candidate.start_time)
        effective_end = float(clip.end_time if clip.end_time is not None else candidate.end_time)

        from app.services.audio_spike_detector_service import AudioSpikeDetectorService
        detector = AudioSpikeDetectorService()
        spikes = detector.detect_spikes(video.file_path, effective_start, effective_end)

        if not isinstance(candidate.score_breakdown, dict):
            candidate.score_breakdown = {}
        candidate.score_breakdown["audio_spike"] = spikes

        peak_time = spikes.get("peak_time", (effective_start + effective_end) / 2.0)
        h_start, h_end = detector.get_hook_window_from_spike(
            peak_time=peak_time,
            window_start=effective_start,
            window_end=effective_end,
            teaser_duration=2.5,
        )

        candidate.hook_moment_start = h_start
        candidate.hook_moment_end = h_end
        candidate.hook_type = "shock"
        if not candidate.hook_caption:
            contextual_caption = None
            try:
                transcript = self.transcript_repo.get_by_video(candidate.video_id)
                if transcript:
                    segs = self.segment_repo.get_by_transcript(transcript.id)
                    near = [
                        s for s in segs
                        if isinstance(getattr(s, "text", None), str)
                        and s.end_time >= h_start
                        and s.start_time <= h_end
                        and s.text.strip()
                    ]
                    if near:
                        words = near[0].text.strip().split()[:6]
                        if words:
                            contextual_caption = " ".join(words)
            except Exception:
                contextual_caption = None
            candidate.hook_caption = contextual_caption or "REAKSI TAK TERDUGA!"
        self.db.commit()

        return self.regenerate_hook(
            clip_id,
            punch_zoom_scale=punch_zoom_scale,
            zoom_target=zoom_target,
        )

    @staticmethod
    def _resolve_aspect_and_layout(aspect_ratio: str, layout: str = "stacked_split") -> tuple[str, str]:
        """Normalize aspect_ratio and layout.
        Examples:
        - "9:16_split" -> ("9:16", "stacked_split")
        - "9:16_blur"  -> ("9:16", "blurred_fit")
        - "9:16_crop"  -> ("9:16", "center_crop")
        - ("9:16", "stacked_split") -> ("9:16", "stacked_split")
        - ("16:9", ...) -> ("16:9", "default")
        """
        if "_" in aspect_ratio:
            parts = aspect_ratio.split("_", 1)
            base = parts[0]
            sub = parts[1]
            if sub in ("split", "stacked_split"):
                return base, "stacked_split"
            elif sub in ("blur", "blurred_fit"):
                return base, "blurred_fit"
            elif sub in ("crop", "center_crop"):
                return base, "center_crop"
            return base, sub
        if aspect_ratio == "9:16":
            return "9:16", layout or "stacked_split"
        return aspect_ratio, "default" if layout == "stacked_split" else (layout or "default")

    def _extract_clip(
        self,
        input_path: str,
        output_path: str,
        start: float,
        end: float,
        aspect_ratio: str,
        layout: str = "stacked_split",
        facecam_position: str = "auto",
    ) -> None:
        """Extract clip using FFmpeg with reframing for social media output.

        Untuk 9:16 (TikTok/Reels/Shorts):
        - stacked_split (default): Facecam streamer di atas (1080x800) + Gameplay di bawah (1080x1120).
        - blurred_fit: Gameplay utuh di tengah dengan background blur dinamis di atas/bawah.
        - center_crop: Crop tengah standar dari video sumber.
        Untuk 16:9 dan 1:1: tetap pakai scale+pad (lebih aman untuk konten landscape).
        """
        norm_ratio, norm_layout = self._resolve_aspect_and_layout(aspect_ratio, layout)
        width, height = self._parse_aspect_ratio(norm_ratio)
        duration = end - start

        filter_args: list[str] = []
        if norm_ratio == "9:16":
            if norm_layout == "stacked_split":
                # Stacked Split: Facecam (Top) + Gameplay (Bottom)
                facecam_pos = facecam_position
                if facecam_pos == "auto":
                    try:
                        from app.services.facecam_detector_service import FacecamDetectorService
                        det = FacecamDetectorService().detect_facecam_position(input_path, start, end)
                        detected = det.get("position", "bottom_right")
                        facecam_pos = detected if detected != "none" else "bottom_right"
                    except Exception as e:
                        logger.warning("Facecam detection failed, fallback to bottom_right: %s", e)
                        facecam_pos = "bottom_right"

                from app.services.facecam_detector_service import FacecamDetectorService
                vface_filter = FacecamDetectorService.get_facecam_crop_filter(facecam_pos)

                fc = (
                    "[0:v]split=2[vface][vgame];"
                    f"{vface_filter}"
                    "[vgame]crop=w=min(iw\\,ih*1080/1120):h=ih:x=(iw-min(iw\\,ih*1080/1120))/2:y=0,scale=1080:1120:flags=lanczos[bot];"
                    "[top][bot]vstack=inputs=2[vout]"
                )
                filter_args = ["-filter_complex", fc, "-map", "[vout]", "-map", "0:a?"]
            elif norm_layout == "blurred_fit":
                fc = (
                    f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},boxblur=25:5[bg];"
                    f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
                    f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vout]"
                )
                filter_args = ["-filter_complex", fc, "-map", "[vout]", "-map", "0:a?"]
            else:  # "center_crop"
                vf = (
                    f"crop=min(iw\\,ih*9/16):min(ih\\,iw*16/9):(iw-min(iw\\,ih*9/16))/2:(ih-min(ih\\,iw*16/9))/2,"
                    f"scale={width}:{height}:flags=lanczos"
                )
                filter_args = ["-vf", vf, "-map", "0:v:0", "-map", "0:a?"]
        else:
            vf = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
            )
            filter_args = ["-vf", vf, "-map", "0:v:0", "-map", "0:a?"]

        cmd = [
            self.ffmpeg.ffmpeg_path,
            "-y",
            "-ss", str(start),
            "-i", input_path,
            "-t", str(duration),
            *filter_args,
            "-c:v", "libx264",
            "-preset", "slow",   # slow = kualitas lebih baik, ukuran lebih kecil vs fast
            "-crf", "18",        # 18 = kualitas tinggi (visually lossless), sosmed-ready
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",      # naik dari 128k untuk audio sosmed
            "-movflags", "+faststart",  # progressive download, penting untuk sosmed
            output_path,
        ]

        logger.info("Running FFmpeg: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        if result.returncode != 0:
            logger.error("FFmpeg failed: %s", result.stderr)
            raise RuntimeError(f"FFmpeg error: {result.stderr}")

        logger.info("Clip saved: %s", output_path)

    def _parse_aspect_ratio(self, ratio: str) -> tuple[int, int]:
        """Parse aspect ratio string to (width, height)."""
        if ratio.startswith("9:16"):
            return (1080, 1920)
        if ratio.startswith("16:9"):
            return (1920, 1080)
        if ratio.startswith("1:1"):
            return (1080, 1080)
        # Default: 16:9
        return (1920, 1080)

