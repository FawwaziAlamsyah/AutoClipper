"""Clip Edit History Manager.

Mengelola stack riwayat edit (versioned step files) untuk sebuah clip:
- Pencatatan langkah edit (push_step)
- Rollback 1-langkah (undo)
- Maju 1-langkah (redo)
- Reset ke original
- Deteksi basis video untuk hook chaining (agar hook tidak mengulang dari video mentah)
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException

logger = logging.getLogger(__name__)


class ClipHistoryManager:
    """Manages versioned step snapshots and undo/redo navigation for a Clip."""

    def __init__(self, clip_id: int, max_steps: int = 15) -> None:
        self.clip_id = clip_id
        self.max_steps = max_steps
        self.history_dir = settings.OUTPUT_DIR / "edited" / "history" / f"clip_{clip_id}"
        self.manifest_file = self.history_dir / "history.json"

    def _read_manifest(self) -> dict[str, Any]:
        try:
            if not self.manifest_file.exists():
                return {}
            return json.loads(self.manifest_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_manifest(self, data: dict[str, Any]) -> None:
        try:
            self.history_dir.mkdir(parents=True, exist_ok=True)
            self.manifest_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Gagal menulis history manifest clip %d: %s", self.clip_id, e)

    def init_if_needed(self, clip: Any) -> dict[str, Any]:
        """Inisialisasi manifest jika belum ada, atau sinkronkan langkah awal."""
        data = self._read_manifest()
        steps = data.get("steps", [])

        if not steps:
            self.history_dir.mkdir(parents=True, exist_ok=True)
            step_0 = {
                "step": 0,
                "action": "original",
                "label": "Klip Original",
                "file_path": str(clip.file_path),
                "start_time": float(clip.start_time or 0.0),
                "end_time": float(clip.end_time or 0.0),
                "hook_applied": False,
                "created_at": time.time(),
            }
            steps = [step_0]
            current_step = 0

            # Jika clip sudah punya edited_file_path dari sesi terdahulu
            if clip.edited_file_path and Path(clip.edited_file_path).exists() and clip.edited_file_path != clip.file_path:
                step_1 = {
                    "step": 1,
                    "action": "edit",
                    "label": "Hasil Edit Sebelumnya",
                    "file_path": str(clip.edited_file_path),
                    "start_time": float(clip.start_time or 0.0),
                    "end_time": float(clip.end_time or 0.0),
                    "hook_applied": bool(getattr(clip, "hook_applied", False)),
                    "created_at": time.time(),
                }
                steps.append(step_1)
                current_step = 1

            data = {
                "clip_id": self.clip_id,
                "current_step": current_step,
                "steps": steps,
            }
            self._write_manifest(data)

        return data

    def get_current_source(self, clip: Any) -> Path:
        """Sumber video aktif untuk edit selanjutnya: langkah aktif atau fallback."""
        manifest = self.init_if_needed(clip)
        current_step_idx = manifest.get("current_step", 0)
        steps = manifest.get("steps", [])

        if 0 <= current_step_idx < len(steps):
            active_step = steps[current_step_idx]
            step_path = Path(active_step.get("file_path", ""))
            if step_path.exists():
                return step_path

        # Fallback jika file step tidak ditemukan
        if clip.edited_file_path and Path(clip.edited_file_path).exists():
            return Path(clip.edited_file_path)
        if clip.file_path and Path(clip.file_path).exists():
            return Path(clip.file_path)
        raise ValidationException(f"File sumber clip {self.clip_id} tidak ditemukan di disk.")

    def get_base_for_hook(self, clip: Any) -> Path:
        """Dapatkan path video untuk concat hook teaser.

        Jika user sudah edit (misal trim durasi), hook akan menempel ke video hasil trim,
        BUKAN kembali ke video mentah awal.
        Jika hook sedang di-generate ulang (current_step saat ini adalah hook),
        cari langkah terakhir SEBELUM hook agar tidak terjadi double-hook.
        """
        manifest = self.init_if_needed(clip)
        current_step_idx = manifest.get("current_step", 0)
        steps = manifest.get("steps", [])

        # Cari mundur dari current_step untuk menemukan langkah non-hook
        for i in range(current_step_idx, -1, -1):
            if i < len(steps):
                step = steps[i]
                if step.get("action") != "hook":
                    p = Path(step.get("file_path", ""))
                    if p.exists():
                        return p

        # Fallback
        if clip.edited_file_path and Path(clip.edited_file_path).exists() and not getattr(clip, "hook_applied", False):
            return Path(clip.edited_file_path)
        if clip.file_path and Path(clip.file_path).exists():
            return Path(clip.file_path)
        raise ValidationException(f"File sumber dasar untuk hook clip {self.clip_id} tidak ditemukan.")

    def prepare_base_for_subtitle(self, clip: Any) -> Path:
        """Siapkan file sumber dasar untuk burn subtitle.

        Jika langkah aktif saat ini adalah 'subtitle' (misal re-generate subtitle),
        mundurkan current_step ke langkah tepat sebelum 'subtitle' tersebut, sehingga
        subtitle baru tidak menimpa / double-burn di atas pixel subtitle lama.
        """
        manifest = self.init_if_needed(clip)
        current_step_idx = manifest.get("current_step", 0)
        steps = manifest.get("steps", [])

        if 0 <= current_step_idx < len(steps):
            if steps[current_step_idx].get("action") == "subtitle" and current_step_idx > 0:
                clean_idx = current_step_idx - 1
                manifest["current_step"] = clean_idx
                self._write_manifest(manifest)
                clean_step = steps[clean_idx]
                clip.hook_applied = bool(clean_step.get("hook_applied", False))
                clean_path = Path(clean_step.get("file_path", ""))
                if clean_path.exists():
                    return clean_path

        # Jika belum ada subtitle atau langkah saat ini adalah edit lanjutan
        return self.get_current_source(clip)

    def push_step(
        self,
        clip: Any,
        action: str,
        label: str,
        temp_file_path: Path,
        new_start_time: float | None = None,
        new_end_time: float | None = None,
        hook_applied: bool | None = None,
    ) -> dict[str, Any]:
        """Simpan hasil render baru ke dalam stack riwayat."""
        manifest = self.init_if_needed(clip)
        current_step_idx = manifest.get("current_step", 0)
        steps = manifest.get("steps", [])

        # Jika user pernah undo lalu melakukan edit baru, truncate redo steps
        if current_step_idx < len(steps) - 1:
            for discarded in steps[current_step_idx + 1:]:
                p = Path(discarded.get("file_path", ""))
                # Jangan hapus file original (step 0)
                if p.exists() and p != Path(clip.file_path):
                    try:
                        p.unlink()
                    except Exception as e:
                        logger.warning("Gagal hapus file redo terbuang %s: %s", p, e)
            steps = steps[:current_step_idx + 1]

        target_step_num = current_step_idx + 1
        ts_slug = int(time.time() * 1000) % 1000000
        step_filename = self.history_dir / f"step_{target_step_num}_{action}_{ts_slug}.mp4"

        # Pindahkan file temp ke tujuan riwayat
        try:
            self.history_dir.mkdir(parents=True, exist_ok=True)
            if temp_file_path.exists():
                shutil.move(str(temp_file_path), str(step_filename))
        except Exception as e:
            logger.warning("Gagal move temp file ke step history: %s", e)

        # Sync ke output edited legacy untuk kompatibilitas
        legacy_edited_path = settings.OUTPUT_DIR / "edited" / f"clip_{self.clip_id}_edited.mp4"
        try:
            legacy_edited_path.parent.mkdir(parents=True, exist_ok=True)
            if step_filename.exists():
                shutil.copy2(str(step_filename), str(legacy_edited_path))
        except Exception as e:
            logger.warning("Gagal sync ke legacy edited file: %s", e)

        step_start = new_start_time if new_start_time is not None else float(clip.start_time or 0.0)
        step_end = new_end_time if new_end_time is not None else float(clip.end_time or 0.0)
        step_hook = hook_applied if hook_applied is not None else bool(getattr(clip, "hook_applied", False))

        new_step_entry = {
            "step": target_step_num,
            "action": action,
            "label": label,
            "file_path": str(step_filename),
            "start_time": step_start,
            "end_time": step_end,
            "hook_applied": step_hook,
            "created_at": time.time(),
        }
        steps.append(new_step_entry)

        # Batasi jumlah maksimal step agar hemat disk
        if len(steps) > self.max_steps + 1:
            # Hapus step paling awal setelah step 0
            evicted = steps.pop(1)
            evicted_p = Path(evicted.get("file_path", ""))
            if evicted_p.exists() and evicted_p != Path(clip.file_path):
                try:
                    evicted_p.unlink()
                except Exception:
                    pass

        current_step_idx = len(steps) - 1
        manifest["current_step"] = current_step_idx
        manifest["steps"] = steps
        self._write_manifest(manifest)

        # Update clip DB record
        clip.edited_file_path = str(step_filename)
        clip.start_time = step_start
        clip.end_time = step_end
        clip.hook_applied = step_hook

        # Invalidate cache thumbnail clip
        self._invalidate_thumbnail_cache()

        return self.get_status(clip)

    def undo(self, clip: Any) -> dict[str, Any]:
        """Rollback 1 langkah mundur ke status sebelumnya."""
        manifest = self.init_if_needed(clip)
        current_step_idx = manifest.get("current_step", 0)
        steps = manifest.get("steps", [])

        if current_step_idx <= 0:
            raise ValidationException("Sudah berada di langkah awal (Klip Original). Tidak bisa undo lebih jauh.")

        current_step_idx -= 1
        target_step = steps[current_step_idx]

        if current_step_idx == 0:
            clip.edited_file_path = None
            legacy_edited_path = settings.OUTPUT_DIR / "edited" / f"clip_{self.clip_id}_edited.mp4"
            if legacy_edited_path.exists():
                try:
                    legacy_edited_path.unlink()
                except Exception:
                    pass
        else:
            clip.edited_file_path = target_step["file_path"]
            legacy_edited_path = settings.OUTPUT_DIR / "edited" / f"clip_{self.clip_id}_edited.mp4"
            try:
                legacy_edited_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target_step["file_path"], str(legacy_edited_path))
            except Exception:
                pass

        clip.start_time = target_step.get("start_time", clip.start_time)
        clip.end_time = target_step.get("end_time", clip.end_time)
        clip.hook_applied = target_step.get("hook_applied", False)

        manifest["current_step"] = current_step_idx
        self._write_manifest(manifest)
        self._invalidate_thumbnail_cache()

        return self.get_status(clip)

    def redo(self, clip: Any) -> dict[str, Any]:
        """Maju 1 langkah ke depan jika langkah sebelumnya pernah di-undo."""
        manifest = self.init_if_needed(clip)
        current_step_idx = manifest.get("current_step", 0)
        steps = manifest.get("steps", [])

        if current_step_idx >= len(steps) - 1:
            raise ValidationException("Sudah berada di langkah paling akhir. Tidak ada redo.")

        current_step_idx += 1
        target_step = steps[current_step_idx]

        clip.edited_file_path = target_step["file_path"]
        legacy_edited_path = settings.OUTPUT_DIR / "edited" / f"clip_{self.clip_id}_edited.mp4"
        try:
            legacy_edited_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target_step["file_path"], str(legacy_edited_path))
        except Exception:
            pass

        clip.start_time = target_step.get("start_time", clip.start_time)
        clip.end_time = target_step.get("end_time", clip.end_time)
        clip.hook_applied = target_step.get("hook_applied", False)

        manifest["current_step"] = current_step_idx
        self._write_manifest(manifest)
        self._invalidate_thumbnail_cache()

        return self.get_status(clip)

    def reset(self, clip: Any, original_start_time: float | None = None, original_end_time: float | None = None) -> dict[str, Any]:
        """Hapus semua riwayat edit dan kembalikan clip ke file original."""
        if self.history_dir.exists():
            try:
                shutil.rmtree(self.history_dir)
            except Exception as e:
                logger.warning("Gagal membersihkan history_dir clip %d: %s", self.clip_id, e)

        legacy_edited_path = settings.OUTPUT_DIR / "edited" / f"clip_{self.clip_id}_edited.mp4"
        if legacy_edited_path.exists():
            try:
                legacy_edited_path.unlink()
            except Exception:
                pass

        clip.edited_file_path = None
        if original_start_time is not None:
            clip.start_time = original_start_time
        if original_end_time is not None:
            clip.end_time = original_end_time
        clip.hook_applied = False

        self._invalidate_thumbnail_cache()
        return self.init_if_needed(clip)

    def get_status(self, clip: Any) -> dict[str, Any]:
        """Ambil ringkasan status riwayat untuk UI."""
        manifest = self.init_if_needed(clip)
        current_step_idx = manifest.get("current_step", 0)
        steps = manifest.get("steps", [])

        current_step = steps[current_step_idx] if 0 <= current_step_idx < len(steps) else {}
        undo_step = steps[current_step_idx - 1] if current_step_idx > 0 else {}
        redo_step = steps[current_step_idx + 1] if current_step_idx < len(steps) - 1 else {}

        return {
            "can_undo": current_step_idx > 0,
            "can_redo": current_step_idx < len(steps) - 1,
            "current_step": current_step_idx,
            "total_steps": len(steps),
            "current_label": current_step.get("label", "Klip Original"),
            "current_action": current_step.get("action", "original"),
            "undo_label": undo_step.get("label"),
            "redo_label": redo_step.get("label"),
            "steps": steps,
        }

    def _invalidate_thumbnail_cache(self) -> None:
        """Hapus cache thumbnail agar crop frame & preview sinkron dengan langkah aktif."""
        cache_file = Path("data/cache/thumbnails") / f"clip_{self.clip_id}.jpg"
        if cache_file.exists():
            try:
                cache_file.unlink()
            except Exception:
                pass
