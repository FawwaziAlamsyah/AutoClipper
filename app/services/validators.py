"""Text-based content validators for clip scoring.

Each validator returns (score 0-10, reason). Pure functions, no I/O,
easy to unit test. This is the real "review" layer — every candidate
gets per-validator scores and human-readable reasons stored in DB.
"""

import re

HOOK_STARTERS = (
    "bayangkan", "apakah", "kenapa", "bagaimana", "tahukah", "wow",
    "the thing is", "here is why", "here's why", "you won't believe",
    "wait", "wait for it", "perhatian", "penting", "rahasia",
)
QUESTION_MARK = re.compile(r"[?？]")
EXCLAMATION_MARK = re.compile(r"[!！]")
STORY_MARKERS = (
    "pertama", "kedua", "kemudian", "akhirnya", "setelah", "tapi",
    "namun", "jadi", "karena", "ternyata", "sebenarnya", "first",
    "then", "after", "finally", "but", "so", "because", "turns out",
)
EMOTION_WORDS = (
    "gila", "hebat", "luar biasa", "sedih", "takjub", "terkejut",
    "senang", "marah", "takut", "kecewa", "bangga", "haru", "saya",
    "aku", "kita", "amazing", "incredible", "shocked", "happy", "angry",
    "scared", "proud", "sad",
)
EDUCATIONAL_WORDS = (
    "adalah", "berarti", "fakta", "contoh", "caranya", "tutorial",
    "langkah", "cara", "tips", "rahasia", "prinsip", "teori", "data",
    "persen", "%", "tahun", "is", "means", "fact", "example", "how to",
    "steps", "tips",
)
VIRAL_WORDS = (
    "viral", "luar biasa", "gila", "gak nyangka", "mengejutkan",
    "shocking", "unbelievable", "crazy", "insane", "wild", "explode",
    "trending",
)
CONTEXT_REFERENCE = (
    "karena", "yang tadi", "seperti yang", "ini", "itu", "tersebut",
    "seperti tadi", "as i said", "as we", "this", "that",
)
ENDING_MARKERS = (
    "jadi", "kesimpulannya", "intinya", "kesimpulan", "dengan kata lain",
    "akhirnya", "so", "in conclusion", "to sum up", "that's why",
    "the point is", "basically",
)
PENALTY_KEYWORDS = (
    "sponsor", "subscribe", "like and subscribe", "jangan lupa subscribe",
    "follow", "like", "iklan", "advertisement", "jangan lupa like",
    "bagikan", "share this", "intro", "outro",
)
NUMBER = re.compile(r"\d+")

_NEUTRAL = {"score": 5.0, "reason": "Validator tidak tersedia (dependency belum diinstall)."}


def _words(text: str) -> str:
    return text.lower()


