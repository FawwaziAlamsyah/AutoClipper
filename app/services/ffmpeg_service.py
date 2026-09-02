"""FFmpeg & ffprobe service for video metadata extraction and audio extraction."""

import json
import logging
import subprocess
from pathlib import Path

from app.core.config.settings import settings
from app.core.exceptions.base import ExternalToolException

logger = logging.getLogger(__name__)

# Windows default encoding (cp1252) crash kalau ffprobe/ffmpeg emit byte non-ASCII
# (judul YouTube, metadata). Paksa UTF-8 + replace supaya stdout selalu str.
_SUBPROCESS_KW = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}


class FFmpegService:
    """Wrapper service for FFmpeg and ffprobe operations."""

    def __init__(self) -> None:
        """Initialize and verify executable names/paths."""
        self.ffmpeg_path = settings.FFMPEG_PATH
        self.ffprobe_path = settings.FFPROBE_PATH

    def extract_metadata(self, video_path: str) -> dict:
        """Extract video metadata (duration, width, height, fps, bitrate) using ffprobe."""
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found at: {video_path}")

        cmd = [
            self.ffprobe_path,
            "-v", "error",
            "-show_format",
            "-show_streams",
            "-of", "json",
            video_path
        ]

        try:
            result = subprocess.run(cmd, check=True, **_SUBPROCESS_KW)
            probe_data = json.loads(result.stdout)
            
            metadata = {
                "duration_seconds": None,
                "width": None,
                "height": None,
                "fps": None,
            }

            # Ambil detail format info
            fmt = probe_data.get("format", {})
            if "duration" in fmt:
                metadata["duration_seconds"] = float(fmt["duration"])

            # Cari video stream
            for stream in probe_data.get("streams", []):
                if stream.get("codec_type") == "video":
                    metadata["width"] = int(stream["width"]) if "width" in stream else None
                    metadata["height"] = int(stream["height"]) if "height" in stream else None
                    
                    # Hitung FPS (misal: "30/1" atau "24000/1001")
                    r_frame_rate = stream.get("r_frame_rate", "")
                    if "/" in r_frame_rate:
                        num, den = map(int, r_frame_rate.split("/"))
                        if den != 0:
                            metadata["fps"] = round(num / den, 2)
                    break

            logger.info("Extracted metadata for %s: %s", video_path, metadata)
            return metadata

        except (subprocess.SubprocessError, json.JSONDecodeError) as e:
            logger.error("Failed to run ffprobe on: %s", video_path, exc_info=e)
            raise ExternalToolException(f"Gagal mengekstrak metadata video: {str(e)}")

    def extract_preview_clip(self, video_path: str, start: float, end: float, output_path: str) -> str:
        """Potong cepat segmen video jadi file preview kecil (stream copy, tanpa re-encode).

        Pakai -c copy supaya nyaris instan bahkan untuk source video berjam-jam —
        ini BUKAN untuk kualitas final (potongan bisa meleset ke keyframe terdekat,
        bukan frame presisi), cukup untuk preview cepat di UI. Untuk hasil final
        yang presisi & reframe, tetap pakai ClipService.generate_clip().
        """
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found at: {video_path}")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        duration = max(end - start, 0.1)

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            output_path,
        ]

        try:
            logger.info("Trimming preview clip: %s [%s-%s]", video_path, start, end)
            subprocess.run(cmd, check=True, **_SUBPROCESS_KW)
            return output_path
        except subprocess.SubprocessError as e:
            logger.error("Preview trim failed for: %s", video_path, exc_info=e)
            raise ExternalToolException(f"Gagal membuat preview clip: {str(e)}")

    def extract_audio(self, video_path: str, output_wav_path: str) -> str:
        """Extract audio stream to a 16kHz mono 16-bit PCM WAV file."""
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found at: {video_path}")

        # Pastikan parent directory output file ada
        Path(output_wav_path).parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.ffmpeg_path,
            "-y",  # Overwrite file jika sudah ada
            "-i", video_path,
            "-vn",  # Abaikan video stream
            "-acodec", "pcm_s16le",  # Format PCM 16-bit
            "-ar", "16000",  # Sample rate 16000Hz (optimal untuk Whisper)
            "-ac", "1",  # Mono channel
            output_wav_path
        ]

        try:
            logger.info("Running FFmpeg extraction command: %s", " ".join(cmd))
            subprocess.run(cmd, check=True, **_SUBPROCESS_KW)
            logger.info("Extracted audio successfully to: %s", output_wav_path)
            return output_wav_path
        except subprocess.SubprocessError as e:
            logger.error("FFmpeg audio extraction failed for: %s", video_path, exc_info=e)
            raise ExternalToolException(f"Gagal memisahkan audio dari video: {str(e)}")

    def generate_vision_proxy(
        self,
        video_path: str,
        output_path: str,
        height: int = 480,
    ) -> str:
        """Generate proxy video beresolusi rendah khusus untuk analisis visual.

        Hanya resolusi yang diturunkan (scale ke height px, lebar proporsional).
        FPS TIDAK diubah — penting agar sampling temporal gesture/scene tetap akurat.
        Audio di-strip karena proxy ini hanya untuk cv2 frame decode.

        Proxy ini adalah step opsional sebelum VideoVisionPass. Karena hanya
        resolusi yang berubah (bukan fps/durasi), semua timestamp window tetap valid.
        """
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found at: {video_path}")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # scale=-2:{height} → lebar dihitung otomatis agar tetap divisible by 2
        # (libx264 mensyaratkan dimensi genap).
        # -an: strip audio (tidak dibutuhkan untuk visual-only analysis).
        # -crf 28: kualitas sedikit lebih rendah dari default; cukup untuk deteksi
        #          wajah/tangan/scene — bukan untuk output final.
        # -preset fast: keseimbangan kecepatan encode vs ukuran file.
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", video_path,
            "-vf", f"scale=-2:{height}",
            "-an",
            "-c:v", "libx264",
            "-crf", "28",
            "-preset", "fast",
            output_path,
        ]

        try:
            logger.info(
                "Generating vision proxy %dpx: %s → %s",
                height, video_path, output_path,
            )
            subprocess.run(cmd, check=True, **_SUBPROCESS_KW)
            logger.info("Vision proxy generated: %s", output_path)
            return output_path
        except subprocess.SubprocessError as e:
            logger.error(
                "Vision proxy generation failed for: %s", video_path, exc_info=e,
            )
            raise ExternalToolException(
                f"Gagal membuat vision proxy video: {str(e)}"
            )
