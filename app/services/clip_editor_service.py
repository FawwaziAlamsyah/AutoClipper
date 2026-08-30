"""Edit sederhana pada clip yang sudah di-generate: text overlay, crop, ganti suara.

File asli (clips.file_path) tidak pernah ditimpa — tiap edit menulis ke
clips.edited_file_path, supaya "Reset ke Original" tidak perlu render ulang.
"""

import logging
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import NotFoundException, ValidationException
from app.repositories.clip_repository import ClipRepository
from app.services.ffmpeg_service import FFmpegService

logger = logging.getLogger(__name__)


class ClipEditorService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.clip_repo = ClipRepository(db)
        self.ffmpeg = FFmpegService()

    def _current_source(self, clip) -> Path:
        """Sumber untuk edit berikutnya: hasil edit sebelumnya kalau ada, else file asli."""
        path = Path(clip.edited_file_path) if clip.edited_file_path else Path(clip.file_path)
        if not path.exists():
            raise ValidationException(f"File clip tidak ditemukan di disk: {path}")
        return path

    def _edited_output_path(self, clip_id: int) -> Path:
        edited_dir = settings.OUTPUT_DIR / "edited"
        edited_dir.mkdir(parents=True, exist_ok=True)
        return edited_dir / f"clip_{clip_id}_edited.mp4"

    def add_text(
        self,
        clip_id: int,
        text: str,
        position: str = "bottom",  # "top" | "middle" | "bottom"
        font_size: int = 48,
        color: str = "white",
    ):
        """Tambahkan text overlay ke clip pakai FFmpeg drawtext filter."""
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")
        if not text.strip():
            raise ValidationException("Text tidak boleh kosong")

        source = self._current_source(clip)
        output_path = self._edited_output_path(clip_id)

        y_expr = {"top": "h*0.08", "middle": "(h-text_h)/2", "bottom": "h*0.85"}.get(position, "h*0.85")
        # Escape karakter yang sensitif buat FFmpeg drawtext (: dan ')
        safe_text = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        # Konversi hex color (#ffffff) ke format FFmpeg (0xFFFFFF) kalau perlu
        ffmpeg_color = color.replace("#", "0x") if color.startswith("#") else color
        # Windows: drawtext butuh fontfile explicit, tidak bisa resolve font system otomatis
        # Escape backslash path jadi forward slash untuk FFmpeg filter string
        fontfile = "C\\:/Windows/Fonts/arial.ttf"

        vf = (
            f"drawtext=fontfile='{fontfile}':text='{safe_text}':fontcolor={ffmpeg_color}:fontsize={font_size}:"
            f"x=(w-text_w)/2:y={y_expr}"
        )

        # Tulis ke temp dulu karena source bisa == output_path saat sudah ada edit sebelumnya
        temp_path = output_path.with_suffix(".tmp.mp4")
        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-i", str(source),
            "-vf", vf,
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(temp_path),
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        except subprocess.SubprocessError as e:
            temp_path.unlink(missing_ok=True)
            logger.error("Gagal tambah text overlay clip %d", clip_id, exc_info=e)
            raise ValidationException(f"Gagal tambah text: {str(e)}")

        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)

        clip.edited_file_path = str(output_path)
        self.db.commit()
        logger.info("Text overlay ditambahkan ke clip %d", clip_id)
        return clip

    def crop(self, clip_id: int, start_time: float, end_time: float):
        """Trim clip berdasarkan waktu — potong dari start_time ke end_time (dalam detik)."""
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")
        if start_time < 0:
            raise ValidationException("start_time tidak boleh negatif")
        if end_time <= start_time:
            raise ValidationException("end_time harus lebih besar dari start_time")

        source = self._current_source(clip)
        output_path = self._edited_output_path(clip_id)

        duration = end_time - start_time
        # Tulis ke file temp dulu karena source bisa == output_path (saat sudah ada edit sebelumnya)
        temp_path = output_path.with_suffix(".tmp.mp4")
        # Re-encode video supaya keyframe baru dibuat tepat di titik start.
        # -c:v copy menyebabkan video frozen di awal karena keyframe alignment tidak tepat.
        # -crf 18 menjaga kualitas tinggi (visually lossless), -preset fast untuk kecepatan.
        # -g 60 = keyframe setiap 2 detik (30fps × 2) supaya browser bisa seek tanpa freeze.
        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-i", str(source),
            "-ss", str(start_time),
            "-t", str(duration),
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-c:a", "copy",
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            str(temp_path),
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        except subprocess.SubprocessError as e:
            temp_path.unlink(missing_ok=True)
            logger.error("Gagal trim clip %d", clip_id, exc_info=e)
            raise ValidationException(f"Gagal trim: {str(e)}")

        # Atomic replace: hapus output lama lalu rename temp → final
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)

        clip.edited_file_path = str(output_path)
        # Track posisi trim di video ASLI (kumulatif) supaya subtitle & content
        # filter timing ikut sinkron dengan video yang sudah di-potong.
        new_start = clip.start_time + start_time
        clip.start_time = new_start
        clip.end_time = new_start + duration
        self.db.commit()
        logger.info("Clip %d di-trim: mulai=%s (offset asli %s)", clip_id, clip.start_time, clip.end_time)
        return clip

    def mix_sound(
        self,
        clip_id: int,
        audio_file_path: str,
        audio_start: float = 0.0,   # detik: posisi mulai audio tambahan di dalam video
        video_volume: float = 1.0,  # volume suara asli DI LUAR range audio tambahan
        duck_volume: float = 0.3,   # volume suara asli SAAT audio tambahan bermain (ducking)
        audio_volume: float = 1.0,  # volume audio tambahan
    ):
        """Mix audio tambahan ke atas audio asli dengan ducking.

        - Suara asli tetap ada di seluruh video.
        - Di range audio_start s/d (audio_start + durasi audio tambahan),
          volume suara asli dikecilkan ke duck_volume (ducking).
        - Di luar range itu, volume suara asli kembali ke video_volume.
        """
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")

        audio_path = Path(audio_file_path)
        if not audio_path.exists():
            raise ValidationException(f"File audio tidak ditemukan: {audio_file_path}")
        if not (0.0 <= video_volume <= 2.0):
            raise ValidationException("video_volume harus antara 0.0–2.0")
        if not (0.0 <= duck_volume <= 2.0):
            raise ValidationException("duck_volume harus antara 0.0–2.0")
        if not (0.0 <= audio_volume <= 2.0):
            raise ValidationException("audio_volume harus antara 0.0–2.0")
        if audio_start < 0:
            raise ValidationException("audio_start tidak boleh negatif")

        # Probe durasi audio tambahan untuk hitung range ducking
        import json as _json
        probe = subprocess.run(
            [self.ffmpeg.ffprobe_path,
             "-v", "error", "-show_entries", "format=duration", "-of", "json", str(audio_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        try:
            audio_duration = float(_json.loads(probe.stdout)["format"]["duration"])
        except Exception:
            audio_duration = 9999.0  # fallback: duck sampai akhir video

        duck_end = audio_start + audio_duration

        source = self._current_source(clip)
        output_path = self._edited_output_path(clip_id)
        temp_path = output_path.with_suffix(".tmp.mp4")

        # Volume suara asli: duck_volume saat audio tambahan bermain, video_volume di luar itu
        delay_ms = int(audio_start * 1000)
        af = (
            f"[0:a]volume=enable='between(t,{audio_start},{duck_end})':volume={duck_volume},"
            f"volume=enable='not(between(t,{audio_start},{duck_end}))':volume={video_volume}[a0];"
            f"[1:a]adelay={delay_ms}|{delay_ms},volume={audio_volume}[a1];"
            f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )

        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-i", str(source),
            "-i", str(audio_path),
            "-filter_complex", af,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-movflags", "+faststart",
            str(temp_path),
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        except subprocess.SubprocessError as e:
            temp_path.unlink(missing_ok=True)
            logger.error("Gagal mix suara clip %d", clip_id, exc_info=e)
            raise ValidationException(f"Gagal mix suara: {str(e)}")

        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)

        clip.edited_file_path = str(output_path)
        self.db.commit()
        logger.info(
            "Audio clip %d di-mix: file=%s start=%.1fs duck=%.1f vol_audio=%.1f",
            clip_id, audio_path.name, audio_start, duck_volume, audio_volume,
        )
        return clip

    def adjust_volume(self, clip_id: int, video_volume: float):
        """Ubah volume seluruh audio track — tanpa upload audio baru."""
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")
        if not (0.0 <= video_volume <= 2.0):
            raise ValidationException("video_volume harus antara 0.0–2.0")

        source = self._current_source(clip)
        output_path = self._edited_output_path(clip_id)
        temp_path = output_path.with_suffix(".tmp.mp4")

        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-i", str(source),
            "-af", f"volume={video_volume}",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-movflags", "+faststart",
            str(temp_path),
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        except subprocess.SubprocessError as e:
            temp_path.unlink(missing_ok=True)
            logger.error("Gagal adjust volume clip %d", clip_id, exc_info=e)
            raise ValidationException(f"Gagal adjust volume: {str(e)}")

        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)

        clip.edited_file_path = str(output_path)
        self.db.commit()
        logger.info("Volume clip %d diubah ke %.1f", clip_id, video_volume)
        return clip

    def reset(self, clip_id: int):
        """Hapus semua hasil edit, balik ke file asli hasil generate_clip()."""
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")

        if clip.edited_file_path:
            edited_path = Path(clip.edited_file_path)
            if edited_path.exists():
                edited_path.unlink()
            clip.edited_file_path = None
            self.db.commit()
            logger.info("Clip %d direset ke file asli", clip_id)
        return clip

    def add_watermark(
        self,
        clip_id: int,
        position: str = "bottom",  # "top" | "bottom" | "center" (atas/bawah tengah)
        scale: float = 0.30,   # lebar watermark relatif ke lebar video (0.05–0.5)
        opacity: float = 0.8,  # 0.0–1.0
        margin_px: int = 24,
    ):
        """Tempel watermark PNG (transparan) ke clip pakai FFmpeg overlay filter."""
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")

        watermark_path = settings.WATERMARK_PATH
        if not watermark_path.exists():
            raise ValidationException(
                f"File watermark tidak ditemukan di {watermark_path}. "
                "Download watermark resmi dan taruh di path tsb dulu."
            )
        if not (0.05 <= scale <= 0.5):
            raise ValidationException("scale harus antara 0.05–0.5")
        if not (0.0 <= opacity <= 1.0):
            raise ValidationException("opacity harus antara 0.0–1.0")

        source = self._current_source(clip)
        output_path = self._edited_output_path(clip_id)
        temp_path = output_path.with_suffix(".tmp.mp4")

        # Cari lebar video buat hitung ukuran watermark relatif (pakai method
        # extract_metadata yang sudah ada di FFmpegService, tidak perlu ffprobe manual lagi).
        meta = self.ffmpeg.extract_metadata(str(source))
        video_width = meta.get("width") or 1080
        wm_width = max(int(video_width * scale), 10)

        position_map = {
            "top-left": (f"{margin_px}", f"{margin_px}"),
            "top-right": (f"main_w-overlay_w-{margin_px}", f"{margin_px}"),
            "bottom-left": (f"{margin_px}", f"main_h-overlay_h-{margin_px}"),
            "bottom-right": (f"main_w-overlay_w-{margin_px}", f"main_h-overlay_h-{margin_px}"),
            "center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
            # Posisi tengah atas/bawah (horizontal center).
            "top": (f"(main_w-overlay_w)/2", f"{margin_px}"),
            "bottom": (f"(main_w-overlay_w)/2", f"main_h-overlay_h-{margin_px}"),
        }
        x_expr, y_expr = position_map.get(position, position_map["bottom-right"])

        filter_complex = (
            f"[1:v]scale={wm_width}:-1,format=rgba,colorchannelmixer=aa={opacity}[wm];"
            f"[0:v][wm]overlay=x={x_expr}:y={y_expr}:format=auto[vout]"
        )

        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-i", str(source),
            "-i", str(watermark_path),
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "0:a?",  # "?" = optional, tidak error kalau video tanpa audio
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(temp_path),
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        except subprocess.SubprocessError as e:
            temp_path.unlink(missing_ok=True)
            logger.error("Gagal tambah watermark clip %d", clip_id, exc_info=e)
            raise ValidationException(f"Gagal tambah watermark: {str(e)}")

        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)

        clip.edited_file_path = str(output_path)
        clip.has_watermark = True
        self.db.commit()
        logger.info("Watermark ditambahkan ke clip %d (pos=%s, scale=%.2f, opacity=%.2f)", clip_id, position, scale, opacity)
        return clip

    def burn_subtitle(self, clip_id: int, cues: list[dict]):
        """Burn (hardcode) subtitle ke video clip.

        Satu drawtext per cue, timing RELATIF ke clip (dikurangi clip.start_time)
        supaya sinkron dengan video yang sudah di-trim. Ikut pola edit lain:
        tulis temp → atomic rename → update edited_file_path → commit. Reset()
        otomatis buang subtitle (edited_file_path = None).
        """
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")

        source = self._current_source(clip)
        output_path = self._edited_output_path(clip_id)
        temp_path = output_path.with_suffix(".tmp.mp4")

        # Kelompokkan drawtext per cue pakai filter enable between(t,start,end).
        # Timing relatif ke clip (cue timestamps berdasar video asli).
        fontfile = "C\\:/Windows/Fonts/arial.ttf"
        vf_parts: list[str] = []
        for cue in cues:
            text = cue["text"].strip()
            if not text:
                continue
            start = max(cue["start"] - clip.start_time, 0.0)
            end = max(cue["end"] - clip.start_time, start + 0.1)
            # FFmpeg drawtext: apostrophe ' di text MENUTUP quote pembungkus text='...'
            # dan pecahkan parsing multi-filter chain. Ganti ke RIGHT SINGLE QUOTE (U+2019)
            # — visual sama, tak tabrakan dgn option quote. Colon di-escape (\:), koma
            # aman polos di dalam '...'. Urut: backslash dulu biar tak double-escape.
            safe_text = (
                text.replace("\\", "\\\\")
                .replace(":", "\\:")
                .replace("'", "’")
            )
            # enable pakai gte/lte (bukan between) — setara a<=t<=b, hungry of commas.
            vf_parts.append(
                f"drawtext=fontfile='{fontfile}':text='{safe_text}':fontcolor=white:fontsize=48:"
                f"x=(w-text_w)/2:y=h*0.85:enable='(gte(t,{start:.3f}))*(lte(t,{end:.3f}))'"
            )
        vf = ",".join(vf_parts)

        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-i", str(source),
            "-vf", vf,
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(temp_path),
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        except subprocess.SubprocessError as e:
            temp_path.unlink(missing_ok=True)
            logger.error("Gagal burn subtitle clip %d", clip_id, exc_info=e)
            raise ValidationException(f"Gagal burn subtitle: {str(e)}")

        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)

        clip.edited_file_path = str(output_path)
        clip.has_subtitle = True
        self.db.commit()
        logger.info("Subtitle di-burn ke clip %d (%d cues)", clip_id, len(vf_parts))
        return clip
