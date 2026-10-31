"""AI Curator module for 'Analys by AI' discovery pipeline.

Sends entire video context (transcript with segment markers, audio spike timeline,
scene cut markers, category prompt, and optional 4x4 storyboard grid sheets)
to a vision-capable LLM (Gemini 3.8 Flash or 9Router) in a single request.
Returns curated viral clip candidates with high retention potential.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.core.config.llm_config import get_curator_llm

logger = logging.getLogger(__name__)


class AICuratorError(Exception):
    """Exception khusus kegagalan AI Curator dengan pesan user-friendly."""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.original_error = original_error


class AICurator:
    """Kurator video berbasis AI untuk memilih kandidat klip viral."""

    def __init__(self) -> None:
        cfg = get_curator_llm()
        self.provider = cfg.get("provider", "gemini")
        self.model = cfg.get("model", "gemini-3.8-flash")
        self.api_key = cfg.get("api_key", "").strip()
        self.base_url = cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")

    def curate(
        self,
        category_name: str,
        duration_seconds: float,
        segments: list[Any],
        audio_spikes: list[dict[str, Any]] | None = None,
        scene_cuts: list[float] | None = None,
        storyboard_images: list[str] | None = None,
        scan_visual: bool = True,
        content_brief: str | None = None,
    ) -> dict[str, Any]:
        """Jalankan kurasi AI dalam 1 request LLM multimodal."""
        if not self.api_key:
            provider_label = "Google Gemini" if self.provider == "gemini" else "9Router"
            raise AICuratorError(
                f"API Key untuk {provider_label} belum dikonfigurasi. "
                "Silakan buka menu Settings -> LLM & AI untuk memasukkan API Key."
            )

        prompt_text = self._build_prompt(
            category_name=category_name,
            duration_seconds=duration_seconds,
            segments=segments,
            audio_spikes=audio_spikes or [],
            scene_cuts=scene_cuts or [],
            has_storyboard=bool(storyboard_images and scan_visual),
            content_brief=content_brief,
        )

        user_content = self._build_user_content(prompt_text, storyboard_images if scan_visual else None)

        system_message = (
            "You are an expert short-form video director and viral content strategist "
            "specializing in TikTok FYP, Instagram Reels, and YouTube Shorts algorithms. "
            "Your objective is to find high-performing, standalone viral clip moments "
            "that maximize viewer retention and engagement (target: >= 1k to 200k+ views). "
            "Always return strictly valid JSON matching the requested schema without markdown commentary."
        )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.35,
            "max_tokens": 8192,
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        endpoint = f"{self.base_url}/chat/completions"
        logger.info(
            "AICurator: Mengirim request kurasi ke %s (model=%s, visual=%s, storyboard_sheets=%d)",
            self.provider, self.model, scan_visual, len(storyboard_images or []),
        )

        try:
            with httpx.Client(timeout=300.0) as client:
                response = client.post(endpoint, headers=headers, json=payload)

                # Fallback jika model atau proxy tidak mendukung response_format json_object
                if response.status_code == 400 and "response_format" in response.text.lower():
                    logger.info("AICurator: Provider tidak support response_format json_object, retry tanpa flag tersebut.")
                    payload.pop("response_format", None)
                    response = client.post(endpoint, headers=headers, json=payload)

                # Fallback otomatis jika model experimental overload (HTTP 503) di Google Gemini
                if response.status_code == 503 and self.provider == "gemini" and payload.get("model") != "gemini-flash-lite-latest":
                    logger.warning("AICurator: Model %s sedang padat (HTTP 503), otomatis fallback ke gemini-flash-lite-latest", payload.get("model"))
                    payload["model"] = "gemini-flash-lite-latest"
                    response = client.post(endpoint, headers=headers, json=payload)

                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    return self._parse_response(content)

                self._handle_http_error(response)

        except httpx.TimeoutException as e:
            logger.error("AICurator request timeout: %s", e)
            raise AICuratorError(
                "Request ke AI timeout setelah 300 detik. Video mungkin sangat besar atau koneksi lambat. "
                "Silakan klik tombol Retry untuk mencoba kembali.",
                original_error=e,
            )
        except httpx.HTTPError as e:
            logger.error("AICurator HTTP error: %s", e)
            raise AICuratorError(
                f"Gagal menghubungi server AI ({self.provider}): {str(e)}. Periksa koneksi internet atau Settings.",
                original_error=e,
            )

        return {"candidates": [], "category_interpretation": ""}

    def _handle_http_error(self, response: httpx.Response) -> None:
        """Map HTTP error status codes to clear, actionable error messages."""
        status = response.status_code
        err_body = response.text[:400]
        logger.warning("AICurator error HTTP %d: %s", status, err_body)

        provider_label = "Google Gemini" if self.provider == "gemini" else "9Router"

        if status in (401, 403):
            raise AICuratorError(
                f"Autentikasi gagal (HTTP {status}): API Key untuk {provider_label} tidak valid. "
                "Buka menu Settings -> LLM & AI untuk memastikan API Key benar dan akun aktif."
            )
        elif status == 429:
            raise AICuratorError(
                f"Kuota harian {provider_label} untuk model '{self.model}' telah habis (HTTP 429). "
                "Silakan ganti model atau provider di menu Settings, lalu klik tombol Retry."
            )
        elif status == 404:
            raise AICuratorError(
                f"Model '{self.model}' tidak ditemukan di {provider_label} (HTTP 404). "
                "Silakan pilih model lain di menu Settings."
            )
        elif status == 400 and ("image" in err_body.lower() or "vision" in err_body.lower() or "unsupported" in err_body.lower()):
            raise AICuratorError(
                f"Model '{self.model}' tidak mendukung input gambar/visual (HTTP 400). "
                "Gunakan model vision yang didukung (misal Gemini Flash) atau jalankan dengan Scan Visual OFF."
            )
        elif status in (500, 502, 503, 504):
            raise AICuratorError(
                f"Server {provider_label} sedang mengalami gangguan atau antre padat (HTTP {status}). "
                "Silakan tunggu beberapa saat lalu klik tombol Retry."
            )
        else:
            raise AICuratorError(
                f"Error dari server AI ({provider_label}) HTTP {status}: {err_body[:180]}. "
                "Periksa konfigurasi di menu Settings."
            )

    def _build_user_content(self, prompt_text: str, storyboard_images: list[str] | None) -> Any:
        """Bangun payload content OpenAI-compatible multimodal."""
        if not storyboard_images:
            return prompt_text

        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt_text}
        ]
        for img_uri in storyboard_images:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": img_uri,
                    "detail": "low",
                },
            })
        return content

    def _build_prompt(
        self,
        category_name: str,
        duration_seconds: float,
        segments: list[Any],
        audio_spikes: list[dict[str, Any]],
        scene_cuts: list[float],
        has_storyboard: bool,
        content_brief: str | None = None,
    ) -> str:
        """Bangun prompt kurasi video viral lengkap."""
        mins = int(duration_seconds // 60)
        secs = int(duration_seconds % 60)
        dur_str = f"{mins:02d}:{secs:02d}"

        brief_block = ""
        brief_status = "Tidak ada (Kurasi Umum Berdasarkan Kategori)"
        if content_brief and content_brief.strip():
            brief_status = "AKTIF (Wajib Patuhi Instruksi Client/Campaign)"
            brief_block = f"""
