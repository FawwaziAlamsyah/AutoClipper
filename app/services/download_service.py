"""Download service using yt-dlp."""

import logging
import uuid
from pathlib import Path
import yt_dlp

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.models.history_model import History
from app.models.video_model import Video
from app.repositories.video_repository import VideoRepository

logger = logging.getLogger(__name__)


class DownloadService:
    """Downloads videos from URLs using yt-dlp."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.repo = VideoRepository(db)
        self.db = db

    def download_video(self, url: str) -> Video:
        """Download video from URL using yt-dlp and register in DB."""
        if not url:
            raise ValidationException("URL tidak boleh kosong")

        upload_dir: Path = settings.UPLOAD_DIR
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Gunakan uuid unik agar nama file tidak bertabrakan
        unique_id = str(uuid.uuid4())[:8]
        out_tmpl = str(upload_dir / f"{unique_id}_%(title)s.%(ext)s")

        ydl_opts = {
            # Pilih format video mp4 terbaik atau format default dengan ekstensi aman
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": out_tmpl,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    raise ValidationException("Gagal mengambil informasi video dari URL")

                filename = ydl.prepare_filename(info)
                # Ganti ekstensi output sesuai format penggabungan jika yt-dlp mengubahnya
                dest_path = Path(filename)
                if not dest_path.exists():
                    # coba cari dengan ekstensi .mp4
                    mp4_path = dest_path.with_suffix(".mp4")
                    if mp4_path.exists():
                        dest_path = mp4_path
                    else:
                        raise ValidationException("File hasil download tidak ditemukan di disk")

                original_filename = info.get("title", "downloaded_video") + ".mp4"
                file_size = dest_path.stat().st_size
                duration = info.get("duration")

                video = Video(
                    original_filename=original_filename,
                    source_type="download",
                    source_url=url,
                    file_path=str(dest_path),
                    duration_seconds=float(duration) if duration else None,
                    file_size_bytes=file_size,
                    status="uploaded",
                )
                video = self.repo.add(video)

                # Log to History
                self.db.add(History(
                    video_id=video.id,
                    action="video_downloaded",
                    description=f"Downloaded video from {url}",
                ))
                self.db.commit()

                logger.info("Video downloaded from URL successfully: %s", url)
                return video

        except Exception as e:
            logger.error("Failed to download video from URL: %s", url, exc_info=e)
            raise ValidationException(f"Gagal mendownload video dari URL: {str(e)}")
