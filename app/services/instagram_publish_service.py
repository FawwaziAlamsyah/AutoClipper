"""Service untuk mempublikasikan video klip ke Instagram Reels via Instagram API."""

from dataclasses import dataclass
import logging
from pathlib import Path
import re
import time
from typing import Callable, Generator

import httpx
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.repositories.clip_repository import ClipRepository
from app.services.ffmpeg_service import FFmpegService
from app.services.instagram_video_prep_service import InstagramVideoPrepService
from app.services.token_manager.manager import TokenManager
from app.services.token_manager.setup import build_default_manager

logger = logging.getLogger(__name__)


class PublishUncertainError(ValidationException):
    """Raised saat media_publish ambigu/timeout sehingga status publish tidak pasti."""

    def __init__(
        self,
        message: str = "Status publish tidak pasti — cek akun Instagram secara manual sebelum mengirim ulang",
    ) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class PreflightReport:
    """Hasil preflight check sebelum publish klip ke Instagram."""

    ok: bool
    errors: list[str]      # blokir publish bila tidak kosong
    warnings: list[str]    # hanya peringatan (misal info reframe)
    duration_seconds: float | None
    will_reframe: bool = False
    fit_mode: str = "pad"


@dataclass(frozen=True)
class PublishResult:
    """Hasil akhir dari proses publish Reels ke Instagram."""

    container_id: str
    media_id: str
    permalink: str | None


