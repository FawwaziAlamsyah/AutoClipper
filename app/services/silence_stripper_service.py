"""Silence Stripper Service — Potong jeda hening / dead-air agar klip padat aksi.

Mendeteksi jeda diam (speech silence / acoustic silence) di dalam video klip,
memotong bagian dead-air, dan menyambungkan kembali bagian aktif secara mulus
sehingga klip mencapai Sweet Spot viral TikTok (18–35 detik) dengan retensi tinggi.
"""

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import NotFoundException, ValidationException
from app.repositories.clip_repository import ClipRepository
from app.services.ffmpeg_service import FFmpegService

logger = logging.getLogger(__name__)


class SilenceStripperService:
    """Deteksi dan pemotongan jeda hening (dead-air) pada klip video."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.clip_repo = ClipRepository(db)
        self.ffmpeg = FFmpegService()

    def _history_manager(self, clip_id: int):
        from app.services.clip_history_manager import ClipHistoryManager
        return ClipHistoryManager(clip_id)

    def _current_source(self, clip) -> Path:
        try:
            return self._history_manager(clip.id).get_current_source(clip)
        except Exception:
            path = Path(clip.edited_file_path) if clip.edited_file_path else Path(clip.file_path)
            if not path.exists():
                raise ValidationException(f"File clip tidak ditemukan di disk: {path}")
            return path

    def _temp_output_path(self, clip_id: int, action: str) -> Path:
        settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        return settings.TEMP_DIR / f"edit_{clip_id}_{action}_{ts}.mp4"

    def detect_active_intervals(
        self,
        video_path: str,
        min_silence_duration: float = 1.2,
        padding: float = 0.25,
    ) -> dict:
        """Deteksi interval aktif (bicara/reaksi) dan temukan jeda hening > min_silence_duration.

        Args:
            video_path: Path video input
            min_silence_duration: Ambang minimal durasi hening (detik) untuk dipotong
            padding: Buffer keamanan (detik) sebelum dan sesudah bicara agar tidak terpotong kasar

        Returns:
            dict berisi:
            - active_intervals: list[(start, end)] bagian yang harus dipertahankan
            - total_duration: durasi asli
            - new_duration: durasi hasil pemotongan
            - removed_duration: total detik hening yang dipangkas
            - gaps_count: jumlah titik jeda hening
        """
        src = Path(video_path)
        if not src.exists():
            raise ValidationException(f"Video file tidak ditemukan: {video_path}")

        meta = self.ffmpeg.extract_metadata(str(src))
        total_dur = float(meta.get("duration_seconds") or 0.0)
        if total_dur <= 0.0:
            raise ValidationException("Durasi video tidak valid atau 0 detik.")

        # Ekstrak audio sementara untuk analisa cepat
        cache_dir = settings.DATA_DIR / "outputs" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        wav_path = cache_dir / f"silence_check_{src.stem}.wav"

        if not wav_path.exists():
            cmd = [
                self.ffmpeg.ffmpeg_path, "-y",
                "-i", str(src),
                "-vn", "-ac", "1", "-ar", "16000",
                str(wav_path),
            ]
            try:
                subprocess.run(cmd, capture_output=True, check=True)
            except Exception as e:
                logger.warning("Gagal ekstrak audio untuk silence check: %s", e)
                return {
                    "active_intervals": [(0.0, total_dur)],
                    "total_duration": total_dur,
                    "new_duration": total_dur,
                    "removed_duration": 0.0,
                    "gaps_count": 0,
                }

        speech_intervals: list[tuple[float, float]] = []

        # Metode 1 (Utama): Speech-to-Text Voice Activity via Whisper
        try:
            from app.ai_modules.speech_to_text.whisper_analyzer import WhisperAnalyzer
            analyzer = WhisperAnalyzer()
            res = analyzer.analyze({"audio_path": str(wav_path), "language": "id"})
            segments = res.result_data.get("segments", [])
            for s in segments:
                st = max(0.0, float(s.get("start", 0.0)))
                et = min(total_dur, float(s.get("end", 0.0)))
                if et > st:
                    speech_intervals.append((st, et))
        except Exception as e:
            logger.debug("Whisper VAD deteksi hening skip (%s), coba fallback audio level", e)

        # Jalankan FFmpeg silencedetect untuk verifikasi apakah ada jeda hening akustik nyata (< -30dB)
        silence_starts: list[float] = []
        silence_ends: list[float] = []
        try:
            sd_cmd = [
                self.ffmpeg.ffmpeg_path, "-i", str(wav_path),
                "-af", f"silencedetect=noise=-30dB:d={min_silence_duration}",
                "-f", "null", "-",
            ]
            proc = subprocess.run(sd_cmd, capture_output=True, text=True, errors="replace")
            for line in proc.stderr.splitlines():
                if "silence_start:" in line:
                    m = re.search(r"silence_start:\s*([\d\.]+)", line)
                    if m:
                        silence_starts.append(float(m.group(1)))
                elif "silence_end:" in line:
                    m = re.search(r"silence_end:\s*([\d\.]+)", line)
                    if m:
                        silence_ends.append(float(m.group(1)))
        except Exception as e:
            logger.warning("FFmpeg silencedetect error: %s", e)

        raw_active: list[tuple[float, float]] = []

        if silence_starts:
            # Gunakan acoustic silence nyata sebagai basis pemotongan:
            # Pertahankan semua bagian video yang memiliki suara aktif (gameplay, BGM, efek suara).
            curr_pos = 0.0
            for s_st, s_et in zip(silence_starts, silence_ends):
                act_end = min(total_dur, s_st + padding)
                if act_end > curr_pos + 0.2:
                    raw_active.append((curr_pos, act_end))
                curr_pos = max(0.0, s_et - padding)
            if curr_pos < total_dur - 0.2:
                raw_active.append((curr_pos, total_dur))

            # Lindungi juga segmen bicara Whisper (union) agar ucapan tidak terpotong
            for st, et in speech_intervals:
                raw_active.append((max(0.0, st - padding), min(total_dur, et + padding)))
        elif speech_intervals:
            # Fallback jika silencedetect tidak menghasilkan data (misal di mock unit test)
            for st, et in speech_intervals:
                p_st = max(0.0, st - padding)
                p_et = min(total_dur, et + padding)
                raw_active.append((p_st, p_et))

        if not raw_active:
            return {
                "active_intervals": [(0.0, total_dur)],
                "total_duration": total_dur,
                "new_duration": total_dur,
                "removed_duration": 0.0,
                "gaps_count": 0,
            }

        # Gabungkan dan cari gap yang > min_silence_duration
        raw_active.sort(key=lambda x: x[0])

        # Merge overlapping / touching intervals
        merged: list[list[float]] = []
        for interval in raw_active:
            if not merged:
                merged.append(list(interval))
            else:
                prev = merged[-1]
                # Jika interval bertumpuk atau jeda antar interval < min_silence_duration, leburkan
                if interval[0] <= prev[1] + min_silence_duration:
                    prev[1] = max(prev[1], interval[1])
                else:
                    merged.append(list(interval))

        active_intervals = [(round(st, 2), round(et, 2)) for st, et in merged]
        new_dur = sum(et - st for st, et in active_intervals)
        removed_dur = max(0.0, total_dur - new_dur)
        gaps_count = max(0, len(active_intervals) - 1)

        return {
            "active_intervals": active_intervals,
            "total_duration": round(total_dur, 2),
            "new_duration": round(new_dur, 2),
            "removed_duration": round(removed_dur, 2),
            "gaps_count": gaps_count,
        }

    def strip_silence(
        self,
        clip_id: int,
        min_silence_duration: float = 1.2,
        padding: float = 0.25,
    ):
        """Pangkas dead-air / jeda hening dari klip video dan catat ke riwayat edit."""
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise NotFoundException(f"Clip {clip_id} tidak ditemukan")

        source = self._current_source(clip)
        info = self.detect_active_intervals(
            str(source),
            min_silence_duration=min_silence_duration,
            padding=padding,
        )

        active_intervals = info["active_intervals"]
        removed = info["removed_duration"]

        if removed < 0.5 or len(active_intervals) <= 1:
            raise ValidationException(
                f"Tidak ditemukan jeda hening signifikan (> {min_silence_duration}s) pada klip ini. "
                "Video sudah padat dan siap pakai!"
            )

        temp_path = self._temp_output_path(clip_id, "silence")

        v_trims = []
        a_trims = []
        concat_inputs = []

        for idx, (st, et) in enumerate(active_intervals):
            v_trims.append(f"[0:v]trim=start={st:.2f}:end={et:.2f},setpts=PTS-STARTPTS[v{idx}]")
            a_trims.append(f"[0:a]atrim=start={st:.2f}:end={et:.2f},asetpts=PTS-STARTPTS[a{idx}]")
            concat_inputs.append(f"[v{idx}][a{idx}]")

        fc = ";".join(v_trims + a_trims) + ";" + "".join(concat_inputs) + f"concat=n={len(active_intervals)}:v=1:a=1[vout][aout]"

        cmd = [
            self.ffmpeg.ffmpeg_path, "-y",
            "-i", str(source),
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(temp_path),
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        except subprocess.SubprocessError as e:
            temp_path.unlink(missing_ok=True)
            logger.error("Gagal strip silence clip %d: %s", clip_id, e)
            raise ValidationException(f"Gagal memotong jeda hening: {str(e)}")

        new_dur = info["new_duration"]
        # push_step memindahkan temp_path ke step_filename permanen di data/outputs/edited/history/
        # dan menyinkronkan clip.edited_file_path secara benar ke file permanen.
        self._history_manager(clip_id).push_step(
            clip=clip,
            action="silence",
            label=f"Pangkas Hening (-{removed:.1f}s)",
            temp_file_path=temp_path,
            new_end_time=clip.start_time + new_dur,
        )
        clip.end_time = clip.start_time + new_dur
        self.db.commit()

        logger.info(
            "Silence Stripper clip %d: durasi %.1fs -> %.1fs (-%.1fs hening dipotong di %d titik)",
            clip_id, info["total_duration"], new_dur, removed, info["gaps_count"],
        )
        return clip
