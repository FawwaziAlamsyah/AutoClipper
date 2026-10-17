"""Tests for CaptionStyleService and Hook Caption Styling."""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config.settings import settings
from app.services.caption_style_service import CaptionStyleService, rgb_to_ass_color


# ── 1. Format dasar ASS & PlayRes ─────────────────────────────────────────────

def test_build_ass_playres_and_headers() -> None:
    """Verifikasi PlayResX=1080, PlayResY=1920, WrapStyle=2, dan struktur ASS valid."""
    ass = CaptionStyleService.build_ass(
        caption="WINDAH KENAPA SAMPAI TERIAK?",
        reaction_type="teriak",
        duration=2.0,
        width=1080,
        height=1920,
    )

    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "WrapStyle: 2" in ass
    assert "[Script Info]" in ass
    assert "[V4+ Styles]" in ass
    assert "[Events]" in ass
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Default" in ass


# ── 2. Maksimal 2 baris teks ──────────────────────────────────────────────────

def test_build_ass_produces_at_most_two_lines() -> None:
    """build_ass menghasilkan dialog dengan maksimal 2 baris (maks 1 tanda \\N)."""
    captions = [
        "SINGKAT",
        "DUA KATA",
        "WINDAH KENAPA SAMPAI TERIAK?",
        "REAKSI KAGET MELIHAT KEJADIAN YANG SANGAT TIDAK TERDUGA SAMA SEKALI",
    ]
    for cap in captions:
        ass = CaptionStyleService.build_ass(caption=cap, duration=2.0)
        # Ambil bagian teks dari baris Dialogue
        dialogue_line = [line for line in ass.splitlines() if line.startswith("Dialogue:")][0]
        # Hapus tag override {\...}
        text_content = re.sub(r"\{.*?\}", "", dialogue_line)
        # Hitung jumlah baris berdasarkan \\N
        lines = text_content.split("\\N")
        assert len(lines) <= 2, f"Caption '{cap}' menghasilkan lebih dari 2 baris: {lines}"


# ── 3. Highlight tepat 1 kata kunci ───────────────────────────────────────────

def test_build_ass_highlight_tag_exactly_one_keyword() -> None:
    """Tepat 1 kata kunci diberi warna kuning (&H00E6FF&) dan kembali putih."""
    ass = CaptionStyleService.build_ass(
        caption="WINDAH KENAPA SAMPAI TERIAK?",
        reaction_type="teriak",
        duration=2.0,
    )
    dialogue_line = [line for line in ass.splitlines() if line.startswith("Dialogue:")][0]

    # Warna kuning highlight muncul tepat 1 kali
    assert dialogue_line.count("{\\c&H00E6FF&}") == 1
    # Ditutup kembali ke putih
    assert dialogue_line.count("{\\c&HFFFFFF&}") >= 1
    # Kata 'TERIAK?' yang di-highlight karena sesuai reaction_type='teriak'
    assert "{\\c&H00E6FF&}TERIAK?{\\c&HFFFFFF&}" in dialogue_line


def test_build_ass_highlight_fallback_to_longest_word() -> None:
    """Jika reaction_type tidak cocok dengan teks, highlight kata terpanjang."""
    ass = CaptionStyleService.build_ass(
        caption="LIHAT PERISTIWA ANEH INI",
        reaction_type="shock",  # 'shock' tidak ada di teks
        duration=2.0,
    )
    dialogue_line = [line for line in ass.splitlines() if line.startswith("Dialogue:")][0]
    assert dialogue_line.count("{\\c&H00E6FF&}") == 1
    # Kata terpanjang adalah 'PERISTIWA' (9 huruf)
    assert "{\\c&H00E6FF&}PERISTIWA{\\c&HFFFFFF&}" in dialogue_line


# ── 4. Posisi dan safe box ────────────────────────────────────────────────────

