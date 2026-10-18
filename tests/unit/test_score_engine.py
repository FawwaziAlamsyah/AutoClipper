"""Tests for ScoreEngine."""

from unittest.mock import MagicMock, patch

from app.services.score_engine import ScoreEngine


def test_calculate_score_breakdown() -> None:
    """ScoreEngine should aggregate weighted scores correctly."""
    mock_db = MagicMock()

    mock_repo = MagicMock()
    mock_repo.get_by_job.return_value = [
        MagicMock(analyzer_type="hook", score=8.0, start_time=0.0, end_time=10.0, result_data={"reason": "Pembuka kuat"}),
        MagicMock(analyzer_type="story", score=7.0, start_time=0.0, end_time=10.0, result_data={"reason": "Alur jelas"}),
        MagicMock(analyzer_type="llm_content", score=6.0, start_time=0.0, end_time=10.0, result_data={"reason": "Konten LLM"}),
        MagicMock(analyzer_type="voice_emotion", score=5.0, start_time=0.0, end_time=10.0, result_data={"reason": "Vokal netral"}),
        MagicMock(analyzer_type="face_emotion", score=4.0, start_time=0.0, end_time=10.0, result_data={"reason": "Wajah minim"}),
    ]

    with patch("app.services.score_engine.VideoRepository") as MockVideoRepo, \
         patch("app.services.score_engine.JobRepository") as MockJobRepo, \
         patch("app.services.score_engine.AnalysisResultRepository") as MockAnalysisRepo, \
         patch("app.services.score_engine.CandidateRepository") as MockCandidateRepo:
        MockAnalysisRepo.return_value = mock_repo
        engine = ScoreEngine(mock_db)
        engine.analysis_repo = mock_repo

        candidate = MagicMock(start_time=0.0, end_time=10.0)
        breakdown = engine._calculate_score_breakdown(job_id=1, candidate=candidate)

        assert "llm_content" in breakdown
        assert "hook" in breakdown
        assert "story" in breakdown

        # Shape baru: dict-of-dicts dengan score/weight/contribution/reason
        hook = breakdown["hook"]
        assert set(hook) == {"score", "weight", "contribution", "reason"}
        assert hook["score"] == 8.0
        assert hook["contribution"] == round(8.0 * hook["weight"], 2)
        assert hook["reason"] == "Pembuka kuat"


def test_final_score_uses_weighted_as_base_with_trained_blend() -> None:
    """Kiblat bobot: final_score = bobot (0.8) + trained (0.2) bila model ada."""
    mock_db = MagicMock()

    cand = MagicMock(start_time=0.0, end_time=10.0, final_score=0.0, score_breakdown={})

    with patch("app.services.score_engine.VideoRepository"), \
         patch("app.services.score_engine.JobRepository") as MockJobRepo, \
         patch("app.services.score_engine.AnalysisResultRepository") as MockAR, \
         patch("app.services.score_engine.CandidateRepository") as MockCR, \
         patch("app.services.score_engine.predict_score") as mock_predict, \
         patch("app.services.score_engine.get_trained_weight", return_value=0.8), \
         patch("app.services.score_engine.get_fallback_weight", return_value=0.2):
        mock_predict.return_value = 7.0
        mock_job = MagicMock(category_id=66)
        MockJobRepo.return_value.get.return_value = mock_job
        MockCR.return_value.get_by_job.return_value = [cand]
        MockAR.return_value.get_by_job.return_value = [
            MagicMock(analyzer_type="hook", score=10.0, start_time=0.0, end_time=10.0, result_data={}),
        ]

        engine = ScoreEngine(mock_db)
        # stub breakdown → weighted 4.0, trained 7.0 → final 0.8*7 + 0.2*4 = 6.4
        engine._calculate_score_breakdown = lambda j, c, cat: {
            "hook": {"score": 10.0, "weight": 0.4, "contribution": 4.0, "reason": ""},
            "_meta": {
                "scoring_method": "trained_model",
                "legacy_weighted_sum_score": 4.0,
                "model_predicted_score": 7.0,
            },
        }

        engine.calculate_for_job(1)
        assert cand.final_score == round(0.8 * 7.0 + 0.2 * 4.0, 2)  # 6.4


