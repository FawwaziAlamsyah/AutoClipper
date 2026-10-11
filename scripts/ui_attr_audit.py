"""UI Attribute & Functional Audit Script.

Memindai template HTML untuk memastikan tidak ada ID, nama, handler HTMX/JS,
link rute, tag Jinja, atau kunci terjemahan yang hilang selama proses redesign UI.

Penggunaan:
    python scripts/ui_attr_audit.py snapshot
    python scripts/ui_attr_audit.py check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATES_DIR = ROOT_DIR / "app" / "templates"
DEFAULT_BASELINE_FILE = ROOT_DIR / "scripts" / "ui_attr_baseline.json"
DEFAULT_ALLOWLIST_FILE = ROOT_DIR / "scripts" / "ui_attr_allowlist.json"

RE_ID = re.compile(r'\bid=["\']([^"\']+)["\']')
RE_NAME = re.compile(r'\bname=["\']([^"\']+)["\']')
RE_FOR = re.compile(r'\bfor=["\']([^"\']+)["\']')
RE_HX = re.compile(r'\b(hx-[\w-]+)=["\']([^"\']*)["\']')
RE_ON = re.compile(r'\b(on[a-zA-Z]+)=["\']([^"\']*)["\']')
RE_DATA = re.compile(r'\b(data-[\w-]+)=["\']([^"\']*)["\']')
RE_URL = re.compile(r'\b(href|action|src)=["\']([^"\']*)["\']')
RE_JINJA = re.compile(r'({%\s*(?:extends|include|block)\b[^%]*%})')
RE_T = re.compile(r'\b(?:__)?t\(\s*["\']([^"\']+)["\']')
RE_SCRIPT = re.compile(r'<script\b[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)


def normalize_ws(s: str) -> str:
    return " ".join(s.split())


def extract_template_attrs(content: str) -> dict[str, Any]:
    """Ekstraksi himpunan atribut fungsional dan hash script dari teks template."""
    ids = sorted(set(RE_ID.findall(content)))
    names = sorted(set(RE_NAME.findall(content)))
    fors = sorted(set(RE_FOR.findall(content)))

    hx_attrs = sorted(set(f"{k}:{v}" for k, v in RE_HX.findall(content)))
    on_attrs = sorted(set(f"{k}:{normalize_ws(v)}" for k, v in RE_ON.findall(content)))
    data_attrs = sorted(set(f"{k}:{v}" for k, v in RE_DATA.findall(content)))

    urls = []
    for attr, val in RE_URL.findall(content):
        val_clean = val.strip()
        if "{{" in val_clean or "{%" in val_clean or val_clean.startswith("/"):
            urls.append(f"{attr}:{val_clean}")
    urls = sorted(set(urls))

    jinja_tags = sorted(set(normalize_ws(tag) for tag in RE_JINJA.findall(content)))
    t_keys = sorted(set(RE_T.findall(content)))

    script_hashes = []
    for script_body in RE_SCRIPT.findall(content):
        body_clean = script_body.strip().encode("utf-8")
        script_hashes.append(hashlib.sha256(body_clean).hexdigest())
    script_hashes = sorted(script_hashes)

    return {
        "ids": ids,
        "names": names,
        "fors": fors,
        "hx_attrs": hx_attrs,
        "on_attrs": on_attrs,
        "data_attrs": data_attrs,
        "urls": urls,
        "jinja_tags": jinja_tags,
        "t_keys": t_keys,
        "script_hashes": script_hashes,
    }


def to_item_set(data: dict[str, Any]) -> set[str]:
    """Ubah data template menjadi himpunan string terformat untuk perbandingan."""
    items: set[str] = set()
    for v in data.get("ids", []):
        items.add(f"id:{v}")
    for v in data.get("names", []):
        items.add(f"name:{v}")
    for v in data.get("fors", []):
        items.add(f"for:{v}")
    for v in data.get("hx_attrs", []):
        items.add(v)  # format: hx-get:...
    for v in data.get("on_attrs", []):
        items.add(v)  # format: onclick:...
    for v in data.get("data_attrs", []):
        items.add(v)  # format: data-candidate-id:...
    for v in data.get("urls", []):
        items.add(v)  # format: href:... atau action:... atau src:...
    for v in data.get("jinja_tags", []):
        items.add(f"jinja:{v}")
    for v in data.get("t_keys", []):
        items.add(f"t:{v}")
    return items


def scan_templates(templates_dir: Path) -> dict[str, dict[str, Any]]:
    """Scan seluruh file template .html dan kembalikan pemetaan atribut."""
    results: dict[str, dict[str, Any]] = {}
    if not templates_dir.exists():
        return results

    for file_path in sorted(templates_dir.rglob("*.html")):
        rel_path = file_path.relative_to(templates_dir).as_posix()
        content = file_path.read_text(encoding="utf-8")
        results[rel_path] = extract_template_attrs(content)
    return results


def make_snapshot(templates_dir: Path, output_file: Path) -> None:
    data = scan_templates(templates_dir)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✓ Snapshot berhasil disimpan: {output_file} ({len(data)} template dipindai)")


def run_check(
    templates_dir: Path,
    baseline_file: Path,
    allowlist_file: Path,
) -> bool:
    if not baseline_file.exists():
        print(f"✗ File baseline tidak ditemukan: {baseline_file}. Jalankan snapshot dulu.")
        return False

    baseline_data: dict[str, dict[str, Any]] = json.loads(baseline_file.read_text(encoding="utf-8"))
    allowlist_data: dict[str, list[str]] = {}
    if allowlist_file.exists():
        try:
            allowlist_data = json.loads(allowlist_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠ Gagal membaca allowlist: {e}")

    current_data = scan_templates(templates_dir)

    all_ok = True
    total_missing = 0
    script_warnings = []

    for filename, base_record in baseline_data.items():
        curr_record = current_data.get(filename)
        allowed = set(allowlist_data.get(filename, []))

        if curr_record is None:
            # File dihapus
            print(f"✗ File template hilang sepenuhnya: {filename}")
            all_ok = False
            continue

        base_items = to_item_set(base_record)
        curr_items = to_item_set(curr_record)

        missing = base_items - curr_items
        # Saring item yang ada di allowlist
        unallowed_missing = {item for item in missing if item not in allowed}

        if unallowed_missing:
            all_ok = False
            total_missing += len(unallowed_missing)
            print(f"✗ {filename}: {len(unallowed_missing)} atribut/fungsi HILANG:")
            for item in sorted(unallowed_missing):
                print(f"    - {item}")

        # Periksa script hashes (hanya WARNING)
        if base_record.get("script_hashes") != curr_record.get("script_hashes"):
            script_warnings.append(filename)

    if script_warnings:
        print("\n⚠ WARNING: Isi tag <script> berubah pada file berikut (wajib diverifikasi/dijelaskan):")
        for f in script_warnings:
            print(f"    * {f}")

    if all_ok:
        print(f"\n✓ AUDIT LULUS: Semua fungsionalitas dan atribut baseline terjaga ({len(current_data)} template).")
    else:
        print(f"\n✗ AUDIT GAGAL: Total {total_missing} atribut/fungsi hilang tanpa izin allowlist.")

    return all_ok


def main() -> None:
    parser = argparse.ArgumentParser(description="UI Attribute & Functional Audit Tool")
    parser.add_argument("action", choices=["snapshot", "check"], help="Aksi: snapshot atau check")
    parser.add_argument(
        "--templates-dir",
        type=Path,
        default=DEFAULT_TEMPLATES_DIR,
        help="Folder templates (default: app/templates)",
    )
    parser.add_argument(
        "--baseline-file",
        type=Path,
        default=DEFAULT_BASELINE_FILE,
        help="File baseline JSON",
    )
    parser.add_argument(
        "--allowlist-file",
        type=Path,
        default=DEFAULT_ALLOWLIST_FILE,
        help="File allowlist JSON",
    )

    args = parser.parse_args()

    if args.action == "snapshot":
        make_snapshot(args.templates_dir, args.baseline_file)
        # Pastikan file allowlist juga ada jika belum ada
        if not args.allowlist_file.exists():
            args.allowlist_file.write_text("{}\n", encoding="utf-8")
        sys.exit(0)
    elif args.action == "check":
        ok = run_check(args.templates_dir, args.baseline_file, args.allowlist_file)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
