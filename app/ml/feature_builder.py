"""Ubah analysis_results jadi feature vector konsisten untuk model scoring."""

FEATURE_ORDER = [
    "llm_content", "hook", "story", "voice_emotion", "face_emotion",
    "gesture", "eye_contact", "scene", "audio", "context", "ending",
]


def build_feature_vector(analysis_results: list) -> list[float]:
    """Ubah list AnalysisResultModel (untuk SATU window/candidate) jadi vector.

    Kategori yang tidak ada hasil analyzer-nya (mis. analyzer mati/skip)
    diisi 0.5 (netral) — SAMA seperti fallback lama di score_engine, supaya
    training data konsisten dengan cara live scoring memperlakukan data hilang.
    """
    by_type: dict[str, list[float]] = {}
    for result in analysis_results:
        by_type.setdefault(result.analyzer_type, []).append(result.score or 0.0)

    vector = []
    for feature_name in FEATURE_ORDER:
        scores = by_type.get(feature_name)
        if not scores:
            vector.append(0.5)
        else:
            vector.append(sum(scores) / len(scores))
    return vector
