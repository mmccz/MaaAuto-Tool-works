"""Windows version detection (fixed in 1.4.1).

The About page used ``platform.release()`` + ``platform.version()``, which on
Windows 11 reported ``Windows 10 10.0.22631``: Microsoft never updated
``platform.release()`` (it reads ``GetVersionEx``, pinned to 6.2/10.0 by the
compatibility layer), so the API stopped matching the real brand at Windows 8.1.

Everything now comes from the registry ``HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion``,
using the real fields plus a **build-number** check for Windows 10 vs 11:

    build 10240 .. 19045  -> Windows 10 (21H2 / 22H2 included)
    build 20348           -> Windows Server 2022 (a 10 kernel; do not call it 11)
    build >= 22000        -> Windows 11 (24H2 / 25H2, Server 2025 likewise)

Note that the registry ``ProductName`` still says ``Windows 10`` on Windows 11
(a known Microsoft issue), so the build number decides - never copy it verbatim.

The module **reads the local registry only**, no network, no subprocess; on error it falls back to ``platform``.
"""

import platform
import sys

_WIN_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"

# first Windows 11 build (22000 = the first 21H2 release)
WIN11_MIN_BUILD = 22000

_PRODUCT_WORKSTATION = 1
_PRODUCT_SERVER = 3


def _read_registry() -> dict:
    """Version strings from the registry; {} on non-Windows or on failure."""
    if not sys.platform.startswith("win"):
        return {}
    try:
        import winreg
    except Exception:
        return {}

    data = {}
    try:
        # 64-bit view, so even a 32-bit Python (old machines) never lands in WOW6432Node
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
    """(major, minor, build, product_type) from ``sys.getwindowsversion()``."""
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
    """Correct the registry ProductName to the real brand name (pure function, easy to test).

    * ``Windows 10 xxx`` with build >= 22000 and not a Server -> ``Windows 11 xxx``
    * Servers are never touched (Server 2022 is 20348, a 10 kernel anyway)
    * a missing ProductName gets a sensible name from the build number
    """
    name = (product_name or "").strip()
    if not name:
        if is_server:
            return "Windows Server"
        return "Windows 11" if build >= WIN11_MIN_BUILD else "Windows 10"

    lowered = name.lower()
    looks_server = is_server or "server" in lowered
    if build >= WIN11_MIN_BUILD and not looks_server and "11" not in lowered:
        # replace only the leading brand words; keep the edition text ("Pro" etc.) as is
        for old in ("Windows 10", "Windows 8.1", "Windows 8", "Windows 7"):
            if name.startswith(old):
                return "Windows 11" + name[len(old):]
        return name
    return name


def windows_info() -> dict:
    """System info dict for this machine (all keys present; missing values are ""/0)."""
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
    # without product_type a Server is often reported as 1, so fall back to the name

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
    """One-line display text, e.g. ``Windows 11 Pro 23H2 (10.0.22631.4317)``.

    When the registry is unreadable it falls back to a ``platform`` combination, so the
    result is at least never blank.
    """
    info = windows_info()
    if not info["build"]:
        # non-Windows, or an unreadable registry (only non-Windows should get here)
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
