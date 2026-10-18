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
    "tunggu", "lihat", "kok bisa", "jangan", "hati-hati", "ternyata",
    "alasan", "masalahnya", "gila", "anjir", "astaga", "waduh", "sumpah",
)
QUESTION_MARK = re.compile(r"[?？]")
EXCLAMATION_MARK = re.compile(r"[!！]")
STORY_MARKERS = (
    "pertama", "kedua", "kemudian", "akhirnya", "setelah", "tapi",
    "namun", "jadi", "karena", "ternyata", "sebenarnya", "first",
    "then", "after", "finally", "but", "so", "because", "turns out",
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
SLOW_INTRO_STARTERS = (
    "halo semuanya", "halo guys", "halo gaes", "halo kawan-kawan",
    "kembali lagi bersama", "kembali lagi di", "welcome back",
    "tes tes", "oke jadi gini", "jadi gini ya", "jadi di video kali ini",
    "di video kali ini kita", "hari ini kita mau", "hari ini gue mau",
    "jumpa lagi", "assalamualaikum teman-teman", "selamat datang kembali",
    "ok guys jadi", "oke guys jadi", "so guys jadi",
)


def _words(text: str) -> str:
    return text.lower()


def validate_hook(text: str) -> tuple[float, str]:
    """Hook: opening grabs attention + cold-open potential from early-mid/body."""
    low = _words(text)
    split_pos = min(len(low), len(low) // 5 + 200)
    head = low[:split_pos]
    body = low[split_pos:]
    score = 2.0
    reasons = []
    if any(s in head for s in HOOK_STARTERS):
        score += 3.0
        reasons.append("Pembuka memakai kata hook")
    if QUESTION_MARK.search(head):
        score += 2.5
        reasons.append("Ada pertanyaan pembuka")
    if EXCLAMATION_MARK.search(head):
        score += 1.5
        reasons.append("Ada tanda seru pembuka")

    # Potensi Cold-Open Reorder: jika bagian awal-menengah/tengah memiliki pemicu
    # penasaran atau reaksi kuat yang bisa ditarik ke detik 0 oleh Auto Hook Engine
    if body and (
        any(s in body for s in HOOK_STARTERS)
        or (QUESTION_MARK.search(body) and EXCLAMATION_MARK.search(body))
    ):
        score += 4.0
        reasons.append("Potensi cold-open hook di dalam klip")

    if not reasons:
        reasons.append("Tidak ada pola hook jelas di pembuka")
    return min(score, 10.0), ", ".join(reasons)


def validate_story(text: str) -> tuple[float, str]:
    """Story: has narrative flow markers."""
    low = _words(text)
    hits = [m for m in STORY_MARKERS if m in low]
    score = min(3.0 + len(hits) * 1.5, 10.0) if hits else 3.0
    reason = f"{len(hits)} penanda alur cerita" if hits else "Tidak ada penanda alur cerita"
    return score, reason


def validate_viral(text: str) -> tuple[float, str]:
    """Viral potential: strong/power words."""
    low = _words(text)
    hits = [w for w in VIRAL_WORDS if w in low]
    score = min(2.0 + len(hits) * 2.5, 10.0) if hits else 2.0
    reason = f"{len(hits)} kata berpotensi viral" if hits else "Tidak ada kata viral kuat"
    return score, reason


def validate_context(text: str) -> tuple[float, str]:
    """Context completeness: references to prior info."""
    low = _words(text)
    hits = [w for w in CONTEXT_REFERENCE if w in low]
    score = min(3.0 + len(hits) * 1.5, 10.0) if hits else 3.0
    reason = f"{len(hits)} referensi konteks" if hits else "Konteks terasa lepas (kemungkinan potongan di tengah)"
    return score, reason


def validate_ending(text: str) -> tuple[float, str]:
    """Ending completeness: conclusive markers at the end."""
    low = _words(text)
    tail = low[-300:]
    hits = [w for w in ENDING_MARKERS if w in tail]
    score = min(3.5 + len(hits) * 2.0, 10.0) if hits else 2.5
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


def validate_pacing(
    text: str,
    start_delay: float = 0.0,
) -> tuple[float, str]:
    """Pacing & Dead-Air: deteksi keheningan di detik 0 dan pembuka lambat (basa-basi).

    Returns (penalty_score <= 0.0, reason).
    0.0 = pacing pembuka baik tanpa penalti.
    < 0.0 = penalti keheningan awal atau pembuka basa-basi.
    """
    penalties = 0.0
    reasons = []

    # 1. Deteksi keheningan (dead-air) sebelum kata pertama dimulai
    if start_delay >= 2.0:
        penalties -= 1.5
        reasons.append(f"Dead air di detik awal ({start_delay:.1f}s hening)")
    elif start_delay >= 1.2:
        penalties -= 0.8
        reasons.append(f"Jeda hening di detik awal ({start_delay:.1f}s)")

    # 2. Deteksi pembuka basa-basi (filler / slow-pacing intro) di awal teks
    low = _words(text)
    head = low[:min(len(low), 120)]
    matched_slow = [s for s in SLOW_INTRO_STARTERS if s in head]
    if matched_slow:
        penalties -= 1.0
        reasons.append(f"Pembuka basa-basi/slow-pacing: '{matched_slow[0]}'")

    if penalties == 0.0:
        return 0.0, "Pacing pembuka baik tanpa dead-air"

    return penalties, ", ".join(reasons)


def run_all_validators(
    text: str,
    keywords: list[str] | None = None,
    skip_keywords: list[str] | None = None,
    start_delay: float = 0.0,
) -> dict[str, dict]:
    """Run all text-based validators on a window of text.

    Returns {analyzer_type: {"score": float, "reason": str}}.
    Analyzer AI (llm_content, face_emotion, dst) tidak di sini — dipanggil
    via registry di AnalysisService (app/ai_modules/).
    """
    result = {
        "hook": _pack(*validate_hook(text)),
        "story": _pack(*validate_story(text)),
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

    score, reason = validate_pacing(text, start_delay=start_delay)
    if score < 0:
        result["slow_start"] = _pack(score, reason)

    return result


def _pack(score: float, reason: str) -> dict:
    """Pack score+reason into dict."""
    return {"score": round(score, 2), "reason": reason}
