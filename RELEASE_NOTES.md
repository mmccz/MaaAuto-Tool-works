# MaaAuto v1.4.2

> **小更新** · 修「升级后桌面图标 / 开始菜单 / 设置→应用 条目消失」 · 2026-10-25

## 本版要点

- 修好 **升级后快捷方式与「设置 → 应用」条目消失**（Windows 显示「系统找不到应用」）。
- 程序本身和数据一直是好的：直接跑安装目录里的 `MaaAuto.exe` 就能用。
- 已经被误删的机器可以用 `tools/repair_integration.py` 一键重建，不用重装。

## 到底发生了什么

出问题的不是自动升级，而是**我发布前在本机跑的校验脚本**：

`verify_release.py` / `smoke_install.py` 会「装一份 → 跑断言 → 卸载」。它们默认装在
`%LOCALAPPDATA%\Programs\MaaAuto`，而 Inno 的这三样东西是**按 AppId 全局共享**的，
跟装在哪个目录无关：

| 东西 | 位置 |
| --- | --- |
| 「设置 → 应用」记录 | `HKCU\...\Uninstall\{AppId}_is1` |
| 开始菜单组 | `%APPDATA%\...\Programs\MaaAuto` |
| 桌面快捷方式 | `%USERPROFILE%\Desktop\MaaAuto.lnk` |

所以校验脚本那一次「卸载」，把用户真正装在 `D:\MaaAuto` 的那份的登记信息一起删掉了。

## 修复内容

- **校验隔离**：两个脚本改装到 `%LOCALAPPDATA%\Programs\MaaAuto_verify`；
- **备份还原**：新增 `installer/core/shell_integration.py`，跑前 `snapshot()` 备份
  注册表值 + 快捷方式原始字节，结束时 `restore()` 原样写回，并断言用户那份登记已恢复；
- **强制拦截**：`smoke_install.py` 直接拒绝在 `Programs\MaaAuto`（正式目录）上运行；
- **一键修复**：`tools/repair_integration.py` 重建卸载注册表项、开始菜单组、桌面快捷方式
  （只补登记，不动程序文件与配置）；
- **测试**：新增 `test_shell_integration.py` 9 项，其中一项专门校验代码里的 AppId
  与 `packaging/installer.iss` 一致，避免以后改一处忘另一处。

## 第一次使用请先改这两处

1. **MAA → 设置 → 启动设置 → 勾选「完成后退出模拟器」**
2. **MaaEnd → 任务列表 → 最后添加「关闭程序」或「关闭模拟器」**

## 下载

| 文件 | 用途 |
| --- | --- |
| `MaaAuto_Setup_v1.4.2-Windows-x64.exe`（约 56 MB） | **推荐**：新用户，断网可装 |
| `MaaAuto_Online_v1.4.2-Windows-x64.exe`（约 2 MB） | 在线引导包 |
| `MaaAuto_payload_v1.4.2.zip`（约 61 MB） | 升级器自动下载（整包） |
| `MaaAuto_delta_v1.4.1_to_1.4.2.zip` | 1.4.1 用户直达（本轮只改了安装器脚本，补丁很小） |
| `SHA256SUMS.txt` | 校验和 |

## 如果图标已经没了

两种都行：

1. 装本版安装包（会自动恢复图标与「设置 → 应用」条目）；
2. 只跑修复工具，不重装：

```powershell
python MaaAutoInstaller\tools\repair_integration.py
```

## 已知问题

- 差分最多串 4 跳；更老版本回退整包。
- 1.1.0 及更早版本的**第一次**升级仍是整包（差分能力由 `upgrade.exe` 自身携带）。
- 未做代码签名（渠道已确认，仍暂缓），SmartScreen 提示「未知发布者」。
- 后台点击（PostMessage）对 DirectInput / 独占全屏的游戏无效；定时最小粒度 1 分钟。
