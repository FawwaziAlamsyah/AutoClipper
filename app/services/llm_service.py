"""LLM analysis service using OpenAI (abstraction layer)."""

import json
import logging
from typing import Any

import httpx

from app.core.config.settings import settings
from app.core.exceptions.base import ExternalToolException

logger = logging.getLogger(__name__)


class LLMService:
    """OpenAI abstraction for video content analysis."""

    def __init__(self) -> None:
        """Validate and prepare client."""
        self.model = settings.LLM_MODEL
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL.rstrip("/")

        if not self.api_key:
            logger.warning("LLM API key not configured. Some features will be disabled.")

        self.client = httpx.Client(
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    def analyze_video(
        self,
        transcript: str,
        content_type: str = "podcast",
        objective: str | None = None,
    ) -> dict[str, Any]:
        """Analyze video content using LLM."""
        prompt = self._build_analysis_prompt(transcript, content_type, objective)

        if not self.api_key:
            logger.warning("No API key, returning mock analysis")
            return self._mock_analysis()

        try:
            response = self._call_llm(prompt)
            return self._parse_analysis_response(response)
        except httpx.HTTPError as e:
            logger.error("LLM request failed: %s", str(e))
            raise ExternalToolException(f"LLM API error: {str(e)}")

    def detect_hooks(self, transcript: str) -> list[dict]:
        """Detect hook phrases and timestamps from transcript."""
        prompt = f"""Extract hook phrases from this transcript.
Return as JSON array of objects with "text" and "start_time" (seconds).
If timestamps unknown, use null.

Transcript:
{transcript[:4000]}"""

        if not self.api_key:
            return [{"text": "Hook placeholder", "start_time": None}]

        try:
            resp = self._call_llm(prompt, response_format="json")
            return resp if isinstance(resp, list) else []
        except Exception as e:
            logger.error("Hook detection failed: %s", str(e))
            return []

    def _build_analysis_prompt(self, transcript: str, content_type: str, objective: str | None) -> str:
        """Build analysis prompt for content understanding."""
        obj_part = f"\nObjective: {objective}" if objective else ""
        return f"""Analyze this {content_type} transcript for viral clip potential.

{obj_part}

Transcript:
{transcript[:8000]}

Return JSON with:
- hook_score: 0-10
- story_score: 0-10
- emotional_score: 0-10
- educational_value: 0-10
- viral_potential: 0-10
- summary: 1 sentence
- key_points: list of 3-5 bullet points
"""

    def _call_llm(self, prompt: str, response_format: str = "text") -> str:
        """Make OpenAI API call."""
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

        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        response = self.client.post(f"{self.base_url}/chat/completions", json=payload)
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _parse_analysis_response(self, raw: str) -> dict[str, Any]:
        """Parse LLM response into structured score dict."""
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
            return self._mock_analysis()

    def _mock_analysis(self) -> dict[str, Any]:
        """Return deterministic mock data when no API key."""
        return {
            "hook_score": 6.5,
            "story_score": 7.0,
            "emotional_score": 6.0,
            "educational_value": 7.5,
            "viral_potential": 5.5,
            "summary": "Content analyzed (mock mode - no API key)",
            "key_points": ["Key point 1", "Key point 2", "Key point 3"],
        }
