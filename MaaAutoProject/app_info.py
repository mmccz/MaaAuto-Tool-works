"""Application metadata.

NOTE: MaaAutoInstaller parses this file with a line-start regex to read the
version and constants. Keep each value on a single line as a plain string
literal: no type annotations, concatenation or multi-line expressions.
"""

APP_NAME = "MaaAuto"
APP_DISPLAY_NAME = "MaaAuto"

# Cross-repo contract: the installer / upgrader parses this line.
# Accepted version syntax (aligned with the upgrader's parser):
#   X.Y.Z / X.Y.ZaN / X.Y.ZbN / X.Y.ZrcN / X.Y.Z.postN
APP_VERSION = "1.4.5"
APP_ORG = "MaaAuto"
APP_GITHUB = "https://github.com/mmccz/MaaAuto-Tool-works"
APP_EMAIL = "Frank010700@outlook.com"
APP_LICENSE = "MIT"
APP_DESCRIPTION_KEY = "app.description"  # resolved via i18n

# ---- Update related (aligned with MaaAutoInstaller) ----
# Duplicated from installer/contract.py (manifest.extra.*). Changing them is a
# protocol change: update and release the installer too, otherwise an installed
# upgrade.exe keeps the old URL / asset name (extra is written at install only).
APP_UPDATE_API = "https://api.github.com/repos/mmccz/MaaAuto-Tool-works/releases/latest"
APP_MIN_INSTALLER_VERSION = "1.0.0"       # below this version, prompt the user to download the full installer again

# Prebuilt payload downloaded by the upgrader; file name = prefix + version + ".zip"
# e.g. MaaAuto_payload_v1.0.0.zip. Built by CI; user machines no longer compile it.
APP_PAYLOAD_ASSET_PREFIX = "MaaAuto_payload_v"

# Delta package; file name = prefix + "{old}_to_{new}" + ".zip"
# e.g. MaaAuto_delta_v1.1.1_to_1.2.0.zip; if the asset is missing, fall back to the full package.
APP_DELTA_ASSET_PREFIX = "MaaAuto_delta_v"

# ---- Online announcements (outside the installer contract: retargeting needs no rebuild) ----
# The content is this repo file. Push to main and clients fetch it on their next
# launch, with no new release. jsDelivr is a China-reachable mirror of raw.githubusercontent.
APP_ANNOUNCEMENTS_URLS = (
    "https://raw.githubusercontent.com/mmccz/MaaAuto-Tool-works/main/"
    "MaaAutoProject/resources/announcements.json",
    "https://cdn.jsdelivr.net/gh/mmccz/MaaAuto-Tool-works@main/"
    "MaaAutoProject/resources/announcements.json",
)