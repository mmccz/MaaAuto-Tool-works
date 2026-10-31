"""Version check via the GitHub Release API.

Rules:
  - check and display only, never download or replace
  - user confirms an upgrade -> launch <install>/upgrade.exe
  - versions compare through packaging.version; an invalid version fails the check
  - channels: stable reads releases/latest only; beta reads the releases list (prereleases too)
"""
import os
import sys
import json
import logging
import subprocess
import urllib.request

from packaging.version import Version, InvalidVersion

from app_info import APP_VERSION, APP_UPDATE_API, APP_PAYLOAD_ASSET_PREFIX

logger = logging.getLogger("MaaAuto")

_UA = "MaaAuto-UpdateChecker/1.0"

# /releases/latest -> /releases (used by the beta channel)
RELEASES_LIST_API = APP_UPDATE_API.rstrip("/")
if RELEASES_LIST_API.endswith("/latest"):
    RELEASES_LIST_API = RELEASES_LIST_API[: -len("/latest")]


# --------------------------------------------------------------------------- #
# GitHub API
# --------------------------------------------------------------------------- #
def _fetch_json(url, timeout=15):
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _UA,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_latest_release(channel="stable", timeout=15):
    if channel != "beta":
        return _fetch_json(APP_UPDATE_API, timeout)

    releases = _fetch_json(RELEASES_LIST_API, timeout)
    if not isinstance(releases, list):
        return {}
    candidates = []
    for rel in releases:
        if rel.get("draft"):
            continue
        version = _parse_version(rel.get("tag_name", ""))
        if version is not None:
            candidates.append((version, rel))
    if not candidates:
        return {}
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _parse_version(tag):
    """Normalise a tag into a Version; None on failure.
    Accepts: v2.0.1 / 2.0.1 / 2.1.0b1 / 2.1.0rc2 / 2.1.0.post1
    Rejects: 2.1.0-beta / garbage / empty
    """
    v = (tag or "").strip().lstrip("vV")
    if not v:
        return None
    try:
        return Version(v)
    except InvalidVersion:
        logger.warning(f"无法解析版本号: {tag!r}（建议使用 PEP 440 格式，如 2.1.0b1）")
        return None


def _pick_asset(release, latest_version=""):
    """Priority order (since 3.0.0):
      1) name == MaaAuto_payload_v{latest}.zip - the prebuilt payload the upgrader downloads
      2) name == MaaAuto_Source.zip            - the 2.x transitional source package
      3) name contains 'win' and ends with .zip
      4) any .zip

    The result is only for **display** (the About page shows the package size); the real
    download re-queries the Release inside upgrade.exe, so a wrong pick here is harmless.
    """
    assets = release.get("assets") or []
    want = f"{APP_PAYLOAD_ASSET_PREFIX}{latest_version}.zip".lower()

    if latest_version:
        for a in assets:
            if (a.get("name") or "").lower() == want:
                return a

    for a in assets:
        name = (a.get("name") or "").lower()
        if "win" in name and name.endswith(".zip"):
            return a

    for a in assets:
        if (a.get("name") or "").lower().endswith(".zip"):
            return a

    return None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def check_update(channel="stable"):
    """Returns a dict, or None:
      {
        "has_update": bool,
        "current":    "1.0.0",
        "latest":     "1.0.1",
        "tag":        "v1.0.1",
        "asset":      {...} | None,
        "notes":      "release body",
        "html_url":   "https://...",
        "channel":    "stable" | "beta",
      }

    ``beta`` reads the Release list including prereleases; ``stable`` reads latest only.
    Any network or parsing failure -> None.
    """
    try:
        release = _fetch_latest_release(channel)
    except Exception as e:
        logger.warning(f"检查更新失败（网络）: {e}")
        return None

    latest = _parse_version(release.get("tag_name", ""))
    current = _parse_version(APP_VERSION)
    if latest is None or current is None:
        logger.warning("版本解析失败，跳过更新检查。")
        return None

    return {
        "has_update": latest > current,
        "current": str(current),
        "latest": str(latest),
        "tag": release.get("tag_name", ""),
        "asset": _pick_asset(release, str(latest)),
        "notes": release.get("body", "") or "",
        "html_url": release.get("html_url", "") or "",
        "channel": channel,
    }


def apply_update(parent=None, silent=False, channel="stable"):
    """Launch upgrade.exe; the app then exits.
      --from-main  required
      --restart    always passed (restarts the app afterwards)
      --silent     True on the automatic upgrade path
      --channel    stable / beta (beta looks at prereleases)
    True means upgrade.exe was Popen'ed successfully.
    """
    from PySide6.QtWidgets import QMessageBox

    # after an onedir build __file__ lives in _internal/, so sys.executable is safer
    install_dir = os.path.dirname(os.path.abspath(sys.executable))
    upgrade_exe = os.path.join(install_dir, "upgrade.exe")

    if not os.path.exists(upgrade_exe):
        if not silent:
            QMessageBox.warning(
                parent, "MaaAuto",
                "未找到 upgrade.exe。\n\n"
                "请重新下载完整安装包以启用自动升级功能。",
            )
        return False

    args = [upgrade_exe, "--from-main", "--restart"]
    if silent:
        args.append("--silent")
    if channel and channel != "stable":
        args += ["--channel", channel]

    try:
        subprocess.Popen(args, cwd=install_dir)
        logger.info(f"已调起升级器: {' '.join(args)}")
        return True
    except Exception as e:
        logger.error(f"调起升级器失败: {e}")
        if not silent:
            QMessageBox.critical(parent, "MaaAuto", f"无法启动升级器：\n{e}")
        return False