def test_build_ass_position_center_crop_safe_zone() -> None:
    """Layout default center_crop: x=tengah (540), y di area 30-38% tinggi."""
    ass = CaptionStyleService.build_ass(
        caption="TEST POSITION",
        duration=2.0,
        width=1080,
        height=1920,
        safe_box=None,
    )
    # y = int(1920 * 0.35) = 672
    assert "\\pos(540,672)" in ass


def test_build_ass_position_facecam_top_safe_box() -> None:
    """Layout facecam_top: posisi y berada di bawah split line divider."""
    safe_box = {
        "layout": "facecam_top",
        "split_y": 680,
        "offset_y": 30,
    }
    ass = CaptionStyleService.build_ass(
        caption="TEST FACECAM",
        duration=2.0,
        width=1080,
        height=1920,
        safe_box=safe_box,
    )
    # y = 680 + 30 = 710
    assert "\\pos(540,710)" in ass


def test_calculate_position_clamps_safe_margins() -> None:
    """Koordinat yang terlalu dekat tepi luar akan di-clamp agar tidak tertutup UI TikTok."""
    # x terlalu kiri (0) di-clamp ke min 14% frame (151)
    # y terlalu bawah (1900) di-clamp ke max 88% frame (1689)
    x, y = CaptionStyleService.calculate_position(1080, 1920, (0, 1900))
    assert x >= int(1080 * 0.14)
    assert y <= int(1920 * 0.88)


# ── 5. Font selection & bundle assets ─────────────────────────────────────────

def test_bundled_fonts_exist() -> None:
    """Memastikan font bundel Anton, Bangers, dan Poppins Black tersedia di folder assets."""
    fonts_dir = Path(settings.AUTO_HOOK_FONTS_DIR)
    assert (fonts_dir / "Anton-Regular.ttf").exists()
    assert (fonts_dir / "Bangers-Regular.ttf").exists()
    assert (fonts_dir / "Poppins-Black.ttf").exists()
    assert (fonts_dir / "OFL-Anton.txt").exists()
    assert (fonts_dir / "OFL-Bangers.txt").exists()
    assert (fonts_dir / "OFL-Poppins.txt").exists()


def test_font_style_selection_by_reaction() -> None:
    """joget/nyanyi -> Bangers (fun), selain itu -> Anton (impact)."""
    assert CaptionStyleService.resolve_style("joget") == "fun"
    assert CaptionStyleService.resolve_style("nyanyi") == "fun"
    assert CaptionStyleService.resolve_style("teriak") == "impact"
    assert CaptionStyleService.resolve_style("kaget") == "impact"
    assert CaptionStyleService.resolve_style(None) == "impact"

    fam_fun, _ = CaptionStyleService.get_font_info("fun")
    assert fam_fun == "Bangers"

    fam_impact, _ = CaptionStyleService.get_font_info("impact")
    assert fam_impact == "Anton"


def test_font_style_override_via_settings() -> None:
    """HOOK_FONT_STYLE di settings meng-override deteksi otomatis."""
    with patch.object(settings, "HOOK_FONT_STYLE", "clean"):
        style = CaptionStyleService.resolve_style("joget")
        assert style == "clean"
        fam, _ = CaptionStyleService.get_font_info(style)
        assert fam == "Poppins Black"


def test_missing_font_logs_warning_and_uses_fallback(caplog: pytest.LogCaptureFixture) -> None:
    """Jika font file tidak ada di disk, log warning dan fallback tanpa crash."""
    with patch.object(settings, "AUTO_HOOK_FONTS_DIR", "data/non_existent_fonts_dir"):
        family, path = CaptionStyleService.get_font_info("fun")
        assert family is not None
        assert any("tidak ditemukan" in record.message for record in caplog.records)


# ── 6. Caption panjang (>=34 karakter) & penyesuaian ukuran font ──────────────