def test_final_score_pure_weighted_when_no_model() -> None:
    """Tanpa trained model → final_score = weighted sum murni (bobot kiblat)."""
    mock_db = MagicMock()

    cand = MagicMock(start_time=0.0, end_time=10.0, final_score=0.0, score_breakdown={})

    with patch("app.services.score_engine.VideoRepository"), \
         patch("app.services.score_engine.JobRepository") as MockJobRepo, \
         patch("app.services.score_engine.AnalysisResultRepository") as MockAR, \
         patch("app.services.score_engine.CandidateRepository") as MockCR, \
         patch("app.services.score_engine.predict_score") as mock_predict:
        mock_predict.return_value = None
        MockJobRepo.return_value.get.return_value = MagicMock(category_id=None)
        MockCR.return_value.get_by_job.return_value = [cand]
        MockAR.return_value.get_by_job.return_value = [
            MagicMock(analyzer_type="hook", score=10.0, start_time=0.0, end_time=10.0, result_data={}),
        ]

        engine = ScoreEngine(mock_db)
        engine._calculate_score_breakdown = lambda j, c, cat: {
            "hook": {"score": 10.0, "weight": 0.4, "contribution": 4.0, "reason": ""},
            "_meta": {
                "scoring_method": "weighted_sum",
                "legacy_weighted_sum_score": 4.0,
                "model_predicted_score": None,
            },
        }

        engine.calculate_for_job(1)
        assert cand.final_score == 4.0

    """Regression test: dua candidate window beda HARUS skor beda (bukan rata-rata global).

    Bug: analysis difilter per window. Tanpa filter, semua candidate dapat
    final_score identik (rata-rata seluruh job).
    """
    mock_db = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_by_job.return_value = [
        # Window A (0-10s): hook tinggi
        MagicMock(analyzer_type="hook", score=9.0, start_time=0.0, end_time=10.0, result_data={"reason": "A"}),
        # Window B (100-110s): hook rendah
        MagicMock(analyzer_type="hook", score=3.0, start_time=100.0, end_time=110.0, result_data={"reason": "B"}),
    ]

    with patch("app.services.score_engine.VideoRepository"), \
         patch("app.services.score_engine.JobRepository"), \
         patch("app.services.score_engine.AnalysisResultRepository"), \
         patch("app.services.score_engine.CandidateRepository"):
        engine = ScoreEngine(mock_db)
        engine.analysis_repo = mock_repo

        cand_a = MagicMock(start_time=0.0, end_time=10.0)
        cand_b = MagicMock(start_time=100.0, end_time=110.0)
        bd_a = engine._calculate_score_breakdown(1, cand_a)
        bd_b = engine._calculate_score_breakdown(1, cand_b)

        score_a = sum(v["contribution"] for k, v in bd_a.items() if k != "_meta")
        score_b = sum(v["contribution"] for k, v in bd_b.items() if k != "_meta")

        assert score_a != score_b, f"skor harus beda per window: A={score_a}, B={score_b}"
        assert bd_a["hook"]["score"] == 9.0
        assert bd_b["hook"]["score"] == 3.0


def test_select_top_n_filters_below_min_score() -> None:
    """Candidates below settings.MIN_CANDIDATE_SCORE (6.0) must be rejected."""
    engine = ScoreEngine(MagicMock())
    cands = [
        MagicMock(id=1, start_time=0.0, end_time=30.0, final_score=7.5),
        MagicMock(id=2, start_time=35.0, end_time=65.0, final_score=5.2),  # di bawah 6.0
        MagicMock(id=3, start_time=70.0, end_time=100.0, final_score=4.8), # di bawah 6.0
    ]
    engine.candidate_repo = MagicMock()
    engine.candidate_repo.get_by_job.return_value = cands
    engine.db = MagicMock()

    with patch("app.services.score_engine.settings.MIN_CANDIDATE_SCORE", 6.0):
        selected = engine.select_top_n(1, n=3)

    assert len(selected) == 1
    assert selected[0].id == 1


def test_get_analyzer_score_neutral_fallback() -> None:
    """Missing analyzer results in window should fallback to 5.0 (0-10 neutral scale)."""
    engine = ScoreEngine(MagicMock())
    score = engine._get_analyzer_score([], "gesture")
    assert score == 5.0


