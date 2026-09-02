"""Application configuration.

Semua nilai konfigurasi HARUS diambil dari sini. Tidak boleh ada
hardcode path/parameter di module lain.
"""

from functools import lru_cache
from pathlib import Path

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
    APP_DEFAULT_THEME: str = "light"  # light | dark

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

    # Clip defaults
    DEFAULT_MIN_CLIP_DURATION: int = 30
    DEFAULT_MAX_CLIP_DURATION: int = 60
    DEFAULT_NUM_CLIPS: int = 5

    # FFmpeg
    FFMPEG_PATH: str = "ffmpeg"
    FFPROBE_PATH: str = "ffprobe"

    # Whisper
    WHISPER_MODEL: str = "large-v3"
    WHISPER_DEVICE: str = "auto"

    # LLM
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"

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


@lru_cache
def get_settings() -> Settings:
    """Return a cached, single instance of Settings."""
    return Settings()


settings = get_settings()