def test_long_caption_scales_down_to_min_size() -> None:
    """Caption sangat panjang (>=34 karakter) tetap muat dan ukuran turun >= HOOK_FONT_MIN_SIZE."""
    long_caption = "REAKSI KAGET MELIHAT KEJADIAN YANG SANGAT TIDAK TERDUGA SAMA SEKALI"
    ass = CaptionStyleService.build_ass(
        caption=long_caption,
        duration=2.0,
        width=1080,
        height=1920,
    )

    # Style: Default,Anton,<font_size>,...
    match = re.search(r"Style:\s*Default,\w+,(\d+),", ass)
    assert match is not None
    font_size = int(match.group(1))

    # Font size turun dari default 120, tapi tetap >= min_size (84)
    assert font_size < 120
    assert font_size >= settings.HOOK_FONT_MIN_SIZE


# ── 7. Animasi pop-in dan fade ────────────────────────────────────────────────

def test_pop_in_animation_tags_present() -> None:
    """Memastikan tag skala pop-in dan fade-out 120ms ada di baris dialog."""
    ass = CaptionStyleService.build_ass(caption="TEST POP ANIMATION", duration=2.0)
    assert "\\fscx60\\fscy60" in ass
    assert "\\t(0,140,\\fscx112\\fscy112)" in ass
    assert "\\t(140,240,\\fscx100\\fscy100)" in ass
    assert "\\fad(0,120)" in ass


def test_pop_in_animation_disabled_when_flag_false() -> None:
    """Jika HOOK_POP_ANIMATION=False, tag animasi pop dihilangkan."""
    with patch.object(settings, "HOOK_POP_ANIMATION", False):
        ass = CaptionStyleService.build_ass(caption="NO POP ANIMATION", duration=2.0)
        assert "\\fscx60\\fscy60" not in ass
        assert "\\fad(0,120)" in ass  # fade-out tetap ada


# ── 8. Pembersihan emoji ──────────────────────────────────────────────────────

def test_clean_text_strips_emojis() -> None:
    """Emoji dibersihkan dari caption burn-in agar tidak memunculkan kotak rusak (missing glyph)."""
    text_with_emoji = "WINDAH TERIAK BANGET! 🔥😂✨ KOCAK"
    cleaned = CaptionStyleService.clean_text(text_with_emoji)
    assert "🔥" not in cleaned
    assert "😂" not in cleaned
    assert "✨" not in cleaned
    assert "WINDAH TERIAK BANGET! KOCAK" == cleaned


# ── 9. Fallback plain text drawtext ───────────────────────────────────────────

def test_build_fallback_text() -> None:
    """build_fallback_text menghasilkan teks uppercase 2 baris bersih tanpa tag ASS."""
    caption = "WINDAH KENAPA SAMPAI TERIAK?"
    fallback = CaptionStyleService.build_fallback_text(caption)
    assert "{" not in fallback
    assert "}" not in fallback
    assert "\\N" not in fallback
    assert "\n" in fallback
    assert "TERIAK?" in fallback


# ── 10. HookComposerService._apply_caption ASS & Fallback ─────────────────────

def test_hook_composer_apply_caption_ass_success(tmp_path: Path) -> None:
    """_apply_caption menggunakan filter subtitles dengan path relatif dan fontsdir bundel."""
    from app.services.hook_composer_service import HookComposerService

    mock_db = MagicMock()
    service = HookComposerService(mock_db)

    with patch.object(service, "_run") as mock_run:
        service._apply_caption(
            source="dummy_in.mp4",
            output="dummy_out.mp4",
            caption="WINDAH KENAPA SAMPAI TERIAK?",
            duration=2.0,
            reaction_type="teriak",
            tmp_dir=tmp_path,
        )

        mock_run.assert_called_once()
        cmd, step = mock_run.call_args[0][:2]
        cwd = mock_run.call_args[1].get("cwd")

        assert step == "apply_caption_ass"
        assert cwd == settings.BASE_DIR

        # Cari filter -vf
        vf_idx = cmd.index("-vf")
        vf_val = cmd[vf_idx + 1]
        assert "subtitles=" in vf_val
        assert "fontsdir=data/assets/fonts" in vf_val
        assert "\\" not in vf_val.split(":")[0]  # Garis miring / (tanpa backslash Windows)


