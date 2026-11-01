"""
Read/write .maaauto.json.
This file is the contract between the installer and the updater.

MANIFEST_VERSION history:
  1 -> initial version
  2 -> added requirements_hash / mirror
  3 -> added release_channel / last_checked_at / last_upgrade_from / source_hash
      (frozen with MaaAutoProject in 2026-09)
"""

import json
import datetime
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional


MANIFEST_NAME = ".maaauto.json"
MANIFEST_VERSION = 3


@dataclass
class Manifest:
    # ---- versions ----
    version: str = "0.0.0"              # MaaAuto main app version
    installer_version: str = "0.0.0"    # installer/updater version
    manifest_version: int = MANIFEST_VERSION

    # ---- paths ----
    install_dir: str = ""
    app_exe: str = ""                   # <install>/MaaAuto.exe
    uninstall_exe: str = ""             # <install>/uninstall.exe
    upgrade_exe: str = ""               # <install>/upgrade.exe

    # ---- dependency info ----
    requirements_hash: str = ""         # sha256 of requirements.txt
    mirror: str = ""                    # PyPI mirror key used at install time

    # ---- timestamps ----
    installed_at: str = ""
    updated_at: str = ""

    # ---- upgrade-related (added in v3) ----
    release_channel: str = "stable"     # stable / beta
    last_checked_at: str = ""           # last update check time
    last_upgrade_from: str = ""         # version before the last upgrade
    source_hash: str = ""               # sha256 of MaaAuto_Source.zip for this version

    # ---- reserved ----
    extra: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def write(self, install_dir: Path) -> Path:
        path = Path(install_dir) / MANIFEST_NAME
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, data: dict) -> "Manifest":
        valid = set(cls.__dataclass_fields__.keys())
        filtered = {k: v for k, v in (data or {}).items() if k in valid}
        return cls(**filtered)


def read_manifest(install_dir: Path) -> Optional[Manifest]:
    path = Path(install_dir) / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Manifest.from_dict(data)
    except Exception:
        return None


def write_manifest(install_dir: Path, manifest: Manifest) -> Path:
    now = datetime.datetime.now().isoformat(timespec="seconds")
    if not manifest.installed_at:
        manifest.installed_at = now
    manifest.updated_at = now
    return manifest.write(install_dir)