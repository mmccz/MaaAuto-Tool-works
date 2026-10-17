"""应用元信息

注意：MaaAutoInstaller 会用「行首正则」解析本文件（见
docs/INSTALLER_INTEGRATION.md §4.1）。修改常量时请保持
单行、普通字符串字面量，不要改成类型注解、拼接或多行写法。
"""

APP_NAME = "MaaAuto"
APP_DISPLAY_NAME = "MaaAuto"

# 跨仓库契约：安装器 / 升级器读取本行。
# 允许的版本语法（与升级器解析器对齐）：
#   X.Y.Z / X.Y.ZaN / X.Y.ZbN / X.Y.ZrcN / X.Y.Z.postN
APP_VERSION = "2.1.0"
APP_ORG = "MaaAuto"
APP_GITHUB = "https://github.com/mmccz/MaaAuto-Tool-works"
APP_EMAIL = "Frank010700@outlook.com"
APP_LICENSE = "MIT"
APP_DESCRIPTION_KEY = "app.description"  # 走 i18n

# ---- 升级相关（与 MaaAutoInstaller 对齐，2026-09 冻结）----
# 这三个常量与安装器 manifest 的 extra.* 重复。改动属于「协议变更」：
# 需同步安装器并更新 docs/INSTALLER_INTEGRATION.md，否则已安装用户
# 的 upgrade.exe 仍会使用旧地址 / 旧 asset 名。
APP_UPDATE_API = "https://api.github.com/repos/mmccz/MaaAuto-Tool-works/releases/latest"
APP_MIN_INSTALLER_VERSION = "1.0.0"       # 升级器低于该版本时提示用户重新下载完整安装包
APP_SOURCE_ASSET = "MaaAuto_Source.zip"   # Release 里源码包的固定 asset 名