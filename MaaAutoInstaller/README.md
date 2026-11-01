<div align="center">

<img src="docs/images/logo.png" width="96" alt="MaaAuto logo">

# MaaAuto Installer

**MaaAuto 的打包与升级仓库** —— Inno Setup 安装包 + payload 升级器

[![Version](https://img.shields.io/badge/version-1.4.6-2f81f7.svg)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/Python-3.15%2B-3776AB.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011%20x64-0078D4.svg)](https://github.com/mmccz/MaaAuto-Installer/releases)
[![Main App](https://img.shields.io/badge/main%20app-MaaAuto--Tool--works-6f42c1.svg)](https://github.com/mmccz/MaaAuto-Tool-works)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

</div>

**简体中文** ｜ [English](README.en.md) ｜ 🌐 [使用者文档（主仓库 Wiki）](https://github.com/mmccz/MaaAuto-Tool-works/wiki)

---

## 这是什么

**1.0.0 起，程序在 CI 预构建，用户机器上不再有 Python / pip / PyInstaller。**

本仓库负责两件事：

1. **打包**：把主程序的 onedir 产物裁剪、压缩成 payload，再用 Inno Setup 生成安装包；
2. **升级**：`upgrade.exe` 下载 payload、校验、替换程序文件，失败回滚。

主程序本身（界面、调度、找图、推送）在 [MaaAuto-Tool-works](https://github.com/mmccz/MaaAuto-Tool-works)。

### 产物

| 文件 | 大小 | 用途 |
| --- | --- | --- |
| `MaaAuto_Setup_v{ver}-Windows-x64.exe` | ~59 MB | 完整安装包，内嵌 payload，断网可装 |
| `MaaAuto_Online_v{ver}-Windows-x64.exe` | ~2 MB | 在线引导包，安装时才下载完整包 |
| `MaaAuto_payload_v{ver}.zip` | ~66 MB | 升级器下载的预构建程序包 |
| `MaaAuto_delta_v{old}_to_{new}.zip` | ~0.5 MB | 差分包（相邻版本才有，没有就回退整包） |
| `SHA256SUMS.txt` | — | 上述文件的校验和（发版时生成） |

---

## 安装包行为

| 项 | 说明 |
| --- | --- |
| 默认目录 | `%LOCALAPPDATA%\Programs\MaaAuto`（per-user，免 UAC） |
| 可选模式 | 向导中选「为所有用户安装」→ `Program Files\MaaAuto`（需要提权） |
| 需要联网 | **否**（完整包） |
| 需要 Python | **否** |
| 安装耗时 | 约 30 秒 |
| 快捷方式 | 开始菜单固定创建；桌面可选 |
| 卸载 | Inno 生成的 `unins000.exe`（开始菜单也有「卸载 MaaAuto」入口）：先停主程序，再删文件/快捷方式/注册表/自启项；默认保留 `config` 与 `logs`，加 `/PURGEDATA` 彻底删除 |

主程序 exe 内嵌 `requireAdministrator` 清单，**每次启动弹一次 UAC**（它需要点击游戏的提权窗口）；安装本身不再写 `RUNASADMIN` 兼容标志，安装时还会清理 2.x 留下的旧标志。

---

## 升级流程

```
主程序（5 秒后或手动）：查 releases/latest，比对版本
        │  有新版 → 写 config/.upgrading 并调起 upgrade.exe
        ▼
upgrade.exe：读 .maaauto.json → 重新查询 Release
        │  找到 MaaAuto_payload_v{ver}.zip
        ▼
   下载到 %TEMP% → 校验 sha256 → 等主程序退出（15s，超时强杀）
        ▼
   解压到 <parent>/.MaaAuto_new_<ts>
        ▼
   逐文件：旧文件移到 .MaaAuto_bak_<ts>，新文件替换进去
        │  任一步失败 → 反向恢复 → 写 upgrade_failed.flag
        ▼
   更新 .maaauto.json（version / installer_version / source_hash）
        ▼
   清 .upgrading → 按 last_launch_args.json 重启主程序
```

### 差分更新（1.2.0）

有新版本时会先看有没有 `MaaAuto_delta_v{当前版本}_to_{新版本}.zip`：

```
upgrade.exe：找到差分包
        ▼
   下载（通常 0.5 MB 级）→ 校验资产 digest
        ▼
   逐文件还原：base_sha256 必须与本地文件一致 → bspatch 打补丁 → 校验目标 sha256
        │  基准不符 / 补丁损坏 / 没有该资产 → 静默回退整包，不影响用户
        ▼
   替换 + 删除清单（上一版有、这一版没有的文件）→ 同一套备份/回滚
```

- 内容没变的文件完全不下载（Qt DLL / 模板等占 ~93% 体积）；
- `upgrade.exe`、`MaaAuto.exe` 这类每次构建都会变的文件走 bsdiff 补丁
  （实测 7.5 MB → 403 KB、5.4 MB → 148 KB）；
- **应用端是纯标准库**（`installer/core/bspatch.py`），`bsdiff4` 只在构建机用，
  升级器体积不变；
- 只对「上一版 → 本版」有效；连跳多个版本会回退整包。

- `config/`、`logs/`、`.maaauto.json` **永远不参与替换**。
- 正在运行的 `upgrade.exe` 会被改名让位（`.old`），下次启动时清理，因此**升级器自身可以随 payload 更新**。
- 用户取消、已是最新、检查失败等终态都会回到主程序（`--restart` 且主程序未运行时）。

命令行（与旧版保持一致，主程序无需改动）：

```text
upgrade.exe --from-main [--restart] [--silent] [--check-only] [--no-ui] [--channel stable|beta] [--downgrade]
```

- `--silent`：显示不可交互的进度窗；
- `--no-ui`：完全无窗口，只写日志，供自动化 / CI 使用；
- `--channel beta`：同时接受预发布（`bN` / `rcN`），稳定版只看 `releases/latest`。

退出码：`0` 成功/有新版本，`1` 仅 `--check-only` 且已最新，`2` 错误。

---

## 构建

### 环境

```powershell
cd MaaAutoInstaller
py -m pip install -r requirements.txt   # psutil（upgrade.exe 已不再需要 PySide6）
py -m pip install pyinstaller
winget install JRSoftware.InnoSetup     # 提供 ISCC.exe
```

> `upgrade.exe` 的进度窗是纯 ctypes/Win32（`installer/core/native_ui.py`），
> 1.0.2 起体积从 43 MB 降到 7.5 MB。跑主程序 `build.py` 仍然需要 PySide6，
> 那是主程序自己的依赖，与本仓库无关。

还需要主程序源码目录（默认自动探测同级仓库，或 `--source-dir` 指定）。
本机开发用 Python 3.15（`py` 启动器），CI 也用 3.15；`upgrade.exe` 与安装包本身不依赖 Python。

### 一条命令

```powershell
cd MaaAutoInstaller
py build_release.py                    # 完整构建
py build_release.py --keep-build       # 保留中间产物
py build_release.py --skip-main-build  # 复用主程序 dist/
py build_release.py --skip-stub        # 复用 _build/stub/upgrade.exe
py build_release.py --no-trim          # 不裁剪
py build_release.py --debug            # upgrade.exe 保留控制台
py build_release.py --source-dir ..\..\MaaAuto-Tool-works\MaaAutoProject
py build_release.py --skip-main-build --delta-from ../dist/MaaAuto_payload_v1.4.4.zip  # 本机补 delta
```

流程：**契约校验** → 主程序 `build.py` → 复制并裁剪 payload（约 −67 MB）→ PyInstaller 打包 `upgrade.exe` → 压缩 payload（LZMA）→ Inno 编译完整包 → 计算 sha256 → Inno 编译在线包 → 写 `dist/SHA256SUMS.txt`。

产物在 `dist/`。

### 测试

```powershell
cd ..                 # 仓库根
py -m pip install pytest
py -m pytest tests -q        # 98 passed
```

覆盖：版本解析/比较、payload 资产匹配与 stable/beta 频道选择、
`.maaauto.json` 读写契约、payload 替换（`config/` `logs/` 受保护）/
路径穿越拒绝/中途失败回滚、假 Release 服务器本身，以及「`upgrade.exe`
不许再 import PySide6/PyQt/tkinter」的回归测试（守住 43 MB → 7.5 MB 的瘦身成果）。
纯逻辑测试，不联网、不需要图形界面，CI 里随主程序仓库一起跑。

### 手工验证升级链路（不用发版也能测）

`tools/fake_release_server.py` 用 `http.server` 模拟 GitHub Releases API，
把本地构建的 payload 当作「远端资产」，于是升级器会完整跑一遍
查版本 → 下载 → sha256 校验 → 停主程序 → 替换 → 更新 manifest：

```powershell
# ① 起假服务器（顺手把测试安装的 update_api 指向本机、版本改成 1.0.0）
py tools\fake_release_server.py --payload ..\dist\MaaAuto_payload_v1.0.x.zip `
    --port 8765 --patch-manifest "$env:LOCALAPPDATA\Programs\MaaAuto"

# ② 另开窗口：只检查 / 真正升级
#    upgrade.exe 是 GUI 子系统程序，用 & 调用不会等待、也拿不到退出码，
#    必须 Start-Process -Wait -PassThru。
$app = "$env:LOCALAPPDATA\Programs\MaaAuto"
(Start-Process -Wait -PassThru -FilePath "$app\upgrade.exe" `
    -ArgumentList '--from-main','--check-only','--no-ui').ExitCode
(Start-Process -Wait -PassThru -FilePath "$app\upgrade.exe" `
    -ArgumentList '--from-main','--no-ui').ExitCode
```

加 `--corrupt-digest` 可让校验必定失败，用来验证「回滚 + 写
`upgrade_failed.flag`」；测完记得重装，或把 `extra.update_api` 改回 GitHub 地址。

### 发版验证脚本

```powershell
# 安装包 E2E：静默安装 → 内容校验 → 假 Release 升级 → 卸载（发版前本机跑）
py tools\verify_release.py 1.4.6

# 发布前 smoke：静默安装 → 查产物/manifest → 卸干净（CI 每版必跑，也可本机跑）
py tools\smoke_install.py 1.4.6

# 发布后元数据：Release/digest/公告源（不下载大文件，发版后跑）
py tools\verify_release_meta.py mmccz/MaaAuto-Tool-works 1.4.6

# 被误删了图标 / 「设置→应用」条目：重建登记（不动程序文件与配置）
py tools\repair_integration.py
py tools\repair_integration.py --dir D:\MaaAuto
```

> ⚠️ **千万别把校验脚本指向正式安装目录**。Inno 的卸载注册表项、开始菜单组、桌面快捷方式
> 都是**按 AppId 全局共享**的，跟装在哪个目录无关：在 `MaaAuto` 目录上「装一份 → 卸载」，
> 会把你（或用户）真正那份的「设置 → 应用」记录和图标一起删掉。1.4.1 就是这样翻车的
> （现象：系统提示「找不到应用」，图标全没）。脚本现在默认装到
> `%LOCALAPPDATA%\Programs\MaaAuto_verify`，跑前 `snapshot()` 备份、跑完 `restore()` 还原，
> `smoke_install.py` 还会直接拒绝在正式目录上运行。

`installer/core/shell_integration.py` 提供 `snapshot()` / `restore()` /
`foreign_install()` / `repair_integration()`；`tests/test_shell_integration.py`
里有一项会校验代码里的 AppId 与 `packaging/installer.iss` 是否一致。

### CI

`.github/workflows/release.yml` **位于主程序仓库**（Release 与 tag 都在那边）：推 `v*` tag 后检出本仓库、装依赖与 Inno（Python 3.15），跑 `build_release.py`，把资产（Setup / Online / payload / delta / SHA256SUMS）挂到 Release；正文取主程序仓库的 `RELEASE_NOTES.md`，构建成功**直接发布**（`draft: false`），tag 含 `b` / `rc` 时自动标记为 prerelease。发布会自己找上一版产物生成差分包（`--delta-auto`）。发布后建议跑一遍 `tools\verify_release_meta.py` 复核。

发布前还有一道 **安装/卸载 smoke**（`tools\smoke_install.py`）：在干净 runner 上真的静默安装 → 校验
`MaaAuto.exe` / `upgrade.exe` / `.maaauto.json`（版本与 `contract.py` 契约）→ 静默卸载并确认目录清空。
任一项失败则构建红在「发布 Release」之前，不会把装不上的版本发出去；失败日志（`build.log` +
`smoke.log`）会推到 `ci-logs` 分支的 `ci-last.log`。

---

## 关键契约

| 文件 | 写入方 | 读取方 | 语义 |
| --- | --- | --- | --- |
| `config/.upgrading` | 升级器 | 主程序（启动 + 每秒轮询） | 存在即退出；**必须由升级器删除**，残留 5 分钟后主程序兜底清理 |
| `config/upgrade_failed.flag` | 升级器 | 主程序（启动 300ms 后） | JSON；弹窗提示后由主程序删除 |
| `config/last_launch_args.json` | 主程序 | 升级器 | 重启时恢复 `--autostart` 等参数 |

`.maaauto.json`（`manifest_version = 3`）由安装包写入、升级器更新，主程序从不读写。

**冻结常量**（改动 = 协议变更，两仓库必须同时发版）：

```text
APP_UPDATE_API               ↔ extra.update_api
APP_SOURCE_ASSET             ↔ extra.source_asset_name      （过渡期）
APP_MIN_INSTALLER_VERSION    ↔ extra.min_installer_version
APP_PAYLOAD_ASSET_PREFIX     ↔ extra.payload_asset_prefix
```

`extra` 只在安装时写入、升级不刷新——改了地址等于老用户永远读旧值。

---

## 目录结构

```text
MaaAuto-Installer/
├─ CHANGELOG.md
├─ docs/images/logo.png
├─ .github/workflows/release.yml   ← tag 触发构建
└─ MaaAutoInstaller/
   ├─ VERSION                      ← 安装器/升级器版本
   ├─ build_release.py             ← 一键构建
   ├─ packaging/
   │  ├─ installer.iss             ← 完整安装包
   │  ├─ online.iss                ← 在线引导包
   │  ├─ trim_payload.py           ← 裁剪规则
   │  └─ languages/ChineseSimplified.isl
   ├─ installer/
   │  ├─ contract.py               ← 冻结常量与 manifest.extra
   │  └─ core/
   │     ├─ payload.py             ← 升级核心：下载/校验/替换/回滚
   │     ├─ manifest.py            ← .maaauto.json
   │     └─ downloader.py          ← 带进度的下载
   ├─ tools/upgrade_stub.py        ← upgrade.exe 源码
   └─ resources/
```

---

## 已知限制

| 限制 | 说明 |
| --- | --- |
| 未签名 | SmartScreen 会提示「未知发布者」；构建脚本预留了签名步骤，拿到证书后接入即可 |
| 差分包只覆盖相邻版本 | `MaaAuto_delta_v{old}_to_{new}.zip` 只对上一版有效；跨多版会静默回退整包（约 66 MB） |
| 安装包体积 | Setup ~59 MB、payload ~66 MB；用体积换「免编译 + 可复现」 |
| 升级器版本门槛 | `min_installer_version = 1.0.0`；低于它的旧安装包需要重装一次 |
| 登录自启 | 打包版带 `requireAdministrator` 清单，1.4.5 起改用「登录时运行 + 最高权限」计划任务；旧的 HKCU Run 项会在启动时自动迁移 |

---

## 许可证

[MIT](LICENSE)。本项目为第三方工具，与 MAA / MaaEnd 官方无关联。
