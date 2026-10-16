"""Hook Moment Finder — cari momen terbaik untuk cold-open reorder via LLM.

Digabung dengan HookCaptionGenerator dalam SATU LLM call per candidate
yang di-generate (hemat biaya; tidak dipanggil saat pipeline analisis massal).

Prinsip utama:
- Kalau LLM_API_KEY kosong → langsung return None (hook_skip_reason="llm_unavailable").
  TIDAK pakai mock random — reorder video berdasarkan tebakan lebih berbahaya dari skip.
- Kalau segments < 4 → return None (window terlalu pendek untuk cold-open bermakna).
- Kalau best_idx terlalu dekat ke awal (< 3 segment atau < 5 detik dari segment[0])
  → return None (hook_skip_reason="moment_too_close_to_start") — tidak ada gunanya reorder.
- Semua kegagalan parse/network → return None (hook_skip_reason sesuai).
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, UTC

import httpx

from app.core.config.settings import settings

logger = logging.getLogger(__name__)

# ── In-memory cache status LLM (reset saat restart server) ────────────────────
# Diisi dari response header OpenAI setiap kali LLM dipanggil.
_llm_status: dict = {
    "last_called_at": None,        # ISO string
    "remaining_tokens": None,      # int | None
    "limit_tokens": None,          # int | None
    "remaining_requests": None,    # int | None
    "reset_tokens_at": None,       # string waktu reset dari header
    "last_error": None,            # string error terakhir (429, dll)
    "last_error_at": None,         # ISO string
}


def _update_llm_status(headers) -> None:
    """Update cache status dari response headers OpenAI."""
    now = datetime.now(UTC).isoformat()
    _llm_status["last_called_at"] = now
    _llm_status["last_error"] = None  # clear error kalau berhasil
    try:
        if "x-ratelimit-remaining-tokens" in headers:
            _llm_status["remaining_tokens"] = int(headers["x-ratelimit-remaining-tokens"])
        if "x-ratelimit-limit-tokens" in headers:
            _llm_status["limit_tokens"] = int(headers["x-ratelimit-limit-tokens"])
        if "x-ratelimit-remaining-requests" in headers:
            _llm_status["remaining_requests"] = int(headers["x-ratelimit-remaining-requests"])
        if "x-ratelimit-reset-tokens" in headers:
            _llm_status["reset_tokens_at"] = headers["x-ratelimit-reset-tokens"]
    except Exception:
        pass


def update_llm_error(error_msg: str) -> None:
    """Catat error LLM (429, dll) ke cache status."""
    _llm_status["last_error"] = error_msg
    _llm_status["last_error_at"] = datetime.now(UTC).isoformat()


def get_llm_status() -> dict:
    """Return salinan status LLM saat ini."""
    return dict(_llm_status)


@dataclass
class HookMoment:
    """Hasil temuan momen hook dari satu window candidate."""
    hook_moment_start: float    # timestamp absolut (detik dari video asli)
    hook_moment_end: float      # biasanya hook_moment_start + 2.0, max = window end
    hook_type: str              # question|shock|stat|conflict|curiosity_gap
    hook_confidence: float      # 0.0–1.0
    hook_caption: str           # caption overlay (maks 8 kata)
    best_idx: int               # index relatif ke list segments window
    audio_spike_time: float | None = None  # timestamp lonjakan emosi/teriakan (jika terdeteksi)
    has_audio_spike: bool = False


class HookMomentFinder:
    """Cari momen hook terbaik + generate caption dalam satu LLM call.

    Reuse pola httpx client dari llm_analyzer.py — client tersendiri
    agar tidak tersambung ke pipeline analisis window massal.
    """

    def __init__(self) -> None:
        from app.core.config.llm_config import get_active_llm
        cfg = get_active_llm()
        self.api_key = cfg.get("api_key") or settings.LLM_API_KEY
        self.model = cfg.get("model") or settings.LLM_MODEL
        self.base_url = (cfg.get("base_url") or settings.LLM_BASE_URL).rstrip("/")
        self.provider = cfg.get("provider", "9router")
        self.client = httpx.Client(
            # 9Router auto-fallback / provider gratis → bisa butuh waktu.
            # JANGAN kasih timeout pendek; biarkan sampai selesai.
            timeout=None,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    def find(
        self,
        segments: list,
        category_name: str | None = None,
        audio_spikes: dict | None = None,
    ) -> tuple[HookMoment | None, str | None]:
        """Cari momen hook terbaik dari segments window candidate.

        Args:
            segments: list of transcript segment objects (.start_time, .end_time, .text)
                      URUTAN sesuai window (bukan seluruh video).
            category_name: nama kategori candidate (opsional, untuk konteks prompt).
            audio_spikes: dict hasil deteksi lonjakan audio dari AudioSpikeDetectorService.

        Returns:
            (HookMoment, None)        → sukses
            (None, hook_skip_reason)  → skip dengan alasan
        """
        # Guard: API key wajib ada
        if not self.api_key:
            logger.debug("HookMomentFinder skip: LLM API key tidak dikonfigurasi")
            return None, "llm_unavailable"

        # Guard: window minimal 4 segment
        if len(segments) < 4:
            logger.debug("HookMomentFinder skip: segments < 4 (%d)", len(segments))
            return None, "window_too_short"

        # Bangun list segment untuk prompt
        seg_list = [
            {"idx": i, "text": seg.text.strip()}
            for i, seg in enumerate(segments)
        ]

        prompt = self._build_prompt(seg_list, category_name, audio_spikes=audio_spikes)

        try:
            raw = self._call_llm(prompt)
            parsed = self._parse_response(raw)
        except httpx.HTTPError as e:
            err_msg = str(e)
            logger.warning("HookMomentFinder LLM request gagal: %s", err_msg)
            update_llm_error(err_msg)
            return None, "llm_unavailable"
        except Exception as e:
            logger.warning("HookMomentFinder parse gagal: %s", e)
            return None, "llm_unavailable"

        if parsed is None:
            return None, "llm_unavailable"

        best_idx = parsed.get("best_idx")
        confidence = float(parsed.get("confidence", 0.0))
        hook_type = str(parsed.get("hook_type", "curiosity_gap"))
        caption = str(parsed.get("caption", "")).strip()

        # Validasi best_idx range
        if not isinstance(best_idx, int) or best_idx < 0 or best_idx >= len(segments):
            logger.debug("HookMomentFinder skip: best_idx=%s di luar range", best_idx)
            return None, "llm_unavailable"

        # Guard: confidence minimum
        if confidence < settings.AUTO_HOOK_MIN_CONFIDENCE:
            logger.debug(
                "HookMomentFinder skip: confidence %.2f < threshold %.2f",
                confidence, settings.AUTO_HOOK_MIN_CONFIDENCE,
            )
            return None, "low_confidence"

        # Guard: momen hook tidak boleh terlalu dekat ke awal window.
        # Untuk klip pendek/hasil trim (< 8 segment), beri batas lebih fleksibel (idx >= 1 dan delta >= 2.0s)
        window_start_time = float(segments[0].start_time)
        hook_start_time = float(segments[best_idx].start_time)
        if len(segments) < 8:
            too_close_by_index = best_idx < 1
            too_close_by_time = (hook_start_time - window_start_time) < 2.0
        else:
            too_close_by_index = best_idx < 3
            too_close_by_time = (hook_start_time - window_start_time) < 5.0

        if too_close_by_index or too_close_by_time:
            logger.debug(
                "HookMomentFinder skip: momen terlalu dekat ke awal window "
                "(idx=%d, delta_t=%.1fs)",
                best_idx, hook_start_time - window_start_time,
            )
            return None, "moment_too_close_to_start"

        # Map ke timestamp absolut.
        # Durasi hook tidak kaku 2 detik — pakai hook_duration dari LLM agar
        # momen kejutan selesai utuh, lalu snap akhir ke boundary segment
        # (end segmen yang memuat titik akhir) supaya tidak terpotong di
        # tengah kalimat.
        window_end_time = float(segments[-1].end_time)
        hook_moment_start = hook_start_time
        try:
            duration = float(parsed.get("hook_duration", 2.0))
        except (ValueError, TypeError):
            duration = 2.0
        duration = max(1.0, min(duration, 6.0))

        hook_duration_end = hook_moment_start + duration
        snapped_end: float | None = None
        for i in range(best_idx, len(segments)):
            seg_end = float(segments[i].end_time)
            if hook_duration_end <= seg_end:
                snapped_end = seg_end
                break
        hook_moment_end = (
            min(snapped_end, window_end_time)
            if snapped_end is not None
            else min(hook_duration_end, window_end_time)
        )

        # Fallback caption: ambil teks segment kalau kosong.
        # Guard konsistensi: kalau caption memuat angka yang TIDAK ada di
        # transkrip window, kemungkinan LLM bohong/melebih-lebihkan → buang
        # caption LLM, pakai teks verbatim segment (dijamin jujur).
        if not caption or not self._caption_consistent(caption, segments):
            caption = " ".join(segments[best_idx].text.split()[:8])

        return HookMoment(
            hook_moment_start=hook_moment_start,
            hook_moment_end=hook_moment_end,
            hook_type=hook_type,
            hook_confidence=confidence,
            hook_caption=caption,
            best_idx=best_idx,
            audio_spike_time=audio_spikes.get("peak_time") if audio_spikes else None,
            has_audio_spike=bool(audio_spikes and audio_spikes.get("has_spike")),
        ), None

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _caption_consistent(caption: str, segments: list) -> bool:
        """Cek tiap token angka di caption muncul di teks transkrip window.

        Mencegah LLM membuat angka/klaim baru yang tidak ada di sumber.
        Caption tanpa angka → dianggap konsisten (tidak ada angka bohong).
        """
        import re
        numbers = re.findall(r"\d[\d.,]*", caption)
        if not numbers:
            return True
        transcript = " ".join(seg.text or "" for seg in segments).lower()
        return all(num.lower() in transcript for num in numbers)

    def _build_prompt(
        self,
        seg_list: list[dict],
        category_name: str | None,
        audio_spikes: dict | None = None,
    ) -> str:
        category_ctx = (
            f"Kategori konten: {category_name}." if category_name else "Konten umum."
        )
        spike_hint = ""
        if audio_spikes and audio_spikes.get("has_spike"):
            peak_t = audio_spikes.get("peak_time", 0.0)
            spike_hint = (
                f"- CATATAN AUDIO SPIKE: Terdeteksi puncak teriakan/reaksi emosi tinggi di sekitar "
                f"timestamp ~{peak_t:.1f} detik. Jika ada segmen di sekitar timestamp ini yang emosional atau kaget, "
                f"prioritaskan segmen tersebut sebagai momen hook!\n"
            )

        segs_json = json.dumps(seg_list, ensure_ascii=False, indent=2)
        if len(seg_list) < 8:
            start_rule = "- JANGAN pilih segmen paling awal (idx 0) — cold open membutuhkan momen yang berbeda dari pembuka klip."
        else:
            start_rule = "- JANGAN pilih segmen di awal daftar (idx 0, 1, atau 2) — cold open hanya bermakna kalau momen tersebut jauh dari awal klip."

        return f"""Kamu adalah editor video viral untuk platform TikTok/Reels.
{category_ctx}

