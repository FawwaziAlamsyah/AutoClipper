"""Subtitle generation service (SRT/VTT) with word-level cues and styles.

Word-level timestamps dihitung dari durasi segmen dibagi rata per kata
(karena whisper word timestamps tidak dipersist ke DB — enhancement nanti
bisa simpan kata+timestamp bila mau presisi penuh).
"""

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.repositories.clip_repository import ClipRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.services.job_service import JobService

logger = logging.getLogger(__name__)

MAX_CAPTION_CHARS = 42

STYLE_FORMATTERS = {
    "minimal": lambda text: text,
    "tiktok": lambda text: text.upper(),
    "youtube": lambda text: text.capitalize(),
}


class SubtitleService:
    """Generate subtitle files from transcript for clips."""

    def __init__(self, db: Session) -> None:
        """Initialize repositories."""
        self.db = db
        self.clip_repo = ClipRepository(db)
        self.transcript_repo = TranscriptRepository(db)
        self.job_service = JobService(db)

    def generate_subtitle(
        self,
        clip_id: int,
        format: str = "srt",
        language: str = "id",
        style: str = "minimal",
    ) -> dict:
        """Generate SRT or VTT subtitle for a clip.

        Returns: {format, language, style, content, file_path, lines}
        """
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise ValueError(f"Clip {clip_id} not found")

        transcript = self.transcript_repo.get_by_job(clip.job_id)
        if transcript is None:
            raise ValueError(f"Transcript for job {clip.job_id} not found")

        style = style if style in STYLE_FORMATTERS else "minimal"
        formatter = STYLE_FORMATTERS[style]

        segments = [
            s for s in transcript.segments
            if s.start_time >= clip.start_time and s.end_time <= clip.end_time
        ]

        cues = self._build_word_cues(segments)
        cues = [c for c in cues if c["text"].strip()]
        for cue in cues:
            cue["text"] = formatter(cue["text"])

        content = self._render(cues, format, language)
        lines = len(cues)

        output_path = f"data/outputs/clip_{clip.id}_sub_{style}.{format}"

        # Step opsional "subtitle" — catat job_steps TANPA ubah status job
        job_id = clip.job_id
        logger.debug("Subtitle process: generate %s (%s) untuk clip %d", format, style, clip_id)
        self.job_service.start_optional_step(job_id, "subtitle")
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            self.job_service.finish_optional_step(job_id, "subtitle", success=False, error="Gagal menulis file subtitle")
            logger.debug("Subtitle process: error menulis file")
            raise
        self.job_service.finish_optional_step(job_id, "subtitle", success=True)
        logger.debug("Subtitle process: success (%d cues)", lines)

        return {
            "format": format,
            "language": language,
            "style": style,
            "content": content,
            "file_path": output_path,
            "lines": lines,
        }

    def _build_word_cues(self, segments: list) -> list[dict]:
        """Group words into caption lines with word-level timestamps."""
        cues: list[dict] = []
        for seg in segments:
            words = seg.text.split()
            if not words:
                continue
            duration = max(seg.end_time - seg.start_time, 0.1)
            per_word = duration / len(words)

            buf: list[str] = []
            buf_start = seg.start_time
            for i, word in enumerate(words):
                buf.append(word)
                if sum(len(w) for w in buf) + len(buf) - 1 >= MAX_CAPTION_CHARS or i == len(words) - 1:
                    cue_text = " ".join(buf)
                    cues.append({
                        "start": buf_start,
                        "end": buf_start + len(buf) * per_word,
                        "text": cue_text,
                    })
                    buf_start += len(buf) * per_word
                    buf = []
        return cues

    def _render(self, cues: list[dict], format: str, language: str) -> str:
        """Render cues into SRT or VTT."""
        if format == "vtt":
            return self._render_vtt(cues, language)
        return self._render_srt(cues)

    def _render_srt(self, cues: list[dict]) -> str:
        """Build SRT content."""
        lines = []
        for i, cue in enumerate(cues, 1):
            start = self._format_srt(cue["start"])
            end = self._format_srt(cue["end"])
            lines.extend([str(i), f"{start} --> {end}", cue["text"], ""])
        return "\n".join(lines)

    def _render_vtt(self, cues: list[dict], language: str) -> str:
        """Build VTT content."""
        lines = ["WEBVTT", f"Language: {language}", ""]
        for cue in cues:
            start = self._format_vtt(cue["start"])
            end = self._format_vtt(cue["end"])
            lines.extend([f"{start} --> {end}", cue["text"], ""])
        return "\n".join(lines)

    def _format_srt(self, seconds: float) -> str:
        """Format seconds to SRT timestamp (00:00:00,000)."""
        delta = timedelta(seconds=seconds)
        hours, rem = divmod(delta.total_seconds(), 3600)
        minutes, secs = divmod(rem, 60)
        return f"{int(hours):02d}:{int(minutes):02d}:{int(secs):02d},{int(delta.microseconds / 1000):03d}"

    def _format_vtt(self, seconds: float) -> str:
        """Format seconds to VTT timestamp (00:00:00.000)."""
        return self._format_srt(seconds).replace(",", ".")
