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


def test_llm_parse_viral_criteria_with_markdown_fence() -> None:
    """_parse_analysis_response should correctly strip markdown code fences and parse viral fields."""
    analyzer = LLMAnalyzer()

    mock_raw = """```json
    {
        "curiosity_hook": 9.0,
        "emotional_payoff": 8.0,
        "shareability": 8.5,
        "idea_completeness": 7.0,
        "viral_reason": "Pembuka langsung menarik rasa penasaran penonton dan ada punchline kuat.",
        "hook_headline": "Rahasia Bisnis Terbesar 2026",
        "key_points": ["Strategi marketing baru", "Hasil penjualan fantastis"]
    }
    ```"""

    result = analyzer._parse_analysis_response(mock_raw)

    assert result["curiosity_hook"] == 9.0
    assert result["emotional_payoff"] == 8.0
    assert result["shareability"] == 8.5
    assert result["idea_completeness"] == 7.0
    assert result["hook_headline"] == "Rahasia Bisnis Terbesar 2026"
    assert "punchline kuat" in result["viral_reason"]
    assert len(result["key_points"]) == 2


def test_llm_analyze_weighted_scoring() -> None:
    """analyze() should apply viral retention weights: 35% hook, 25% payoff, 25% share, 15% complete."""
    from unittest.mock import patch
    analyzer = LLMAnalyzer()

    mock_dict = {
        "_source": "llm",
        "curiosity_hook": 10.0,
        "emotional_payoff": 8.0,
        "shareability": 6.0,
        "idea_completeness": 8.0,
        "viral_reason": "High viral potential",
        "hook_headline": "Amazing Secret",
        "key_points": ["Key 1"],
    }

    with patch.object(analyzer, "_analyze_video", return_value=mock_dict):
        result = analyzer.analyze({"transcript_text": "sample text"})

    # 10*0.35 (3.5) + 8*0.25 (2.0) + 6*0.25 (1.5) + 8*0.15 (1.2) = 8.20
    assert result.score == 8.20
    assert result.result_data["curiosity_hook"] == 10.0
    assert result.result_data["hook_headline"] == "Amazing Secret"

