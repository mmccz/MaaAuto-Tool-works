"""Delta updates: the build side generates a patch package, the run side
(``upgrade.exe``) restores the new files from it.

Design trade-offs
-----------------
* **File level + bsdiff hybrid**: unchanged files never enter the package; a
  changed file ships as a small bsdiff patch when that is cheap enough,
  otherwise as the whole file. Measured 1.1.0 -> 1.1.1: full package 61.2 MB,
  pure file-level 13.1 MB, hybrid about 0.55 MB.
* **Build side** uses ``bsdiff4`` (installed on build machines/CI only); the
  **run side** uses ``bspatch`` (stdlib only), so the updater size stays the same.
* **Safety**: before applying a patch the local old file sha256 is checked
  against the ``base_sha256`` recorded in the package (a locally modified or
  differently built install must be rejected and fall back to the full package);
  after restoring, the new file sha256 is verified too.

Package layout::

    delta.json                       # manifest: format/base/target/files/delete
    patches/<relative path>.bsdiff   # files with mode=patch
    <relative path>                  # files with mode=full
"""

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

from . import bspatch

DELTA_FORMAT = 1
DELTA_MANIFEST = "delta.json"
PATCH_DIR = "patches"

# Above this fraction of the target file a patch is not worth it; ship the whole file
PATCH_THRESHOLD = 0.5
# Even a tiny patch is not worth it (zip header + read/write overhead)
PATCH_MIN_SAVING = 4096


class DeltaError(RuntimeError):
    """Corrupt package, unsupported format, or failed restore verification."""


class BaseMismatch(DeltaError):
    """Local files do not match the base version recorded in the package (a different install)."""


# --------------------------------------------------------------------------- #
# Basic helpers
# --------------------------------------------------------------------------- #
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_rel(name: str) -> str:
    """Reject absolute paths and ``..`` (zip-slip guard)."""
    rel = name.replace("\\", "/").lstrip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise DeltaError(f"非法路径: {name!r}")
    return "/".join(parts)


def index_dir(root: Union[str, Path]) -> Dict[str, Tuple[int, str]]:
    """``relative path -> (byte count, sha256)``."""
    root = Path(root)
    out: Dict[str, Tuple[int, str]] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = (p.stat().st_size, sha256_file(p))
    return out


def index_zip(zip_path: Union[str, Path]) -> Dict[str, Tuple[int, str]]:
    """Index a payload zip directly, without extracting to disk."""
    out: Dict[str, Tuple[int, str]] = {}
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = _safe_rel(info.filename)
            h = hashlib.sha256()
            with zf.open(info) as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            out[rel] = (info.file_size, h.hexdigest())
    return out


def index_of(base: Union[str, Path]) -> Dict[str, Tuple[int, str]]:
    base = Path(base)
    if base.is_dir():
        return index_dir(base)
    if base.suffix.lower() == ".zip":
        return index_zip(base)
    raise DeltaError(f"不支持的基准: {base}")


def _read_base_file(base: Path, rel: str) -> bytes:
    if base.is_dir():
        return (base / rel).read_bytes()
    with zipfile.ZipFile(base) as zf:
        return zf.read(rel)


