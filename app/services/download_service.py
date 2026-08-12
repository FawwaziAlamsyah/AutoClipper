"""Download service using yt-dlp."""

import logging
import threading
import uuid
from pathlib import Path
from typing import Callable
import yt_dlp

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.models.history_model import HistoryModel
from app.models.video_model import VideoModel
from app.repositories.video_repository import VideoRepository

logger = logging.getLogger(__name__)

# Store progress download aktif — in-memory (app lokal single-user).
# Key: download_id → {percent, status, video, error}
_DOWNLOADS: dict[str, dict] = {}


def _new_download_id() -> str:
    """Buat id unik untuk satu proses download."""
    return f"dl_{uuid.uuid4().hex[:8]}"


def _video_payload(video: VideoModel) -> dict:
    """Ringkas VideoModel jadi payload untuk UI."""
    return {
        "id": video.id,
        "original_filename": video.original_filename,
        "source_type": video.source_type,
        "duration_seconds": video.duration_seconds,
        "status": video.status,
    }


class DownloadService:
    """Downloads videos from URLs using yt-dlp."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.repo = VideoRepository(db)
        self.db = db

    def start_download(self, url: str) -> dict:
        """Mulai download di background thread; return download_id untuk polling.

        Progress dicatat ke _DOWNLOADS[download_id] — dibaca via get_download_progress.
        Thread pakai SessionLocal sendiri (session request sudah ditutup FastAPI).
        """
        if not url:
            raise ValidationException("URL tidak boleh kosong")

        dl_id = _new_download_id()
        _DOWNLOADS[dl_id] = {"percent": 0, "status": "downloading", "video": None, "error": None}
        logger.debug("Download process %s: start untuk URL %s", dl_id, url)

        def _run() -> None:
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                service = DownloadService(db)
                video = service.download_video(url, progress_cb=lambda p: _update_progress(dl_id, p))
                _DOWNLOADS[dl_id] = {
                    "percent": 100,
                    "status": "finished",
                    "video": _video_payload(video),
                    "error": None,
                }
                logger.debug("Download process %s: success, video %d terdaftar", dl_id, video.id)
            except Exception as e:
                logger.error("Download %s failed: %s", dl_id, e)
                _DOWNLOADS[dl_id]["status"] = "error"
                _DOWNLOADS[dl_id]["error"] = service._user_friendly_download_error(str(e))
                logger.debug("Download process %s: error - %s", dl_id, e)
            finally:
                db.close()

        threading.Thread(target=_run, daemon=True).start()
        return {"download_id": dl_id, "status": "downloading"}

    def get_download_progress(self, dl_id: str) -> dict:
        """Baca progress download aktif."""
        entry = _DOWNLOADS.get(dl_id)
        if entry is None:
            return {"status": "unknown", "percent": 0}
        return entry

    def download_video(self, url: str, progress_cb: Callable[[int], None] | None = None) -> VideoModel:
        """Download video from URL using yt-dlp and register in DB.

        progress_cb dipanggil dengan persen (0-100) via yt-dlp progress_hooks.

        Strategi dicoba berurutan, berhenti di percobaan pertama yang sukses:
        1. player_client "android" TANPA cookies — client Android sering lolos
           pengecekan bot YouTube tanpa perlu login sama sekali (ini yang dipakai
           kebanyakan situs downloader publik, bukan cookies).
        2. Kalau gagal dan COOKIES_FILE tersedia → pakai file cookies manual.
        3. Kalau tidak ada cookies file → coba baca cookies dari browser
           (Chrome → Firefox → Edge) secara berurutan.
        4. Terakhir, coba tanpa cookies sama sekali (client web default).
        """
        if not url:
            raise ValidationException("URL tidak boleh kosong")

        upload_dir: Path = settings.UPLOAD_DIR
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Gunakan uuid unik agar nama file tidak bertabrakan
        unique_id = str(uuid.uuid4())[:8]
        out_tmpl = str(upload_dir / f"{unique_id}_%(title)s.%(ext)s")

        def _hook(d: dict) -> None:
            if progress_cb is None:
                return
            if d.get("status") != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            pct = int(done * 100 / total) if total else 0
            progress_cb(pct)

        base_opts = {
            # Pilih format video mp4 terbaik atau format default dengan ekstensi aman
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": out_tmpl,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
            "progress_hooks": [_hook] if progress_cb else [],
            # User-agent realistis + header HTTP — hindari 403 anti-bot YouTube
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            "extractor_retries": 3,
            "noplaylist": True,
            # yt-dlp gagal auto-deteksi Node untuk n-challenge YouTube (2026.07).
            # Paksa pakai Node — tanpanya format video disembunyikan (cuma storyboard).
            "js_runtimes": {"node": {}},
        }

        # Susun daftar strategi dicoba berurutan: (label, ydl_opts).
        attempts: list[tuple[str, dict]] = []

        # 1. Client Android tanpa cookies — percobaan pertama, paling murah (tak perlu
        #    login/browser sama sekali) dan sering lolos "Sign in to confirm you're not a bot".
        android_opts = dict(base_opts)
        android_opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
        attempts.append(("android (tanpa cookies)", android_opts))

        # 2. Cookies file manual (export via ekstensi browser) — prioritas kalau tersedia.
        if settings.COOKIES_FILE and Path(settings.COOKIES_FILE).exists():
            cookie_file_opts = dict(base_opts)
            cookie_file_opts["cookiesfile"] = settings.COOKIES_FILE
            attempts.append(("web + cookies file", cookie_file_opts))
        else:
            # 3. Tidak ada cookies file → coba baca cookies langsung dari browser.
            for browser in ("chrome", "firefox", "edge"):
                browser_opts = dict(base_opts)
                browser_opts["cookiesfrombrowser"] = (browser,)
                attempts.append((f"web + cookies {browser}", browser_opts))

        # 4. Terakhir: coba tanpa cookies sama sekali (client web default).
        attempts.append(("web tanpa cookies", dict(base_opts)))

        last_error: str | None = None
        for label, opts in attempts:
            try:
                return self._extract_and_register(url, opts)
            except yt_dlp.utils.DownloadError as e:
                msg = str(e)
                last_error = msg
                logger.debug(
                    "Download process: strategi '%s' gagal (%s), coba strategi berikutnya",
                    label, msg[:120],
                )
                continue

        raise ValidationException(self._user_friendly_download_error(last_error or "unknown"))

    def _user_friendly_download_error(self, msg: str) -> str:
        """Map yt-dlp error to user-friendly message for UI."""
        msg_lower = msg.lower()
        if "sign in to confirm" in msg.lower() and "not a bot" in msg.lower():
            return (
                "YouTube meminta verifikasi bahwa Anda bukan bot. "
                "Ini terjadi karena cookies login Anda tidak valid (guest/expired). "
                "Silakan: 1) Buka youtube.com di Chrome, pastikan login & avatar akun tampil. "
                "2) Ekspor ulang cookies via ekstensi 'Get cookies.txt LOCALLY' → overwrite data/cookies.txt. "
                "3) Coba download lagi. Jika masih gagal, coba browser lain (Firefox/Edge) untuk export cookies."
            )
        if "could not copy" in msg.lower():
            return (
                "Browser yang dipilih (Chrome/Firefox/Edge) sedang berjalan dan database cookies terkunci. "
                "Silakan tutup browser tersebut SEPENUHNYA (termasuk tray icon), lalu coba lagi."
            )
        if "could not find" in msg.lower() and "firefox" in msg.lower():
            return (
                "Profil Firefox tidak ditemukan. Pastikan Firefox sudah pernah dibuka & login YouTube, "
                "atau pilih browser lain (Chrome/Edge) di pengaturan download."
            )
        if "cookiesfrombrowser" in msg.lower():
            return (
                "Gagal membaca cookies dari browser. Pastikan browser target sudah login YouTube "
                "dan tidak sedang berjalan saat download."
            )
        # Generic fallback
        return f"Gagal mendownload video: {msg}"

    def _extract_and_register(self, url: str, ydl_opts: dict) -> VideoModel:
        """Jalankan yt-dlp dengan satu opsi cookies, lalu daftarkan video ke DB."""
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.debug("Download process: ambil info video %s", url)
                info = ydl.extract_info(url, download=True)
                if not info:
                    raise ValidationException("Gagal mengambil informasi video dari URL")
                logger.debug("Download process: info didapat, title=%s", info.get("title"))

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

                logger.debug("Download process: file siap %s (%.1f MB)", dest_path.name, file_size / 1e6)

                video = VideoModel(
                    original_filename=original_filename,
                    source_type="download",
                    source_url=url,
                    file_path=str(dest_path),
                    duration_seconds=float(duration) if duration else None,
                    file_size_bytes=file_size,
                    status="uploaded",
                )
                logger.debug("Download process: import process ke DB (video %s)", video.original_filename)
                video = self.repo.add(video)

                # Log to HistoryModel
                self.db.add(HistoryModel(
                    video_id=video.id,
                    action="video_downloaded",
                    description=f"Downloaded video from {url}",
                ))
                self.db.commit()

                logger.info("Video downloaded from URL successfully: %s", url)
                return video

        except yt_dlp.utils.DownloadError:
            # Propagasi polos — caller (download_video) yang handle fallback strategi lain
            raise
        except Exception as e:
            logger.error("Failed to download video from URL: %s", url, exc_info=e)
            if isinstance(e, ValidationException):
                raise
            raise ValidationException(f"Gagal mendownload video dari URL: {str(e)}")


def _update_progress(dl_id: str, percent: int) -> None:
    """Update persen download di store (thread-safe cukup untuk app single-user)."""
    entry = _DOWNLOADS.get(dl_id)
    if entry is not None:
        entry["percent"] = min(percent, 99)  # 100 hanya saat finished