class InstagramPublishService:
    """Service untuk mengelola preflight dan alur penerbitan Reels ke Instagram."""

    def __init__(
        self,
        db: Session,
        token_manager: TokenManager | None = None,
        video_prep_service: InstagramVideoPrepService | None = None,
    ) -> None:
        self.db = db
        self.token_manager = token_manager or build_default_manager()
        self.clip_repo = ClipRepository(db)
        self.ffmpeg_service = FFmpegService()
        self.video_prep_service = video_prep_service or InstagramVideoPrepService(self.ffmpeg_service)

    def _build_url(self, path: str) -> str:
        """Bangun URL endpoint Instagram Graph API dengan opsional prefix versi."""
        base = settings.IG_GRAPH_BASE_URL.rstrip("/")
        version = settings.IG_GRAPH_VERSION.strip("/")
        p = path.lstrip("/")
        if version:
            return f"{base}/{version}/{p}"
        return f"{base}/{p}"

    def _handle_graph_error(self, resp: httpx.Response, default_msg: str) -> None:
        """Parse error body Graph API, tangani error code 190 dan rate limits."""
        try:
            body = resp.json()
        except Exception:
            body = {}

        err = body.get("error", {})
        code = err.get("code")
        subcode = err.get("error_subcode")
        msg = err.get("message", "")
        if not msg:
            if isinstance(body, dict) and body:
                msg = str(body.get("debug_info") or body.get("description") or body.get("message") or "")
            if not msg and resp.text:
                msg = resp.text[:300].strip()

        # Unpack nested JSON strings inside body or message (e.g. Meta rupload processing errors)
        if isinstance(msg, str) and (msg.startswith("{") or msg.startswith("[")):
            import json as _json
            try:
                nested = _json.loads(msg)
                while isinstance(nested, dict):
                    if "error" in nested and isinstance(nested["error"], dict):
                        nested = nested["error"]
                    elif "message" in nested:
                        nested = nested["message"]
                        if isinstance(nested, str) and nested.startswith("{"):
                            nested = _json.loads(nested)
                    else:
                        break
                if isinstance(nested, str) and nested:
                    msg = nested
            except Exception:
                pass

        user_msg = err.get("error_user_msg")

        logger.warning(
            "Instagram Graph API error: status=%d, code=%s, subcode=%s, msg=%s, user_msg=%s",
            resp.status_code,
            code,
            subcode,
            msg,
            user_msg,
        )

        if code == 190 or resp.status_code == 401:
            self.token_manager.mark_needs_reconnect(
                self.db, "instagram", f"Token invalid/expired (code {code}): {msg}"
            )
            raise ValidationException(
                "Token Instagram tidak valid atau telah kedaluwarsa. Silakan generate ulang token di Meta dashboard."
            )

        if code in (4, 17, 32, 613) or resp.status_code == 429:
            raise ValidationException("Terlalu banyak request ke Instagram (rate limit), coba lagi nanti.")

        final_msg = user_msg or msg or f"{default_msg} (HTTP {resp.status_code})"
        raise ValidationException(final_msg)

    def _check_quota(self, access_token: str) -> tuple[bool, str | None]:
        """Cek kuota publishing Instagram.

        Kegagalan memanggil endpoint kuota tidak memblokir publish (non-blocking).
        """
        if not settings.IG_USER_ID:
            return True, None

        url = self._build_url(f"{settings.IG_USER_ID}/content_publishing_limit")
        params = {
            "fields": "quota_usage,config",
            "access_token": access_token,
        }
        try:
            resp = httpx.get(url, params=params, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", [])
                item = items[0] if isinstance(items, list) and items else data
                usage = item.get("quota_usage")
                config = item.get("config", {})
                total = config.get("quota_total")
                if usage is not None and total is not None:
                    if int(usage) >= int(total):
                        return False, f"Kuota publikasi harian Instagram telah habis ({usage}/{total}). Coba lagi nanti."
            return True, None
        except Exception as e:
            logger.warning("Gagal memeriksa kuota publikasi Instagram (non-blocking): %s", e)
            return True, None

    def preflight(self, clip_id: int, caption: str, fit_mode: str | None = None) -> PreflightReport:
        """Validasi menyeluruh sebelum publish klip ke Instagram Reels."""
        errors: list[str] = []
        warnings: list[str] = []
        duration: float | None = None
        will_reframe: bool = False

        effective_fit_mode = fit_mode or settings.IG_FIT_MODE
        if effective_fit_mode not in ("pad", "blur", "off"):
            effective_fit_mode = "pad"

        # 1. Cek keberadaan klip di database
        clip = self.clip_repo.get(clip_id)
        if not clip:
            errors.append(f"Klip dengan ID {clip_id} tidak ditemukan di database.")
            return PreflightReport(
                ok=False,
                errors=errors,
                warnings=warnings,
                duration_seconds=None,
                will_reframe=will_reframe,
                fit_mode=effective_fit_mode,
            )

        # 2. Cek file video di disk
        file_path_str = clip.edited_file_path or clip.file_path
        if not file_path_str:
            errors.append("File klip belum tersedia (path file kosong).")
            return PreflightReport(
                ok=False,
                errors=errors,
                warnings=warnings,
                duration_seconds=None,
                will_reframe=will_reframe,
                fit_mode=effective_fit_mode,
            )

        file_path = Path(file_path_str)
        if not file_path.exists():
            errors.append(f"File video klip tidak ditemukan di disk: {file_path_str}")
            return PreflightReport(
                ok=False,
                errors=errors,
                warnings=warnings,
                duration_seconds=None,
                will_reframe=will_reframe,
                fit_mode=effective_fit_mode,
            )

        # 3. Cek ekstensi file video
        ext = file_path.suffix.lower()
        if ext not in (".mp4", ".mov"):
            errors.append(f"Format file '{ext}' tidak didukung untuk Reels (harus .mp4 atau .mov).")

        # 4. Cek batas ukuran file sumber
        if settings.IG_MAX_FILE_MB > 0:
            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            if file_size_mb > settings.IG_MAX_FILE_MB:
                errors.append(
                    f"Ukuran file ({file_size_mb:.1f} MB) melebihi batas maksimum ({settings.IG_MAX_FILE_MB} MB)."
                )

        # 5. Cek metadata via FFmpegService
        try:
            meta = self.ffmpeg_service.extract_metadata(str(file_path))
            duration = meta.get("duration_seconds")
            width = meta.get("width")
            height = meta.get("height")
            rot = meta.get("rotation") or 0

            if duration is None:
                errors.append("Gagal mendeteksi durasi video dari metadata ffprobe.")
            else:
                if duration < settings.IG_MIN_REEL_SECONDS:
                    errors.append(
                        f"Durasi video ({duration:.1f} detik) kurang dari batas minimum Instagram ({settings.IG_MIN_REEL_SECONDS} detik)."
                    )
                elif duration > settings.IG_MAX_REEL_SECONDS:
                    errors.append(
                        f"Durasi video ({duration:.1f} detik) melebihi batas maksimum Instagram Reels ({settings.IG_MAX_REEL_SECONDS} detik)."
                    )

            if width and height and height > 0:
                disp_w, disp_h = (height, width) if abs(int(rot)) % 180 == 90 else (width, height)
                reframe_needed = self.video_prep_service.needs_reframe(disp_w, disp_h)
                transcode_needed = self.video_prep_service.needs_transcode(meta)
                if reframe_needed or transcode_needed:
                    if effective_fit_mode != "off":
                        will_reframe = True
                        if reframe_needed:
                            warnings.append(
                                f"Video akan dimasukkan ke bingkai 9:16 (mode: {effective_fit_mode})"
                            )
                        else:
                            warnings.append(
                                f"Format video akan dinormalisasi ke standar Instagram H.264/yuv420p (mode: {effective_fit_mode})"
                            )
                    else:
                        will_reframe = False
                        warnings.append("Video bukan 9:16 / belum standar Instagram. Reframing dinonaktifkan (mode: off)")
        except Exception as e:
            errors.append(f"Gagal mengekstrak metadata video klip: {e}")

        # 6. Cek batas caption dan hashtag
        if len(caption) > settings.IG_CAPTION_MAX_CHARS:
            errors.append(
                f"Panjang caption ({len(caption)} karakter) melebihi batas maksimum ({settings.IG_CAPTION_MAX_CHARS} karakter)."
            )

        hashtags = re.findall(r"#\S+", caption)
        if len(hashtags) > settings.IG_CAPTION_MAX_HASHTAGS:
            errors.append(
                f"Jumlah hashtag ({len(hashtags)}) melebihi batas maksimum ({settings.IG_CAPTION_MAX_HASHTAGS})."
            )

        # 7. Cek konfigurasi dan validitas token
        if not settings.IG_USER_ID:
            errors.append("Pengaturan IG_USER_ID belum dikonfigurasi di .env.")

        access_token: str | None = None
        try:
            self.token_manager.ensure_valid(self.db, "instagram")
            access_token = self.token_manager.get_access_token(self.db, "instagram")
        except ValidationException as e:
            errors.append(f"Kredensial token Instagram tidak valid: {e.message}")
        except Exception as e:
            errors.append(f"Gagal memverifikasi token Instagram: {e}")

        # 8. Cek kuota harian Instagram jika token valid
        if access_token and settings.IG_USER_ID:
            quota_ok, quota_msg = self._check_quota(access_token)
            if not quota_ok and quota_msg:
                errors.append(quota_msg)

        return PreflightReport(
            ok=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            duration_seconds=duration,
            will_reframe=will_reframe,
            fit_mode=effective_fit_mode,
        )

    def publish_reel(
        self,
        clip_id: int,
        caption: str,
        share_to_feed: bool = True,
        fit_mode: str | None = None,
        on_progress: Callable[[str, int], None] | None = None,
    ) -> PublishResult:
        """Publish klip ke Instagram Reels secara resumable."""
        # 1. Jalankan Preflight
        report = self.preflight(clip_id, caption, fit_mode=fit_mode)
        if not report.ok:
            raise ValidationException("; ".join(report.errors))

        def _report(stage: str, percent: int) -> None:
            if on_progress:
                try:
                    on_progress(stage, percent)
                except Exception:
                    pass

        # 2. Persiapan Data & Token
        access_token = self.token_manager.get_access_token(self.db, "instagram")
        user_id = settings.IG_USER_ID
        clip = self.clip_repo.get(clip_id)
        if not clip:
            raise ValidationException(f"Klip dengan ID {clip_id} tidak ditemukan.")

        file_path_str = clip.edited_file_path or clip.file_path
        file_path = Path(file_path_str)

        # 3. Langkah 0: Prepare Video (Auto 9:16 reframe bila diperlukan)
        _report("preparing", 5)
        prepared = self.video_prep_service.prepare(file_path, fit_mode=fit_mode)
        _report("preparing", 20)

        try:
            upload_path = prepared.path
            file_size = upload_path.stat().st_size

            # Cek ukuran file hasil prepare jika IG_MAX_FILE_MB diatur
            if settings.IG_MAX_FILE_MB > 0:
                size_mb = file_size / (1024 * 1024)
                if size_mb > settings.IG_MAX_FILE_MB:
                    raise ValidationException(
                        f"Ukuran file video hasil reframe ({size_mb:.1f} MB) melebihi batas ({settings.IG_MAX_FILE_MB} MB)."
                    )

            # 4. Langkah 1: Buat Media Container
            _report("uploading", 20)
            container_url = self._build_url(f"{user_id}/media")
            container_data = {
                "media_type": "REELS",
                "upload_type": "resumable",
                "caption": caption,
                "share_to_feed": "true" if share_to_feed else "false",
                "access_token": access_token,
            }

            try:
                resp_container = httpx.post(container_url, data=container_data, timeout=30.0)
            except httpx.TimeoutException as e:
                raise ValidationException(f"Timeout saat membuat media container Instagram: {e}") from e
            except httpx.RequestError as e:
                raise ValidationException(f"Koneksi gagal saat membuat media container Instagram: {e}") from e

            if resp_container.status_code != 200:
                self._handle_graph_error(resp_container, "Gagal membuat media container Instagram")

            container_res = resp_container.json()
            if "error" in container_res:
                self._handle_graph_error(resp_container, "Gagal membuat media container Instagram")

            container_id = container_res.get("id")
            upload_uri = container_res.get("uri")
            if not container_id or not upload_uri:
                raise ValidationException("Response container Instagram tidak memuat container ID atau upload URI.")

            # 5. Langkah 2: Upload Resumable (Gunakan binary raw octet-stream untuk rupload endpoint)
            _report("uploading", 35)
            upload_headers = {
                "Authorization": f"OAuth {access_token}",
                "offset": "0",
                "file_size": str(file_size),
                "Content-Length": str(file_size),
                "Content-Type": "application/octet-stream",
            }

            resp_upload: httpx.Response | None = None
            last_upload_err: Exception | None = None

            # Retry hingga 2x untuk mengatasi transient glitch pada gateway rupload Meta
            for attempt in range(1, 3):
                try:
                    with open(upload_path, "rb") as f:
                        video_bytes = f.read()
                    resp_upload = httpx.post(
                        upload_uri,
                        headers=upload_headers,
                        content=video_bytes,
                        timeout=httpx.Timeout(300.0, connect=30.0),
                    )
                    if resp_upload.status_code in (200, 201):
                        break
                    logger.warning(
                        "Upload video ke Instagram rupload gagal (attempt %d/2, status %d): %s",
                        attempt,
                        resp_upload.status_code,
                        resp_upload.text[:200],
                    )
                    if attempt < 2:
                        time.sleep(2.0)
                except httpx.TimeoutException as e:
                    last_upload_err = e
                    if attempt < 2:
                        time.sleep(2.0)
                except httpx.RequestError as e:
                    last_upload_err = e
                    if attempt < 2:
                        time.sleep(2.0)

            if resp_upload is None:
                if isinstance(last_upload_err, httpx.TimeoutException):
                    raise ValidationException(f"Timeout saat mengunggah file video ke Instagram: {last_upload_err}")
                raise ValidationException(f"Koneksi terputus saat mengunggah video ke Instagram: {last_upload_err}")

            if resp_upload.status_code not in (200, 201):
                self._handle_graph_error(resp_upload, "Gagal mengunggah file video ke Instagram")

            _report("uploading", 50)

            # 6. Langkah 3: Polling status pemrosesan container sampai FINISHED
            _report("processing", 50)
            poll_url = self._build_url(container_id)
            poll_params = {
                "fields": "status_code,status",
                "access_token": access_token,
            }
            start_time = time.monotonic()
            poll_finished = False

            while (time.monotonic() - start_time) < settings.IG_PROCESS_TIMEOUT_SECONDS:
                poll_resp: httpx.Response | None = None
                # Retry idempoten hingga 3x untuk polling status jika terjadi error jaringan / 5xx
                for attempt in range(3):
                    try:
                        poll_resp = httpx.get(poll_url, params=poll_params, timeout=15.0)
                        if poll_resp.status_code >= 500:
                            time.sleep(1.0)
                            continue
                        break
                    except (httpx.TimeoutException, httpx.RequestError):
                        if attempt == 2:
                            raise ValidationException("Koneksi terputus saat memeriksa status pemrosesan video Instagram.")
                        time.sleep(1.0)

                if not poll_resp or poll_resp.status_code != 200:
                    if poll_resp:
                        self._handle_graph_error(poll_resp, "Gagal memeriksa status container Instagram")
                    raise ValidationException("Gagal menghubungi server Instagram saat polling status.")

                poll_data = poll_resp.json()
                status_code = poll_data.get("status_code", "").upper()

                if status_code == "FINISHED":
                    poll_finished = True
                    break
                elif status_code in ("ERROR", "EXPIRED"):
                    raise ValidationException(f"Proses encoding video Instagram gagal dengan status: {status_code}")
                elif status_code == "IN_PROGRESS":
                    elapsed = time.monotonic() - start_time
                    pct = min(89, 50 + int(40 * (elapsed / min(120.0, float(settings.IG_PROCESS_TIMEOUT_SECONDS)))))
                    _report("processing", pct)
                    time.sleep(settings.IG_PROCESS_POLL_SECONDS)
                else:
                    time.sleep(settings.IG_PROCESS_POLL_SECONDS)

            if not poll_finished:
                raise ValidationException(
                    f"Waktu pemrosesan video Instagram melebihi batas waktu ({settings.IG_PROCESS_TIMEOUT_SECONDS} detik)."
                )

            # 7. Langkah 4: Publish Reels (JANGAN PERNAH AUTO-RETRY media_publish!)
            _report("publishing", 95)
            publish_url = self._build_url(f"{user_id}/media_publish")
            publish_data = {
                "creation_id": container_id,
                "access_token": access_token,
            }

            try:
                resp_publish = httpx.post(publish_url, data=publish_data, timeout=60.0)
            except (httpx.TimeoutException, httpx.RequestError) as e:
                logger.warning("media_publish mengalami network/timeout error: %s", e)
                raise PublishUncertainError() from e

            if resp_publish.status_code >= 500:
                logger.warning("media_publish menerima HTTP %s dari Instagram", resp_publish.status_code)
                raise PublishUncertainError()

            if resp_publish.status_code != 200:
                self._handle_graph_error(resp_publish, "Gagal mempublikasikan Reels ke Instagram")

            pub_data = resp_publish.json()
            if "error" in pub_data:
                self._handle_graph_error(resp_publish, "Gagal mempublikasikan Reels ke Instagram")

            media_id = pub_data.get("id")
            if not media_id:
                raise ValidationException("Response media_publish tidak memuat ID media yang dipublikasikan.")

            # 8. Langkah 5: Ambil permalink (Idempoten, retry maks 3x. Gagal tidak membatalkan sukses)
            permalink: str | None = None
            permalink_url = self._build_url(media_id)
            permalink_params = {
                "fields": "permalink",
                "access_token": access_token,
            }

            for attempt in range(3):
                try:
                    resp_perm = httpx.get(permalink_url, params=permalink_params, timeout=10.0)
                    if resp_perm.status_code == 200:
                        perm_data = resp_perm.json()
                        permalink = perm_data.get("permalink")
                        break
                    elif resp_perm.status_code >= 500:
                        time.sleep(1.0)
                        continue
                    else:
                        break
                except (httpx.TimeoutException, httpx.RequestError):
                    if attempt < 2:
                        time.sleep(1.0)
                    else:
                        logger.warning("Gagal mengambil permalink setelah 3x percobaan (non-fatal)")

            _report("publishing", 100)
            return PublishResult(
                container_id=container_id,
                media_id=media_id,
                permalink=permalink,
            )
        finally:
            self.video_prep_service.cleanup(prepared)