=== CLIENT CAMPAIGN CONTENT BRIEF (STRICT REQUIREMENT) ===
The user has provided a mandatory campaign brief for this video. You MUST prioritize and curate clips that fulfill these specific guidelines:
\"\"\"
{content_brief.strip()}
\"\"\"

CAMPAIGN BRIEF CURATION INSTRUCTIONS:
1. Primary Selection Filter: Prioritize and select segments matching the brief criteria (e.g. required brand/campaign mentions, promo shoutouts, specific creators/talents present, required gameplay + facecam interactions, or funny moments).
2. Balance with High Virality: Ensure each clip still delivers high viewer retention (punchy 3-second hook, emotional climax, standalone clarity).
3. In each candidate's "why_viral" explanation, explicitly explain how the clip fulfills BOTH the campaign brief requirements AND viral retention standards.
===========================================================
"""

        # Format transcript segments
        transcript_lines: list[str] = []
        for s in segments:
            seg_id = getattr(s, "id", None) or (s.get("id") if isinstance(s, dict) else None)
            start = getattr(s, "start_time", 0.0) if hasattr(s, "start_time") else s.get("start_time", 0.0)
            end = getattr(s, "end_time", 0.0) if hasattr(s, "end_time") else s.get("end_time", 0.0)
            text = getattr(s, "text", "") if hasattr(s, "text") else s.get("text", "")

            m1, s1 = int(start // 60), int(start % 60)
            m2, s2 = int(end // 60), int(end % 60)
            transcript_lines.append(f"[#{seg_id} {m1:02d}:{s1:02d}-{m2:02d}:{s2:02d}] {text.strip()}")

        transcript_block = "\n".join(transcript_lines)
        if not transcript_block.strip():
            transcript_block = "(Tidak ada dialog vokal yang terdeteksi)"

        # Format audio spikes timeline
        spike_lines: list[str] = []
        for sp in audio_spikes[:30]:
            spike_lines.append(f"{sp.get('time_str', '00:00')} (+{sp.get('spike_db', 0)}dB)")
        spikes_block = ", ".join(spike_lines) if spike_lines else "(Tidak ada lonjakan audio signifikan)"

        # Format scene cuts
        cut_strings = [f"{int(c//60):02d}:{int(c%60):02d}" for c in scene_cuts[:40]]
        cuts_block = ", ".join(cut_strings) if cut_strings else "(Scene statis)"

        storyboard_note = ""
        if has_storyboard:
            storyboard_note = """
