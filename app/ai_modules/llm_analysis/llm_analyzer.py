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
        self.model = settings.LLM_MODEL
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL.rstrip("/")

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
        Rata-ratakan 5 sub-skor LLM jadi satu skor llm_content 0-10.
        """
        transcript_text = input.get("transcript_text", "")
        analysis = self._analyze_video(transcript_text)

        sub = [
            analysis.get("hook_score", 5.0),
            analysis.get("story_score", 5.0),
            analysis.get("emotional_score", 5.0),
            analysis.get("educational_value", 5.0),
            analysis.get("viral_potential", 5.0),
        ]
        return AnalysisResult(
            score=round(sum(sub) / len(sub), 2),
            result_data={
                "reason": "Skor konten dari analisis LLM",
                "summary": analysis.get("summary", ""),
                "key_points": analysis.get("key_points", []),
            },
        )

    def _analyze_video(self, transcript_text: str) -> dict:
        """Build prompt, call LLM, parse response."""
        prompt = self._build_analysis_prompt(transcript_text)

        if not self.api_key:
            return self._mock_analysis(transcript_text)

        try:
            response = self._call_llm(prompt)
            return self._parse_analysis_response(response, transcript_text)
        except httpx.HTTPError as e:
            logger.error("LLM request failed: %s", str(e))
            raise AnalyzerUnavailable(f"LLM API error: {str(e)}")

    def _build_analysis_prompt(self, transcript_text: str) -> str:
        """Build analysis prompt for content understanding."""
        return f"""Analyze this podcast transcript for viral clip potential.

Transcript:
{transcript_text[:8000]}

Return JSON with:
- hook_score: 0-10
- story_score: 0-10
- emotional_score: 0-10
- educational_value: 0-10
- viral_potential: 0-10
- summary: 1 sentence
- key_points: list of 3-5 bullet points
"""

    def _call_llm(self, prompt: str) -> str:
        """Make OpenAI-compatible API call."""
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a video content analyst. Return valid JSON only when requested.",
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
            parsed = json.loads(raw)
            return {
                "hook_score": float(parsed.get("hook_score", 5)),
                "story_score": float(parsed.get("story_score", 5)),
                "emotional_score": float(parsed.get("emotional_score", 5)),
                "educational_value": float(parsed.get("educational_value", 5)),
                "viral_potential": float(parsed.get("viral_potential", 5)),
                "summary": parsed.get("summary", ""),
                "key_points": parsed.get("key_points", []),
            }
        except (json.JSONDecodeError, ValueError):
            logger.warning("LLM response parse failed, returning defaults")
            return self._mock_analysis(transcript_text)

    def _mock_analysis(self, transcript_text: str) -> dict:
        """Mock skor yang bervariasi berdasarkan isi transcript (tanpa API key).

        Bukan akurasi LLM sungguhan — hanya mencegah llm_content (30% bobot)
        jadi angka konstan di semua window, supaya urutan ranking candidate
        tetap masuk akal walau tanpa key. Variasi dari: panjang teks, kata unik,
        hook/marker cerita, angka/digit.
        """
        text = (transcript_text or "").strip()
        words = text.split()
        unique = len(set(w.lower() for w in words))
        char_len = len(text)

        # Komponen dasar 5.0 + sinyal teks (0.0–~2.0), dibatasi 0–10
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

        return {
            "hook_score": _clamp(6.5, hook_boost + hook_q),
            "story_score": _clamp(7.0, story_boost),
            "emotional_score": _clamp(6.0, activity * 0.5),
            "educational_value": _clamp(7.5, edu_boost),
            "viral_potential": _clamp(5.5, activity * 0.4),
            "summary": "Content analyzed (mock mode - no API key)",
            "key_points": ["Key point 1", "Key point 2", "Key point 3"],
        }
