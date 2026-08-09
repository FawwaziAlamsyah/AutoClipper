"""Tests for TranscriptService orchestration."""

from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.ai_modules.base.analyzer_interface import AnalysisResult
from app.models.video_model import VideoModel
from app.services.transcript_service import TranscriptService


def _seed_video(db: Session) -> VideoModel:
    video = VideoModel(
        original_filename="sample.mp4",
        source_type="upload",
        file_path="C:/fake/sample.mp4",
        status="uploaded",
        file_size_bytes=1000,
        created_at=datetime.now(UTC),
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


def test_transcribe_orchestrates_ffmpeg_and_whisper(db_session: Session) -> None:
    """TranscriptService should extract, transcribe, and persist segments."""
    video = _seed_video(db_session)

    mock_ffmpeg = MagicMock()
    mock_ffmpeg.extract_metadata.return_value = {
        "duration_seconds": 10.0,
        "width": 1280,
        "height": 720,
        "fps": 30.0,
    }
    mock_ffmpeg.extract_audio.return_value = "C:/fake/audio.wav"

    mock_whisper = MagicMock()
    mock_whisper.analyze.return_value = AnalysisResult(
        score=5.0,
        result_data={
            "language": "id",
            "full_text": "Halo dunia",
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.5,
                    "text": " Halo dunia",
                    "words": [{"word": "Halo", "probability": 0.9}],
                }
            ],
        },
    )

    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.mkdir"):
        service = TranscriptService(db_session, ffmpeg=mock_ffmpeg, whisper=mock_whisper)
        # Force audio path to "exist" after extract
        with patch.object(service, "_audio_path_for") as mock_path:
            audio = MagicMock()
            audio.exists.return_value = True
            audio.__str__ = lambda self: "C:/fake/audio.wav"
            mock_path.return_value = audio

            transcript = service.transcribe(video.id, force=True)

    assert transcript.id is not None
    assert transcript.language == "id"
    assert transcript.full_text == "Halo dunia"
    assert transcript.video_id == video.id

    segs = service.segment_repo.get_by_transcript(transcript.id)
    assert len(segs) == 1
    assert segs[0].text == "Halo dunia"
    mock_ffmpeg.extract_metadata.assert_called_once()
    mock_whisper.analyze.assert_called_once()


def test_transcribe_reuses_existing(db_session: Session) -> None:
    """Without force, existing transcript is returned and whisper not called."""
    video = _seed_video(db_session)

    mock_ffmpeg = MagicMock()
    mock_ffmpeg.extract_metadata.return_value = {
        "duration_seconds": 5.0,
        "width": 640,
        "height": 360,
        "fps": 24.0,
    }
    mock_ffmpeg.extract_audio.return_value = "C:/fake/audio.wav"
    mock_whisper = MagicMock()
    mock_whisper.analyze.return_value = AnalysisResult(
        score=5.0,
        result_data={
            "language": "en",
            "full_text": "first",
            "segments": [{"start": 0.0, "end": 1.0, "text": "first", "words": []}],
        },
    )

    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.mkdir"):
        service = TranscriptService(db_session, ffmpeg=mock_ffmpeg, whisper=mock_whisper)
        with patch.object(service, "_audio_path_for") as mock_path:
            audio = MagicMock()
            audio.exists.return_value = True
            audio.__str__ = lambda self: "C:/fake/audio.wav"
            mock_path.return_value = audio
            first = service.transcribe(video.id, force=True)
            second = service.transcribe(video.id, force=False)

    assert first.id == second.id
    assert mock_whisper.analyze.call_count == 1