# --------------------------------------------------------------------------- #
# Build side
# --------------------------------------------------------------------------- #
def build_delta(new_payload_dir: Union[str, Path],
                base: Union[str, Path],
                out_zip: Union[str, Path],
                target_version: str,
                base_version: str,
                log: Optional[Callable[[str], None]] = None,
                threshold: float = PATCH_THRESHOLD) -> dict:
    """Build the delta package for ``base`` -> ``new_payload_dir``; return stats.

    :param base: previous payload (``.zip`` or an extracted directory)
    """
    new_dir = Path(new_payload_dir)
    out_zip = Path(out_zip)
    base = Path(base)

    def _log(msg: str) -> None:
        if log:
            try:
                log(msg)
            except Exception:
                pass

    try:
        import bsdiff4  # build side only
    except Exception:
        bsdiff4 = None
        _log("未安装 bsdiff4：本次只做文件级差分（不带二进制补丁）")

    base_idx = index_of(base)
    new_idx = index_dir(new_dir)

    entries: List[dict] = []
    deleted = sorted(rel for rel in base_idx if rel not in new_idx)
    patched = full = 0
    raw_changed = 0

    if out_zip.exists():
        out_zip.unlink()
    out_zip.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_LZMA) as zf:
        for rel in sorted(new_idx):
            size, digest = new_idx[rel]
            old = base_idx.get(rel)
            if old and old[1] == digest:
                continue                      # content unchanged
            data = (new_dir / rel).read_bytes()
            raw_changed += len(data)
            entry = {"path": rel, "sha256": digest, "size": size}

            if bsdiff4 is not None and old is not None:
                try:
                    patch = bsdiff4.diff(_read_base_file(base, rel), data)
                except Exception as e:        # tiny/odd file, fall back to the whole file
                    _log(f"  bsdiff 失败，整文件带走 {rel}: {e}")
                    patch = None
                if patch is not None and len(patch) < min(
                        size * threshold, size - PATCH_MIN_SAVING):
                    zf.writestr(f"{PATCH_DIR}/{rel}.bsdiff", patch)
                    entry.update(mode="patch", base_sha256=old[1], patch_size=len(patch))
                    entries.append(entry)
                    patched += 1
                    continue

            zf.writestr(rel, data)
            entry.update(mode="full")
            entries.append(entry)
            full += 1

        zf.writestr(DELTA_MANIFEST, json.dumps({
            "format": DELTA_FORMAT,
            "base_version": base_version,
            "target_version": target_version,
            "delete": deleted,
            "files": entries,
        }, ensure_ascii=False, indent=2))

    stat = {
        "path": str(out_zip),
        "size": out_zip.stat().st_size,
        "patch_files": patched,
        "full_files": full,
        "deleted": len(deleted),
        "raw_changed": raw_changed,
        "base_version": base_version,
        "target_version": target_version,
    }
    _log(f"delta: {patched} 个补丁文件 + {full} 个整文件，"
         f"{stat['size'] / 1048576:.2f} MB（变更原始 {raw_changed / 1048576:.2f} MB）")
    return stat


# --------------------------------------------------------------------------- #
# Run side
# --------------------------------------------------------------------------- #
def read_manifest_from_zip(delta_zip: Union[str, Path]) -> dict:
    with zipfile.ZipFile(delta_zip) as zf:
        try:
            meta = json.loads(zf.read(DELTA_MANIFEST).decode("utf-8"))
        except KeyError:
            raise DeltaError("补丁包里没有 delta.json")
    if meta.get("format") != DELTA_FORMAT:
        raise DeltaError(f"不支持的补丁格式: {meta.get('format')!r}")
    if not meta.get("files"):
        raise DeltaError("补丁包里没有任何文件")
    return meta


def materialize(delta_zip: Union[str, Path],
                install_dir: Union[str, Path],
                stage_dir: Union[str, Path],
                log: Optional[Callable[[str], None]] = None,
                progress: Optional[Callable[[int, int], None]] = None,
                cancel_check: Optional[Callable[[], bool]] = None) -> Tuple[int, List[str]]:
    """Restore the package into a tree holding only the changed files.

    :return: ``(restored file count, list of relative paths to delete)``
    :raises BaseMismatch: local files do not match the base (fall back to the full package)
    :raises DeltaError: corrupt patch or failed restore verification
    """
    install_dir = Path(install_dir)
    stage_dir = Path(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    def _log(msg: str) -> None:
        if log:
            try:
                log(msg)
            except Exception:
                pass

    meta = read_manifest_from_zip(delta_zip)
    files = meta["files"]
    total = len(files)

    with zipfile.ZipFile(delta_zip) as zf:
        for idx, entry in enumerate(files, 1):
            if cancel_check and cancel_check():
                raise DeltaError("用户取消")
            rel = _safe_rel(entry["path"])
            dst = stage_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)

            if entry.get("mode") == "patch":
                base_file = install_dir / rel
                if not base_file.exists():
                    raise BaseMismatch(f"本地缺少基准文件: {rel}")
                if sha256_file(base_file) != entry.get("base_sha256"):
                    raise BaseMismatch(f"本地文件与基准版本不一致: {rel}")
                patch = zf.read(f"{PATCH_DIR}/{rel}.bsdiff")
                data = bspatch.apply_patch(base_file.read_bytes(), patch)
            else:
                data = zf.read(rel)

            if sha256_bytes(data) != entry.get("sha256"):
                raise DeltaError(f"还原结果校验失败: {rel}")
            dst.write_bytes(data)

            if progress:
                progress(idx, total)
            if idx % 100 == 0:
                _log(f"还原补丁 {idx}/{total}")

    return total, list(meta.get("delete") or [])