Diberikan daftar segmen transkrip dari satu klip video (urutan kronologis):
{segs_json}

Tugasmu:
1. Pilih SATU segmen yang paling menarik untuk dijadikan "cold open" (potongan pembuka sebelum klip asli mengalir), agar penonton tidak skip.
2. Tentukan durasi cold open (hook_duration) yang CUKUP agar momen kejutan selesai utuh, TANPA terpotong di tengah kalimat. Biasanya 2.0–5.0 detik.
3. Buat 1 kalimat caption pendek (MAKS 8 KATA) dalam BAHASA YANG SAMA dengan transkrip, yang memancing rasa penasaran terhadap momen itu. BUKAN copy-paste kalimat asli — buat kalimat provokatif BARU.

Aturan:
- Pilih segmen yang mengandung kejutan, klaim mengejutkan, pertanyaan retorik, konflik, atau fakta menarik.
{start_rule}
{spike_hint}- hook_type harus salah satu: question, shock, stat, conflict, curiosity_gap.
- confidence: 0.0–1.0 seberapa yakin momen ini akan membuat penonton tertarik.
- CAPTION WAJIB JUJUR: hanya boleh memakai ulang fakta/angka yang benar-benar ada di transkrip. DILARANG mengubah, menambah, atau melebih-lebihkan angka maupun klaim (contoh salah: transkrip bilang 6 juta tapi caption bilang 100 juta). Dilarang klikbait palsu — kalimat provokatif boleh, tapi isi faktual harus sama persis dengan transkrip.

