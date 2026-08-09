"""Tests for LLMAnalyzer plugin."""

import json

from app.ai_modules.llm_analysis.llm_analyzer import LLMAnalyzer


def test_llm_parse_analysis_response() -> None:
    """_parse_analysis_response should convert JSON string to dict."""
    analyzer = LLMAnalyzer()

    mock_raw = json.dumps({
        "hook_score": 8,
        "story_score": 9,
        "emotional_score": 7,
        "educational_value": 8,
        "viral_potential": 6,
        "summary": "Great content",
        "key_points": ["Point A", "Point B"],
    })

    result = analyzer._parse_analysis_response(mock_raw)

    assert result["hook_score"] == 8.0
    assert result["story_score"] == 9.0
    assert result["summary"] == "Great content"
    assert len(result["key_points"]) == 2


def test_llm_no_api_key_fallback() -> None:
    """LLMAnalyzer should return mock analysis when no API key."""
    analyzer = LLMAnalyzer()
    analyzer.api_key = ""

    result = analyzer.analyze({"transcript_text": "any"})

    assert result.score == 6.5  # rata-rata mock: (6.5+7.0+6.0+7.5+5.5)/5 = 6.5
    assert "summary" in result.result_data
