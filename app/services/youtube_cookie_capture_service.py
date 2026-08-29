"""Ambil cookies YouTube otomatis lewat browser login interaktif.

User login manual di browser asli yang muncul (project tidak pernah lihat/
simpan password) — begitu login terdeteksi berhasil, cookies sesi itu
diambil dan disimpan ke data/cookies.txt (format yang sama dipakai yt-dlp).

Kenapa subprocess + CDP, bukan Playwright launch: `p.chromium.launch()` menempel
penanda automation ke browser (navigator.webdriver + --enable-automation), dan
Google memblokir login (`This browser or app may not be secure`). Chrome asli
yang di-launch langsung lewat subprocess TIDAK punya penanda itu — Playwright
cuma attach via CDP untuk baca cookies. Ini yang bikin Google melihat browser
normal.

Status live: capture() menerima status_cb yang dipanggil tiap perubahan fase
(menunggu login / login terdeteksi / menyimpan cookies) supaya UI bisa tampilkan
progress nyata, bukan cuma "menunggu login" selama berjam-jam.
"""

import logging
import socket
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.core.config.settings import settings

logger = logging.getLogger(__name__)

LOGIN_TIMEOUT_SEC = 300  # 5 menit — batas wajar buat user login manual
SID_WAIT_TIMEOUT_SEC = 60  # setelah login terdeteksi, SID non-guest harus cepat muncul
POLL_INTERVAL_SEC = 2

# Cookie ini muncul cuma kalau user sudah benar-benar login ke akun Google.
LOGIN_INDICATOR_COOKIES = {"SAPISID", "LOGIN_INFO"}

_CAPTURE_SESSIONS: dict[str, dict] = {}


def _session_update(session_id: str, phase: str, message: str, error: str | None = None) -> None:
    """Update satu session capture (thread-safe untuk app single-user)."""
    entry = _CAPTURE_SESSIONS.get(session_id)
    if entry is None:
        return
    entry["status"] = phase if error is None else "error"
    entry["message"] = message
    if error is not None:
        entry["error"] = error
    logger.info("[cookie-capture] %s — %s", phase, message)


