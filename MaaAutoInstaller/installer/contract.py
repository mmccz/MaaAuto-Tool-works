"""Frozen contract between the installer and ``MaaAutoProject/app_info.py``.

These values are written into the ``extra`` block of ``.maaauto.json`` in the
install directory; the updater only reads them from there afterwards.
Protocol agreement (unified to the 1.0.0 baseline on 2026-10-24):

* ``APP_UPDATE_API``            == ``extra.update_api``
* ``APP_MIN_INSTALLER_VERSION`` == ``extra.min_installer_version``
* ``APP_PAYLOAD_ASSET_PREFIX``  == ``extra.payload_asset_prefix``
* ``APP_DELTA_ASSET_PREFIX``    == ``extra.delta_asset_prefix`` (delta asset naming)

Changing any value is a protocol change and requires releasing both sides
together; the build enforces it strictly via
``build_release.py::check_app_info_contract()``.
"""

from typing import Dict


def default_manifest_extra() -> Dict[str, object]:
    """Return a fresh copy of the default ``Manifest.extra`` (callers may mutate it)."""
    return {
        "github_url": "https://github.com/mmccz/MaaAuto-Tool-works",
        "update_api": "https://api.github.com/repos/mmccz/MaaAuto-Tool-works/releases/latest",
        "release_channel": "stable",
        "launch_args": [],
        "payload_asset_prefix": "MaaAuto_payload_v",
        "delta_asset_prefix": "MaaAuto_delta_v",
        "setup_asset_prefix": "MaaAuto_Setup_v",
        "min_installer_version": "1.0.0",
    }


# extra key -> app_info.py constant name (asserted at build time)
APP_INFO_CONSTANTS = {
    "update_api": "APP_UPDATE_API",
    "min_installer_version": "APP_MIN_INSTALLER_VERSION",
    "payload_asset_prefix": "APP_PAYLOAD_ASSET_PREFIX",
    "delta_asset_prefix": "APP_DELTA_ASSET_PREFIX",
}
