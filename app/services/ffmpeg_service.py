"""FFmpeg & ffprobe service for video metadata extraction and audio extraction."""

import json
import logging
import subprocess
from pathlib import Path

from app.core.config.settings import settings
from app.core.exceptions.base import ExternalToolException

logger = logging.getLogger(__name__)


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
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
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
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info("Extracted audio successfully to: %s", output_wav_path)
            return output_wav_path
        except subprocess.SubprocessError as e:
            logger.error("FFmpeg audio extraction failed for: %s", video_path, exc_info=e)
            raise ExternalToolException(f"Gagal memisahkan audio dari video: {str(e)}")
