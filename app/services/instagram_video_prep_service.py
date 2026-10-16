"""Service untuk menyiapkan video ke bingkai 9:16 untuk Instagram Reels."""

from dataclasses import dataclass
import logging
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.services.ffmpeg_service import FFmpegService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedVideo:
    """Hasil persiapan video untuk Instagram Reels."""

    path: Path
    is_temp: bool
    reframed: bool
    width: int = 0
    height: int = 0


class InstagramVideoPrepService:
    """Service untuk otomatis memasukkan video ke kanvas 9:16 (1080x1920)."""

    def __init__(self, ffmpeg_service: FFmpegService | None = None) -> None:
        self.ffmpeg_service = ffmpeg_service or FFmpegService()

    def needs_reframe(self, width: int, height: int) -> bool:
        """Cek apakah rasio video berbeda dari vertikal 9:16 dengan toleransi 1% (|w/h - 9/16| > 0.01)."""
        if width <= 0 or height <= 0:
            return False
        return abs((width / height) - (9.0 / 16.0)) > 0.01

    def needs_transcode(self, meta: dict) -> bool:
        """Cek apakah video membutuhkan normalisasi encoding untuk kepatuhan Instagram Reels.
        
        Instagram menolak video yang bukan H.264, bukan yuv420p (misal yuv444p High 4:4:4 Predictive),
        atau memiliki SAR non-square yang menyebabkan 'Video Transcoding Error: both HD and SD progressive failed to transcode'.
        """
        if not meta:
            return False

        # 1. Pixel format harus yuv420p (atau yuvj420p)
        pix_fmt = meta.get("pix_fmt")
        if pix_fmt and pix_fmt not in ("yuv420p", "yuvj420p"):
            return True

        # 2. Profile tidak boleh 4:4:4
        profile = (meta.get("profile") or "").lower()
        if "4:4:4" in profile:
            return True

        # 3. Video codec harus h264 jika diketahui
        video_codec = (meta.get("video_codec") or "").lower()
        if video_codec and video_codec not in ("h264", "avc", "avc1"):
            return True

        # 4. Sample Aspect Ratio (SAR) harus 1:1 jika ada
        sar = str(meta.get("sample_aspect_ratio") or "")
        if sar and sar not in ("1:1", "1/1", "0:1", "1", "None", ""):
            return True

        return False

    def prepare(
        self,
        source: Path,
        fit_mode: str | None = None,
        on_progress: Callable[[str, int], None] | None = None,
    ) -> PreparedVideo:
        """Siapkan video untuk Instagram Reels.

        Jika video bukan 9:16 atau encoding-nya belum standar Instagram (bukan yuv420p / SAR != 1:1),
        dan fit_mode bukan 'off', transcode ke salinan sementara 1080x1920 (pad atau blur).
        File sumber asli tidak pernah diubah.
        """
        source = Path(source)
        if not source.exists():
            raise ValidationException(f"File video sumber tidak ditemukan di disk: {source}")

        # 1. Validasi dan tentukan fit_mode
        mode = fit_mode or settings.IG_FIT_MODE
        if mode not in ("pad", "blur", "off"):
            logger.warning("Fit mode '%s' tidak valid, fallback ke 'pad'", mode)
            mode = "pad"

        # Jika mode="off", langsung bypass tanpa reframe
        if mode == "off":
            meta = {}
            try:
                meta = self.ffmpeg_service.extract_metadata(str(source))
            except Exception:
                pass
            w = meta.get("width") or 0
            h = meta.get("height") or 0
            return PreparedVideo(path=source, is_temp=False, reframed=False, width=w, height=h)

        # 2. Ekstrak metadata dimensi tampilan
        meta = self.ffmpeg_service.extract_metadata(str(source))
        w = meta.get("width") or 0
        h = meta.get("height") or 0
        rot = meta.get("rotation") or 0

        # Jika ada rotasi tampilan 90 atau 270 derajat, tukar lebar dan tinggi
        if abs(int(rot)) % 180 == 90:
            w, h = h, w

        if w <= 0 or h <= 0:
            raise ValidationException("Dimensi video tidak valid atau gagal dibaca.")

        # 3. Cek apakah reframe atau normalisasi encoding diperlukan
        reframe_needed = self.needs_reframe(w, h)
        transcode_needed = self.needs_transcode(meta)

        if not reframe_needed and not transcode_needed:
            logger.info(
                "InstagramVideoPrep: Video tidak perlu reframe/transcode (mode=%s, w=%d, h=%d)",
                mode,
                w,
                h,
            )
            return PreparedVideo(path=source, is_temp=False, reframed=False, width=w, height=h)

        # 4. Buat folder temporary unik
        temp_dir = Path(tempfile.mkdtemp(prefix="ig_fit_"))
        target_path = temp_dir / "reel.mp4"

        target_w = settings.IG_TARGET_WIDTH
        target_h = settings.IG_TARGET_HEIGHT
        fps = meta.get("fps") or 30.0
        fps_clause = ",fps=30" if fps > 30.0 else ""

        # 5. Bangun argumen perintah ffmpeg berdasarkan mode
        ffmpeg_bin = self.ffmpeg_service.ffmpeg_path
        cmd: list[str] = [ffmpeg_bin, "-y", "-i", str(source)]

        if reframe_needed and mode == "blur":
            fc = (
                f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
                f"crop={target_w}:{target_h},boxblur=20:5[bg];"
                f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1{fps_clause}[v]"
            )
            cmd.extend([
                "-filter_complex", fc,
                "-map", "[v]",
                "-map", "0:a?",
            ])
        else:  # mode == "pad" atau transcode_needed pada video 9:16
            vf = (
                f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1{fps_clause}"
            )
            cmd.extend([
                "-vf", vf,
                "-map", "0:v:0",
                "-map", "0:a?",
            ])

        cmd.extend([
            "-c:v", "libx264",
            "-profile:v", "main",
            "-level", "4.1",
            "-preset", settings.IG_FIT_PRESET,
            "-crf", str(settings.IG_FIT_CRF),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            "-movflags", "+faststart",
            str(target_path),
        ])

        # 6. Eksekusi ffmpeg
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=settings.IG_FIT_TIMEOUT_SECONDS,
            )
            if res.returncode != 0:
                self._cleanup_temp_dir(temp_dir)
                raw_err = (res.stderr or "").strip()[-500:]
                clean_err = self._sanitize_error(raw_err)
                raise ValidationException(f"Gagal menyiapkan video 9:16: {clean_err}")

        except subprocess.TimeoutExpired as e:
            self._cleanup_temp_dir(temp_dir)
            raise ValidationException(
                f"Gagal menyiapkan video 9:16: Timeout setelah {settings.IG_FIT_TIMEOUT_SECONDS} detik"
            ) from e
        except Exception:
            self._cleanup_temp_dir(temp_dir)
            raise

        logger.info(
            "InstagramVideoPrep: Video berhasil di-reframe 9:16 (mode=%s, target=%s)",
            mode,
            target_path,
        )
        return PreparedVideo(
            path=target_path,
            is_temp=True,
            reframed=True,
            width=target_w,
            height=target_h,
        )

    def cleanup(self, prepared: PreparedVideo | None) -> None:
        """Hapus file dan folder temp jika is_temp=True. File sumber asli tidak disentuh."""
        if prepared is None or not prepared.is_temp:
            return

        parent = prepared.path.parent
        self._cleanup_temp_dir(parent)

    def _cleanup_temp_dir(self, directory: Path) -> None:
        """Hapus direktori temporary jika berawalan 'ig_fit_'."""
        try:
            if directory.exists() and directory.name.startswith("ig_fit_"):
                shutil.rmtree(directory, ignore_errors=True)
        except Exception as e:
            logger.warning("Gagal membersihkan direktori temporary %s: %s", directory, e)

    @staticmethod
    def _sanitize_error(err_text: str) -> str:
        """Bersihkan path lokal sensitif dari pesan error stderr."""
        # Samarkan path Windows / Unix
        sanitized = re.sub(r"[A-Za-z]:\\[^\s\r\n]+", "[PATH]", err_text)
        sanitized = re.sub(r"/(?:Users|home|root)/[^\s\r\n]+", "[PATH]", sanitized)
        return sanitized or "Terjadi kesalahan pada transcode FFmpeg."
