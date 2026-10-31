"""Unit tests for AICurator module."""

import json
from unittest.mock import MagicMock, patch
import pytest

from app.ai_modules.llm_analysis.ai_curator import AICurator, AICuratorError


def test_build_prompt():
    """Test format prompt teks dengan transcript dan timeline."""
    curator = AICurator()
    segments = [
        {"id": 1, "start_time": 0.0, "end_time": 4.5, "text": "Halo semuanya selamat datang."},
        {"id": 2, "start_time": 4.5, "end_time": 10.0, "text": "Hari ini kita bahas topik seru."},
    ]
    audio_spikes = [{"time": 5.2, "time_str": "00:05", "spike_db": 12.3, "peak_db": -10.0}]
    scene_cuts = [4.5]

    prompt = curator._build_prompt(
        category_name="Podcast Edukasi",
        duration_seconds=60.0,
        segments=segments,
        audio_spikes=audio_spikes,
        scene_cuts=scene_cuts,
        has_storyboard=False,
    )

    assert "Podcast Edukasi" in prompt
    assert "[#1 00:00-00:04] Halo semuanya selamat datang." in prompt
    assert "00:05 (+12.3dB)" in prompt
    assert "00:04" in prompt


def test_build_user_content():
    """Test pembuatan multimodal user content vs text-only content."""
    curator = AICurator()
    text = "Hello world prompt"

    # Text only
    res_text = curator._build_user_content(text, None)
    assert res_text == text

    # Multimodal with storyboard sheets
    images = ["data:image/jpeg;base64,AAA123", "data:image/jpeg;base64,BBB456"]
    res_multi = curator._build_user_content(text, images)
    assert isinstance(res_multi, list)
    assert len(res_multi) == 3
    assert res_multi[0]["type"] == "text"
    assert res_multi[1]["type"] == "image_url"
    assert res_multi[1]["image_url"]["url"] == images[0]


def test_parse_response_fenced_json():
    """Test parsing respon LLM yang dibungkus markdown code fence."""
    curator = AICurator()
    mock_payload = {
        "category_interpretation": "Testing category",
        "scan_notes": ["Raw moment 1", "Raw moment 2"],
        "candidates": [
            {
                "start_seg": 1,
                "end_seg": 2,
                "title": "Judul Menarik",
                "archetype": "story",
                "why_viral": "Cerita relate dan ada twist",
                "confidence": 8.5,
                "hook": {
                    "moment_time": 6.5,
                    "type": "shock",
                    "caption": "MOMEN SHOCK",
                },
            }
        ],
    }

    raw_response = f"Berikut adalah hasilnya:\n```json\n{json.dumps(mock_payload)}\n```\nSemoga membantu!"
    parsed = curator._parse_response(raw_response)

    assert parsed["category_interpretation"] == "Testing category"
    assert len(parsed["candidates"]) == 1
    assert parsed["candidates"][0]["title"] == "Judul Menarik"
    assert parsed["candidates"][0]["confidence"] == 8.5


def test_handle_http_error_429():
    """Test mapping error HTTP 429 kuota habis."""
    curator = AICurator()
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "Quota exceeded"

    with pytest.raises(AICuratorError) as exc_info:
        curator._handle_http_error(mock_resp)

    assert "Kuota harian" in str(exc_info.value)
    assert "HTTP 429" in str(exc_info.value)


def test_handle_http_error_vision_unsupported():
    """Test mapping error model tidak mendukung gambar/vision."""
    curator = AICurator()
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "Invalid request: vision image input is unsupported by this model"

    with pytest.raises(AICuratorError) as exc_info:
        curator._handle_http_error(mock_resp)

    assert "tidak mendukung input gambar/visual" in str(exc_info.value)



def test_parse_response_unclosed_fence():
    """Test parsing respon LLM saat code fence tidak ditutup dengan ``` di akhir."""
    curator = AICurator()
    raw = '```json\n{\n  "category_interpretation": "Unclosed fence test",\n  "candidates": [{"title": "Test 1", "confidence": 8.0}]\n}'
    parsed = curator._parse_response(raw)
    assert parsed["category_interpretation"] == "Unclosed fence test"
    assert len(parsed["candidates"]) == 1


def test_parse_response_trailing_commas():
    """Test parsing JSON dengan trailing commas yang sering dihasilkan model LLM."""
    curator = AICurator()
    raw = '{\n  "category_interpretation": "Trailing comma test",\n  "candidates": [\n    {"title": "Test 1", "confidence": 8.0,},\n  ],\n}'
    parsed = curator._parse_response(raw)
    assert parsed["category_interpretation"] == "Trailing comma test"
    assert len(parsed["candidates"]) == 1


def test_parse_response_truncated_recovery():
    """Test recovery otomatis saat output JSON terpotong di tengah jalan."""
    curator = AICurator()
    raw = '```json\n{\n  "category_interpretation": "Truncated test",\n  "candidates": [\n    {"start_seg": 10, "end_seg": 20, "title": "Good Clip", "confidence": 9.0},\n    {"start_seg": 30, "end_seg": 40, "title": "Cutoff'
    parsed = curator._parse_response(raw)
    assert len(parsed["candidates"]) >= 1
    assert parsed["candidates"][0]["title"] == "Good Clip"


def test_build_prompt_with_content_brief():
    """Test format prompt teks ketika content brief diberikan."""
    curator = AICurator()
    segments = [
        {"id": 1, "start_time": 0.0, "end_time": 4.5, "text": "Promo ShopeePay Games seru banget."},
    ]
    brief = "Wajib clip momen promo ShopeePay Games dan reaksi kocak Reza Auditore."

    prompt = curator._build_prompt(
        category_name="Gaming Promo",
        duration_seconds=30.0,
        segments=segments,
        audio_spikes=[],
        scene_cuts=[],
        has_storyboard=False,
        content_brief=brief,
    )

    assert "CLIENT CAMPAIGN CONTENT BRIEF (STRICT REQUIREMENT)" in prompt
    assert "ShopeePay Games" in prompt
    assert "Reza Auditore" in prompt
    assert "AKTIF (Wajib Patuhi Instruksi Client/Campaign)" in prompt

