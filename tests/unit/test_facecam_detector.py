"""Tests for FacecamDetectorService."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.facecam_detector_service import FacecamDetectorService, _FACECAM_CACHE


def test_get_facecam_crop_filter_mappings():
    """Verify crop filters generate correct x, y, w, h formulas for FFmpeg."""
    service = FacecamDetectorService()

    # bottom_left
    bl = service.get_facecam_crop_filter("bottom_left")
    assert "x=0" in bl
    assert "y=ih-ih*0.39" in bl
    assert "1080:800" in bl

    # bottom_right
    br = service.get_facecam_crop_filter("bottom_right")
    assert "x=iw-iw*0.31" in br
    assert "y=ih-ih*0.39" in br
    assert "1080:800" in br

    # top_left
    tl = service.get_facecam_crop_filter("top_left")
    assert "x=0" in tl
    assert "y=0" in tl
    assert "1080:800" in tl

    # top_right
    tr = service.get_facecam_crop_filter("top_right")
    assert "x=iw-iw*0.31" in tr
    assert "y=0" in tr
    assert "1080:800" in tr

    # default/fallback
    fallback = service.get_facecam_crop_filter("unknown_position")
    assert fallback == br


def test_detect_facecam_nonexistent_file():
    """Detection on a non-existent file returns bottom_right with 0 confidence."""
    service = FacecamDetectorService()
    result = service.detect_facecam_position("non_existent_video_path.mp4")
    assert result["position"] == "bottom_right"
    assert result["confidence"] == 0.0


def test_detect_facecam_cached():
    """FacecamDetector returns cached result if already scanned."""
    service = FacecamDetectorService()
    test_path = "C:/test_dummy_video.mp4"
    resolved_key = str(Path(test_path).resolve())
    _FACECAM_CACHE[resolved_key] = {
        "position": "bottom_left",
        "confidence": 1.0,
        "center": (0.15, 0.85),
        "corner_scores": {"bottom_left": 4, "bottom_right": 0, "top_left": 0, "top_right": 0},
    }

    result = service.detect_facecam_position(test_path)
    assert result["position"] == "bottom_left"
    assert result["confidence"] == 1.0
