"""Caption Style Service — Generator gaya teks hook ASS (libass) & fallback drawtext.

Satu-satunya tempat konfigurasi dan perakitan gaya teks hook di project ini:
- Font bundel lokal (Anton, Bangers, Poppins Black)
- Outline tebal (9px), shadow halus (4px)
- Highlight 1 kata kunci berwarna kuning (&H00E6FF&)
- Animasi pop-in singkat (\fscx, \t) + fade-out (\fad)
- Wrap otomatis maks 2 baris dengan skala ukuran adaptif
- Deteksi koordinat safe box (hindari menutupi wajah / panel divider)
"""

import logging
import re
from pathlib import Path
from typing import Any

from app.core.config.settings import settings

logger = logging.getLogger(__name__)

# Emoji & symbols pattern untuk membersihkan teks burn-in
_EMOJI_PATTERN = re.compile(
    "["
    "\U00010000-\U0010ffff"
    "\u2600-\u27bf"
    "\u2300-\u23ff"
    "\u2b50-\u2b55"
    "\ufe00-\ufe0f"
    "]+",
    flags=re.UNICODE,
)

# Registry font bundel
FONT_STYLES: dict[str, dict[str, str]] = {
    "impact": {
        "family": "Anton",
        "file": "Anton-Regular.ttf",
    },
    "fun": {
        "family": "Bangers",
        "file": "Bangers-Regular.ttf",
    },
    "clean": {
        "family": "Poppins Black",
        "file": "Poppins-Black.ttf",
    },
}

# Kata kunci reaksi prioritas (dalam huruf kecil)
PRIORITY_REACTION_KEYWORDS: list[str] = [
    "teriak",
    "kaget",
    "joget",
    "nyanyi",
    "kenapa",
    "gak kuat",
    "kuat",
]


def rgb_to_ass_color(hex_color: str) -> str:
    """Konversi format hex RGB (#RRGGBB) ke format warna ASS (&HBBGGRR&)."""
    clean = hex_color.lstrip("#")
    if len(clean) == 6:
        r, g, b = clean[0:2].upper(), clean[2:4].upper(), clean[4:6].upper()
        return f"&H{b}{g}{r}&"
    return "&H00E6FF&"


