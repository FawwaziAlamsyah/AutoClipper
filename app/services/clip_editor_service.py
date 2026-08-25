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
        self.db.commit()
        logger.info("Clip %d di-trim: %.2fs – %.2fs", clip_id, start_time, end_time)
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
