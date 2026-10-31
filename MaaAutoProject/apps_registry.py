"""维护「设置 → 应用」里的 MaaAuto 记录（D-2 自愈）。

**为什么要它**：自动升级只替换程序文件、不跑 Inno 安装器，所以卸载项里的
``DisplayVersion`` 会永远停在**安装时**的版本——用户升到 1.4.2 了，「设置→应用」
里还写着 1.4.1（2026-10-31 复核发现）。

**怎么修**：主程序每次启动时找一次卸载项，只有 ``InstallLocation`` 正好指向
自己时才把 ``DisplayVersion`` / ``DisplayIcon`` / ``VersionMajor`` / ``VersionMinor``
更新到当前版本。写入失败只记 DEBUG，绝不影响启动；不是 Windows 直接跳过。

只碰 ``HKCU``（本安装是 per-user 安装），不需要管理员。
"""

import os
from typing import Dict

APP_DISPLAY_NAME = "MaaAuto"
MAIN_EXE = "MaaAuto.exe"
UNINSTALL_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


def _norm(path: object) -> str:
    """路径归一化，用于比较登记目录与实际安装目录。"""
    try:
        text = str(path).strip().strip('"')
        if not text:
            return ""
        return os.path.normcase(os.path.abspath(text)).rstrip("\\/")
    except Exception:
        return ""


def _version_parts(text: str):
    out = []
    for piece in str(text or "").split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return out


def updates_for(values: Dict[str, object], app_version: str,
                install_dir: str) -> Dict[str, object]:
    """算出卸载项里需要改写的值；不需要/不是自己这条时返回 ``{}``。

    纯函数：不读注册表，方便单测。
    """
    if not app_version:
        return {}
    if str(values.get("DisplayName", "")).strip() != APP_DISPLAY_NAME:
        return {}
    loc = values.get("InstallLocation") or values.get("Inno Setup: App Path") or ""
    if _norm(loc) != _norm(install_dir):
        return {}

    out: Dict[str, object] = {}
    if str(values.get("DisplayVersion", "")) != app_version:
        out["DisplayVersion"] = app_version

    icon = os.path.join(os.path.abspath(install_dir), MAIN_EXE)
    if _norm(values.get("DisplayIcon", "")) != _norm(icon):
        out["DisplayIcon"] = icon

    parts = _version_parts(app_version) + [0, 0]
    if values.get("VersionMajor") != parts[0]:
        out["VersionMajor"] = parts[0]
    if values.get("VersionMinor") != parts[1]:
        out["VersionMinor"] = parts[1]
    return out


def _enum_subkeys(root, path: str):
    import winreg
    names = []
    try:
        with winreg.OpenKey(root, path) as key:
            index = 0
            while True:
                try:
                    names.append(winreg.EnumKey(key, index))
                    index += 1
                except OSError:
                    break
    except OSError:
        pass
    return names


def _read_values(root, path: str):
    import winreg
    values = {}
    try:
        with winreg.OpenKey(root, path) as key:
            index = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, index)
                    index += 1
                    values[name] = value
                except OSError:
                    break
    except OSError:
        return None
    return values


def sync_display_version(app_version: str, install_dir: str) -> bool:
    """把指向 ``install_dir`` 的卸载项版本号刷成 ``app_version``。

    返回是否真的写了注册表。任何异常都吞掉（这是展示信息，不该影响启动）。
    """
    if os.name != "nt":
        return False
    try:
        import winreg
    except Exception:
        return False

    root = winreg.HKEY_CURRENT_USER
    for name in _enum_subkeys(root, UNINSTALL_ROOT):
        path = UNINSTALL_ROOT + "\\" + name
        values = _read_values(root, path)
        if not values:
            continue
        updates = updates_for(values, app_version, install_dir)
        if not updates:
            continue
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_SET_VALUE) as key:
                for key_name, value in updates.items():
                    kind = (winreg.REG_DWORD
                            if isinstance(value, int) else winreg.REG_SZ)
                    winreg.SetValueEx(key, key_name, 0, kind, value)
            return True
        except OSError:
            return False
    return False
