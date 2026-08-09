"""Tests for LLMService."""

import json

from app.services.llm_service import LLMService


def test_llm_parse_analysis_response() -> None:
    """_parse_analysis_response should convert JSON string to dict."""
    service = LLMService()

    mock_raw = json.dumps({
        "hook_score": 8,
        "story_score": 9,
        "emotional_score": 7,
        "educational_value": 8,
        "viral_potential": 6,
        "summary": "Great content",
        "key_points": ["Point A", "Point B"],
    })

    result = service._parse_analysis_response(mock_raw)

    assert result["hook_score"] == 8.0
    assert result["story_score"] == 9.0
    assert result["summary"] == "Great content"
    assert len(result["key_points"]) == 2


def test_llm_no_api_key_fallback() -> None:
    """LLMService should return mock analysis when no API key."""
    service = LLMService()
    service.api_key = ""

    result = service.analyze_video("any")

    assert result["hook_score"] == 6.5
    assert result["summary"] == "Content analyzed (mock mode - no API key)"
