"""
版本检查（GitHub Release API）。

与 MaaAutoInstaller 的对齐约定（2026-09 冻结）：
  - 只做「检查 + 展示」，不做「下载 + 替换」
  - 用户确认升级 → 调起 <install>/upgrade.exe（方案 B）
  - 版本比较用 packaging.version，非法版本号 → 视为检查失败
  - 挑 asset 优先 MaaAuto_Source.zip，其次 win+.zip，再次任意 .zip
"""
import os
import sys
import json
import logging
import subprocess
import urllib.request

from packaging.version import Version, InvalidVersion

from app_info import APP_VERSION, APP_UPDATE_API, APP_SOURCE_ASSET

logger = logging.getLogger("MaaAuto")

_UA = "MaaAuto-UpdateChecker/1.0"


# --------------------------------------------------------------------------- #
# GitHub API
# --------------------------------------------------------------------------- #
def _fetch_latest_release(timeout=15):
    req = urllib.request.Request(
        APP_UPDATE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _UA,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


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


def _pick_asset(release):
    """
    三级优先：
      1) name == MaaAuto_Source.zip
      2) name 含 'win' 且以 .zip 结尾（大小写不敏感）
      3) 任意 .zip
    """
    assets = release.get("assets") or []

    for a in assets:
        if a.get("name") == APP_SOURCE_ASSET:
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
def check_update():
    """
    返回 dict 或 None：
      {
        "has_update": bool,
        "current":    "2.0.1",
        "latest":     "2.1.0",
        "tag":        "v2.1.0",
        "asset":      {...} | None,
        "notes":      "release body",
        "html_url":   "https://...",
      }
    任何网络/解析失败 → None。
    """
    try:
        release = _fetch_latest_release()
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
        "asset": _pick_asset(release),
        "notes": release.get("body", "") or "",
        "html_url": release.get("html_url", "") or "",
    }


def apply_update(parent=None, silent=False):
    """
    方案 B + 变更 2：调起 upgrade.exe，主程序随后退出。
      --from-main  必须
      --restart    默认带（用户要求升级完必重启主程序）
      --silent     自动升级路径传 True
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

    try:
        subprocess.Popen(args, cwd=install_dir)
        logger.info(f"已调起升级器: {' '.join(args)}")
        return True
    except Exception as e:
        logger.error(f"调起升级器失败: {e}")
        if not silent:
            QMessageBox.critical(parent, "MaaAuto", f"无法启动升级器：\n{e}")
        return False