def validate_hook(text: str) -> tuple[float, str]:
    """Hook: opening grabs attention."""
    low = _words(text)
    head = low[: len(low) // 5 + 200]
    score = 5.0
    reasons = []
    if any(s in head for s in HOOK_STARTERS):
        score += 2.0
        reasons.append("Pembuka memakai kata hook")
    if QUESTION_MARK.search(head):
        score += 1.5
        reasons.append("Ada pertanyaan pembuka")
    if EXCLAMATION_MARK.search(head):
        score += 1.0
        reasons.append("Ada tanda seru pembuka")
    if not reasons:
        reasons.append("Tidak ada pola hook jelas di pembuka")
    return min(score, 10.0), ", ".join(reasons)


def validate_story(text: str) -> tuple[float, str]:
    """Story: has narrative flow markers."""
    low = _words(text)
    hits = [m for m in STORY_MARKERS if m in low]
    score = min(5.0 + len(hits) * 1.2, 10.0)
    reason = f"{len(hits)} penanda alur cerita" if hits else "Tidak ada penanda alur cerita"
    return score, reason


def validate_emotion(text: str) -> tuple[float, str]:
    """Emotion: emotional vocabulary density."""
    low = _words(text)
    hits = [w for w in EMOTION_WORDS if w in low]
    score = min(5.0 + len(hits) * 1.0, 10.0)
    reason = f"{len(hits)} kata emosional" if hits else "Nada datar, sedikit kata emosional"
    return score, reason


def validate_educational(text: str) -> tuple[float, str]:
    """Educational value: facts, numbers, explanations."""
    low = _words(text)
    hits = [w for w in EDUCATIONAL_WORDS if w in low]
    numbers = len(NUMBER.findall(text))
    score = min(5.0 + len(hits) * 0.8 + numbers * 0.3, 10.0)
    reason = f"{len(hits)} penanda edukasi, {numbers} angka" if hits or numbers else "Sedikit konten edukasi"
    return score, reason


def validate_viral(text: str) -> tuple[float, str]:
    """Viral potential: strong/power words."""
    low = _words(text)
    hits = [w for w in VIRAL_WORDS if w in low]
    score = min(5.0 + len(hits) * 1.5, 10.0)
    reason = f"{len(hits)} kata berpotensi viral" if hits else "Tidak ada kata viral kuat"
    return score, reason


def validate_context(text: str) -> tuple[float, str]:
    """Context completeness: references to prior info."""
    low = _words(text)
    hits = [w for w in CONTEXT_REFERENCE if w in low]
    score = min(4.0 + len(hits) * 1.0, 10.0)
    reason = f"{len(hits)} referensi konteks" if hits else "Konteks terasa lepas (kemungkinan potongan di tengah)"
    return score, reason


def validate_ending(text: str) -> tuple[float, str]:
    """Ending completeness: conclusive markers at the end."""
    low = _words(text)
    tail = low[-300:]
    hits = [w for w in ENDING_MARKERS if w in tail]
    score = min(4.0 + len(hits) * 1.5, 10.0)
    reason = "Ada penutup/kesimpulan" if hits else "Konteks terasa lepas (kemungkinan potongan di tengah)"
    return score, reason


def validate_keyword_boost(text: str, keywords: list[str]) -> tuple[float, str]:
    """Keyword boost: user keywords mentioned."""
    low = _words(text)
    matched = [k for k in keywords if k.lower() in low]
    if not matched:
        return 5.0, "Tidak ada keyword yang disebutkan"
    score = min(5.0 + len(matched) * 1.5, 10.0)
    return score, f"{len(matched)} keyword disebut: {', '.join(matched)}"


def validate_penalty(text: str, skip_keywords: list[str] | None = None) -> tuple[float, str]:
    """Penalty: sponsor/intro/outro/CTA — negative."""
    low = _words(text)
    skip = list(PENALTY_KEYWORDS) + [k.lower() for k in (skip_keywords or [])]
    matched = [k for k in skip if k in low]
    if not matched:
        return 0.0, "Tidak ada konten sponsor/CTA"
    return -1.0, f"Konten spam/CTA terdeteksi: {', '.join(matched)}"


# Validators berat yang butuh audio/video processing library.
# Belum dipasang (librosa, mediapipe, deepface, pyannote). Diberi skor netral
# dan alasan jujur, bukan angka palsu.
HEAVY_VALIDATORS = (
    ("voice_emotion", _NEUTRAL),
    ("face_emotion", _NEUTRAL),
    ("gesture", _NEUTRAL),
    ("eye_contact", _NEUTRAL),
    ("scene", _NEUTRAL),
    ("audio", _NEUTRAL),
)


def run_all_validators(
    text: str,
    keywords: list[str] | None = None,
    skip_keywords: list[str] | None = None,
) -> dict[str, dict]:
    """Run all validators on a window of text.

    Returns {analyzer_type: {"score": float, "reason": str}}.
    """
    result = {
        "hook": _pack(*validate_hook(text)),
        "story": _pack(*validate_story(text)),
        "llm_content": _pack(5.0 + (validate_educational(text)[0] - 5.0) * 0.6, "Skor konten gabungan dari validasi edukasi"),
        "voice_emotion": _pack(validate_emotion(text)[0], validate_emotion(text)[1]),
        "context": _pack(*validate_context(text)),
        "ending": _pack(*validate_ending(text)),
        "viral_potential": _pack(*validate_viral(text)),
    }

    score, reason = validate_keyword_boost(text, keywords or [])
    if keywords:
        result["keyword_boost"] = _pack(score, reason)

    score, reason = validate_penalty(text, skip_keywords)
    if score < 0:
        result["penalty"] = _pack(score, reason)

    for name, neutral in HEAVY_VALIDATORS:
        result[name] = neutral

    return result


def _pack(score: float, reason: str) -> dict:
    """Pack score+reason into dict."""
    return {"score": round(score, 2), "reason": reason}
