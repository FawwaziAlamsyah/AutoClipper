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

    # Paths (relatif terhadap root project)
    BASE_DIR: Path = Path(__file__).resolve().parents[3]
    DATA_DIR: Path = BASE_DIR / "data"
    LOG_DIR: Path = BASE_DIR / "logs"
    UPLOAD_DIR: Path = DATA_DIR / "uploads"
    OUTPUT_DIR: Path = DATA_DIR / "outputs"
    CACHE_DIR: Path = DATA_DIR / "cache"
    TEMP_DIR: Path = DATA_DIR / "temp"

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

    # Cookies file untuk yt-dlp (hindari 403 anti-bot YouTube).
    # Kosong = pakai cookiesfrombrowser fallback. Isi path cookies.txt untuk
    # export manual (Get cookies.txt LOCALLY extension).
    COOKIES_FILE: str = ""

    # Whisper
    WHISPER_MODEL: str = "large-v3"
    WHISPER_DEVICE: str = "auto"

    # LLM
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"

    # Score weights (default, user-overridable per job)
    # Semua analyzer sudah diimplementasi asli di app/ai_modules/ — total bobot 100%.
    SCORE_WEIGHT_LLM_CONTENT: float = 0.30
    SCORE_WEIGHT_HOOK: float = 0.10
    SCORE_WEIGHT_STORY: float = 0.15
    SCORE_WEIGHT_VOICE_EMOTION: float = 0.10
    SCORE_WEIGHT_FACE_EMOTION: float = 0.08
    SCORE_WEIGHT_GESTURE: float = 0.05
    SCORE_WEIGHT_EYE_CONTACT: float = 0.03
    SCORE_WEIGHT_SCENE: float = 0.04
    SCORE_WEIGHT_AUDIO: float = 0.05
    SCORE_WEIGHT_CONTEXT: float = 0.05
    SCORE_WEIGHT_ENDING: float = 0.05


@lru_cache
def get_settings() -> Settings:
    """Return a cached, single instance of Settings."""
    return Settings()


settings = get_settings()
