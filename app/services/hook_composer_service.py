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
    ) -> bool:
        """Terapkan cold-open hook ke clip.

        Args:
            clip_id: ID ClipModel yang sudah tersimpan (hasil _extract_clip).
            video_source_path: path video ASLI (bukan clip hasil trim).
            aspect_ratio: "9:16" | "16:9" | "1:1" — harus sama dengan clip utuh.
            hook_moment: hasil HookMomentFinder.find().
            window_duration: durasi window candidate (detik) — untuk guard min window.

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
            result_path = self._render_hook(clip, video_source_path, aspect_ratio, hook_moment)
            clip.edited_file_path = str(result_path)
            clip.hook_applied = True
            clip.hook_skip_reason = None
            self.db.commit()
            logger.info(
                "HookComposer: hook diterapkan ke clip %d → %s",
                clip_id, result_path.name,
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
    ) -> bool:
        """Render ulang hook dari momen yang sudah tersimpan di candidate.

        Dipakai tombol "Generate Ulang Hook" di UI saat render sebelumnya gagal
        (hook_skip_reason=render_failed) atau user ingin coba lagi. Momen hook
        TIDAK dicari ulang — pakai yang tersimpan di candidate, langsung compose.
        """
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            logger.warning("HookComposer.regenerate: clip %d tidak ditemukan", clip_id)
            return False

        try:
            result_path = self._render_hook(clip, video_source_path, aspect_ratio, hook_moment)
            clip.edited_file_path = str(result_path)
            clip.hook_applied = True
            clip.hook_skip_reason = None
            self.db.commit()
            logger.info(
                "HookComposer.regenerate: hook diterapkan ke clip %d → %s",
                clip_id, result_path.name,
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
            logger.warning(
                "HookComposer render gagal untuk clip %d (clip normal tetap dipakai): %s",
                clip_id, e,
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
    ) -> Path:
        """Render seluruh pipeline hook, return path file akhir."""
        clip_path = Path(clip.file_path)
        output_dir = clip_path.parent
        stem = clip_path.stem

        # Pastikan TEMP_DIR ada sebelum TemporaryDirectory
        settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix="hook_", dir=str(settings.TEMP_DIR)
        ) as tmpdir:
            tmp = Path(tmpdir)

            # Step 1 — Extract teaser dari video sumber
            teaser_raw = tmp / "teaser_raw.mp4"
            self._extract_teaser(
                video_source_path, str(teaser_raw),
                hook_moment.hook_moment_start, hook_moment.hook_moment_end,
                aspect_ratio,
            )

            # Step 2 — Zoom-punch (crop 85% tengah → scale balik)
            teaser_zoomed = tmp / "teaser_zoomed.mp4"
            self._apply_zoom_punch(str(teaser_raw), str(teaser_zoomed), aspect_ratio)

            # Step 3 — Caption overlay
            teaser_caption = tmp / "teaser_caption.mp4"
            teaser_duration = hook_moment.hook_moment_end - hook_moment.hook_moment_start
            self._apply_caption(
                str(teaser_zoomed), str(teaser_caption),
                hook_moment.hook_caption, teaser_duration,
                reaction_type=hook_moment.hook_type,
                aspect_ratio=aspect_ratio,
                tmp_dir=tmp,
            )

            # Step 4 — SFX whoosh (best-effort, bisa skip). Letaknya di POTONGAN
            # (akhir teaser → masuk klip utuh), bukan di awal teaser.
            teaser_final = tmp / "teaser_final.mp4"
            self._apply_sfx(str(teaser_caption), str(teaser_final), teaser_duration)

            # Step 5 — Concat teaser + clip utuh (dengan fadewhite di titik cut)
            output_path = output_dir / f"{stem}_hook.mp4"
            self._concat(str(teaser_final), str(clip_path), str(output_path), tmp, teaser_duration)

        return output_path

    def _extract_teaser(
        self,
        source: str,
        output: str,
        start: float,
        end: float,
        aspect_ratio: str,
    ) -> None:
        """Extract 2 detik teaser dari video sumber, terapkan crop/scale identik _extract_clip."""
        duration = end - start
        width, height = self._parse_aspect_ratio(aspect_ratio)

        if aspect_ratio == "9:16":
            vf = (
                f"crop=min(iw\\,ih*9/16):min(ih\\,iw*16/9):"
                f"(iw-min(iw\\,ih*9/16))/2:(ih-min(ih\\,iw*16/9))/2,"
                f"scale={width}:{height}:flags=lanczos"
            )
        else:
            vf = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
            )

        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-ss", str(start), "-i", source, "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output,
        ]
        self._run(cmd, "extract_teaser")

    def _apply_zoom_punch(self, source: str, output: str, aspect_ratio: str) -> None:
        """Zoom-punch: crop 85% area tengah frame → scale balik ke resolusi penuh.

        Efek "zoomed in" statis — lebih stabil dari zoompan animasi dan tidak ada
        keyframe drift. Sama meyakinkan secara visual untuk cold-open 2 detik.
        """
        width, height = self._parse_aspect_ratio(aspect_ratio)
        crop_w = int(width * 0.85)
        crop_h = int(height * 0.85)
        # Pastikan dimensi genap (libx264 syarat)
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
