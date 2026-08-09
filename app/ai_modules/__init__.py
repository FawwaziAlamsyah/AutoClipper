"""AI module plugins: speech-to-text, LLM, face, dan placeholder.

Semua analyzer didaftarkan ke registry saat modul di-import. Import package
ini mengaktifkan seluruh registry.
"""

from app.ai_modules import registry  # noqa: F401
from app.ai_modules.face_analysis import eye_contact_analyzer, face_emotion_analyzer  # noqa: F401
from app.ai_modules.gesture_analysis import gesture_analyzer  # noqa: F401
from app.ai_modules.llm_analysis import llm_analyzer  # noqa: F401
from app.ai_modules.scene_analysis import scene_change_analyzer  # noqa: F401
from app.ai_modules.speech_to_text import whisper_analyzer  # noqa: F401
from app.ai_modules.voice_analysis import audio_quality_analyzer, voice_emotion_analyzer  # noqa: F401
