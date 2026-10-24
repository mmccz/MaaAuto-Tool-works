"""
版本检查（GitHub Release API）。

约定：
  - 只做「检查 + 展示」，不做「下载 + 替换」
  - 用户确认升级 → 调起 <install>/upgrade.exe
  - 版本比较用 packaging.version，非法版本号 → 视为检查失败
  - 频道：stable 只看 releases/latest；beta 看 releases 列表（含 prerelease）
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

# /releases/latest → /releases（用于 beta 频道）
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
    """
    规整 tag → Version。失败返回 None。
    支持：v2.0.1 / 2.0.1 / 2.1.0b1 / 2.1.0rc2 / 2.1.0.post1
    拒绝：2.1.0-beta / garbage / 空
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
    """
    优先级（3.0.0 起）：
      1) name == MaaAuto_payload_v{latest}.zip —— 升级器真正下载的预构建包
      2) name == MaaAuto_Source.zip            —— 2.x 过渡期的源码包
      3) name 含 'win' 且以 .zip 结尾
      4) 任意 .zip

    这里的结果只用于**展示**（「关于」页提示升级包大小）；真正的下载由
    upgrade.exe 自己重新查询 Release 决定，因此本函数选错也不影响升级。
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
# 对外
# --------------------------------------------------------------------------- #
def check_update(channel="stable"):
    """
    返回 dict 或 None：
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

    ``beta`` 频道会看 Release 列表并包含 prerelease；``stable`` 只看 latest。
    任何网络/解析失败 → None。
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
    """
    调起 upgrade.exe，主程序随后退出。
      --from-main  必须
      --restart    默认带（升级完重启主程序）
      --silent     自动升级路径传 True
      --channel    stable / beta（beta 会看 prerelease）
    返回 True 表示已成功 Popen upgrade.exe。
    """
    from PySide6.QtWidgets import QMessageBox

    # onedir 打包后 __file__ 在 _internal/ 里，用 sys.executable 更稳
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