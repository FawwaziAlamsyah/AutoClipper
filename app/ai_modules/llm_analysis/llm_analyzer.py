"""LLM content analyzer plugin (OpenAI-compatible chat completions).

Pindahan dari `app/services/llm_service.py`. analyzer_type "llm_content".
"""

import json
import logging

import httpx

from app.ai_modules.base.analyzer_interface import (
    AnalysisResult,
    AnalyzerInterface,
    AnalyzerUnavailable,
)
from app.ai_modules.registry import register_analyzer
from app.core.config.settings import settings

logger = logging.getLogger(__name__)


@register_analyzer
class LLMAnalyzer(AnalyzerInterface):
    """Analisis kualitas konten via LLM (OpenAI abstraction)."""

    analyzer_type = "llm_content"

    def __init__(self) -> None:
        """Validate and prepare client."""
        from app.core.config.llm_config import get_active_llm
        cfg = get_active_llm()
        self.model = cfg.get("model") or settings.LLM_MODEL
        self.api_key = cfg.get("api_key") or settings.LLM_API_KEY
        self.base_url = (cfg.get("base_url") or settings.LLM_BASE_URL).rstrip("/")
        self.provider = cfg.get("provider", "9router")

        if not self.api_key:
            logger.warning("LLM API key not configured. Using mock analysis.")

        self.client = httpx.Client(
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    def analyze(self, input: dict) -> AnalysisResult:
        """Analisis satu window transcript.

        input: {"transcript_text": str}.
        Menggabungkan 4 dimensi retensi viral:
        - Curiosity Hook (detik awal): 35%
        - Emotional Payoff (klimaks emosi/insight): 25%
        - Shareability (daya sebar & relate): 25%
        - Idea Completeness (keutuhan bahasan): 15%
        """
        transcript_text = input.get("transcript_text", "")
        analysis = self._analyze_video(transcript_text)

        c_hook = float(analysis.get("curiosity_hook", analysis.get("hook_score", 5.0)))
        e_payoff = float(analysis.get("emotional_payoff", analysis.get("emotional_score", 5.0)))
        share = float(analysis.get("shareability", analysis.get("viral_potential", 5.0)))
        complete = float(analysis.get("idea_completeness", analysis.get("story_score", 5.0)))

        # Pembobotan terkalibrasi untuk short-form virality (0-10)
        final_score = round(
            c_hook * 0.35 + e_payoff * 0.25 + share * 0.25 + complete * 0.15,
            2,
        )

        reason = analysis.get("viral_reason") or analysis.get("summary") or "Skor konten dari analisis LLM"

        return AnalysisResult(
            score=min(max(final_score, 0.0), 10.0),
            result_data={
                "reason": reason,
                "source": analysis.get("_source", "llm"),
                "summary": analysis.get("summary", ""),
                "viral_reason": analysis.get("viral_reason", ""),
                "hook_headline": analysis.get("hook_headline", ""),
                "key_points": analysis.get("key_points", []),
                "curiosity_hook": round(c_hook, 2),
                "emotional_payoff": round(e_payoff, 2),
                "shareability": round(share, 2),
                "idea_completeness": round(complete, 2),
            },
        )

    def _analyze_video(self, transcript_text: str) -> dict:
        """Build prompt, call LLM, parse response."""
        if not self.api_key:
            return self._mock_analysis(transcript_text)

        try:
            response = self._call_llm(self._build_analysis_prompt(transcript_text))
            return self._parse_analysis_response(response, transcript_text)
        except httpx.HTTPError as e:
            logger.error("LLM request failed: %s", str(e))
            raise AnalyzerUnavailable(f"LLM API error: {str(e)}")

    def _build_analysis_prompt(self, transcript_text: str) -> str:
        """Build analysis prompt for short-form viral retention understanding."""
        return f"""Analyze this video/podcast transcript segment for viral short-form clip potential (target: >= 200k views on TikTok FYP, Instagram Reels, YouTube Shorts).

Transcript:
\"\"\"{transcript_text[:8000]}\"\"\"

Evaluate the transcript based on these 4 viral retention factors (score 0.0 to 10.0 each):
1. curiosity_hook: Does the opening sentence create an immediate curiosity gap, open loop, or provocative question that stops scrolling in the first 3 seconds? (0 = boring/slow preamble, 10 = irresistible curiosity)
2. emotional_payoff: Is there a strong emotional peak, punchline, shocking revelation, or exciting insight? (0 = flat monotonous conversation, 10 = intense emotion/aha-moment)
3. shareability: Would viewers share this clip to friends or debate it in comments (relatability, controversial opinion, or high-value tip)? (0 = niche/unrelatable, 10 = massive broad appeal)
4. idea_completeness: Does this segment form a cohesive, satisfying idea from start to finish without feeling awkwardly cut off? (0 = fragmented snippet, 10 = complete punchy takeaway)

Return pure JSON only with keys:
- curiosity_hook: float (0.0 - 10.0)
- emotional_payoff: float (0.0 - 10.0)
- shareability: float (0.0 - 10.0)
- idea_completeness: float (0.0 - 10.0)
- viral_reason: string (1-2 concise sentences explaining why this clip has or lacks viral potential)
- hook_headline: string (a punchy 4-7 word viral caption headline)
- key_points: list of 2-4 key takeaways
"""

    def _call_llm(self, prompt: str) -> str:
        """Make OpenAI-compatible API call."""
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert viral content strategist specialized in short-form video "
                        "algorithms (TikTok FYP, Instagram Reels, YouTube Shorts). Your goal is to evaluate "
                        "transcripts for viral retention and 200k+ views potential. Return valid JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }

        response = self.client.post(f"{self.base_url}/chat/completions", json=payload)
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _parse_analysis_response(self, raw: str, transcript_text: str = "") -> dict:
        """Parse LLM response into structured score dict.

        transcript_text dipakai fallback mock kalau response gagal parse.
        """
        try:
            text = (raw or "").strip()
            # Handle markdown code fence wrapping ```json ... ```
            if "```" in text:
                import re
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
                if match:
                    text = match.group(1).strip()

            parsed = json.loads(text)

            curiosity_hook = float(parsed.get("curiosity_hook", parsed.get("hook_score", 5.0)))
            emotional_payoff = float(parsed.get("emotional_payoff", parsed.get("emotional_score", 5.0)))
            shareability = float(parsed.get("shareability", parsed.get("viral_potential", 5.0)))
            idea_completeness = float(parsed.get("idea_completeness", parsed.get("story_score", 5.0)))

            viral_reason = parsed.get("viral_reason") or parsed.get("summary") or "Analisis konten viral LLM"
            headline = parsed.get("hook_headline") or ""
            key_points = parsed.get("key_points", [])

            return {
                "_source": "llm",
                "curiosity_hook": curiosity_hook,
                "emotional_payoff": emotional_payoff,
                "shareability": shareability,
                "idea_completeness": idea_completeness,
                # Legacy compatibility keys
                "hook_score": curiosity_hook,
                "story_score": idea_completeness,
                "emotional_score": emotional_payoff,
                "educational_value": float(parsed.get("educational_value", (shareability + curiosity_hook) / 2)),
                "viral_potential": shareability,
                "summary": viral_reason,
                "viral_reason": viral_reason,
                "hook_headline": headline,
                "key_points": key_points,
            }
        except (json.JSONDecodeError, ValueError):
            logger.warning("LLM response parse failed, returning defaults")
            return self._mock_analysis(transcript_text)

    def _mock_analysis(self, transcript_text: str) -> dict:
        """Mock skor yang bervariasi berdasarkan isi transcript (tanpa API key).

        Bukan akurasi LLM sungguhan — hanya mencegah llm_content (bobot 22%)
        jadi angka konstan di semua window, supaya urutan ranking candidate
        tetap masuk akal walau tanpa key. Variasi dari: panjang teks, kata unik,
        hook/marker cerita, angka/digit.
        """
        text = (transcript_text or "").strip()
        words = text.split()
        unique = len(set(w.lower() for w in words))
        char_len = len(text)

        # Komponen dasar 6.5 + sinyal teks
        hook_boost = 1.2 if any(s in text.lower() for s in (
            "bayangkan", "apakah", "kenapa", "bagaimana", "tahukah", "perhatian",
            "the thing is", "here is why", "wait",
        )) else 0.0
        hook_q = 0.6 if any(m in text for m in ("?", "？")) else 0.0

        story_hits = sum(1 for m in (
            "pertama", "kedua", "kemudian", "akhirnya", "tapi", "jadi", "karena",
            "first", "then", "after", "finally", "but", "so",
        ) if m in text.lower())
        story_boost = min(story_hits * 0.4, 2.0)

        edu_hits = sum(1 for w in words if any(ch.isdigit() for ch in w))
        edu_boost = min(edu_hits * 0.3, 2.0)

        # Panjang + kata unik → aktivitas konten (0–2)
        activity = min((char_len / 300.0) * 0.8 + (unique / 50.0) / 0.6, 2.0)

        def _clamp(base: float, extra: float) -> float:
            return round(min(base + extra, 10.0), 1)

        c_hook = _clamp(6.5, hook_boost + hook_q)
        complete = _clamp(6.5, story_boost * 0.5)
        e_payoff = _clamp(6.5, activity * 0.5)
        share = _clamp(6.5, edu_boost * 0.5)

        return {
            "_source": "mock",
            "curiosity_hook": c_hook,
            "emotional_payoff": e_payoff,
            "shareability": share,
            "idea_completeness": complete,
            # Legacy compatibility
            "hook_score": c_hook,
            "story_score": complete,
            "emotional_score": e_payoff,
            "educational_value": _clamp(6.5, edu_boost),
            "viral_potential": share,
            "summary": "Analisis konten transcript (mode fallback - tanpa API key)",
            "viral_reason": "Analisis konten transcript (mode fallback - tanpa API key)",
            "hook_headline": "Momen Menarik Pembicaraan",
            "key_points": ["Topik utama obrolan", "Poin diskusi menarik"],
        }