def test_hook_composer_apply_caption_fallback_on_ass_error(tmp_path: Path) -> None:
    """Jika ASS gagal, _apply_caption beralih ke drawtext dengan font bundel Anton dan borderw=8."""
    from app.services.hook_composer_service import HookComposerService

    mock_db = MagicMock()
    service = HookComposerService(mock_db)

    # Buat pemanggilan ASS pertama gagal
    def fake_run(cmd, step, cwd=None):
        if step == "apply_caption_ass":
            raise RuntimeError("libass error simulating failure")
        return None

    with patch.object(service, "_run", side_effect=fake_run) as mock_run:
        service._apply_caption(
            source="dummy_in.mp4",
            output="dummy_out.mp4",
            caption="WINDAH KENAPA SAMPAI TERIAK?",
            duration=2.0,
            tmp_dir=tmp_path,
        )

        assert mock_run.call_count == 2
        fallback_cmd, fallback_step = mock_run.call_args_list[1][0][:2]
        assert fallback_step == "apply_caption_fallback"

        vf_idx = fallback_cmd.index("-vf")
        vf_val = fallback_cmd[vf_idx + 1]
        assert "drawtext=" in vf_val
        assert "fontfile='data/assets/fonts/Anton-Regular.ttf'" in vf_val
        assert "borderw=8:bordercolor=black" in vf_val
        assert "fontsize=110" in vf_val
        assert "textfile=" in vf_val
        assert "box=" not in vf_val


def test_build_ass_highlight_word_from_llm_takes_priority() -> None:
    """highlight_word pilihan LLM diprioritaskan di atas kata terpanjang."""
    ass = CaptionStyleService.build_ass(
        caption="DETIK TERAKHIR BIKIN PINTU TERBUKA",
        reaction_type="curiosity_gap",
        highlight_word="pintu",
    )
    assert "{\\c&H00E6FF&}PINTU{\\c&HFFFFFF&}" in ass


def test_build_ass_highlights_numeric_token_before_longest_word() -> None:
    """Jika tidak ada keyword reaksi, angka/nominal diprioritaskan di atas kata terpanjang."""
    ass = CaptionStyleService.build_ass(
        caption="KERUGIAN MENCAPAI 500 JUTA",
        reaction_type="stat",
    )
    assert "{\\c&H00E6FF&}500{\\c&HFFFFFF&}" in ass


def test_render_hook_stacked_split_passes_facecam_top_safe_box(tmp_path: Path) -> None:
    """Pada layout 9:16 stacked_split, _render_hook meneruskan safe_box facecam_top (split_y=800, offset_y=0)
    agar caption berada di perbatasan y=800px dan tidak menutupi wajah streamer."""
    from app.ai_modules.hook_analysis.hook_moment_finder import HookMoment
    from app.services.hook_composer_service import HookComposerService

    mock_db = MagicMock()
    service = HookComposerService(mock_db)
    moment = HookMoment(
        hook_moment_start=10.0,
        hook_moment_end=12.5,
        hook_type="shock",
        hook_confidence=0.9,
        hook_caption="DETIK TERAKHIR BIKIN PANIK!",
        best_idx=3,
        highlight_word="panik",
    )

    mock_clip = MagicMock()
    mock_clip.id = 1
    mock_clip.file_path = str(tmp_path / "dummy_clip.mp4")

    with (
        patch.object(service, "_extract_teaser"),
        patch.object(service, "_apply_zoom_punch"),
        patch.object(service, "_apply_caption") as mock_apply_caption,
        patch.object(service, "_apply_sfx"),
        patch.object(service, "_concat"),
    ):
        service._render_hook(
            clip=mock_clip,
            video_source_path="dummy_source.mp4",
            aspect_ratio="9:16",
            hook_moment=moment,
            base_clip_path="dummy_clip.mp4",
            layout="stacked_split",
        )

    assert mock_apply_caption.called
    kwargs = mock_apply_caption.call_args.kwargs
    assert kwargs["safe_box"] == {"layout": "facecam_top", "split_y": 800, "offset_y": 0}
    assert kwargs["highlight_word"] == "panik"