def test_score_weights_sum_and_priorities() -> None:
    """Total default score weights must equal 1.00 and prioritize hook & content."""
    from app.core.config.settings import settings

    weights = [
        settings.SCORE_WEIGHT_HOOK,
        settings.SCORE_WEIGHT_LLM_CONTENT,
        settings.SCORE_WEIGHT_VOICE_EMOTION,
        settings.SCORE_WEIGHT_GESTURE,
        settings.SCORE_WEIGHT_FACE_EMOTION,
        settings.SCORE_WEIGHT_ENDING,
        settings.SCORE_WEIGHT_STORY,
        settings.SCORE_WEIGHT_SCENE,
        settings.SCORE_WEIGHT_EYE_CONTACT,
        settings.SCORE_WEIGHT_AUDIO,
        settings.SCORE_WEIGHT_CONTEXT,
        settings.SCORE_WEIGHT_VIRAL_POTENTIAL,
    ]
    assert round(sum(weights), 4) == 1.00
    # Prioritas utama: Hook > LLM Content > Voice Emotion > Gesture > Face Emotion
    assert settings.SCORE_WEIGHT_HOOK >= 0.25
    assert settings.SCORE_WEIGHT_LLM_CONTENT >= 0.20
    assert settings.SCORE_WEIGHT_VOICE_EMOTION >= 0.15
    assert settings.SCORE_WEIGHT_HOOK > settings.SCORE_WEIGHT_GESTURE
    assert settings.SCORE_WEIGHT_LLM_CONTENT > settings.SCORE_WEIGHT_FACE_EMOTION


def test_hook_gatekeeper_multiplier_levels() -> None:
    """Gatekeeper should apply correct multipliers according to hook quality."""
    engine = ScoreEngine(MagicMock())

    # None hook -> netral 1.0x
    mult, reason = engine._calculate_hook_gatekeeper(None)
    assert mult == 1.0
    assert "netral" in reason

    # Strong hook (>= 6.0) -> 1.0x
    mult, reason = engine._calculate_hook_gatekeeper(7.5)
    assert mult == 1.0
    assert "Lolos Gatekeeper" in reason

    # Moderate hook (4.0 - 5.9) -> 0.85x
    mult, reason = engine._calculate_hook_gatekeeper(5.0)
    assert mult == 0.85
    assert "0.85" in reason

    # Weak hook (< 4.0) -> 0.60x
    mult, reason = engine._calculate_hook_gatekeeper(2.0)
    assert mult == 0.60
    assert "Penalty" in reason


def test_weak_hook_gets_gatekeeper_discount_in_breakdown() -> None:
    """Window with weak hook (< 4.0) should have its final legacy score discounted."""
    mock_db = MagicMock()
    mock_repo = MagicMock()
    # Analyzer: Hook 2.0 (lemah), gesture 10.0 (tinggi)
    mock_repo.get_by_job.return_value = [
        MagicMock(analyzer_type="hook", score=2.0, start_time=0.0, end_time=10.0, result_data={"reason": "Pembuka lemah"}),
        MagicMock(analyzer_type="gesture", score=10.0, start_time=0.0, end_time=10.0, result_data={"reason": "Tangan aktif"}),
    ]

    engine = ScoreEngine(mock_db)
    engine.analysis_repo = mock_repo

    cand = MagicMock(start_time=0.0, end_time=10.0)
    bd = engine._calculate_score_breakdown(1, cand)

    raw_weighted = bd["_meta"]["raw_weighted_sum_score"]
    mult = bd["_meta"]["gatekeeper_multiplier"]
    discounted = bd["_meta"]["legacy_weighted_sum_score"]

    assert mult == 0.60
    assert discounted == round(raw_weighted * 0.60, 2)
    assert "Penalty" in bd["_meta"]["gatekeeper_reason"]


def test_score_engine_applies_slow_start_penalty() -> None:
    """ScoreEngine should deduct slow_start penalty from weighted score."""
    mock_db = MagicMock()
    mock_repo = MagicMock()
    # Analyzer: Hook 8.0, gesture 8.0, slow_start -1.5
    mock_repo.get_by_job.return_value = [
        MagicMock(analyzer_type="hook", score=8.0, start_time=0.0, end_time=10.0, result_data={"reason": "Pembuka kuat"}),
        MagicMock(analyzer_type="gesture", score=8.0, start_time=0.0, end_time=10.0, result_data={"reason": "Tangan aktif"}),
        MagicMock(analyzer_type="slow_start", score=-1.5, start_time=0.0, end_time=10.0, result_data={"reason": "Dead air 2.5s"}),
    ]

    engine = ScoreEngine(mock_db)
    engine.analysis_repo = mock_repo

    cand = MagicMock(start_time=0.0, end_time=10.0)
    bd = engine._calculate_score_breakdown(1, cand)

    assert "penalty" in bd
    assert bd["penalty"]["contribution"] == -1.5
    assert "Dead air 2.5s" in bd["penalty"]["reason"]




