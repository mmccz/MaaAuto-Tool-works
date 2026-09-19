"""应用元信息"""

APP_NAME = "MaaAuto"
APP_DISPLAY_NAME = "MaaAuto"
APP_VERSION = "2.1.0"
APP_ORG = "MaaAuto"
APP_GITHUB = "https://github.com/mmccz/MaaAuto-Tool-works"
APP_EMAIL = "Frank010700@outlook.com"
APP_LICENSE = "MIT"
APP_DESCRIPTION_KEY = "app.description"  # 走 i18n

# ---- 升级相关（与 MaaAutoInstaller 对齐，2026-09 冻结）----
APP_UPDATE_API = "https://api.github.com/repos/mmccz/MaaAuto-Tool-works/releases/latest"
APP_MIN_INSTALLER_VERSION = "1.0.0"       # 升级器低于该版本时提示用户重新下载完整安装包
APP_SOURCE_ASSET = "MaaAuto_Source.zip"   # Release 里源码包的固定 asset 名