"""Tests for text-based validators."""

from app.services.validators import (
    run_all_validators,
    validate_hook,
    validate_penalty,
    validate_keyword_boost,
)


def test_validate_hook_question():
    """Hook validator should boost on opening question."""
    score, reason = validate_hook("Apakah kamu tahu kenapa ini viral? Itu karena...")
    assert score >= 7.0
    assert "pertanyaan" in reason


def test_validate_penalty_sponsor():
    """Penalty validator should flag sponsor content."""
    score, reason = validate_penalty("Video ini di sponsor oleh brand")
    assert score < 0
    assert "sponsor" in reason


def test_validate_keyword_boost():
    """Keyword boost should increase on matched keywords."""
    score, reason = validate_keyword_boost("Investasi Bitcoin sangat menarik", ["bitcoin", "ai"])
    assert score > 5.0
    assert "bitcoin" in reason


def test_run_all_validators_shape():
    """run_all_validators should return dict of analyzer payloads."""
    result = run_all_validators("Bayangkan! Pertama kita investasi, akhirnya kita sukses.", ["investasi"])
    assert "hook" in result
    assert "story" in result
    assert "llm_content" in result
    assert "ending" in result
    assert "keyword_boost" in result
    assert all({"score", "reason"} <= set(v) for v in result.values())