Balas HANYA dengan JSON valid (tidak ada teks lain):
{{"best_idx": <int>, "hook_type": "<str>", "confidence": <float>, "hook_duration": <float, detik>, "reason": "<singkat>", "caption": "<maks 8 kata>"}}"""

    def _call_llm(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Kamu adalah editor video ahli. Balas HANYA dengan JSON valid.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        try:
            response = self.client.post(f"{self.base_url}/chat/completions", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Jika 404 Not Found, 429 Quota Exceeded, atau 503 Service Unavailable, fallback otomatis
            if self.provider == "gemini" and e.response.status_code in (404, 429, 503):
                fallback_models = ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-flash-latest"]
                fallback_resp = None
                for fb_model in fallback_models:
                    if fb_model == self.model:
                        continue
                    logger.info(
                        "Model '%s' mengalami HTTP %d, mencoba fallback otomatis ke '%s'",
                        self.model, e.response.status_code, fb_model,
                    )
                    payload["model"] = fb_model
                    try:
                        fb_call = self.client.post(f"{self.base_url}/chat/completions", json=payload)
                        fb_call.raise_for_status()
                        fallback_resp = fb_call
                        break
                    except httpx.HTTPStatusError as fb_err:
                        logger.warning("Fallback model '%s' gagal dengan HTTP %d", fb_model, fb_err.response.status_code)
                        continue

                if fallback_resp is not None:
                    response = fallback_resp
                else:
                    raise
            else:
                raise

        # Simpan info rate limit dari header (best-effort) untuk ditampilkan di UI
        _update_llm_status(response.headers)

        # 9Router kadang sisipkan trailing artefak SSE ("...}data: [DONE]")
        # setelah body JSON → response.json() lempar Extra data. Ambil teks
        # mentah lalu strip trailing junk sebelum parse (lihat _parse_response).
        raw_body = response.text.rstrip()
        trailing = raw_body.rfind("data: [DONE]")
        if trailing != -1:
            raw_body = raw_body[:trailing].rstrip()
        body = json.loads(raw_body)
        return body["choices"][0]["message"]["content"]

    def _parse_response(self, raw: str) -> dict | None:
        """Parse JSON dari LLM response. Return None kalau gagal.

        Tahan terhadap lafalan LLM yang tidak patuh: code fence, teks di
        sekitar JSON, dan trailing clutter — selalu ekstrak blok JSON valid.
        """
        raw = raw.strip()
        # Strip markdown code fences kalau ada
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                line for line in lines
                if not line.startswith("```")
            ).strip()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            # Kode fence tersisa atau teks bercampur JSON — cari blok JSON
            # dari '{' pertama sampai '}' terakhir yang seimbang.
            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1 or end <= start:
                logger.warning("HookMomentFinder parse JSON gagal (tak ada blok JSON): %s | raw: %.200s", repr(raw[:100]), raw)
                return None
            candidate = raw[start : end + 1]
            try:
                data = json.loads(candidate)
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logger.warning("HookMomentFinder parse JSON gagal: %s | raw: %.200s", e, raw)
                return None
        # Konversi best_idx ke int eksplisit (LLM kadang kirim float)
        if "best_idx" in data:
            try:
                data["best_idx"] = int(data["best_idx"])
            except (ValueError, TypeError):
                pass
        return data
