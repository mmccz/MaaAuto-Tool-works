"""系统版本识别（1.4.1 修复）。

以前「关于」页直接用 ``platform.release()`` + ``platform.version()``，在
Windows 11 上会显示成 ``Windows 10 10.0.22631`` —— 因为微软没让
``platform.release()`` 跟着改（它读的是 ``GetVersionEx``，被兼容层
钉死在 6.2/10.0 上），所以从 Windows 8.1 起这个 API 就对不上真实品牌名了。

现在统一从注册表 ``HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion``
读真实字段，并用**构建号**判断到底是 Windows 10 还是 11：

    构建 10240 ~ 19045  → Windows 10（含 21H2/22H2）
    构建 20348          → Windows Server 2022（10 内核，别误判成 11）
    构建 >= 22000       → Windows 11（含 24H2/25H2，Server 2025 同理）

注意注册表里的 ``ProductName`` 在 Windows 11 上也仍然写着 ``Windows 10``
（微软官方承认的已知问题），所以必须按构建号纠正，不能照抄。

整个模块**只读本机注册表**，不联网、不启子进程，异常时退回 ``platform``。
"""

import platform
import sys

_WIN_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"

# Windows 11 的起始构建号（22000 = 21H2 首个正式版）
WIN11_MIN_BUILD = 22000

_PRODUCT_WORKSTATION = 1
_PRODUCT_SERVER = 3


def _read_registry() -> dict:
    """读注册表里的版本文案；非 Windows 或读取失败返回空 dict。"""
    if not sys.platform.startswith("win"):
        return {}
    try:
        import winreg
    except Exception:
        return {}

    data = {}
    try:
        # 64 位视图：32 位 Python（老机器）下也不会跑到 WOW6432Node
        access = winreg.KEY_READ
        access |= getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _WIN_KEY, 0, access) as key:
            for name, field in (("ProductName", "product_name"),
                                ("EditionID", "edition_id"),
                                ("DisplayVersion", "display_version"),
                                ("ReleaseId", "release_id"),
                                ("CurrentBuildNumber", "build"),
                                ("CurrentBuild", "build"),
                                ("CurrentMajorVersionNumber", "major"),
                                ("CurrentMinorVersionNumber", "minor")):
                if field in data:
                    continue
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                if value not in (None, ""):
                    data[field] = value
            try:
                ubr, _ = winreg.QueryValueEx(key, "UBR")
                data["ubr"] = int(ubr)
            except (OSError, TypeError, ValueError):
                pass
    except OSError:
        return data
    return data


def _win_version_tuple():
    """``sys.getwindowsversion()`` 的 (major, minor, build, product_type)。"""
    getter = getattr(sys, "getwindowsversion", None)
    if getter is None:
        return None
    try:
        v = getter()
    except Exception:
        return None
    return (getattr(v, "major", 0), getattr(v, "minor", 0),
            getattr(v, "build", 0), getattr(v, "product_type", 0))


def version_label(product_name: str, build: int, is_server: bool = False) -> str:
    """把注册表的 ProductName 纠正成真实的品牌名（纯函数，方便测试）。

    * ``Windows 10 xxx`` + 构建 >= 22000 且不是 Server → ``Windows 11 xxx``
    * Server 一律不动（Server 2022 是 20348，本来就是 10 内核）
    * ProductName 缺失时按构建号给个合理的名字
    """
    name = (product_name or "").strip()
    if not name:
        if is_server:
            return "Windows Server"
        return "Windows 11" if build >= WIN11_MIN_BUILD else "Windows 10"

    lowered = name.lower()
    looks_server = is_server or "server" in lowered
    if build >= WIN11_MIN_BUILD and not looks_server and "11" not in lowered:
        # 只替换开头的品牌词，后面的「专业版 / Pro」原样保留
        for old in ("Windows 10", "Windows 8.1", "Windows 8", "Windows 7"):
            if name.startswith(old):
                return "Windows 11" + name[len(old):]
        return name
    return name


def windows_info() -> dict:
    """返回本机系统信息 dict（字段齐全，取不到的用空串/0）。"""
    reg = _read_registry()
    ver = _win_version_tuple()

    major = int(reg.get("major") or (ver[0] if ver else 0) or 0)
    minor = int(reg.get("minor") or (ver[1] if ver else 0) or 0)
    build = 0
    for raw in (reg.get("build"), ver[2] if ver else None):
        try:
            build = int(str(raw).split(".")[0])
        except (TypeError, ValueError):
            continue
        if build:
            break

    product_type = ver[3] if ver else 0
    product_name = str(reg.get("product_name") or "")
    is_server = product_type == _PRODUCT_SERVER or "server" in product_name.lower()
    # 读不到 product_type 时，Server 也常被报成 1，只能靠名字兜底

    name = version_label(product_name, build, is_server)
    display_version = str(reg.get("display_version") or reg.get("release_id") or "")
    ubr = int(reg.get("ubr") or 0)

    numeric = f"{major}.{minor}.{build}" if build else ""
    full = f"{numeric}.{ubr}" if numeric and ubr else numeric

    return {
        "name": name,
        "edition_id": str(reg.get("edition_id") or ""),
        "display_version": display_version,
        "major": major,
        "minor": minor,
        "build": build,
        "ubr": ubr,
        "numeric": full,
        "is_server": is_server,
    }


def describe_system() -> str:
    """一行展示用文案，例如 ``Windows 11 专业版 23H2 (10.0.22631.4317)``。

    注册表完全读不到时退回 ``platform`` 的组合，至少不会显示成空白。
    """
    info = windows_info()
    if not info["build"]:
        # 非 Windows 或注册表读不到（理论上只有非 Windows 会走到这里）
        bits = " ".join(x for x in (platform.system(), platform.release()) if x)
        ver = platform.version()
        if ver and ver not in bits:
            return f"{bits} ({ver})" if bits else ver
        return bits or "-"

    head = info["name"]
    if info["display_version"]:
        head = f"{head} {info['display_version']}"
    if info["numeric"]:
        head = f"{head} ({info['numeric']})"
    return head
