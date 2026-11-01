"""core: all installer/updater business logic, no GUI dependency.

Since 3.0.0 only these pieces remain:

* ``manifest``    -- read/write ``.maaauto.json``
* ``payload``     -- update core (check version / download / verify / replace / roll back)
* ``downloader``  -- HTTP download with progress
* ``delta``       -- delta package generation (build side) and restore (run side)
* ``bspatch``     -- apply BSDIFF40 patches (stdlib only)
"""

from installer.core.manifest import (Manifest, read_manifest, write_manifest,
                                     MANIFEST_NAME, MANIFEST_VERSION)
from installer.core.downloader import download_file, DownloadError
from installer.core.payload import (
    UpdateInfo, ApplyResult,
    parse_version, compare_versions, check_update, pick_payload_asset,
    sha256_of_file, is_main_running, request_main_exit,
    clear_upgrading_flag, write_failure_flag, clear_failure_flag,
    apply_payload, apply_delta, apply_delta_chain, restart_main, read_launch_args,
    cleanup_old_exe, cleanup_backups,
    MAIN_EXE_NAME, UPGRADE_EXE_NAME, UPGRADE_FLAG_NAME, FAILURE_FLAG_NAME,
    DEFAULT_EXIT_TIMEOUT, DEFAULT_MIN_INSTALLER_VERSION,
    DELTA_ASSET_PREFIX,
)

__all__ = [
    "Manifest", "read_manifest", "write_manifest",
    "MANIFEST_NAME", "MANIFEST_VERSION",
    "download_file", "DownloadError",
    "UpdateInfo", "ApplyResult",
    "parse_version", "compare_versions", "check_update", "pick_payload_asset",
    "sha256_of_file", "is_main_running", "request_main_exit",
    "clear_upgrading_flag", "write_failure_flag", "clear_failure_flag",
    "apply_payload", "apply_delta", "apply_delta_chain", "restart_main", "read_launch_args",
    "cleanup_old_exe", "cleanup_backups",
    "MAIN_EXE_NAME", "UPGRADE_EXE_NAME", "UPGRADE_FLAG_NAME", "FAILURE_FLAG_NAME",
    "DEFAULT_EXIT_TIMEOUT", "DEFAULT_MIN_INSTALLER_VERSION",
    "DELTA_ASSET_PREFIX",
]
