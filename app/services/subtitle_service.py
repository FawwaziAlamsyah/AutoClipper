import logging
from pathlib import Path
import re
import subprocess
from datetime import timedelta

from sqlalchemy.orm import Session

from app.repositories.clip_repository import ClipRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.services.caption_style_service import (
    FONT_STYLES,
    PRIORITY_REACTION_KEYWORDS,
    format_ass_time,
    rgb_to_ass_color,
)
from app.services.job_service import JobService

logger = logging.getLogger(__name__)

MAX_CAPTION_CHARS = 42

KINETIC_EMOTION_KEYWORDS = set(PRIORITY_REACTION_KEYWORDS) | {
    "gila", "waduh", "anjir", "anjay", "kocak", "woi", "astaga",
    "buset", "parah", "hoki", "sumpah", "hah", "lol", "gg",
    "mantap", "mati", "kena", "aduh", "ampun", "yah", "yahh", "sial"
}

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
        burn: bool = True,
        font_style: str = "impact",
        position: str = "center_low",
    ) -> dict:
        """Generate SRT/VTT/ASS subtitle + (default) burn ke video clip.

        Returns: {format, language, style, content, file_path, lines, burned}
        """
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise ValueError(f"Clip {clip_id} not found")

        # job_id ada di candidate, bukan di clip langsung
        if clip.candidate_id is None:
            raise ValueError(f"Clip {clip_id} tidak punya candidate terkait")

        from app.repositories.candidate_repository import CandidateRepository
        candidate = CandidateRepository(self.db).get(clip.candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {clip.candidate_id} not found")

        job_id = candidate.job_id

        transcript = self.transcript_repo.get_by_job(job_id)
        if transcript is None:
            raise ValueError(f"Transcript for job {job_id} not found")

        style = style if style in STYLE_FORMATTERS or style in ("kinetic", "capcut") else "minimal"
        formatter = STYLE_FORMATTERS.get(style, lambda t: t)

        # Coba transkripsi langsung audio klip untuk akurasi kata 100% dan timing presisi
        cues = None
        if style in ("tiktok", "kinetic", "capcut"):
            cues = self._transcribe_clip_audio(clip, language)

        if not cues:
            # Fallback ke segmen transkrip DB: gunakan window irisan agar kalimat pembuka/penutup klip tidak terpotong
            segments = [
                s for s in transcript.segments
                if s.end_time > clip.start_time and s.start_time < clip.end_time
            ]
            # Pastikan segmen selalu terurut secara kronologis
            segments.sort(key=lambda s: s.start_time)

            if style in ("tiktok", "kinetic", "capcut"):
                cues = self._build_kinetic_cues(segments)
            else:
                cues = self._build_word_cues(segments)
                cues = [c for c in cues if c["text"].strip()]
                for cue in cues:
                    cue["text"] = formatter(cue["text"])

        # Anti-overlap clamp: setiap cue dijamin berakhir sebelum cue berikutnya mulai (tidak akan pernah saling tumpuk)
        for i in range(len(cues) - 1):
            if cues[i]["end"] > cues[i + 1]["start"]:
                cues[i]["end"] = max(cues[i]["start"] + 0.1, cues[i + 1]["start"] - 0.02)

        # Burn subtitle langsung ke video clip (hardcode) — kalau user mau.
        # Hasil ikut edit chain (edited_file_path); reset akan membuangnya.
        if burn and cues:
            from app.services.clip_editor_service import ClipEditorService
            ClipEditorService(self.db).burn_subtitle(
                clip_id,
                cues,
                style=style,
                font_style=font_style,
                position=position,
            )

        # Hitung dimensi default sesuai aspect ratio klip
        clip_aspect = getattr(clip, "aspect_ratio", "9:16")
        if not isinstance(clip_aspect, str):
            clip_aspect = "9:16"
        width, height = (1080, 1920) if clip_aspect == "9:16" else (1920, 1080)
        pos_y = int(height * 0.67) if position == "center_low" else int(height * 0.50)

        content = self._render(
            cues,
            format,
            language,
            font_style=font_style,
            width=width,
            height=height,
            position_y=pos_y,
        )
        lines = len(cues)

        output_path = f"data/outputs/clip_{clip.id}_sub_{style}.{format}"

        # Step opsional "subtitle" — catat job_steps TANPA ubah status job
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
            "burned": bool(burn and cues),
        }

    def _build_kinetic_cues(self, segments: list) -> list[dict]:
        """Bagi segmen menjadi potongan 1–3 kata (gaya CapCut/TikTok) dengan timing proporsional."""
        cues: list[dict] = []
        for seg in segments:
            words = [w.strip() for w in seg.text.split() if w.strip()]
            if not words:
                continue

            raw_dur = seg.end_time - seg.start_time
            duration = max(raw_dur, 0.1)

            # Filter noise transkripsi: 1 kata di durasi < 0.25 detik (misal napas/desah atau audio glitch)
            if len(words) == 1 and raw_dur < 0.25:
                continue

            total_chars = sum(max(len(w), 1) for w in words)

            word_timings = []
            curr_t = seg.start_time
            # Batasi durasi efektif per kata agar jeda diam panjang tidak membuat kata menggantung lama
            avg_word_dur = duration / len(words)
            dur_scale = min(1.0, 1.2 / avg_word_dur) if avg_word_dur > 1.2 else 1.0
            effective_duration = duration * dur_scale

            for w in words:
                w_dur = max(effective_duration * (max(len(w), 1) / total_chars), 0.15)
                word_timings.append((curr_t, curr_t + w_dur))
                curr_t += w_dur

            chunk_words: list[str] = []
            chunk_start = word_timings[0][0]
            chunk_end = word_timings[0][1]

            for i, (w, (w_start, w_end)) in enumerate(zip(words, word_timings)):
                chunk_words.append(w)
                chunk_end = w_end

                chunk_len = sum(len(cw) for cw in chunk_words) + len(chunk_words) - 1
                is_last = (i == len(words) - 1)
                should_break = (
                    len(chunk_words) >= 3
                    or (len(chunk_words) >= 2 and chunk_len >= 9)
                    or (chunk_len >= 16)
                    or is_last
                )

                if should_break:
                    cue_text = " ".join(chunk_words).upper()
                    clean_tokens = [re.sub(r"[^\w]", "", cw).lower() for cw in chunk_words]
                    highlight_word = None
                    for cw, clean_t in zip(chunk_words, clean_tokens):
                        if clean_t in KINETIC_EMOTION_KEYWORDS:
                            highlight_word = cw.upper()
                            break
                    if not highlight_word:
                        highlight_word = max(chunk_words, key=len).upper()

                    cues.append({
                        "start": chunk_start,
                        "end": chunk_end,
                        "text": cue_text,
                        "words": [cw.upper() for cw in chunk_words],
                        "highlight_word": highlight_word,
                    })

                    chunk_words = []
                    if not is_last and i + 1 < len(word_timings):
                        chunk_start = word_timings[i + 1][0]

        return cues

    def _transcribe_clip_audio(self, clip, language: str | None = None) -> list[dict] | None:
        """Transkrip langsung dari file video klip untuk akurasi kata 100% dan timing presisi."""
        source_path = getattr(clip, "edited_file_path", None) or getattr(clip, "file_path", None)
        if not source_path:
            return None
        src_file = Path(source_path)
        if not src_file.exists():
            return None

        from app.core.config.settings import settings
        cache_dir = settings.DATA_DIR / "outputs" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        wav_path = cache_dir / f"clip_{clip.id}_audio.wav"

        # Ekstrak audio 16kHz mono via ffmpeg jika belum ada di cache
        if not wav_path.exists():
            cmd = [
                "ffmpeg", "-y",
                "-i", str(src_file),
                "-vn", "-ac", "1", "-ar", "16000",
                str(wav_path),
            ]
            try:
                subprocess.run(cmd, capture_output=True, check=True)
            except Exception as e:
                logger.debug("Gagal ekstrak audio klip %d: %s", getattr(clip, "id", 0), e)
                return None

        try:
            from app.ai_modules.speech_to_text.whisper_analyzer import WhisperAnalyzer
            analyzer = WhisperAnalyzer()
            res = analyzer.analyze({"audio_path": str(wav_path), "language": language or "id"})
            segments = res.result_data.get("segments", [])
            if not segments:
                return None

            all_words = []
            for s in segments:
                for w in s.get("words", []):
                    word_text = w.get("word", "").strip()
                    if word_text:
                        all_words.append({
                            "word": word_text,
                            "start": float(w.get("start", 0.0)),
                            "end": float(w.get("end", 0.0)),
                        })
            if not all_words:
                return None

            return self._build_kinetic_cues_from_words(all_words)
        except Exception as e:
            logger.warning("Direct clip audio transcribe gagal untuk clip %d, fallback ke DB: %s", getattr(clip, "id", 0), e)
            return None

    def _build_kinetic_cues_from_words(self, all_words: list[dict]) -> list[dict]:
        """Group word-level timestamps directly into 1-3 word kinetic cues with zero overlap."""
        chunks: list[dict] = []
        curr_chunk: list[dict] = []

        for i, w in enumerate(all_words):
            curr_chunk.append(w)
            chunk_len = sum(len(cw["word"]) for cw in curr_chunk) + len(curr_chunk) - 1
            is_last = (i == len(all_words) - 1)
            has_punct = w["word"].endswith((".", "?", "!", "...", "…"))

            should_break = (
                has_punct
                or len(curr_chunk) >= 3
                or (len(curr_chunk) >= 2 and chunk_len >= 8)
                or is_last
            )

            # Jika kata terakhir di stream hanya 1 kata kecil (<= 3 huruf),
            # gabungkan ke chunk sebelumnya agar tidak berkedip sendirian
            if is_last and len(curr_chunk) == 1 and len(curr_chunk[0]["word"]) <= 3 and chunks:
                prev = chunks[-1]
                prev["text"] = f"{prev['text']} {curr_chunk[0]['word'].upper()}"
                prev["words"].append(curr_chunk[0]["word"].upper())
                prev["end"] = curr_chunk[0]["end"]
                break

            if should_break:
                chunk_start = curr_chunk[0]["start"]
                chunk_end = curr_chunk[-1]["end"]
                chunk_words = [cw["word"] for cw in curr_chunk]
                cue_text = " ".join(chunk_words).upper()

                clean_tokens = [re.sub(r"[^\w]", "", cw).lower() for cw in chunk_words]
                highlight_word = None
                for cw, clean_t in zip(chunk_words, clean_tokens):
                    if clean_t in KINETIC_EMOTION_KEYWORDS:
                        highlight_word = cw.upper()
                        break
                if not highlight_word:
                    highlight_word = max(chunk_words, key=len).upper()

                chunks.append({
                    "start": chunk_start,
                    "end": chunk_end,
                    "text": cue_text,
                    "words": [cw.upper() for cw in chunk_words],
                    "highlight_word": highlight_word,
                })
                curr_chunk = []

        # Anti-overlap clamp: setiap cue dijamin berakhir sebelum cue berikutnya mulai
        for i in range(len(chunks) - 1):
            if chunks[i]["end"] > chunks[i + 1]["start"]:
                chunks[i]["end"] = max(chunks[i]["start"] + 0.1, chunks[i + 1]["start"] - 0.02)

        return chunks


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

    def _render(
        self,
        cues: list[dict],
        format: str,
        language: str,
        font_style: str = "impact",
        width: int = 1080,
        height: int = 1920,
        position_y: int = 1280,
    ) -> str:
        """Render cues into ASS, SRT, or VTT."""
        if format == "ass":
            return self._render_ass(
                cues,
                width=width,
                height=height,
                font_style=font_style,
                position_y=position_y,
            )
        elif format == "vtt":
            return self._render_vtt(cues, language)
        return self._render_srt(cues)

    def _render_ass(
        self,
        cues: list[dict],
        width: int = 1080,
        height: int = 1920,
        font_style: str = "impact",
        highlight_color: str = "#FFE600",
        position_y: int = 1280,
    ) -> str:
        """Render cues ke format file script ASS dengan gaya TikTok kinetic."""
        family_name = FONT_STYLES.get(font_style, {}).get("family", "Anton")
        highlight_bgr = rgb_to_ass_color(highlight_color)
        pos_x = width // 2
        font_size = 76 if height >= 1920 else (64 if height >= 1080 else 46)

        dialogues = []
        for cue in cues:
            start_ts = format_ass_time(max(0.0, cue["start"]))
            end_ts = format_ass_time(max(cue["start"] + 0.05, cue["end"]))

            words = cue.get("words", cue["text"].split())
            hl_word = cue.get("highlight_word", "")
            hl_applied = False
            formatted_words = []
            for w in words:
                clean_w = re.sub(r"[^\w]", "", w).upper()
                clean_hl = re.sub(r"[^\w]", "", hl_word).upper() if hl_word else ""
                if not hl_applied and clean_w and clean_w == clean_hl:
                    formatted_words.append(f"{{\\c{highlight_bgr}}}{w}{{\\c&HFFFFFF&}}")
                    hl_applied = True
                else:
                    formatted_words.append(w)

            if not hl_applied and formatted_words:
                formatted_words[0] = f"{{\\c{highlight_bgr}}}{formatted_words[0]}{{\\c&HFFFFFF&}}"

            body_text = " ".join(formatted_words)
            pop_tag = "\\fscx106\\fscy106\\t(0,70,\\fscx100\\fscy100)"
            dialogues.append(
                f"Dialogue: 0,{start_ts},{end_ts},TikTokKinetic,,0,0,0,,"
                f"{{\\pos({pos_x},{position_y}){pop_tag}}}{body_text}"
            )

        events_str = "\n".join(dialogues)
        return (
            "[Script Info]\n"
            "; Script generated by Daboji SubtitleService\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {width}\n"
            f"PlayResY: {height}\n"
            "WrapStyle: 2\n"
            "ScaledBorderAndShadow: yes\n"
            "\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: TikTokKinetic,{family_name},{font_size},&H00FFFFFF&,&H0000FFFF&,&H00000000&,&H80000000&,1,0,0,0,100,100,1,0,1,8,2,2,60,60,120,1\n"
            "\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"{events_str}\n"
        )

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
