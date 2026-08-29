"""Download service using yt-dlp."""

import ctypes
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import yt_dlp

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.models.video_model import VideoModel
from app.repositories.video_repository import VideoRepository
from app.services.history_service import HistoryService

logger = logging.getLogger(__name__)

# Store progress download aktif — in-memory (app lokal single-user).
# Key: download_id → {percent, status, video, error}
_DOWNLOADS: dict[str, dict] = {}

# Anti-hang: kalau yt-dlp diam (tanpa progress byte) selama ini, anggap download
# berhenti diam-diam (stream freeze tanpa error) lalu abort & lanjut ke strategi
# berikutnya. yt-dlp kadang hang tanpa melempar pengecualian — socket_timeout
# tidak selalu men-trigger saat koneksi diam.
HANG_TIMEOUT_SEC = 120
# Setelah hang di-abort, kasih worker waktu ini utk cleanup .part sebelum lanjut.
# Short — kalau KeyboardInterrupt nggak nembus blocking C, jangan nunggu selamanya.
ABORT_GRACE_SEC = 5


def _abort_thread(tid: int, exc: BaseException) -> None:
    """Suntik pengecualian ke thread lain (pakai KeyboardInterrupt — pola yt-dlp
    Ctrl+C menangani cleanup dengan bersih; interpreter aman utk KI)."""
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(tid), ctypes.py_object(exc)
    )
    if res == 0:
        raise RuntimeError(f"Thread {tid} tidak ditemukan")
    if res != 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)
        raise RuntimeError("Gagal menyuntik pengecualian ke thread download")


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


class _YtDlpLogger:
    """Kirim pesan yt-dlp ke logger aplikasi, bukan stderr terminal."""

    def debug(self, message: str) -> None:
        logger.debug("yt-dlp: %s", message)

    def warning(self, message: str) -> None:
        logger.debug("yt-dlp warning: %s", message)

    def error(self, message: str) -> None:
        logger.debug("yt-dlp error: %s", message)


