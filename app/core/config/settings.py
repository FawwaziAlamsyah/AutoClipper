"""Application configuration.

Semua nilai konfigurasi HARUS diambil dari sini. Tidak boleh ada
hardcode path/parameter di module lain.
"""

from functools import lru_cache
import logging
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings, loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    APP_NAME: str = "Daboji Auto Clipper"
    APP_ENV: str = "development"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    DEBUG: bool = True

    # Contact legal pages — placeholder email utk halaman Privacy/Terms.
    # Ganti lewat env var (.env: APP_CONTACT_EMAIL=...). Kosong = link "About" saja.
    APP_CONTACT_EMAIL: str = ""
    # Base URL publik (kalau nanti punya domain) — kosong = detected dari request.
    APP_PUBLIC_URL: str = ""

    # Preferences UI (bisa diubah user lewat menu Settings)
    APP_DEFAULT_LANGUAGE: str = "en"  # en | id
    APP_DEFAULT_THEME: str = "dark"  # light | dark

    # Paths (relatif terhadap root project)
    BASE_DIR: Path = Path(__file__).resolve().parents[3]
    DATA_DIR: Path = BASE_DIR / "data"
    LOG_DIR: Path = BASE_DIR / "logs"
    UPLOAD_DIR: Path = DATA_DIR / "uploads"
    OUTPUT_DIR: Path = DATA_DIR / "outputs"
    CACHE_DIR: Path = DATA_DIR / "cache"
    TEMP_DIR: Path = DATA_DIR / "temp"
    WATERMARK_PATH: Path = DATA_DIR / "assets" / "watermark.png"

    # Database (PostgreSQL)
    DATABASE_URL: str = "postgresql+psycopg://app:app@localhost:5432/ai_auto_clipper"

    # Logging
    LOG_LEVEL: str = "INFO"

    # Upload
    ALLOWED_VIDEO_EXTENSIONS: list[str] = [".mp4", ".mov", ".mkv", ".avi"]
    MAX_UPLOAD_SIZE_MB: int = 2048

    # Clip defaults (Sweet Spot Viral TikTok: 18–35 detik untuk retensi maksimal)
    DEFAULT_MIN_CLIP_DURATION: int = 18
    DEFAULT_MAX_CLIP_DURATION: int = 35
    DEFAULT_NUM_CLIPS: int = 5

    # FFmpeg
    FFMPEG_PATH: str = "ffmpeg"
    FFPROBE_PATH: str = "ffprobe"

    # Whisper
    WHISPER_MODEL: str = "large-v3"
    WHISPER_DEVICE: str = "auto"

    # LLM (Default: 9Router / OpenAI / Gemini)
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"

    # Google Gemini Configuration
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    GOOGLE_ACCOUNT_EMAIL: str = ""

    # Score weights — kiblat urutan scoring (default, user-overridable per job).
    # Prioritas user: gesture(20%) > voice_emotion > face_emotion > hook (4 utama).
    # gesture = gerakan tangan (HandLandmarker), bukan gerakan badan.
    # Sisa (0.34) sesuai riset sinyal retention: story > llm_content > scene.
    # llm_content sengaja rendah (masih bisa mock bila tanpa API key).
    # Total bobot = 1.00. Final score = 0.8*bobot + 0.2*trained (bila model ada).
    SCORE_WEIGHT_LLM_CONTENT: float = 0.07
    SCORE_WEIGHT_HOOK: float = 0.14
    SCORE_WEIGHT_STORY: float = 0.09
    SCORE_WEIGHT_VOICE_EMOTION: float = 0.17
    SCORE_WEIGHT_FACE_EMOTION: float = 0.15
    SCORE_WEIGHT_GESTURE: float = 0.20
    SCORE_WEIGHT_EYE_CONTACT: float = 0.04
    SCORE_WEIGHT_SCENE: float = 0.06
    SCORE_WEIGHT_AUDIO: float = 0.03
    SCORE_WEIGHT_CONTEXT: float = 0.02
    SCORE_WEIGHT_ENDING: float = 0.02
    SCORE_WEIGHT_VIRAL_POTENTIAL: float = 0.01  # total = 1.00

    # Training data settings
    MAX_AUTO_NEGATIVES_PER_JOB: int = 5
    LIKED_CLIP_DEFAULT_SCORE: float = 8.0

    # Model scoring toggle — set False di .env untuk paksa pakai weighted-sum lama
    USE_TRAINED_SCORE_MODEL: bool = True

    # Blend score saat model terlatih tersedia (untuk kategori yang SUDAH dilatih).
    # Default: training dominan (0.8) atas bobot analyzer (0.2) — bisa diubah user
    # lewat menu Settings → "Trained category weight" (disimpan ke data/score_blend.json).
    # Kedua nilai ini hanya dipakai JIKA model kategori tsb tersedia; kategori tanpa
    # model tetap murni weighted-sum (fallback weight tidak dipakai).
    SCORE_TRAINED_WEIGHT: float = 0.8
    SCORE_FALLBACK_WEIGHT: float = 0.2

    # Candidate minimum final score (0-10). Candidates di bawah ini ditolak
    # oleh select_top_n — mencegah "sampah" lolos murni karena relatif tertinggi.
    MIN_CANDIDATE_SCORE: float = 4.0

    # Single-pass visual analyzer toggle
    # True  = pakai VideoVisionPass (1 VideoCapture per window, ~3-4x lebih cepat)
    # False = pakai jalur lama (4 VideoCapture+seek per window) — untuk A/B comparison
    USE_VIDEO_VISION_PASS: bool = True

    # Proxy video untuk analisis visual (hanya resolusi diturunkan, fps TETAP)
    # True  = generate + pakai proxy 480p sebelum VideoVisionPass
    # False = pakai video asli (lebih lambat tapi akurasi maksimal)
    # Default False sampai A/B membuktikan 480p tidak menggeser skor/ranking.
    # Prioritas: QUALITY > CORRECTNESS > RELIABILITY > PERFORMANCE.
    USE_VISION_PROXY: bool = False
    # Tinggi proxy (px). FPS tidak diturunkan. Ganti via .env kalau drift skor terlalu besar.
    VISION_PROXY_HEIGHT: int = 480

    # TikTok Content Posting API — kredensial app dari dashboard TikTok for Developers.
    # WAJIB lewat .env — nilai default sengaja kosong, jangan di-hardcode di source.
    TIKTOK_CLIENT_KEY: str = ""
    TIKTOK_CLIENT_SECRET: str = ""
    TIKTOK_REDIRECT_URI: str = "http://localhost:8000/tiktok/oauth/callback"
    TIKTOK_TOKEN_ENCRYPTION_KEY: str = ""  # generate sekali, simpan di .env (lihat instruksi di bawah)
    TOKEN_ENCRYPTION_KEY: str = ""  # kunci enkripsi generik untuk OAuth tokens (Instagram, TikTok, dll)

    # Instagram API with Instagram Login
    IG_USER_ID: str = ""                  # ID akun Instagram Professional (angka)
    IG_ACCESS_TOKEN: str = ""             # token long-lived dari dashboard Meta (seed awal)
    IG_TOKEN_ISSUED_AT: str = ""          # opsional, "YYYY-MM-DD" atau ISO datetime (UTC) kapan token di-generate
    IG_GRAPH_BASE_URL: str = "https://graph.instagram.com"
    IG_GRAPH_VERSION: str = ""            # kosong = tanpa prefix versi; isi mis. "v23.0" bila dokumentasi mensyaratkan
    IG_TOKEN_REFRESH_BEFORE_DAYS: int = 5
    IG_TOKEN_MIN_AGE_HOURS: int = 24
    IG_TOKEN_LIFETIME_DAYS: int = 60      # dipakai hanya untuk estimasi expires_at saat seed
    IG_MIN_REEL_SECONDS: float = 3.0
    IG_MAX_REEL_SECONDS: float = 90.0      # batas Reels via API
    IG_MAX_FILE_MB: int = 0                # 0 = jangan blokir; isi bila dokumentasi resmi menyebut batas
    IG_CAPTION_MAX_CHARS: int = 2200
    IG_CAPTION_MAX_HASHTAGS: int = 30
    IG_PROCESS_POLL_SECONDS: float = 3.0
    IG_PROCESS_TIMEOUT_SECONDS: int = 420

    # Instagram 9:16 Video Prep (Auto Reframe)
    IG_FIT_MODE: str = "pad"      # "pad" (bilah hitam) | "blur" (latar blur) | "off" (kirim apa adanya)
    IG_TARGET_WIDTH: int = 1080
    IG_TARGET_HEIGHT: int = 1920
    IG_FIT_CRF: int = 20
    IG_FIT_PRESET: str = "veryfast"
    IG_FIT_TIMEOUT_SECONDS: int = 900

    @field_validator("IG_FIT_MODE", mode="after")
    @classmethod
    def validate_ig_fit_mode(cls, v: str) -> str:
        if v not in ("pad", "blur", "off"):
            logging.getLogger(__name__).warning("Nilai IG_FIT_MODE '%s' tidak valid, fallback ke 'pad'", v)
            return "pad"
        return v

    # Auto Hook Engine — cold-open reorder + zoom-punch + LLM caption.
    # Memerlukan LLM_API_KEY dikonfigurasi; kalau kosong → hook di-skip otomatis.
    # Set USE_AUTO_HOOK=false di .env untuk matikan seluruh fitur.
    USE_AUTO_HOOK: bool = True
    AUTO_HOOK_MIN_CONFIDENCE: float = 0.6   # threshold confidence LLM (0.0–1.0)
    AUTO_HOOK_MIN_WINDOW_SECONDS: float = 20.0  # durasi window minimum agar hook dicoba

    # Hook Caption Font & Styling (TikTok-style bold text, thick outline, keyword highlight, pop-in)
    HOOK_FONT_STYLE: str = "auto"  # auto | impact | fun | clean
    HOOK_FONT_SIZE: int = 120
    HOOK_FONT_MIN_SIZE: int = 84
    HOOK_TEXT_OUTLINE: int = 9
    HOOK_HIGHLIGHT_COLOR: str = "#FFE600"
    HOOK_POP_ANIMATION: bool = True
    AUTO_HOOK_FONTS_DIR: str = "data/assets/fonts"

    # Fitur 4: Emotion Punch-Zoom & Audio Spike Settings
    AUTO_HOOK_PUNCH_ZOOM_SCALE: float = 1.25  # 1.25x punch-zoom di awal teaser hook
    AUTO_HOOK_ZOOM_TARGET: str = "facecam"    # "facecam" (streamer face) | "full" (seluruh frame)
    AUTO_HOOK_ENABLE_AUDIO_SPIKE: bool = True # Aktifkan deteksi lonjakan audio/teriakan


@lru_cache
def get_settings() -> Settings:
    """Return a cached, single instance of Settings."""
    return Settings()


settings = get_settings()