class YouTubeCookieCaptureService:
    """Jalankan browser interaktif, tunggu login, simpan cookies otomatis."""

    def _chrome_binary(self, p):
        """Path biner browser asli prefer Edge, lalu Chrome. JANGAN pakai
        `executable_path_for_channel` — di mesin ini ia gagal resolve channel dan
        jatuh ke bundled Chromium Playwright yang diblokir Google.
        """
        candidates = [
            Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
            Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
            Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
            Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
            Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
        ]
        for exe in candidates:
            if exe.exists():
                return str(exe)
        return p.chromium.executable_path  # bundled Chromium (last resort)

    def _free_port(self) -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _launch_chrome(self, p):
        """Launch browser asli via subprocess (TANPA penanda automation) + CDP.

        Return (browser_cdp, proc). Browser di-launch normal seperti user buka
        Chrome biasa, Playwright attach read-only lewat remote debugging.
        """
        binary = self._chrome_binary(p)
        port = self._free_port()
        user_dir = Path(settings.DATA_DIR) / "cookie-capture-profile"
        user_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Cookie capture: launch browser normal (subprocess, no automation)")
        proc = subprocess.Popen([
            binary,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
            "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Tunggu CDP endpoint siap
        endpoint = f"http://127.0.0.1:{port}/json/version"
        for _ in range(60):
            try:
                urllib.request.urlopen(endpoint, timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        else:
            proc.terminate()
            raise RuntimeError("Gagal menunggu browser siap (CDP endpoint tidak merespon).")

        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        return browser, proc

    def capture(self, session_id: str | None = None, status_cb=None) -> Path:
        """Buka browser, tunggu user login, simpan cookies ke output_path.

        status_cb: Callable[[str, str], None] dengan (phase, message) — dipanggil
        tiap perubahan fase supaya UI tampilkan progres.
        """
        def _status(phase: str, message: str) -> None:
            if status_cb:
                status_cb(phase, message)

        output_path = Path(settings.COOKIES_FILE or "data/cookies.txt")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            browser, proc = self._launch_chrome(p)
            try:
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()

                _status("opening_browser", "Browser dibuka — silakan login di jendela Chrome...")
                page.goto("https://accounts.google.com/ServiceLogin?service=youtube")

                _status("waiting_login", "Menunggu Anda login di jendela browser...")
                logged_in = self._wait_for_login(context)

                if not logged_in:
                    _status("error", "Login tidak terdeteksi — coba lagi dan pastikan login selesai dalam 5 menit.")
                    raise TimeoutError(
                        f"Login tidak terdeteksi dalam {LOGIN_TIMEOUT_SEC} detik. "
                        "Coba lagi dan pastikan login selesai sebelum waktu habis."
                    )

                # Navigasi ke youtube.com — cookie .youtube.com baru ter-set setelah
                # halaman YouTube di-load. Tanpa ini cookies cuma domain google.com,
                # yt-dlp tetap anggap guest.
                _status("loading_youtube", "Login terdeteksi — memuat halaman YouTube...")
                try:
                    page.goto("https://www.youtube.com", wait_until="domcontentloaded")
                except Exception as e:
                    logger.debug("Cookie capture: goto youtube.com gagal (%s), lanjut saja", e)

                # Tunggu SID bukan guest (g.a000...). SID guest = login belum tuntas
                # (consent/2SV belum submit) atau sesi ga gunakan.
                _status("finalizing", "Memastikan sesi login valid (SID non-guest)...")
                if not self._wait_for_non_guest_sid(context):
                    _status("error", "SID masih guest — login benar-benar selesai sampai dashboard YouTube tampil.")
                    raise TimeoutError(
                        "Login Google selesai, tapi SID YouTube masih guest. "
                        "Kemungkinan ada popup consent/verifikasi yang belum disubmit. "
                        "Coba login lagi dan pastikan sampai dashboard YouTube (avatar akun) tampil."
                    )

                _status("saving_cookies", "Menyimpan cookies ke data/cookies.txt...")
                cookies = context.cookies()
                self._save_as_netscape_format(cookies, output_path)

                # Validasi hasil file: harus ada SID non-guest. Kalau masih guest
                # (mis. login belum tuntas tapi indicator nyala), file cookies itu
                # cuma bikin yt-dlp kena 403 — hapus biar nggak kepakai.
                if not self._file_has_non_guest_sid(output_path):
                    try:
                        output_path.unlink()
                        logger.warning("Cookies hasil masih guest — file %s dihapus.", output_path)
                    except OSError:
                        pass
                    _status("error", "Cookies tersimpan masih guest — file dihapus. Login sampai dashboard YouTube tampil, lalu coba lagi.")
                    raise TimeoutError(
                        "Cookies yang tertangkap masih guest (SID g.a000...). "
                        "Login belum benar-benar tuntas — pastikan sampai dashboard YouTube (avatar) tampil, coba lagi."
                    )
            finally:
                try:
                    browser.close()  # detach CDP
                except Exception:
                    pass
                try:
                    proc.terminate()
                except Exception:
                    pass

        _status("success", f"Cookies tersimpan: {output_path}")
        logger.info("Cookies YouTube berhasil disimpan ke %s", output_path)
        return output_path

    def _wait_for_login(self, context) -> bool:
        """Poll cookies tiap beberapa detik sampai indikator login muncul atau timeout."""
        elapsed = 0
        while elapsed < LOGIN_TIMEOUT_SEC:
            try:
                cookie_names = {c["name"] for c in context.cookies()}
            except Exception:
                return False  # browser tertutup
            if LOGIN_INDICATOR_COOKIES & cookie_names:
                return True
            time.sleep(POLL_INTERVAL_SEC)
            elapsed += POLL_INTERVAL_SEC
        return False

    def _wait_for_non_guest_sid(self, context) -> bool:
        """Tunggu sampai SID login asli (bukan guest) muncul.

        SID login (non-guest) domain .google.com — cek ini, bukan .youtube.com
        (SID YouTube selalu guest). yt-dlp pakai SID/LOGIN domain .google.com/.youtube.com
        sebagai tanda login asli. Poll sampai ada SID non-guest di salah satu domain.
        """
        elapsed = 0
        while elapsed < SID_WAIT_TIMEOUT_SEC:
            try:
                for c in context.cookies():
                    if c["name"] == "SID":
                        val = str(c["value"])
                        # g.a000... = guest (anonymous). Non-guest = punya akun.
                        if not val.startswith("g.a000"):
                            return True
            except Exception:
                return False  # browser tertutup
            time.sleep(POLL_INTERVAL_SEC)
            elapsed += POLL_INTERVAL_SEC
        return False

    def _save_as_netscape_format(self, cookies: list[dict], output_path: Path) -> None:
        """Convert cookies Playwright ke format Netscape yang dipahami yt-dlp."""
        lines = ["# Netscape HTTP Cookie File", "# Auto-generated oleh AutoClipper, jangan edit manual\n"]
        for c in cookies:
            domain = c["domain"]
            if "youtube.com" not in domain and "google.com" not in domain:
                continue  # cuma simpan cookies yang relevan buat YouTube
            flag = "TRUE" if domain.startswith(".") else "FALSE"
            path = c.get("path", "/")
            secure = "TRUE" if c.get("secure") else "FALSE"
            expiry = int(c.get("expires", 0)) if c.get("expires", -1) > 0 else 0
            lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expiry}\t{c['name']}\t{c['value']}")

        output_path.write_text("\n".join(lines), encoding="utf-8")

    def _file_has_non_guest_sid(self, output_path: Path) -> bool:
        """Baca ulang file Netscape, pastikan ada SID non-guest (bukan g.a000...).

        yt-dlp pakai SID/LOGIN domain .google.com/.youtube.com sebagai tanda login
        asli — kalau SID-nya guest, cookies file itu tak berguna & bikin 403.
        """
        if not output_path.exists():
            return False
        try:
            for line in output_path.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                # Netscape: 7 kolom, kolom 7 (index 6) = value.
                if len(parts) >= 7 and parts[5] == "SID":
                    if not parts[6].startswith("g.a000"):
                        return True
        except OSError:
            return False
        return False


def start_capture_session() -> str:
    """Mulai proses capture di background thread, return session_id buat polling."""
    session_id = f"cookie_{uuid.uuid4().hex[:8]}"
    _CAPTURE_SESSIONS[session_id] = {"status": "opening_browser", "message": "Memulai...", "error": None}

    def _cb(phase: str, message: str) -> None:
        _session_update(session_id, phase, message)

    def _run():
        try:
            service = YouTubeCookieCaptureService()
            service.capture(session_id=session_id, status_cb=_cb)
            _CAPTURE_SESSIONS[session_id]["status"] = "success"
        except Exception as e:
            logger.error("Cookie capture gagal: %s", e)
            _CAPTURE_SESSIONS[session_id]["status"] = "error"
            _CAPTURE_SESSIONS[session_id]["error"] = str(e)

    threading.Thread(target=_run, daemon=True).start()
    return session_id


def get_capture_status(session_id: str) -> dict:
    return _CAPTURE_SESSIONS.get(session_id, {"status": "unknown"})