"""Hook Composer Service — render cold-open teaser + zoom-punch + caption + concat.

Dipanggil dari ClipService.generate_clip() SETELAH _extract_clip() berhasil
(clip biasa sudah ada). Gagal total pada tahap apa pun → catch, log,
set hook_skip_reason="render_failed", biarkan clip normal tetap dipakai.

Alur:
1. Prasyarat check (flag, durasi window, hook_moment ada).
2. Extract 2 detik teaser dari VIDEO SUMBER ASLI pakai timestamp absolut.
3. Terapkan zoom-punch ke teaser: crop 85% area tengah → scale balik ke ukuran penuh.
   (Lebih stabil dari zoompan filter — tidak ada keyframe drift.)
4. Bakar caption overlay ke teaser (pola identik add_text() di ClipEditorService).
5. SFX whoosh (best-effort): mix ke teaser jika file ada, skip diam-diam jika tidak.
6. Concat teaser + clip utuh via ffmpeg concat demuxer.
7. Simpan ke clip.edited_file_path (bukan file_path) — konsisten dengan pola editor.
   _clip_result.html dan _clip_edit_preview.html sudah prefer edited_file_path.
"""

import logging
import subprocess
import tempfile
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai_modules.hook_analysis.hook_moment_finder import HookMoment
from app.core.config.settings import settings
from app.repositories.clip_repository import ClipRepository
from app.services.caption_style_service import CaptionStyleService
from app.services.ffmpeg_service import FFmpegService

logger = logging.getLogger(__name__)

_SFX_PATH = Path("data/assets/sfx/whoosh.mp3")
_SFX_WARNED = False   # log warning SFX sekali saja per process


