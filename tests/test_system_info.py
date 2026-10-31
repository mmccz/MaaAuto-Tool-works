"""System version detection tests (1.4.1 fix).

Bug: on Windows 11 the "About" page showed ``Windows 10 10.0.22631``.
Root cause: ``platform.release()`` reads ``GetVersionEx``, which the compatibility layer
pins, so it has not matched the brand name since Windows 8.1; meanwhile the registry
``ProductName`` still says ``Windows 10`` on Windows 11. Only the **build number** can
correct it.
"""

import os
import sys

import pytest

APP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "MaaAutoProject")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import system_info  # noqa: E402


# --------------------------------------------------------------------------- #
# Brand-name correction (pure function)
# --------------------------------------------------------------------------- #
def test_win11_registry_name_is_corrected_from_win10():
    """On Win11 the registry ProductName still says "Windows 10 Pro"; the build number must correct it."""
    assert system_info.version_label(
        "Windows 10 专业版", 22631) == "Windows 11 专业版"
    assert system_info.version_label("Windows 10 Pro", 26100) == "Windows 11 Pro"


def test_win10_stays_win10():
    assert system_info.version_label(
        "Windows 10 Home", 19045) == "Windows 10 Home"
    assert system_info.version_label(
        "Windows 10 家庭中文版", 19044) == "Windows 10 家庭中文版"


def test_win11_build_boundary():
    """22000 is the first GA build of Win11 21H2; 21999 is still Win10."""
    assert system_info.version_label("Windows 10 Pro", 21999) == "Windows 10 Pro"
    assert system_info.version_label("Windows 10 Pro", 22000) == "Windows 11 Pro"


def test_server_is_never_relabelled():
    """Server 2022 is build 20348 (10 kernel) and must not be called Windows 11."""
    assert system_info.version_label(
        "Windows Server 2022 Datacenter", 20348) == "Windows Server 2022 Datacenter"
    # Server 2025 is build 26100; its name is already right, so leave it alone
    assert system_info.version_label(
        "Windows Server 2025 Standard", 26100) == "Windows Server 2025 Standard"
    # Even with is_server passed explicitly, do not rename
    assert system_info.version_label(
        "Windows 10", 22631, is_server=True) == "Windows 10"


def test_already_win11_name_untouched():
    assert system_info.version_label(
        "Windows 11 Pro", 28000) == "Windows 11 Pro"


def test_missing_product_name_falls_back_to_build():
    assert system_info.version_label("", 26100) == "Windows 11"
    assert system_info.version_label("", 19045) == "Windows 10"
    assert system_info.version_label("", 20348, is_server=True) == "Windows Server"


# --------------------------------------------------------------------------- #
# windows_info / describe_system (stubbed registry)
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_machine(monkeypatch):
    def _apply(**reg):
        monkeypatch.setattr(system_info, "_read_registry", lambda: dict(reg))
        monkeypatch.setattr(system_info, "_win_version_tuple",
                            lambda: (10, 0, int(reg.get("build") or 0), 1))
    return _apply


def test_windows_info_win11(fake_machine):
    fake_machine(product_name="Windows 10 专业版", edition_id="Professional",
                 display_version="23H2", build="22631", ubr=4317)
    info = system_info.windows_info()
    assert info["name"] == "Windows 11 专业版"
    assert info["display_version"] == "23H2"
    assert info["build"] == 22631
    assert info["numeric"] == "10.0.22631.4317"
    assert info["is_server"] is False


def test_windows_info_without_ubr(fake_machine):
    fake_machine(product_name="Windows 10 Pro", build="19045")
    info = system_info.windows_info()
    assert info["name"] == "Windows 10 Pro"
    assert info["numeric"] == "10.0.19045"
    assert info["display_version"] == ""


def test_describe_system_format(fake_machine):
    fake_machine(product_name="Windows 10 专业版", display_version="24H2",
                 build="26100", ubr=1742)
    assert system_info.describe_system() == "Windows 11 专业版 24H2 (10.0.26100.1742)"


def test_describe_system_has_no_duplicated_version(fake_machine):
    """The old implementation emitted ``Windows 10 10.0.22631 (10.0.22631)``: duplicated and with the wrong brand."""
    fake_machine(product_name="Windows 10 Pro", display_version="23H2",
                 build="22631", ubr=100)
    text = system_info.describe_system()
    assert text.count("10.0.22631") == 1
    assert not text.startswith("Windows 10 10.0")


def test_describe_system_fallback_when_registry_empty(monkeypatch):
    monkeypatch.setattr(system_info, "_read_registry", lambda: {})
    monkeypatch.setattr(system_info, "_win_version_tuple", lambda: None)
    text = system_info.describe_system()
    assert text and text != "-"


# --------------------------------------------------------------------------- #
# Live smoke test: whatever this machine is, the display name must agree with the build number
# --------------------------------------------------------------------------- #
def test_live_consistency():
    info = system_info.windows_info()
    if not info["build"]:
        pytest.skip("注册表不可读（非 Windows 环境）")
    is_11 = info["build"] >= system_info.WIN11_MIN_BUILD
    if not info["is_server"]:
        if is_11:
            assert "Windows 11" in info["name"], info
        else:
            assert "Windows 11" not in info["name"], info
    assert system_info.describe_system()