class DownloadService:
    """Downloads videos from URLs using yt-dlp."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.repo = VideoRepository(db)
        self.history_service = HistoryService(db)
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
        logger.info("[download] Mulai download: %s (id: %s)", url, dl_id)

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
                logger.info("[download] Selesai: video %d terdaftar", video.id)
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

        Strategi — coba berurutan, berhenti di pertama yang sukses DENGAN minimal
        720p: tv → tv_simply → ios → web. Kalau semua gagal (baik karena bot-check
        atau tidak ada format >=720p), fallback terakhir ke android TANPA minimum
        resolusi — prioritas jadi "dapat videonya" daripada gagal total.
        """
        if not url:
            raise ValidationException("URL tidak boleh kosong")

        upload_dir: Path = settings.UPLOAD_DIR
        upload_dir.mkdir(parents=True, exist_ok=True)

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
            # Max 1080p — prioritas format sudah merged (video+audio), baru split.
            # Format split (bestvideo+bestaudio) sering gagal merge → audio hilang
            # atau kualitas jelek. Merged lebih reliable.
            "format": "best[height<=1080][ext=mp4]/best[height<=1080]/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "logger": _YtDlpLogger(),
            "merge_output_format": "mp4",
            "progress_hooks": [_hook] if progress_cb else [],
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            "extractor_retries": 3,
            "retries": 3,
            "socket_timeout": 30,
            "noplaylist": True,
            "js_runtimes": {"node": {}},
        }

        # Strategi BARU: client kualitas lebih baik dulu (tv/ios/web biasanya
        # expose resolusi lebih tinggi dari android), android jadi LAST RESORT
        # karena walau paling reliable lolos bot-check, resolusinya paling terbatas.
        #
        # Untuk 4 attempt pertama, format WAJIB minimal 720p (height>=720) selain
        # cap 1080p yang sudah ada — kalau client itu cuma punya resolusi rendah,
        # lebih baik gagal & lanjut ke attempt berikutnya, daripada diam-diam
        # terima resolusi jelek.
        min_height_format = (
            "bestvideo[height>=720][height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
            "best[height>=720][height<=1080][ext=mp4]/"
            "bestvideo[height>=720][height<=1080]+bestaudio/"
            "best[height>=720][height<=1080]"
        )

        attempts: list[tuple[str, dict]] = []
        for client in ("tv", "tv_simply", "ios", "web"):
            opts = dict(base_opts)
            opts["format"] = min_height_format
            # outtmpl unik per attempt — kalau satu attempt hang & worker-nya
            # tak benar-benar mati, strategi berikut nggak bentrok nulis file sama.
            opts["outtmpl"] = str(upload_dir / f"{uuid.uuid4().hex[:8]}_%(title)s.%(ext)s")
            if client == "web":
                opts.pop("extractor_args", None)  # web = default, tidak perlu extractor_args
            else:
                opts["extractor_args"] = {"youtube": {"player_client": [client]}}
            attempts.append((client, opts))

        # Last resort: android, TANPA minimum height — lebih baik dapat video
        # resolusi rendah daripada gagal total.
        android_opts = dict(base_opts)
        android_opts["outtmpl"] = str(upload_dir / f"{uuid.uuid4().hex[:8]}_%(title)s.%(ext)s")
        android_opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
        attempts.append(("android (fallback resolusi rendah)", android_opts))

        last_error: str | None = None
        for i, (label, opts) in enumerate(attempts, 1):
            logger.info("[download] Strategi %d/%d: %s", i, len(attempts), label)
            try:
                result = self._extract_and_register(url, opts)
                if "android" in label:
                    logger.warning(
                        "[download] Video ini cuma bisa didapat lewat client android "
                        "(resolusi mungkin di bawah 720p) — client lain (tv/tv_simply/ios/web) "
                        "semuanya gagal untuk video ini."
                    )
                return result
            except yt_dlp.utils.DownloadError as e:
                msg = str(e)
                last_error = msg
                logger.warning("[download] Strategi '%s' gagal: %s", label, msg[:150])
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
        """Jalankan yt-dlp dengan satu opsi, register ke DB.

        Download jalan di worker thread; watchdog memonitor progress. Kalau yt-dlp
        diam tanpa progress melebihi HANG_TIMEOUT_SEC (stream freeze, no error),
        watchdog menyuntik KeyboardInterrupt → download dibatalkan → naik sebagai
        DownloadError → chain lanjut ke strategi berikutnya.
        """
        last_activity = {"t": time.monotonic()}

        def _activity_hook(d: dict) -> None:
            last_activity["t"] = time.monotonic()

        # Tambah hook pemantau progress (tanpa menimpa hook progress UI bawaan).
        ydl_opts["progress_hooks"] = list(ydl_opts.get("progress_hooks") or []) + [_activity_hook]

        result: dict = {}
        done = threading.Event()

        def _worker() -> None:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    logger.info("[download] Mengambil info video...")
                    info = ydl.extract_info(url, download=True)
                    if not info:
                        raise ValidationException("Gagal mengambil informasi video dari URL")
                    result["info"] = info
                    result["title"] = info.get("title", "unknown")
                    logger.info("[download] Info didapat: %s", result["title"])
                    result["filename"] = ydl.prepare_filename(info)
            except BaseException as e:
                result["error"] = e
            finally:
                done.set()

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        aborted = False
        while not done.wait(1):
            if time.monotonic() - last_activity["t"] > HANG_TIMEOUT_SEC:
                logger.warning(
                    "[download] Hang terdeteksi (tanpa progress %ds) — batalkan strategi ini, lanjut strategi berikut.",
                    HANG_TIMEOUT_SEC,
                )
                aborted = True
                try:
                    _abort_thread(t.ident, KeyboardInterrupt())
                except Exception as e:  # thread mungkin sudah selesai
                    logger.debug("[download] Abort thread gagal: %s", e)
                break

        if aborted:
            # GRACE: kasih worker waktu bersih-bersih .part. Kalau KeyboardInterrupt
            # gagal nembus blocking C-level I/O (asyncexc terbatas), jangan nunggu
            # selamanya — lanjut strategi berikut dengan outtmpl berbeda (tanpa tabrakan).
            done.wait(ABORT_GRACE_SEC)
            raise yt_dlp.utils.DownloadError("Download hang (tanpa progress) — dibatalkan")

        done.wait()  # worker selesai normal

        error = result.get("error")
        if error is not None:
            # yt-dlp membungkus KeyboardInterrupt/gancetan saat abort internal;
            # normalisasi: DownloadError naik utk lanjut chain, sisanya jadi ValidationException.
            if isinstance(error, yt_dlp.utils.DownloadError):
                raise error
            logger.error("Failed to download video from URL: %s (%s)", url, type(error).__name__)
            if isinstance(error, ValidationException):
                raise error
            raise ValidationException(f"Gagal mendownload video dari URL: {error}")

        # Download sukses → register ke DB.
        info = result["info"]
        title = result["title"]
        dest_path = Path(result["filename"])
        if not dest_path.exists():
            mp4_path = dest_path.with_suffix(".mp4")
            if mp4_path.exists():
                dest_path = mp4_path
            else:
                raise ValidationException("File hasil download tidak ditemukan di disk")

        file_size = dest_path.stat().st_size
        logger.info("[download] File tersimpan: %s (%.1f MB)", dest_path.name, file_size / 1e6)

        original_filename = title + ".mp4"
        duration = info.get("duration")

        video = VideoModel(
            original_filename=original_filename,
            source_type="download",
            source_url=url,
            file_path=str(dest_path),
            duration_seconds=float(duration) if duration else None,
            file_size_bytes=file_size,
            status="uploaded",
        )
        video = self.repo.add(video)

        self.history_service.log(
            action="video_downloaded",
            description=f"Downloaded video from {url}",
            video_id=video.id,
        )

        logger.info("[download] Video didaftarkan ke DB (id=%d)", video.id)
        return video


def _update_progress(dl_id: str, percent: int) -> None:
    """Update persen download di store (thread-safe cukup untuk app single-user)."""
    entry = _DOWNLOADS.get(dl_id)
    if entry is not None:
        entry["percent"] = min(percent, 99)  # 100 hanya saat finished