class HookComposerService:
    """Compose cold-open hook ke clip yang sudah di-extract."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.clip_repo = ClipRepository(db)
        self.ffmpeg = FFmpegService()

    def compose(
        self,
        clip_id: int,
        video_source_path: str,
        aspect_ratio: str,
        hook_moment: HookMoment,
        window_duration: float,
        layout: str = "stacked_split",
        facecam_position: str = "auto",
        punch_zoom_scale: float | None = None,
        zoom_target: str | None = None,
    ) -> bool:
        """Terapkan cold-open hook ke clip.

        Args:
            clip_id: ID ClipModel yang sudah tersimpan (hasil _extract_clip).
            video_source_path: path video ASLI (bukan clip hasil trim).
            aspect_ratio: "9:16" | "16:9" | "1:1" — harus sama dengan clip utuh.
            hook_moment: hasil HookMomentFinder.find().
            window_duration: durasi window candidate (detik) — untuk guard min window.
            layout: "stacked_split" | "blurred_fit" | "center_crop"
            facecam_position: "auto" | "bottom_left" | "bottom_right" | "top_left" | "top_right"
            punch_zoom_scale: intensitas zoom (misal 1.25x / 1.35x)
            zoom_target: "facecam" (streamer face) | "full" (full frame)

        Returns:
            True  → hook berhasil diterapkan, clip.edited_file_path diupdate.
            False → hook di-skip atau gagal, clip tidak berubah.
        """
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            logger.warning("HookComposer: clip %d tidak ditemukan", clip_id)
            return False

        # Guard: USE_AUTO_HOOK flag
        if not settings.USE_AUTO_HOOK:
            clip.hook_skip_reason = "disabled"
            self.db.commit()
            return False

        # Guard: window minimal
        if window_duration < settings.AUTO_HOOK_MIN_WINDOW_SECONDS:
            logger.debug(
                "HookComposer skip clip %d: window %.1fs < %.1fs minimum",
                clip_id, window_duration, settings.AUTO_HOOK_MIN_WINDOW_SECONDS,
            )
            clip.hook_skip_reason = "window_too_short"
            self.db.commit()
            return False

        try:
            from app.services.clip_history_manager import ClipHistoryManager

            history_mgr = ClipHistoryManager(clip_id)
            base_clip_path = history_mgr.get_base_for_hook(clip)
            result_path = self._render_hook(
                clip, video_source_path, aspect_ratio, hook_moment,
                base_clip_path=base_clip_path, layout=layout,
                facecam_position=facecam_position,
                punch_zoom_scale=punch_zoom_scale,
                zoom_target=zoom_target,
            )
            history_mgr.push_step(
                clip=clip,
                action="hook",
                label="AI Hook Teaser",
                temp_file_path=result_path,
                hook_applied=True,
            )
            clip.hook_applied = True
            clip.hook_skip_reason = None
            self.db.commit()
            logger.info(
                "HookComposer: hook diterapkan ke clip %d → %s",
                clip_id, clip.edited_file_path,
            )
            return True
        except Exception as e:
            logger.warning(
                "HookComposer render gagal untuk clip %d (clip normal tetap dipakai): %s",
                clip_id, e,
            )
            clip.hook_applied = False
            clip.hook_skip_reason = "render_failed"
            self.db.commit()
            return False

    def regenerate_from_candidate(
        self,
        clip_id: int,
        video_source_path: str,
        aspect_ratio: str,
        hook_moment: HookMoment,
        window_duration: float,
        layout: str = "stacked_split",
        facecam_position: str = "auto",
        punch_zoom_scale: float | None = None,
        zoom_target: str | None = None,
    ) -> bool:
        """Render ulang hook dari momen yang sudah tersimpan di candidate."""
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            logger.warning("HookComposer.regenerate: clip %d tidak ditemukan", clip_id)
            return False

        try:
            from app.services.clip_history_manager import ClipHistoryManager

            history_mgr = ClipHistoryManager(clip_id)
            base_clip_path = history_mgr.get_base_for_hook(clip)
            result_path = self._render_hook(
                clip, video_source_path, aspect_ratio, hook_moment,
                base_clip_path=base_clip_path, layout=layout,
                facecam_position=facecam_position,
                punch_zoom_scale=punch_zoom_scale,
                zoom_target=zoom_target,
            )
            history_mgr.push_step(
                clip=clip,
                action="hook",
                label="AI Hook Teaser",
                temp_file_path=result_path,
                hook_applied=True,
            )
            clip.hook_applied = True
            clip.hook_skip_reason = None
            self.db.commit()
            logger.info(
                "HookComposer.regenerate: hook diterapkan ke clip %d → %s",
                clip_id, clip.edited_file_path,
            )
            return True
        except Exception as e:
            logger.warning(
                "HookComposer.regenerate gagal untuk clip %d: %s", clip_id, e,
            )
            clip.hook_applied = False
            clip.hook_skip_reason = "render_failed"
            self.db.commit()
            return False

    # ── Private render pipeline ───────────────────────────────────────────────

    def _render_hook(
        self,
        clip,
        video_source_path: str,
        aspect_ratio: str,
        hook_moment: HookMoment,
        base_clip_path: str | Path | None = None,
        layout: str = "stacked_split",
        facecam_position: str = "auto",
        punch_zoom_scale: float | None = None,
        zoom_target: str | None = None,
    ) -> Path:
        """Render seluruh pipeline hook, return path file akhir."""
        pz_scale = float(punch_zoom_scale if punch_zoom_scale is not None else getattr(settings, "AUTO_HOOK_PUNCH_ZOOM_SCALE", 1.25))
        z_target = str(zoom_target if zoom_target is not None else getattr(settings, "AUTO_HOOK_ZOOM_TARGET", "facecam"))

        if base_clip_path is not None:
            clip_path = Path(base_clip_path)
        else:
            from app.services.clip_history_manager import ClipHistoryManager

            clip_path = ClipHistoryManager(clip.id).get_base_for_hook(clip)

        output_dir = Path(clip.file_path).parent
        stem = Path(clip.file_path).stem

        # Pastikan TEMP_DIR ada sebelum TemporaryDirectory
        settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix="hook_", dir=str(settings.TEMP_DIR)
        ) as tmpdir:
            tmp = Path(tmpdir)

            # Step 1 — Extract teaser dari video sumber (dengan facecam punch-zoom jika split)
            teaser_raw = tmp / "teaser_raw.mp4"
            self._extract_teaser(
                video_source_path, str(teaser_raw),
                hook_moment.hook_moment_start, hook_moment.hook_moment_end,
                aspect_ratio, layout=layout,
                facecam_position=facecam_position,
                punch_zoom_scale=pz_scale,
                zoom_target=z_target,
            )

            # Step 2 — Zoom-punch (crop tengah untuk full-frame, atau passthrough untuk facecam split)
            teaser_zoomed = tmp / "teaser_zoomed.mp4"
            self._apply_zoom_punch(
                str(teaser_raw), str(teaser_zoomed), aspect_ratio,
                punch_zoom_scale=pz_scale,
                zoom_target=z_target,
                layout=layout,
            )

            # Step 3 — Caption overlay
            # Pada layout 9:16 stacked_split, panel atas (0..800px) adalah facecam.
            # Letakkan caption tepat di garis batas (y=800px) agar tidak menutupi wajah streamer!
            norm_ratio, norm_layout = self._resolve_aspect_and_layout(aspect_ratio, layout)
            safe_box = None
            if norm_ratio == "9:16" and norm_layout == "stacked_split":
                safe_box = {"layout": "facecam_top", "split_y": 800, "offset_y": 0}

            teaser_caption = tmp / "teaser_caption.mp4"
            teaser_duration = hook_moment.hook_moment_end - hook_moment.hook_moment_start
            self._apply_caption(
                str(teaser_zoomed), str(teaser_caption),
                hook_moment.hook_caption, teaser_duration,
                reaction_type=hook_moment.hook_type,
                aspect_ratio=norm_ratio,
                safe_box=safe_box,
                tmp_dir=tmp,
                highlight_word=getattr(hook_moment, "highlight_word", None),
            )

            # Step 4 — SFX whoosh (best-effort, bisa skip). Letaknya di POTONGAN
            # (akhir teaser → masuk klip utuh), bukan di awal teaser.
            teaser_final = tmp / "teaser_final.mp4"
            self._apply_sfx(str(teaser_caption), str(teaser_final), teaser_duration)

            # Step 5 — Concat teaser + clip utuh (dengan fadewhite di titik cut)
            ts = int(time.time() * 1000)
            output_path = settings.TEMP_DIR / f"{stem}_hook_{ts}.mp4"
            self._concat(str(teaser_final), str(clip_path), str(output_path), tmp, teaser_duration)

        return output_path

    @staticmethod
    def _resolve_aspect_and_layout(aspect_ratio: str, layout: str = "stacked_split") -> tuple[str, str]:
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

    def _extract_teaser(
        self,
        source: str,
        output: str,
        start: float,
        end: float,
        aspect_ratio: str,
        layout: str = "stacked_split",
        facecam_position: str = "auto",
        punch_zoom_scale: float = 1.25,
        zoom_target: str = "facecam",
    ) -> None:
        """Extract teaser dari video sumber, terapkan crop/scale dan facecam punch-zoom jika split."""
        norm_ratio, norm_layout = self._resolve_aspect_and_layout(aspect_ratio, layout)
        duration = end - start
        width, height = self._parse_aspect_ratio(norm_ratio)

        filter_args: list[str] = []
        if norm_ratio == "9:16":
            if norm_layout == "stacked_split":
                facecam_pos = facecam_position
                face_center = None
                if facecam_pos == "auto":
                    try:
                        from app.services.facecam_detector_service import FacecamDetectorService
                        det = FacecamDetectorService().detect_facecam_position(source, start, end)
                        detected = det.get("position", "bottom_right")
                        facecam_pos = detected if detected != "none" else "bottom_right"
                        if detected != "none":
                            face_center = det.get("center")
                    except Exception as e:
                        logger.warning("Teaser facecam detection failed, fallback to bottom_right: %s", e)
                        facecam_pos = "bottom_right"

                from app.services.facecam_detector_service import FacecamDetectorService
                # Terapkan punch-zoom langsung pada webcam jika target adalah facecam
                face_zoom = punch_zoom_scale if zoom_target == "facecam" else 1.0
                vface_filter = FacecamDetectorService.get_facecam_crop_filter(
                    facecam_pos,
                    zoom_scale=face_zoom,
                    face_center=face_center,
                )

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
                    f"crop=min(iw\\,ih*9/16):min(ih\\,iw*16/9):"
                    f"(iw-min(iw\\,ih*9/16))/2:(ih-min(ih\\,iw*16/9))/2,"
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
            self.ffmpeg.ffmpeg_path, "-y",
            "-ss", str(start), "-i", source, "-t", str(duration),
            *filter_args,
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output,
        ]
        self._run(cmd, "extract_teaser")

    def _apply_zoom_punch(
        self,
        source: str,
        output: str,
        aspect_ratio: str,
        punch_zoom_scale: float = 1.25,
        zoom_target: str = "facecam",
        layout: str = "stacked_split",
    ) -> None:
        """Zoom-punch:
        - Jika layout == 'stacked_split' dan zoom_target == 'facecam', zoom punch SUDAH
          diterapkan langsung ke webcam atas di _extract_teaser tanpa memotong seam gameplay.
          Cukup copy source -> output.
        - Jika zoom_target == 'full' atau layout non-split, crop 1/punch_zoom_scale area tengah frame
          lalu scale balik ke resolusi penuh.
        """
        import shutil

        norm_ratio, norm_layout = self._resolve_aspect_and_layout(aspect_ratio, layout)
        if norm_layout == "stacked_split" and zoom_target == "facecam":
            shutil.copy2(source, output)
            return

        scale = max(1.0, min(float(punch_zoom_scale), 2.0))
        if scale <= 1.001:
            shutil.copy2(source, output)
            return

        width, height = self._parse_aspect_ratio(norm_ratio)
        crop_w = int(width / scale)
        crop_h = int(height / scale)
        crop_w -= crop_w % 2
        crop_h -= crop_h % 2
        x_off = (width - crop_w) // 2
        y_off = (height - crop_h) // 2

        vf = (
            f"crop={crop_w}:{crop_h}:{x_off}:{y_off},"
            f"scale={width}:{height}:flags=lanczos"
        )
        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-i", source,
            "-vf", vf,
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output,
        ]
        self._run(cmd, "zoom_punch")

    def _apply_caption(
        self,
        source: str,
        output: str,
        caption: str,
        duration: float,
        reaction_type: str | None = None,
        aspect_ratio: str = "9:16",
        safe_box: dict | tuple | None = None,
        tmp_dir: Path | None = None,
        highlight_word: str | None = None,
    ) -> None:
        """Bakar caption overlay ke teaser via ASS (libass) atau fallback drawtext bundel."""
        width, height = self._parse_aspect_ratio(aspect_ratio)
        work_dir = tmp_dir or settings.TEMP_DIR
        work_dir.mkdir(parents=True, exist_ok=True)

        ass_file = work_dir / "hook_caption.ass"
        fallback_txt = work_dir / "fallback_caption.txt"

        # 1. Jalur Utama: Render ASS (libass)
        try:
            ass_content = CaptionStyleService.build_ass(
                caption=caption,
                reaction_type=reaction_type,
                duration=duration,
                width=width,
                height=height,
                safe_box=safe_box,
                highlight_word=highlight_word,
            )
            ass_file.write_text(ass_content, encoding="utf-8")

            try:
                rel_ass = ass_file.relative_to(settings.BASE_DIR).as_posix()
            except ValueError:
                rel_ass = ass_file.as_posix()

            fontsdir = Path(getattr(settings, "AUTO_HOOK_FONTS_DIR", "data/assets/fonts")).as_posix()
            vf = f"subtitles={rel_ass}:fontsdir={fontsdir}"

            cmd = [
                self.ffmpeg.ffmpeg_path, "-y",
                "-i", source,
                "-vf", vf,
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-pix_fmt", "yuv420p",
                "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
                "-c:a", "copy",
                "-movflags", "+faststart",
                output,
            ]
            self._run(cmd, "apply_caption_ass", cwd=settings.BASE_DIR)
            return
        except Exception as e:
            logger.warning(
                "HookComposer: ASS subtitle gagal (%s), beralih ke fallback drawtext bundel",
                e,
            )

        # 2. Fallback: Drawtext dengan font bundel Anton-Regular
        try:
            fallback_text = CaptionStyleService.build_fallback_text(caption, width=width)
            fallback_txt.write_text(fallback_text, encoding="utf-8")

            try:
                rel_txt = fallback_txt.relative_to(settings.BASE_DIR).as_posix()
            except ValueError:
                rel_txt = fallback_txt.as_posix()

            fontfile = "data/assets/fonts/Anton-Regular.ttf"
            vf = (
                f"drawtext=fontfile='{fontfile}':textfile='{rel_txt}':"
                f"fontcolor=white:fontsize=110:"
                f"borderw=8:bordercolor=black:"
                f"x=(w-text_w)/2:y=h*0.35"
            )
            cmd = [
                self.ffmpeg.ffmpeg_path, "-y",
                "-i", source,
                "-vf", vf,
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-pix_fmt", "yuv420p",
                "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
                "-c:a", "copy",
                "-movflags", "+faststart",
                output,
            ]
            self._run(cmd, "apply_caption_fallback", cwd=settings.BASE_DIR)
        except Exception as e:
            logger.error("HookComposer: Fallback drawtext juga gagal: %s", e)
            raise

    def _apply_sfx(self, source: str, output: str, teaser_duration: float) -> None:
        """Mix SFX whoosh tepat di potongan (akhir teaser → masuk klip utuh).

        Best-effort, skip diam-diam jika file tidak ada. Whoosh digeser ke
        akhir teaser (delay = teaser_duration - durasi whoosh) supaya letupan
        SFX bertepatan dengan cut ke klip asli — bukan di awal cold-open.
        """
        global _SFX_WARNED

        if not _SFX_PATH.exists():
            if not _SFX_WARNED:
                logger.warning(
                    "HookComposer: SFX whoosh tidak ditemukan di %s — "
                    "hook tetap jalan tanpa SFX. Taruh file di path tsb untuk aktifkan.",
                    _SFX_PATH,
                )
                _SFX_WARNED = True
            # Rename source → output tanpa modifikasi (tetap ada file di tmp)
            import shutil
            shutil.copy2(source, output)
            return

        # Durasi whoosh (cache per-process untuk hindari ffprobe berulang)
        whoosh_dur = self._whoosh_duration()
        delay_ms = max(0, int((teaser_duration - whoosh_dur) * 1000))

        # Mix SFX digeser ke akhir teaser; volume teaser tetap tinggi (0.9)
        # supaya suara hook TIDAK mendem vs klip utuh — whoosh dinaikkan ke 1.5
        # (punchy, sinkron dengan flash visual fadewhite di cut point).
        # amix duration=first memotong audio di panjang teaser.
        af = (
            f"[0:a]volume=0.9[a0];"
            f"[1:a]volume=1.5,adelay={delay_ms}:all=1[a1];"
            f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-i", source,
            "-i", str(_SFX_PATH),
            "-filter_complex", af,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-movflags", "+faststart",
            output,
        ]
        try:
            self._run(cmd, "apply_sfx")
        except Exception as e:
            logger.warning("HookComposer SFX gagal, lanjut tanpa SFX: %s", e)
            import shutil
            shutil.copy2(source, output)

    _WHOOSH_DUR: float | None = None

    def _whoosh_duration(self) -> float:
        """Durasi whoosh.mp3 (ffprobe), cache per-process."""
        if type(self)._WHOOSH_DUR is None:
            try:
                r = subprocess.run(
                    [
                        self.ffmpeg.ffprobe_path, "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        str(_SFX_PATH),
                    ],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=30,
                )
                type(self)._WHOOSH_DUR = float(r.stdout.strip()) if r.returncode == 0 else 0.888
            except Exception:
                type(self)._WHOOSH_DUR = 0.888
        return type(self)._WHOOSH_DUR

    def _concat(
        self,
        teaser_path: str,
        main_clip_path: str,
        output_path: str,
        tmp: Path,
        teaser_duration: float = 2.0,
    ) -> None:
        """Concat teaser + clip utuh via filter_complex dengan xfade fadewhite.

        BUKAN concat demuxer: concat list file rawan di Windows (escaping
        backslash path, dan bisa diam-diam drop file kedua → output cuma
        teaser 2 detik). filter_complex pakai input langsung, tidak ada file
        list, tidak ada masalah path. Re-encode menjamin keyframe align sempurna.

        Animasi transisi: xfade=fadewhite durasi 0.15 detik tepat di cut point
        (teaser_duration - 0.15) — memberi efek flash putih singkat yang sinkron
        dengan whoosh SFX di akhir teaser.
        """
        # Durasi transisi fadewhite: 0.15 detik — cukup punchy, tidak terlalu lama.
        # offset = kapan xfade mulai, dihitung dari awal video pertama.
        # Clamp minimal 0.05s dari teaser supaya tidak overflow ke awal teaser.
        xfade_duration = 0.15
        xfade_offset = max(0.05, teaser_duration - xfade_duration)

        # xfade hanya bekerja untuk video; audio disambung biasa via acrossfade
        # (durasi sama, biar transisi audio juga mulus di cut point).
        filter_complex = (
            f"[0:v][1:v]xfade=transition=fadewhite:duration={xfade_duration:.3f}:offset={xfade_offset:.3f}[v];"
            f"[0:a][1:a]acrossfade=d={xfade_duration:.3f}[a]"
        )
        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-i", str(teaser_path),
            "-i", str(main_clip_path),
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output_path,
        ]
        self._run(cmd, "concat")

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _run(self, cmd: list[str], step: str, cwd: str | Path | None = None) -> None:
        """Jalankan FFmpeg command, raise RuntimeError kalau gagal."""
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            cwd=str(cwd) if cwd else None,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"HookComposer [{step}] FFmpeg error: {result.stderr[-500:]}"
            )

    @staticmethod
    def _parse_aspect_ratio(ratio: str) -> tuple[int, int]:
        if ratio == "9:16":
            return (1080, 1920)
        if ratio == "1:1":
            return (1080, 1080)
        return (1920, 1080)  # default 16:9
