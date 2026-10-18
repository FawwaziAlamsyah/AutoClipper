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
    assert "ending" in result
    assert "keyword_boost" in result
    assert all({"score", "reason"} <= set(v) for v in result.values())
    # llm_content sekarang dihasilkan LLMService, bukan run_all_validators
    assert "llm_content" not in result


def test_validate_hook_cold_open_potential_in_body():
    """Hook validator should add cold-open bonus when body contains hook triggers."""
    intro_filler = "Halo semuanya kembali lagi bersama kita di acara hari ini. " * 6
    body_hook = "Tapi tunggu, ternyata ada rahasia besar yang belum pernah terungkap!"
    score, reason = validate_hook(intro_filler + body_hook)
    assert score >= 6.0
    assert "cold-open hook" in reason


def test_validate_baselines_for_flat_content():
    """Flat/monotone text without hook/viral/story signals should get low calibrated baselines."""
    from app.services.validators import validate_story, validate_viral, validate_ending
    flat_text = "Saya makan nasi goreng tadi pagi dan minum air putih biasa saja."
    hook_score, hook_reason = validate_hook(flat_text)
    assert hook_score == 2.0
    assert "Tidak ada pola hook jelas" in hook_reason

    viral_score, viral_reason = validate_viral(flat_text)
    assert viral_score == 2.0
    assert "Tidak ada kata viral kuat" in viral_reason

    story_score, _ = validate_story(flat_text)
    assert story_score == 3.0

    ending_score, _ = validate_ending(flat_text)
    assert ending_score == 2.5


def test_validate_pacing_dead_air_and_slow_intro():
    """validate_pacing should penalize initial dead-air silence and slow filler intros."""
    from app.services.validators import validate_pacing

    # 1. Dead air >= 2.0s
    score, reason = validate_pacing("Kenapa hal ini bisa terjadi?", start_delay=2.5)
    assert score == -1.5
    assert "Dead air" in reason

    # 2. Moderate silence 1.2s - 1.9s
    score, reason = validate_pacing("Kenapa hal ini bisa terjadi?", start_delay=1.5)
    assert score == -0.8
    assert "Jeda hening" in reason

    # 3. Slow intro filler starter
    score, reason = validate_pacing("Halo semuanya kembali lagi di channel gue hari ini.", start_delay=0.2)
    assert score == -1.0
    assert "slow-pacing" in reason

    # 4. Both dead air and slow intro
    score, reason = validate_pacing("Halo guys kembali lagi bersama kita.", start_delay=2.5)
    assert score == -2.5
    assert "Dead air" in reason
    assert "slow-pacing" in reason

    # 5. Clean, fast intro
    score, reason = validate_pacing("Tahukah kamu bahwa ini rahasia terbesar?", start_delay=0.4)
    assert score == 0.0
    assert "baik" in reason


def test_run_all_validators_includes_slow_start():
    """run_all_validators should include slow_start analyzer when delay or filler exists."""
    res = run_all_validators("Halo guys kembali lagi.", start_delay=2.5)
    assert "slow_start" in res
    assert res["slow_start"]["score"] < 0