VISUAL STORYBOARD:
Attached are sequential storyboard sheets. Each sheet is a 4x4 grid containing 16 sequential video frames.
Each individual thumbnail frame has its exact timestamp (MM:SS) rendered in white text in its upper-left corner.
Use these frames to:
- Spot intense visual action without speech (e.g. gameplay clutches, deaths, jumpscares, goal celebrations, funny faces/gestures, on-screen text).
- Align moments accurately with visual scene changes.
- For purely visual clips (no speech), specify 'start_time' and 'end_time' directly in seconds based on frame timestamps.
"""

        return f"""Analyze this entire video to curate the best short-form viral clip candidates for social media (TikTok, IG Reels, YouTube Shorts).

METADATA:
- Target Category / Style: "{category_name}"
- Campaign Content Brief: {brief_status}
- Video Total Duration: {dur_str} ({duration_seconds:.1f}s)
- Audio Spikes Timeline (Moments of screaming, sudden laughter, or peak audio energy):
  {spikes_block}
- Scene Cuts Timeline:
  {cuts_block}
{brief_block}
TRANSCRIPT WITH SEGMENT IDs:
\"\"\"
{transcript_block}
\"\"\"
{storyboard_note}

VIRAL CURATION RUBRIC:
0. Campaign Brief Compliance: If a Client Campaign Brief is active, strictly prioritize candidates matching its guidelines (e.g., brand promo, talent interactions, required visual setups).
1. Category Adaptation: Interpret what makes content in "{category_name}" go viral. (e.g. Gaming: clutches, rage, fails, jumpscares; Podcast: bold hot takes, intense debates, shocking stories, relatable life truths; Comedy: crisp setup + punchline with contagious laughs; Sports: hype action, dramatic turns, controversial referee calls).
2. The 3-Second Hook Rule: The clip must stop the user scrolling in seconds 0-3. NEVER start with boring filler or slow context ("jadi gini...", "nah sebenarnya..."). Start right when the intrigue, emotion, or action starts.
3. Standalone Completeness: The clip must make complete sense to someone who has never watched the full video.
4. Emotional / Narrative Payoff: Deliver a satisfying climax, punchline, or insight. Do NOT end abruptly mid-sentence or mid-action.
5. Natural Duration: Let the moment determine the length (usually 15-60 seconds, can be up to 90s if the narrative is captivating). Do not truncate the peak moment!
6. Quality Over Quantity: Only return clips with genuine viral potential (confidence >= 7.0/10). Return between 3 and 10 of the strongest clips. If none, return an empty list.

