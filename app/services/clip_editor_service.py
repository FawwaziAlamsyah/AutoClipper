"""Edit sederhana pada clip yang sudah di-generate: text overlay, crop, ganti suara.

File asli (clips.file_path) tidak pernah ditimpa — tiap edit menulis ke
clips.edited_file_path, supaya "Reset ke Original" tidak perlu render ulang.
"""

import json
import logging
import subprocess
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import NotFoundException, ValidationException
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.clip_repository import ClipRepository
from app.services.clip_history_manager import ClipHistoryManager
from app.services.ffmpeg_service import FFmpegService

try:
    from PIL import Image
except ImportError:  # pragma: no cover — kalau PIL belum ada, visible bbox fallback ke canvas
    Image = None

WATERMARK_IDS_FILE = "watermark_ids.json"  # dipakai frontend: visible bbox + img natural size

logger = logging.getLogger(__name__)


class ClipEditorService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.clip_repo = ClipRepository(db)
        self.candidate_repo = CandidateRepository(db)
        self.ffmpeg = FFmpegService()

    def _history_manager(self, clip_id: int) -> ClipHistoryManager:
        return ClipHistoryManager(clip_id)

    def _current_source(self, clip) -> Path:
        """Sumber untuk edit berikutnya: hasil aktif dari riwayat stack atau fallback file asli."""
        try:
            return self._history_manager(clip.id).get_current_source(clip)
        except Exception:
            path = Path(clip.edited_file_path) if clip.edited_file_path else Path(clip.file_path)
            if not path.exists():
                raise ValidationException(f"File clip tidak ditemukan di disk: {path}")
            return path

    def _temp_output_path(self, clip_id: int, action: str) -> Path:
        settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        return settings.TEMP_DIR / f"edit_{clip_id}_{action}_{ts}.mp4"

    def _edited_output_path(self, clip_id: int) -> Path:
        edited_dir = settings.OUTPUT_DIR / "edited"
        edited_dir.mkdir(parents=True, exist_ok=True)
        return edited_dir / f"clip_{clip_id}_edited.mp4"

    def get_history(self, clip_id: int) -> dict:
        """Ambil metadata riwayat langkah edit untuk clip."""
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")
        return self._history_manager(clip_id).get_status(clip)

    def undo(self, clip_id: int):
        """Mundur 1 langkah edit (rollback)."""
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")
        self._history_manager(clip_id).undo(clip)
        self.db.commit()
        logger.info("Clip %d berhasil di-undo 1 langkah", clip_id)
        return clip

    def redo(self, clip_id: int):
        """Maju 1 langkah edit."""
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")
        self._history_manager(clip_id).redo(clip)
        self.db.commit()
        logger.info("Clip %d berhasil di-redo 1 langkah", clip_id)
        return clip

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
        temp_path = self._temp_output_path(clip_id, "text")

        y_expr = {"top": "h*0.08", "middle": "(h-text_h)/2", "bottom": "h*0.85"}.get(position, "h*0.85")
        # Escape karakter yang sensitif buat FFmpeg drawtext (: dan ')
        safe_text = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        # Konversi hex color (#ffffff) ke format FFmpeg (0xFFFFFF) kalau perlu
        ffmpeg_color = color.replace("#", "0x") if color.startswith("#") else color
        # Pakai font bundel (Anton-Regular) agar portable Windows/Linux
        fontfile = "data/assets/fonts/Anton-Regular.ttf"

        vf = (
            f"drawtext=fontfile='{fontfile}':text='{safe_text}':fontcolor={ffmpeg_color}:fontsize={font_size}:"
            f"x=(w-text_w)/2:y={y_expr}:borderw=6:bordercolor=black"
        )

        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-i", str(source),
            "-vf", vf,
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p",
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

        self._history_manager(clip_id).push_step(
            clip=clip,
            action="text",
            label=f"Teks: {text[:20]}",
            temp_file_path=temp_path,
        )
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
        temp_path = self._temp_output_path(clip_id, "trim")

        duration = end_time - start_time
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
            "-pix_fmt", "yuv420p",
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

        new_start = clip.start_time + start_time
        new_end = new_start + duration
        self._history_manager(clip_id).push_step(
            clip=clip,
            action="trim",
            label=f"Trim {start_time:.1f}s - {end_time:.1f}s",
            temp_file_path=temp_path,
            new_start_time=new_start,
            new_end_time=new_end,
            hook_applied=False,
        )
        if clip.candidate_id:
            candidate = self.candidate_repo.get(clip.candidate_id)
            if candidate and candidate.hook_moment_start is not None:
                # Jika momen hook sebelumnya berada di luar rentang hasil trim, reset hook candidate
                if candidate.hook_moment_start < new_start or (candidate.hook_moment_end and candidate.hook_moment_end > new_end):
                    candidate.hook_moment_start = None
                    candidate.hook_moment_end = None
                    candidate.hook_type = None
                    candidate.hook_confidence = None
                    candidate.hook_caption = None
                    clip.hook_applied = False
        self.db.commit()
        logger.info("Clip %d di-trim: mulai=%s (offset asli %s)", clip_id, clip.start_time, clip.end_time)
        return clip

    def strip_silence(
        self,
        clip_id: int,
        min_silence_duration: float = 1.2,
        padding: float = 0.25,
    ):
        """Pangkas dead-air / jeda hening agar video padat aksi (Sweet spot 18-35s)."""
        from app.services.silence_stripper_service import SilenceStripperService
        return SilenceStripperService(self.db).strip_silence(
            clip_id,
            min_silence_duration=min_silence_duration,
            padding=padding,
        )

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
        temp_path = self._temp_output_path(clip_id, "sound")

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
            "-pix_fmt", "yuv420p",
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

        self._history_manager(clip_id).push_step(
            clip=clip,
            action="sound",
            label="Mix Musik / Suara",
            temp_file_path=temp_path,
        )
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
        temp_path = self._temp_output_path(clip_id, "volume")

        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-i", str(source),
            "-af", f"volume={video_volume}",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p",
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

        self._history_manager(clip_id).push_step(
            clip=clip,
            action="volume",
            label=f"Volume {int(video_volume * 100)}%",
            temp_file_path=temp_path,
        )
        self.db.commit()
        logger.info("Volume clip %d diubah ke %.1f", clip_id, video_volume)
        return clip

    def reset(self, clip_id: int):
        """Hapus semua hasil edit, balik ke file asli hasil generate_clip()."""
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")

        candidate = self.candidate_repo.get(clip.candidate_id) if clip.candidate_id else None
        orig_start = float(candidate.start_time) if candidate and candidate.start_time is not None else None
        orig_end = float(candidate.end_time) if candidate and candidate.end_time is not None else None

        self._history_manager(clip_id).reset(
            clip=clip,
            original_start_time=orig_start,
            original_end_time=orig_end,
        )
        self.db.commit()
        logger.info("Clip %d direset ke file asli", clip_id)
        return clip

    def add_watermark(
        self,
        clip_id: int,
        position: str = "bottom",
        scale: float = 0.30,
        opacity: float = 0.8,
        margin_px: int = 10,
        x_pct: float | None = None,   # 0.0–1.0, posisi kiri watermark relatif ke lebar video
        y_pct: float | None = None,   # 0.0–1.0, posisi atas watermark relatif ke tinggi video
    ):
        """Tempel watermark PNG (transparan) ke clip pakai FFmpeg overlay filter.

        Kalau x_pct/y_pct diisi → posisi bebas dari drag (override position_map),
        kalau None → backward-compat pakai `position`/`margin_px`.
        """
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")

        watermark_path = settings.WATERMARK_PATH
        if not watermark_path.exists():
            raise ValidationException(
                f"File watermark tidak ditemukan di {watermark_path}. "
                "Download watermark resmi dan taruh di path tsb dulu."
            )
        # Pakai versi sudak di-CROP (visible) sebagai input overlay, supaya
        # ukuran watermark di layar & hasil FFmpeg identik (anti transparent padding).
        watermark_path = self._crop_watermark()
        if not (0.05 <= scale <= 0.5):
            raise ValidationException("scale harus antara 0.05–0.5")
        if x_pct is not None and not (0.0 <= x_pct <= 1.0):
            raise ValidationException("x_pct harus antara 0.0–1.0")
        if y_pct is not None and not (0.0 <= y_pct <= 1.0):
            raise ValidationException("y_pct harus antara 0.0–1.0")
        if not (0.0 <= opacity <= 1.0):
            raise ValidationException("opacity harus antara 0.0–1.0")

        source = self._current_source(clip)
        temp_path = self._temp_output_path(clip_id, "watermark")

        # Cari lebar video buat hitung ukuran watermark relatif (pakai method
        # extract_metadata yang sudah ada di FFmpegService, tidak perlu ffprobe manual lagi).
        meta = self.ffmpeg.extract_metadata(str(source))
        video_width = meta.get("width") or 1080
        # `scale` = pecahan LEBAR VIDEO untuk ukuran WATERMARK (sudah crop/visible).
        # File overlay = watermark_visible.png → lebarnya sudah = konten, jadi
        # wm_width = video_width * scale langsung (tanpa kompensasi padding).
        wm_width = max(int(video_width * scale), 10)

        position_map = {
            # Tengah layar
            "center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
            # Atas tengah / Bawah tengah
            "top":    ("(main_w-overlay_w)/2", f"{margin_px}"),
            "bottom": ("(main_w-overlay_w)/2", f"main_h-overlay_h-{margin_px}"),
            # Kanan tengah (K)
            "right":       (f"main_w-overlay_w-{margin_px}", "(main_h-overlay_h)/2"),
            # Kanan atas (KA)
            "top_right":   (f"main_w-overlay_w-{margin_px}", f"{margin_px}"),
            # Kanan bawah (KB)
            "bottom_right":(f"main_w-overlay_w-{margin_px}", f"main_h-overlay_h-{margin_px}"),
            # Kiri tengah (Ki)
            "left":        (f"{margin_px}", "(main_h-overlay_h)/2"),
            # Kiri atas (KiA)
            "top_left":    (f"{margin_px}", f"{margin_px}"),
            # Kiri bawah (KiB)
            "bottom_left": (f"{margin_px}", f"main_h-overlay_h-{margin_px}"),
            # Alias format lama (hyphen) untuk kompatibilitas mundur
            "top-left":    (f"{margin_px}", f"{margin_px}"),
            "top-right":   (f"main_w-overlay_w-{margin_px}", f"{margin_px}"),
            "bottom-left": (f"{margin_px}", f"main_h-overlay_h-{margin_px}"),
            "bottom-right":(f"main_w-overlay_w-{margin_px}", f"main_h-overlay_h-{margin_px}"),
        }
        if x_pct is not None and y_pct is not None:
            # Jalur drag: abai position_map & margin_px sepenuhnya.
            x_expr = f"(main_w-overlay_w)*{x_pct}"
            y_expr = f"(main_h-overlay_h)*{y_pct}"
            logger.info("add_watermark clip=%d drag → x=%s y=%s", clip_id, x_expr, y_expr)
        else:
            # UI watermark baru SELALU kirim x_pct/y_pct (tidak ada dropdown position lagi).
            # Kalau sampai None di sini, tandanya ada bug di pengiriman form.
            logger.warning(
                "add_watermark clip=%d: x_pct/y_pct kosong (None), fallback ke position=%r — "
                "ini seharusnya tidak terjadi dari UI drag, cek pengiriman form.",
                clip_id, position,
            )
            x_expr, y_expr = position_map.get(position, position_map["bottom"])

        filter_complex = (
            f"[1:v]scale={wm_width}:-1,"
            f"format=rgba,"
            f"colorchannelmixer=rr=1:gg=1:bb=1:aa={opacity}[wm];"
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
            "-pix_fmt", "yuv420p",
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

        self._history_manager(clip_id).push_step(
            clip=clip,
            action="watermark",
            label="Watermark",
            temp_file_path=temp_path,
        )
        clip.has_watermark = True
        self.db.commit()

        # Simpan posisi/ukuran/opacity terakhir yang dipakai (hanya jalur drag).
        # Gagal simpan preferensi JANGAN menggagalkan proses watermark utama.
        if x_pct is not None and y_pct is not None:
            try:
                pos_file = settings.WATERMARK_PATH.parent / "watermark_position.json"
                pos_file.write_text(
                    json.dumps({
                        "x_pct": x_pct, "y_pct": y_pct,
                        "scale": scale, "opacity": opacity,
                    }),
                    encoding="utf-8",
                )
            except Exception:
                logger.warning("Gagal simpan watermark_position.json (tidak fatal)", exc_info=True)

        logger.info(
            "Watermark ditambahkan ke clip %d (pos=%s, scale=%.2f, opacity=%.2f)",
            clip_id, position if x_pct is None else f"drag(x={x_pct},y={y_pct})", scale, opacity,
        )
        return clip

    @staticmethod
    def _visible_bbox(path: Path) -> dict | None:
        """Ukur visible (non-transparent) bounding box PNG lewat alpha channel.

        PNG watermark bisa punya kanvas jauh lebih besar dari konten yang terlihat
        (transparent padding). Semua perhitungan ukuran/boundary overlay harus
        berdasarkan bbox ini, bukan ukuran canvas.

        Return {"minX","minY","maxX","maxY","w","h"} dalam piksel CANVAS asli,
        atau None kalau PNG kosong / gagal baca.
        """
        if Image is None:
            return None
        try:
            with Image.open(path) as im:
                im = im.convert("RGBA")
                alpha = im.getchannel("A")
                bbox = alpha.getbbox()  # (minX, minY, maxX, maxY), None kalau semua transparan
                if not bbox:
                    return None
                minX, minY, maxX, maxY = bbox
                return {"minX": minX, "minY": minY, "maxX": maxX, "maxY": maxY,
                        "w": maxX - minX, "h": maxY - minY}
        except Exception:
            logger.warning("Gagal baca visible bbox watermark", exc_info=True)
            return None

    @staticmethod
    def _crop_watermark() -> Path:
        """Crop transparent padding PNG watermark ke visible bbox.

        Hasil disimpan sebagai file TERPISAH (watermark_visible.png) di data/assets/
        supaya file asli tidak berubah. Frontend & FFmpeg memakai versi crop ini,
        sehingga ukuran/rasio/boundary = konten yang benar-benar terlihat
        (tanpa padding). Kalau PNG sudah tanpa padding / gagal, pakai file asli.
        """
        src = settings.WATERMARK_PATH
        out = src.parent / "watermark_visible.png"
        if not src.exists() or Image is None:
            return src
        try:
            bb = ClipEditorService._visible_bbox(src)
            if not bb:
                # salin asli kalau tidak ketemu bbox (semua transparan? pakai canvas)
                out.write_bytes(src.read_bytes())
                return out
            with Image.open(src) as im:
                im = im.convert("RGBA")
                cropped = im.crop((bb["minX"], bb["minY"], bb["maxX"], bb["maxY"]))
                cropped.save(out, format="PNG")
            return out
        except Exception:
            logger.warning("Gagal crop watermark, pakai asli", exc_info=True)
            return src

    @staticmethod
    def _write_watermark_ids() -> None:
        """Generate crop PNG + simpan dimensi (visible) ke watermark_ids.json.

        File ini dibaca frontend via endpoint /watermark/dimensions; ditulis ulang
        tiap start & setiap upload watermark supaya selalu sinkron dengan file.
        """
        try:
            crop = ClipEditorService._crop_watermark()
            dims = {"canvasW": 399, "canvasH": 168, "bboxW": 399, "bboxH": 168,
                    "minX": 0, "minY": 0}
            # Ukuran visible = ukuran file crop (Pillow).
            if Image is not None:
                with Image.open(crop) as im:
                    dims = {"canvasW": im.width, "canvasH": im.height,
                            "bboxW": im.width, "bboxH": im.height,
                            "minX": 0, "minY": 0}
            out = settings.WATERMARK_PATH.parent / WATERMARK_IDS_FILE
            out.write_text(json.dumps(dims), encoding="utf-8")
        except Exception:
            logger.warning("Gagal menulis %s (tidak fatal)", WATERMARK_IDS_FILE, exc_info=True)

    @staticmethod
    def get_watermark_dimensions() -> dict:
        """Ukuran visible (crop) watermark — dipakai frontend full."""
        default = {"canvasW": 399, "canvasH": 168, "bboxW": 399, "bboxH": 168,
                   "minX": 0, "minY": 0}
        try:
            data = json.loads((settings.WATERMARK_PATH.parent / WATERMARK_IDS_FILE).read_text(encoding="utf-8"))
            merged = dict(default)
            merged.update({k: v for k, v in data.items() if k in merged})
            # frontend pakai canvasW/H = visible crop size
            if merged.get("bboxW") and merged["bboxW"] != merged.get("canvasW"):
                merged["canvasW"] = merged["bboxW"]
                merged["canvasH"] = merged["bboxH"]
            return merged
        except Exception:
            return default

    def get_last_watermark_position(self) -> dict:
        """Baca posisi/ukuran watermark terakhir dari watermark_position.json.

        Return default (x_pct=0.65, y_pct=0.80, scale=0.30, opacity=0.8)
        kalau file belum ada / corrupt.
        """
        default = {"x_pct": 0.65, "y_pct": 0.80, "scale": 0.30, "opacity": 0.8}
        pos_file = settings.WATERMARK_PATH.parent / "watermark_position.json"
        try:
            data = json.loads(pos_file.read_text(encoding="utf-8"))
            merged = dict(default)
            merged.update({k: v for k, v in data.items() if k in default})
            return merged
        except Exception:
            return default

    def burn_subtitle(
        self,
        clip_id: int,
        cues: list[dict],
        style: str = "tiktok",
        font_style: str = "impact",
        position: str = "center_low",
    ):
        """Burn (hardcode) subtitle ke video clip dengan ASS libass (TikTok Kinetic) atau drawtext.

        Timing RELATIF ke clip (dikurangi clip.start_time) supaya sinkron.
        Menggunakan font bundel Anton/Poppins/Bangers dengan outline tebal & highlight.
        """
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")

        history_mgr = self._history_manager(clip_id)
        source = history_mgr.prepare_base_for_subtitle(clip)
        temp_path = self._temp_output_path(clip_id, "subtitle")

        # Cek dimensi video (default 1080x1920 untuk 9:16)
        width, height = (1080, 1920) if clip.aspect_ratio == "9:16" else (1920, 1080)
        try:
            probe = self.ffmpeg.probe(str(source))
            if probe and "streams" in probe:
                for s in probe["streams"]:
                    if s.get("codec_type") == "video":
                        width = int(s.get("width", width))
                        height = int(s.get("height", height))
                        break
        except Exception:
            pass

        # Hitung posisi Y subtitle
        if position == "middle":
            pos_y = int(height * 0.50)
        else:  # "center_low" (di atas zona UI caption TikTok)
            pos_y = int(height * 0.67)

        # Ubah timestamps cue agar relatif terhadap start_time klip.
        # Jika klip memiliki teaser hook di awal, geser waktu subtitle agar sinkron
        # dengan video utama yang dimulai tepat setelah teaser berakhir.
        hook_offset = 0.0
        if getattr(clip, "hook_applied", False):
            try:
                meta = self.ffmpeg.extract_metadata(str(source))
                vid_dur = float(meta.get("duration_seconds") or 0.0)
                clip_dur = float(clip.end_time - clip.start_time)
                diff = vid_dur - clip_dur
                if diff >= 0.5:
                    hook_offset = diff
            except Exception as e:
                logger.debug("Gagal hitung hook offset durasi video (%s), pakai fallback 0.0", e)

        rel_cues = []
        for cue in cues:
            is_direct_clip_stt = bool(cue.get("relative_to_clip")) or (cue["start"] < clip.start_time - 1.0)
            if not is_direct_clip_stt:
                # Timestamp absolut dari DB transkrip video asli → geser setelah teaser (hook_offset)
                start_rel = max(cue["start"] - clip.start_time, 0.0) + hook_offset
                end_rel = max(cue["end"] - clip.start_time, start_rel + 0.1) + hook_offset
            else:
                # Timestamp sudah relatif terhadap video klip (hasil direct STT klip)
                start_rel = max(cue["start"], 0.0)
                end_rel = max(cue["end"], start_rel + 0.1)
                # Cegah tumpang tindih 2 teks (Hook Caption + Kinetic Subtitle) selama teaser berlangsung
                if hook_offset > 0.5:
                    if end_rel <= hook_offset + 0.05:
                        continue
                    if start_rel < hook_offset:
                        start_rel = round(hook_offset, 2)
                        if end_rel <= start_rel + 0.1:
                            continue

            rel_cues.append({
                **cue,
                "start": start_rel,
                "end": end_rel,
            })

        # Sequential Anti-Overlap Guarantee mutlak pada rel_cues (mencegah teks bertabrakan / saling timpa)
        cleaned_rel_cues: list[dict] = []
        for rc in rel_cues:
            if not rc["text"].strip():
                continue
            if not cleaned_rel_cues:
                cleaned_rel_cues.append(dict(rc))
                continue
            prev = cleaned_rel_cues[-1]
            if rc["start"] < prev["end"]:
                if rc["start"] <= prev["start"] + 0.12:
                    prev["text"] = f"{prev['text']} {rc['text']}"
                    prev["words"] = prev.get("words", []) + rc.get("words", [])
                    prev["end"] = max(prev["end"], rc["end"])
                    continue
                else:
                    prev["end"] = round(max(prev["start"] + 0.15, rc["start"] - 0.03), 2)
                    if rc["start"] <= prev["end"]:
                        rc["start"] = round(prev["end"] + 0.03, 2)
                        rc["end"] = round(max(rc["start"] + 0.2, rc["end"]), 2)
            cleaned_rel_cues.append(dict(rc))
        rel_cues = cleaned_rel_cues

        use_ass = style in ("tiktok", "kinetic", "capcut", "ass")
        rendered_with_ass = False

        if use_ass:
            try:
                from app.services.subtitle_service import SubtitleService
                sub_srv = SubtitleService(self.db)
                ass_content = sub_srv._render_ass(
                    rel_cues,
                    width=width,
                    height=height,
                    font_style=font_style,
                    position_y=pos_y,
                )
                ass_file = temp_path.with_suffix(".ass")
                ass_file.write_text(ass_content, encoding="utf-8")

                ass_posix = ass_file.resolve().as_posix().replace(":", "\\:")
                fonts_dir = Path("data/assets/fonts").resolve().as_posix().replace(":", "\\:")
                vf = f"subtitles='{ass_posix}':fontsdir='{fonts_dir}'"

                cmd = [
                    self.ffmpeg.ffmpeg_path, "-y",
                    "-i", str(source),
                    "-vf", vf,
                    "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                    "-pix_fmt", "yuv420p",
                    "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
                    "-c:a", "copy",
                    "-movflags", "+faststart",
                    str(temp_path),
                ]
                subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
                ass_file.unlink(missing_ok=True)
                rendered_with_ass = True
            except Exception as e:
                logger.warning("Gagal burn subtitle ASS (%s), beralih ke fallback drawtext", e)
                temp_path.unlink(missing_ok=True)
                rendered_with_ass = False

        if not rendered_with_ass:
            # Fallback Drawtext dengan font Anton bundel & outline hitam tebal
            anton_font = Path("data/assets/fonts/Anton-Regular.ttf").resolve()
            if anton_font.exists():
                fontfile = anton_font.as_posix().replace(":", "\\:")
            else:
                fontfile = "C\\:/Windows/Fonts/arial.ttf"

            vf_parts: list[str] = []
            fontsize = 64 if height >= 1920 else 44
            for cue in rel_cues:
                text = cue["text"].strip()
                if not text:
                    continue
                safe_text = (
                    text.replace("\\", "\\\\")
                    .replace(":", "\\:")
                    .replace("'", "’")
                )
                vf_parts.append(
                    f"drawtext=fontfile='{fontfile}':text='{safe_text}':fontcolor=white:fontsize={fontsize}:"
                    f"bordercolor=black:borderw=6:x=(w-text_w)/2:y={pos_y}:"
                    f"enable='(gte(t,{cue['start']:.3f}))*(lte(t,{cue['end']:.3f}))'"
                )
            vf = ",".join(vf_parts)

            cmd = [
                self.ffmpeg.ffmpeg_path, "-y",
                "-i", str(source),
                "-vf", vf,
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-pix_fmt", "yuv420p",
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

        self._history_manager(clip_id).push_step(
            clip=clip,
            action="subtitle",
            label="Burn Subtitle",
            temp_file_path=temp_path,
            hook_applied=bool(getattr(clip, "hook_applied", False)),
        )
        clip.has_subtitle = True
        self.db.commit()
        logger.info("Subtitle di-burn ke clip %d (%d cues, style=%s)", clip_id, len(rel_cues), style)
        return clip

    def crop_frame(
        self,
        clip_id: int,
        x: int,
        y: int,
        width: int,
        height: int,
    ):
        """Crop area visual frame video (spatial crop) — potong piksel, bukan durasi.

        Berbeda dari crop() yang memotong durasi (temporal trim), method ini
        memotong AREA FRAME menggunakan FFmpeg filter crop=w:h:x:y sehingga
        resolusi output berubah sesuai ukuran area yang dipilih.

        Args:
            clip_id: ID clip yang akan di-crop.
            x: jarak piksel dari tepi kiri frame ke titik awal crop.
            y: jarak piksel dari tepi atas frame ke titik awal crop.
            width: lebar area crop dalam piksel.
            height: tinggi area crop dalam piksel.

        Raises:
            NotFoundException: clip tidak ditemukan.
            ValidationException: parameter di luar batas video.
        """
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")

        # Validasi parameter dasar
        if x < 0 or y < 0:
            raise ValidationException("x dan y tidak boleh negatif")
        if width <= 0 or height <= 0:
            raise ValidationException("width dan height harus lebih besar dari 0")

        # Ambil dimensi video untuk validasi batas
        source = self._current_source(clip)
        try:
            meta = self.ffmpeg.extract_metadata(str(source))
            vid_w = meta.get("width") or 0
            vid_h = meta.get("height") or 0
        except Exception as e:
            raise ValidationException(f"Gagal baca dimensi video: {str(e)}")

        if vid_w <= 0 or vid_h <= 0:
            raise ValidationException("Tidak bisa mendapatkan dimensi video")
        if x + width > vid_w:
            raise ValidationException(
                f"Area crop melampaui lebar video ({x}+{width}={x+width} > {vid_w})"
            )
        if y + height > vid_h:
            raise ValidationException(
                f"Area crop melampaui tinggi video ({y}+{height}={y+height} > {vid_h})"
            )

        temp_path = self._temp_output_path(clip_id, "crop_frame")

        # FFmpeg filter crop=w:h:x:y — sesuai requirement di prompt
        # -g 60 = keyframe tiap 2 detik (30fps × 2) supaya browser bisa seek
        # tanpa freeze (sama seperti crop() trim & add_text).
        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-i", str(source),
            "-vf", f"crop={width}:{height}:{x}:{y}",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(temp_path),
        ]

        try:
            subprocess.run(
                cmd,
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                check=True,
            )
        except subprocess.SubprocessError as e:
            temp_path.unlink(missing_ok=True)
            logger.error("Gagal crop frame clip %d", clip_id, exc_info=e)
            raise ValidationException(f"Gagal crop frame: {str(e)}")

        self._history_manager(clip_id).push_step(
            clip=clip,
            action="crop_frame",
            label=f"Crop Frame {width}x{height}",
            temp_file_path=temp_path,
        )
        self.db.commit()
        logger.info(
            "Clip %d di-crop frame: x=%d y=%d w=%d h=%d", clip_id, x, y, width, height
        )
        return clip
