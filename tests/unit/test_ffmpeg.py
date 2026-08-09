"""Tests for FFmpegService using subprocess mock."""

import json
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from app.services.ffmpeg_service import FFmpegService, ExternalToolException


def test_extract_metadata_success() -> None:
    """extract_metadata should parse ffprobe stdout correctly."""
    service = FFmpegService()
    
    mock_stdout = json.dumps({
        "format": {
            "duration": "123.45"
        },
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1"
            }
        ]
    })

    with patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.run") as mock_run:
        
        mock_run.return_value = MagicMock(stdout=mock_stdout, returncode=0)
        
        metadata = service.extract_metadata("dummy.mp4")
        
        assert metadata["duration_seconds"] == 123.45
        assert metadata["width"] == 1920
        assert metadata["height"] == 1080
        assert metadata["fps"] == 30.0


def test_extract_metadata_file_not_found() -> None:
    """extract_metadata should raise FileNotFoundError if file does not exist."""
    service = FFmpegService()
    
    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(FileNotFoundError):
            service.extract_metadata("non_existent.mp4")


def test_extract_audio_success() -> None:
    """extract_audio should trigger correct ffmpeg subprocess args."""
    service = FFmpegService()
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run") as mock_run:
        
        mock_run.return_value = MagicMock(returncode=0)
        
        res = service.extract_audio("input.mp4", "output.wav")
        assert res == "output.wav"
        
        # Verify call contains key flags
        called_args = mock_run.call_args[0][0]
        assert "ffmpeg" in called_args[0]
        assert "-vn" in called_args
        assert "-ar" in called_args
        assert "16000" in called_args
