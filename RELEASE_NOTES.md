# MaaAuto v1.4.3

> **小更新** · 修「设置 → 应用」里的版本号不跟着升级 · 2026-10-31

## 本版要点

- 修好 **自动升级后「设置 → 应用」版本号停在旧值**（程序已是 1.4.2，列表里却写着 1.4.1）。
- 装上本版后第一次启动就会自动改正，不需要重装、不需要手改注册表。
- 顺手加固了发布校验工具：Store 版 Python 下「开始菜单修复」以前是假动作，现在写真实路径。

## 现象

自动升级之后，程序一切都正常，只有「设置 → 应用」里 MaaAuto 显示的版本号没变。

## 原因

自动升级**只替换程序文件，不运行 Inno 安装器**；而卸载注册表项（`DisplayVersion`）
是安装时写的，升级过程没有任何人刷新它。所以从装上那天起，这个数字就再也没变过。

## 修复

主程序启动时做一次自愈（`apps_registry.sync_display_version`）：

- 扫描 `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall`；
- **只有** `InstallLocation` 正好指向自己时才更新 `DisplayVersion`、`DisplayIcon`、
  `VersionMajor` / `VersionMinor`；
- 写失败只记 DEBUG，绝不影响启动；不是 Windows 直接跳过。

装好 1.4.3 后第一次启动，列表里的版本号就会变成 1.4.3，以后每次升级同理。

## 开发侧（用户可忽略）

发布校验工具在 Microsoft Store 版 Python（MSIX）下会踩 `%APPDATA%` 重定向：
`repair_integration.py` 报 OK 但 Explorer 看不到开始菜单，`verify_release` 的还原也是假的。
现在开始菜单的读/写/建快捷方式改走子进程 PowerShell（不继承包身份），
并在 `verify_release` 第 [7] 步断言「开始菜单与桌面已按快照还原」。

## 第一次使用请先改这两处

1. **MAA → 设置 → 启动设置 → 勾选「完成后退出模拟器」**
2. **MaaEnd → 任务列表 → 最后添加「关闭程序」或「关闭模拟器」**

## 下载

| 文件 | 用途 |
| --- | --- |
| `MaaAuto_Setup_v1.4.3-Windows-x64.exe`（约 56 MB） | **推荐**：新用户，断网可装 |
| `MaaAuto_Online_v1.4.3-Windows-x64.exe`（约 2 MB） | 在线引导包 |
| `MaaAuto_payload_v1.4.3.zip`（约 61 MB） | 升级器自动下载（整包） |
| `MaaAuto_delta_v1.4.2_to_1.4.3.zip` | 1.4.2 用户直达（只改了主程序几个文件，补丁很小） |
| `SHA256SUMS.txt` | 校验和 |

## 已知问题

- 差分最多串 4 跳；更老版本回退整包。
- 1.1.0 及更早版本的**第一次**升级仍是整包（差分能力由 `upgrade.exe` 自身携带）。
- `manifest.installer_version` 记录的是「执行本次升级的那个 `upgrade.exe` 版本」，
  会滞后一版；它只用于记录，升级时的版本门槛用的是运行中的升级器自身版本。
- 未做代码签名（渠道已确认，仍暂缓），SmartScreen 提示「未知发布者」。
- 后台点击（PostMessage）对 DirectInput / 独占全屏的游戏无效；定时最小粒度 1 分钟。