def format_ass_time(seconds: float) -> str:
    """Format detik ke format waktu ASS H:MM:SS.cs."""
    safe_sec = max(0.0, float(seconds))
    hrs = int(safe_sec // 3600)
    mins = int((safe_sec % 3600) // 60)
    secs = safe_sec % 60
    return f"{hrs}:{mins:02d}:{secs:05.2f}"


class CaptionStyleService:
    """Service pembuat style caption hook TikTok-ready dengan ASS format."""

    @classmethod
    def resolve_style(cls, reaction_type: str | None = None) -> str:
        """Pilih gaya font berdasarkan setting atau reaction_type.

        - reaction_type in {joget, nyanyi} -> 'fun' (Bangers)
        - lainnya -> 'impact' (Anton)
        - Override lewat HOOK_FONT_STYLE di config
        """
        configured_style = (getattr(settings, "HOOK_FONT_STYLE", "auto") or "auto").lower().strip()
        if configured_style in FONT_STYLES:
            return configured_style

        if reaction_type:
            rt = reaction_type.lower().strip()
            if rt in {"joget", "nyanyi", "fun"}:
                return "fun"
            if rt in {"clean", "poppins", "poppins black"}:
                return "clean"
            if rt in {"impact", "anton"}:
                return "impact"

        return "impact"

    @classmethod
    def get_font_info(cls, style: str) -> tuple[str, Path]:
        """Ambil font family name dan path file ttf.

        Fallback jika file tidak ditemukan: tetap log warning dan fallback
        ke font default Anton atau font apa pun yang ada.
        """
        info = FONT_STYLES.get(style, FONT_STYLES["impact"])
        family = info["family"]
        filename = info["file"]

        fonts_dir = Path(getattr(settings, "AUTO_HOOK_FONTS_DIR", "data/assets/fonts"))
        font_path = fonts_dir / filename

        if not font_path.exists():
            logger.warning(
                "CaptionStyleService: Font file '%s' tidak ditemukan di '%s'. Mencoba fallback.",
                filename, fonts_dir,
            )
            # Coba fallback ke Anton
            fallback_path = fonts_dir / "Anton-Regular.ttf"
            if fallback_path.exists():
                return "Anton", fallback_path
            # Coba font pertama di direktori fonts
            available_fonts = list(fonts_dir.glob("*.ttf"))
            if available_fonts:
                return available_fonts[0].stem, available_fonts[0]

        return family, font_path

    @classmethod
    def clean_text(cls, text: str) -> str:
        """Bersihkan emoji, normalisasi spasi, ubah ke UPPERCASE."""
        no_emoji = _EMOJI_PATTERN.sub("", text or "")
        normalized = " ".join(no_emoji.strip().split())
        return normalized.upper()

    @classmethod
    def measure_text_width(cls, text: str, font_path: Path | None, font_size: int) -> float:
        """Ukur lebar teks dalam piksel memakai Pillow atau estimasi karakter."""
        if font_path and font_path.exists():
            try:
                from PIL import ImageFont
                font = ImageFont.truetype(str(font_path), font_size)
                return float(font.getlength(text))
            except Exception:
                pass
        # Estimasi kasar: rata-rata lebar huruf font condensed ~0.52 * font_size
        return len(text) * font_size * 0.52

    @classmethod
    def wrap_lines(
        cls,
        text: str,
        font_path: Path | None,
        base_font_size: int,
        min_font_size: int,
        max_width: float,
    ) -> tuple[list[str], int]:
        """Wrap teks maksimal 2 baris (split dekat tengah kata) dan kalkulasi font_size.

        Returns:
            (lines, final_font_size)
        """
        words = text.split()
        if not words:
            return [""], base_font_size

        if len(words) == 1:
            lines = [words[0]]
        elif len(words) <= 3 and cls.measure_text_width(text, font_path, base_font_size) <= max_width:
            lines = [text]
        else:
            # Cari titik pisah kata yang membagi karakter paling seimbang di tengah
            best_idx = 1
            best_diff = float("inf")
            for i in range(1, len(words)):
                l1 = " ".join(words[:i])
                l2 = " ".join(words[i:])
                diff = abs(len(l1) - len(l2))
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i
            lines = [" ".join(words[:best_idx]), " ".join(words[best_idx:])]

        # Skala font size agar kedua baris tidak melebihi max_width
        font_size = base_font_size
        longest_line_w = max(cls.measure_text_width(line, font_path, font_size) for line in lines)
        if longest_line_w > max_width and longest_line_w > 0:
            scale_ratio = max_width / longest_line_w
            scaled_size = int(font_size * scale_ratio)
            font_size = max(min_font_size, scaled_size)

        return lines, font_size

    @classmethod
    def highlight_single_keyword(
        cls,
        lines: list[str],
        reaction_type: str | None = None,
        highlight_color_bgr: str = "&H00E6FF&",
    ) -> str:
        """Beri highlight warna kuning pada TEPAT 1 kata kunci, lalu gabungkan dengan \\N.

        Aturan:
        1. Kata reaction_type jika ada di teks
        2. Kata dari PRIORITY_REACTION_KEYWORDS jika ada di teks
        3. Kata terpanjang (fallback)
        """
        all_tokens = [tok for line in lines for tok in line.split()]
        if not all_tokens:
            return ""

        def clean_tok(tok: str) -> str:
            return "".join(ch for ch in tok if ch.isalnum()).lower()

        target_token: str | None = None

        # 1. Cek reaction_type spesifik
        if reaction_type:
            rt_clean = clean_tok(reaction_type)
            if rt_clean and rt_clean not in {"auto", "impact", "clean", "fun"}:
                for tok in all_tokens:
                    if clean_tok(tok) == rt_clean:
                        target_token = tok
                        break

        # 2. Cek priority reaction keywords
        if not target_token:
            for kw in PRIORITY_REACTION_KEYWORDS:
                for tok in all_tokens:
                    if clean_tok(tok) == kw:
                        target_token = tok
                        break
                if target_token:
                    break

        # 3. Fallback: kata terpanjang
        if not target_token:
            target_token = max(all_tokens, key=lambda t: len(clean_tok(t)))

        # Terapkan highlight tepat 1 kali pada kemunculan pertama target_token
        highlighted = False
        new_lines: list[str] = []
        for line in lines:
            if not highlighted and target_token:
                words = line.split()
                for idx, word in enumerate(words):
                    if word == target_token:
                        words[idx] = "{\\c" + highlight_color_bgr + "}" + word + "{\\c&HFFFFFF&}"
                        highlighted = True
                        break
                new_lines.append(" ".join(words))
            else:
                new_lines.append(line)

        return "\\N".join(new_lines)

    @classmethod
    def calculate_position(
        cls,
        width: int,
        height: int,
        safe_box: dict | tuple | Any = None,
    ) -> tuple[int, int]:
        """Tentukan koordinat (x, y) caption hook sesuai safe zone.

        - Layout center_crop: x = tengah, y sekitar 30–38% dari atas
        - Layout facecam_top: tepat di bawah garis pemisah gameplay
        - Hindari batas 12% bawah & 14% sisi kanan/kiri
        """
        # Batas aman (safe margins)
        margin_x = int(width * 0.14)
        margin_top = int(height * 0.08)
        margin_bottom = int(height * 0.88)

        default_x = width // 2
        default_y = int(height * 0.35)  # 35% tinggi (dalam batas 30–38%)

        if safe_box is None:
            x = default_x
            y = default_y
        elif isinstance(safe_box, (tuple, list)):
            if len(safe_box) >= 4:
                x = int((safe_box[0] + safe_box[2]) / 2)
                y = int((safe_box[1] + safe_box[3]) / 2)
            elif len(safe_box) >= 2:
                x = int(safe_box[0])
                y = int(safe_box[1])
            else:
                x, y = default_x, default_y
        elif isinstance(safe_box, dict):
            layout = safe_box.get("layout", "")
            if layout == "facecam_top":
                x = safe_box.get("x", default_x)
                # Tepat di bawah divider panel
                split_y = safe_box.get("split_y") or safe_box.get("divider_y") or int(height * 0.35)
                offset = safe_box.get("offset_y", 30)
                y = int(split_y) + offset
            else:
                x = safe_box.get("x", safe_box.get("center_x", default_x))
                y = safe_box.get("y", safe_box.get("center_y", default_y))
        else:
            x, y = default_x, default_y

        # Clamp ke safe margins
        x = max(margin_x, min(width - margin_x, x))
        y = max(margin_top, min(margin_bottom, y))
        return x, y

    @classmethod
    def build_ass(
        cls,
        caption: str,
        reaction_type: str | None = None,
        duration: float = 2.0,
        width: int = 1080,
        height: int = 1920,
        safe_box: Any = None,
        font_size: int | None = None,
        min_size: int | None = None,
    ) -> str:
        """Hasilkan file script ASS lengkap untuk dibakar via filter libass.

        Args:
            caption: Teks caption hook
            reaction_type: Tipe reaksi momen (misal teriak, joget, nyanyi, shock)
            duration: Durasi tampilan teaser hook (detik)
            width: Resolusi PlayResX (default 1080)
            height: Resolusi PlayResY (default 1920)
            safe_box: Informasi safe area atau layout
            font_size: Override ukuran font dasar
            min_size: Override batas minimum ukuran font
        """
        style_name = cls.resolve_style(reaction_type)
        family_name, font_path = cls.get_font_info(style_name)

        base_size = font_size or getattr(settings, "HOOK_FONT_SIZE", 120)
        min_font_size = min_size or getattr(settings, "HOOK_FONT_MIN_SIZE", 84)
        outline_w = getattr(settings, "HOOK_TEXT_OUTLINE", 9)
        highlight_hex = getattr(settings, "HOOK_HIGHLIGHT_COLOR", "#FFE600")
        highlight_bgr = rgb_to_ass_color(highlight_hex)
        use_pop_animation = getattr(settings, "HOOK_POP_ANIMATION", True)

        cleaned_text = cls.clean_text(caption)

        # Lebar maksimal teks: <= 86% lebar frame
        max_frame_width = width * 0.86
        lines, final_font_size = cls.wrap_lines(
            cleaned_text,
            font_path,
            base_size,
            min_font_size,
            max_frame_width,
        )

        highlighted_text = cls.highlight_single_keyword(
            lines,
            reaction_type=reaction_type,
            highlight_color_bgr=highlight_bgr,
        )

        pos_x, pos_y = cls.calculate_position(width, height, safe_box)

        # Animasi pop-in dan fade-out
        # Mulai \fscx60\fscy60, \t(0,140,\fscx112\fscy112), \t(140,240,\fscx100\fscy100)
        # Fade-out 120 ms di akhir (\fad(0,120))
        anim_tags = "\\an5"
        if use_pop_animation:
            anim_tags += (
                "\\fscx60\\fscy60"
                "\\t(0,140,\\fscx112\\fscy112)"
                "\\t(140,240,\\fscx100\\fscy100)"
            )
        anim_tags += "\\fad(0,120)"

        start_ts = format_ass_time(0.0)
        end_ts = format_ass_time(duration)

        dialogue_line = (
            f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,"
            f"{{\\pos({pos_x},{pos_y}){anim_tags}}}{highlighted_text}"
        )

        ass_content = (
            "[Script Info]\n"
            "; Script generated by Daboji CaptionStyleService\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {width}\n"
            f"PlayResY: {height}\n"
            "WrapStyle: 2\n"
            "ScaledBorderAndShadow: yes\n"
            "\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{family_name},{final_font_size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            f"0,0,0,0,100,100,0,0,1,{outline_w},4,5,10,10,10,1\n"
            "\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"{dialogue_line}\n"
        )
        return ass_content

    @classmethod
    def build_fallback_text(
        cls,
        caption: str,
        width: int = 1080,
    ) -> str:
        """Hasilkan teks polos 2 baris (UPPERCASE tanpa tag ASS) untuk textfile= drawtext fallback."""
        cleaned_text = cls.clean_text(caption)
        fonts_dir = Path(getattr(settings, "AUTO_HOOK_FONTS_DIR", "data/assets/fonts"))
        anton_path = fonts_dir / "Anton-Regular.ttf"
        lines, _ = cls.wrap_lines(
            cleaned_text,
            anton_path if anton_path.exists() else None,
            110,
            84,
            width * 0.86,
        )
        return "\n".join(lines)
