# 更新日志

本文件记录用户可感知的变更。版本号遵循 `X.Y.Z`：`X.Y.ZbN` / `rcN` 为预发布。

---

## [1.0.1b1] - 2026-10-24

测试版：用于验证「测试版更新渠道」与 payload 升级链路。

### 变更

- 版本号改为 `1.0.1b1`，验证 beta 渠道能检测到预发布并完成升级。
- 构建流程适配预发布版本号（Inno 的 `VersionInfoVersion` 需要纯数字，改用 `1.0.1.0`）。
- CI：预发布 tag 自动发布为 prerelease；正式版仍保留草稿供人工检查。

---

## [1.0.0] - 2026-10-24

首个采用「CI 预构建 + payload 升级」的版本。安装与升级都不再在用户机上编译。

### 安装

- 安装包改为 Inno Setup：双击后约 30 秒装完，**不需要 Python、不需要联网、默认不需要管理员**。
- 默认装到 `%LOCALAPPDATA%\Programs\MaaAuto`；向导里可选「为所有用户安装」装到 `Program Files`。
- 主程序 exe 内嵌 `requireAdministrator` 清单，每次启动弹一次 UAC；安装时清理旧版留下的 `RUNASADMIN` 注册表标志。
- 卸载器（`unins000.exe`）会在删除前停掉主程序，默认保留 `config/` 与 `logs/`，并清理快捷方式、卸载项与开机自启项。彻底清理可加 `/PURGEDATA`。

### 升级

- 升级改为下载 `MaaAuto_payload_v{版本}.zip` → 校验 sha256 → 备份 → 逐文件替换 → 失败回滚，通常十几秒完成。
- `upgrade.exe` 随 payload 一起更新，升级链路的修复对老用户即时生效。
- 新增**更新渠道**：稳定版 / 测试版。测试版会同时接收预发布（`bN` / `rcN`），可在「设置 → 常规 → 更新渠道」切换。

### 修复

- 修复升级器在后台线程直接操作界面导致的崩溃（0xC0000005）。
- 修复安装完成页「立即启动」报「错误代码 740，请求的操作需要提升」——改用 ShellExecute。
- 修复静默卸载卡在确认框（改用 SuppressibleMsgBox）。
- 修复 `uninstall_exe` 指向不存在的 `uninstall.exe`（Inno 的卸载器实际叫 `unins000.exe`）。
- 修复工作区/低完整性目录下双击安装包报「无法创建目录 is-*.tmp，错误 5」。

### 体积

- 安装后约 205 MB（裁剪 Qt Quick/QML/PDF/SVG、软件 OpenGL、cv2 视频后端），安装包约 94 MB。

---

更早的版本历史已随版本号重置移除。