REQUIRED OUTPUT FORMAT:
Return strictly a valid JSON object with this exact structure:
```json
{{
  "category_interpretation": "Brief 1-2 sentence explanation of how you analyzed this category",
  "scan_notes": "1-2 concise sentences summarizing the overall video highlights",
  "candidates": [
    {{
      "start_seg": 42,
      "end_seg": 58,
      "start_time": null,
      "end_time": null,
      "title": "Punchy 4-7 word title",
      "archetype": "story|controversy|funny_reaction|insight|clutch_action|emotional|debate",
      "why_viral": "1-2 sentences explaining why this clip will get high retention and views",
      "confidence": 8.5,
      "hook": {{
        "moment_time": 182.4,
        "type": "question|shock|stat|conflict|curiosity_gap",
        "caption": "PUNCHY 3-7 WORD TEASER CAPTION"
      }}
    }}
  ]
}}
```
Note:
- If a clip is based on spoken dialogue, provide `start_seg` and `end_seg` (matching the segment [#ID] numbers). Set `start_time` and `end_time` to null.
- If a clip is purely visual (e.g. gameplay action with no dialogue), set `start_seg` and `end_seg` to null, and provide `start_time` and `end_time` in seconds.
- `hook.moment_time` is the absolute second of the single most shocking or exciting 1-3 second moment inside this clip to be used as a cold-open hook (or null if the beginning is already the strongest hook).
"""

    def _parse_response(self, raw_text: str) -> dict[str, Any]:
        """Ekstrak dan parse JSON dari raw response LLM dengan error recovery berlapis."""
        text = (raw_text or "").strip()

        # 1. Bersihkan markdown code fence (baik yang memiliki closing ``` maupun tidak)
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if fence_match:
            text = fence_match.group(1).strip()
        else:
            text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```\s*$", "", text)
            text = text.strip()

        # 2. Ambil substring mulai dari '{' pertama sampai '}' terakhir
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            json_str = text[first_brace : last_brace + 1]
        elif first_brace != -1:
            json_str = text[first_brace:]
        else:
            json_str = text

        # Helper untuk mencoba parsing dengan strict=False dan pembersihan trailing commas
        def _try_parse(s: str) -> dict[str, Any] | None:
            try:
                res = json.loads(s, strict=False)
                if isinstance(res, dict):
                    return res
                if isinstance(res, list):
                    return {"candidates": res, "category_interpretation": ""}
            except Exception:
                pass

            # Bersihkan trailing commas sebelum '}' atau ']'
            cleaned = re.sub(r",\s*([\]}])", r"\1", s)
            try:
                res = json.loads(cleaned, strict=False)
                if isinstance(res, dict):
                    return res
                if isinstance(res, list):
                    return {"candidates": res, "category_interpretation": ""}
            except Exception:
                pass
            return None

        # Coba parse langsung
        result = _try_parse(json_str)
        if result and "candidates" in result:
            return result

        # 3. Truncation Recovery: jika output LLM terpotong di tengah kandidat
        if '"candidates"' in json_str:
            last_obj_end = json_str.rfind("}")
            if last_obj_end != -1:
                truncated = json_str[: last_obj_end + 1]
                open_brackets = truncated.count("[") - truncated.count("]")
                open_braces = truncated.count("{") - truncated.count("}")
                repaired = truncated + ("]" * max(0, open_brackets)) + ("}" * max(0, open_braces))
                salvaged = _try_parse(repaired)
                if salvaged and "candidates" in salvaged:
                    logger.info("AICurator: Berhasil me-recover JSON yang terpotong (%d kandidat terselamatkan)", len(salvaged.get("candidates", [])))
                    return salvaged

        # 4. Regex Fallback: ekstrak objek kandidat individual satu per satu
        candidates = []
        cand_matches = re.finditer(
            r'\{\s*"start_seg"[\s\S]*?"confidence"\s*:\s*[\d\.]+[\s\S]*?\}',
            json_str,
        )
        for m in cand_matches:
            c = _try_parse(m.group(0))
            if c:
                candidates.append(c)

        if candidates:
            logger.info("AICurator: Berhasil mengekstrak %d kandidat via regex fallback", len(candidates))
            return {"candidates": candidates, "category_interpretation": "Ekstraksi via fallback"}

        # Log preview respon asli agar mudah dianalisis bila benar-benar gagal
        logger.warning("AICurator: Gagal total decode JSON. Raw text: %.500s", raw_text)
        raise AICuratorError("Respon dari AI tidak dapat dibaca sebagai format JSON yang valid. Silakan klik Retry.")
