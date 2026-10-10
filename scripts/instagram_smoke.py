"""Script pengujian manual / smoke test untuk fitur Instagram Reels Publisher.

Penggunaan:
    # 1. Dry-run aman (hanya preflight, cek token & kuota, tidak mengirim video):
    python scripts/instagram_smoke.py --clip-id 1

    # 2. Publish nyata ke Instagram Reels (memerlukan konfirmasi interaktif 'YES'):
    python scripts/instagram_smoke.py --clip-id 1 --caption "Klip tes #reels" --publish
"""

import argparse
import logging
from pathlib import Path
import sys

# Pastikan root direktori proyek dapat di-import
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.core.logging.logger import setup_logging
from app.db.session import SessionLocal
from app.services.instagram_publish_service import InstagramPublishService
from app.services.token_manager.setup import build_default_manager


def main() -> None:
    parser = argparse.ArgumentParser(description="Instagram Reels Publisher Smoke Test")
    parser.add_argument("--clip-id", type=int, required=True, help="ID Klip di database")
    parser.add_argument("--caption", type=str, default="Test Reels via AutoClipper #reels", help="Caption video")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Lakukan publikasi nyata ke Instagram Reels (akan meminta konfirmasi)",
    )
    parser.add_argument(
        "--no-share-to-feed",
        action="store_true",
        help="Jangan bagikan video Reels ke feed utama",
    )
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger("instagram_smoke")

    print("\n" + "=" * 60)
    print("      INSTAGRAM REELS PUBLISHER — SMOKE TEST")
    print("=" * 60)
    print(f"Clip ID      : {args.clip_id}")
    print(f"Caption      : {args.caption}")
    print(f"Mode         : {'PUBLISH NYATA' if args.publish else 'DRY RUN (Aman, hanya cek preflight)'}")
    print(f"IG_USER_ID   : {settings.IG_USER_ID or '(belum diatur)'}")
    print("=" * 60 + "\n")

    db = SessionLocal()
    try:
        manager = build_default_manager()
        service = InstagramPublishService(db, token_manager=manager)

        print("[1] Memeriksa status token Instagram...")
        provider = manager.get_provider("instagram")
        if provider:
            provider.sync_from_config(db)
        try:
            manager.ensure_valid(db, "instagram")
            print("    -> Token Instagram lolos pemeriksaan status & masa berlaku lokal.")
            # Diagnostik manual: panggil validate() langsung ke Meta API
            from app.core.security.token_crypto import decrypt_token
            from app.repositories.oauth_token_repository import OAuthTokenRepository

            rec = OAuthTokenRepository(db).get("instagram")
            if rec and provider:
                token_plain = decrypt_token(rec.access_token_encrypted)
                val_res = provider.validate(rec, token_plain)
                print(f"    -> Validasi Meta API sukses: Akun '{val_res.account_label}' (Professional)")
            print("    -> Token Instagram VALID & SIAP DIGUNAKAN.")
        except ValidationException as e:
            print(f"    -> Token Instagram TIDAK VALID: {e.message}")
        except Exception as e:
            print(f"    -> Gagal mengecek token: {e}")

        print("\n[2] Menjalankan Preflight Check...")
        report = service.preflight(args.clip_id, args.caption)

        print(f"    Status Preflight : {'LOLOS (OK)' if report.ok else 'GAGAL (TIDAK LOLOS)'}")
        if report.duration_seconds is not None:
            print(f"    Durasi Video     : {report.duration_seconds:.2f} detik")

        if report.warnings:
            print("    Peringatan (Warnings):")
            for w in report.warnings:
                print(f"      - {w}")

        if report.errors:
            print("    Error (Memblokir Publish):")
            for err in report.errors:
                print(f"      - {err}")

        # Jika mode dry-run, berhenti di sini
        if not args.publish:
            print("\n[INFO] Mode dry-run selesai. Tidak ada video yang dikirim ke Instagram.")
            return

        # Jika mode publish nyata
        if not report.ok:
            print("\n[ERROR] Preflight gagal. Publikasi dibatalkan.")
            sys.exit(1)

        print("\n" + "!" * 60)
        print("PERINGATAN: Anda akan memposting Reels ini ke akun Instagram!")
        print("!" * 60)
        confirm = input("Ketik 'YES' (huruf besar) untuk melanjutkan posting: ").strip()
        if confirm != "YES":
            print("[INFO] Dibatalkan oleh pengguna. Tidak ada postingan yang dibuat.")
            return

        def on_progress(stage: str, percent: int) -> None:
            print(f"  [PROGRES] {stage.upper()}: {percent}%")

        print("\n[3] Memulai proses upload dan publish Reels...")
        share_to_feed = not args.no_share_to_feed
        result = service.publish_reel(
            clip_id=args.clip_id,
            caption=args.caption,
            share_to_feed=share_to_feed,
            on_progress=on_progress,
        )

        print("\n" + "=" * 60)
        print("PUBLISH BERHASIL!")
        print(f"Container ID : {result.container_id}")
        print(f"Media ID     : {result.media_id}")
        print(f"Permalink    : {result.permalink or '(tidak tersedia)'}")
        print("=" * 60 + "\n")

    finally:
        db.close()


if __name__ == "__main__":
    main()
