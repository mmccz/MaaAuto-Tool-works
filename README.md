<div align="center">

<img src="docs/images/logo.png" width="112" alt="MaaAuto logo">

# MaaAuto

**MAA & MaaEnd 的定时自动化调度台**

[![Version](https://img.shields.io/badge/version-1.4.3-2f81f7.svg)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6-41CD52.svg)](https://pypi.org/project/PySide6/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D4.svg)](#环境要求)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

</div>

---

## 这是什么

MaaAuto 是一个 Windows 桌面端的**调度外壳**：到点拉起 [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights) 或 [MaaEnd](https://github.com/MaaEnd/MaaEnd)，用图像识别点掉「Link Start!」「开始任务」，等游戏退出，再把结果推送到微信或 Webhook。

它本身**不包含任何游戏逻辑**——不修改游戏、不读内存、不模拟输入序列，只做「按日程 + 找图点击 + 进程守护」这三件事。

<table>
<tr><td width="50%" valign="top">

**适合谁**

- 每天固定时段挂机、希望全自动的人
- 同时用 MAA 和 MaaEnd 的人
- 想在自己电脑上留痕（日志 / 推送）的人

</td><td width="50%" valign="top">

**不适合谁**

- 需要多开、多账号批量托管的人
- 期望「零配置开箱即用」的人（仍需填两个程序路径）
- 非 Windows 用户

</td></tr>
</table>

---

## ✨ 核心功能

### 自动化调度

- **每日定时启动** —— 自定义执行时间；当天错过时间点，晚些开软件也会补执行一次。
- **图像识别点击** —— 基于 `opencv` 多尺度模板匹配（`vision.py`），自动点掉 MAA 的「Link Start!」与 MaaEnd 的「开始任务」。**支持不同分辨率与 100% / 125% / 150% 缩放**；搜索限定在目标窗口客户区内，又快又不会点到别处。
- **自截模板** —— 换机器、换缩放或按钮改版时，用「设置 → 找图与点击 → 截取模板」框选按钮存成 `config/templates/*.png`，立即生效并回报自检相似度，不必等发版。
- **两种点击方式** —— 默认真实点击（SendInput，可还原鼠标位置）；也可选实验性的后台 `PostMessage` 点击（不占用鼠标，但游戏通常不响应）。
- **前台处理策略** —— 启动前可选：不做任何操作（默认）/ 关闭所有前台程序 / 仅关闭黑名单程序（带可视化进程选择器）。
- **重试与超时** —— 重试次数、重试间隔、找图超时、游戏启动 / 关闭超时全部可调。
- **进程保活与唤醒** —— 任务结束自动最小化 MAA / MaaEnd；下次执行先拉回前台，避免多开。
- **随时中止** —— 「结束任务」或托盘菜单中止，长循环 1 秒内响应，不残留子进程。

### 自动升级

- **一键升级** —— 关于页「检查更新」，检测到新版本后在新样式弹窗里查看版本对比与 Markdown 发布说明（「立即升级 / 稍后 / 查看发布页」）。
- **启动自动检查** —— 启动 5 秒后后台检查（可关闭）。
- **自动下载并升级（免确认）** —— 勾选后检测到新版即自动升级，任务运行中会等任务结束。
- **公告** —— 首页「公告」里是程序更新与使用提醒（中英双语），**内容从 GitHub 在线更新**：改仓库里的 `MaaAutoProject/resources/announcements.json` 并 push 到 `main` 即可，不需要发新版本；断网时自动用上次缓存或安装包内置内容。有未读/更新时按钮带红点，并自动弹一次。
- **进度可视化** —— 展示下载、装依赖、打包、部署各阶段。
- **失败回滚** —— 失败自动回滚，并写失败标记，下次启动提示。
- **智能重启** —— 升级完成后自动重启，恢复原启动方式（含 `--autostart`）；重启/升级不会顺手关掉你已开着的 MAA / 模拟器。

### 推送通知

| 通道 | 说明 |
| --- | --- |
| **Server酱** | 推送到微信，正文含完整任务日志 |
| **通用 Webhook** | 向自定义 URL POST `{title, content}`，可对接 Bark / Gotify / 企业微信 / 钉钉 / 飞书 |
| **系统通知** | 任务结束时弹 Windows 托盘气泡（不含日志），可开关 |

### 界面与体验

- **三页面** —— 首页（状态 + 日志）/ 设置 / 关于，侧边栏导航 + 左右滑动切页。
- **新手教程** —— 首次启动自动弹出，也可以从首页「新手教程」随时再看；把 MAA / MaaEnd 必须先改的两处设置用醒目警告块标出来。
- **三态主题** —— 浅色 / 深色 / 跟随系统，切换带截图遮罩淡出过渡。
- **强调色自定义** —— 8 种预设 + 取色器，实时生效。
- **中英双语** —— JSON 语言包，切换即时生效。
- **背景图** —— 支持透明度 / 模糊（滑杆 0~60）/ 4 种缩放（填充 / 适应 / 拉伸 / 平铺）。
- **界面缩放** —— 100% / 125% / 150%，切换后**立即生效**（字号、内边距、控件尺寸、侧栏宽度一起缩放）；旁边有「重启程序」，需要按新比例完整重建窗口时一键重启。窗口默认尺寸会按屏幕可用区域收缩，小屏和高 DPI 笔记本上按钮不会被任务栏挡住。
- **全自动保存** —— 设置项改动即时落盘，无保存按钮。
- **日志** —— 按 `logs/年/月/日/run_N_时间/task.log` 存档；界面按级别上色，上限 2000 行，自动滚底。

---

## 🚀 快速开始

### 环境要求

| 项 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 / 11（x64） |
| 屏幕 | 任意分辨率；系统缩放 100% / 125% / 150% 均支持（多尺度匹配，找不到时可用「截取模板」自校准） |
| Python（仅源码运行） | 3.11+，**建议 [python.org](https://www.python.org/downloads/) 安装版**，不要用 Microsoft Store 版 |
| 依赖软件 | 自备 [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights)、[MaaEnd](https://github.com/MaaEnd/MaaEnd) |

> 用安装包时**不需要** Python，也不需要联网（完整包）。

### 方式一：安装包（推荐）

到 [Releases](https://github.com/mmccz/MaaAuto-Tool-works/releases) 下载：

| 文件 | 说明 |
| --- | --- |
| `MaaAuto_Setup_v1.4.3-Windows-x64.exe` | **完整包（约 56 MB）**，内嵌预构建程序，断网也能装 |
| `MaaAuto_Online_v1.4.3-Windows-x64.exe` | 在线引导包（约 2 MB），安装时才下载完整包 |

双击后 30 秒左右装完，**不需要 Python、不联网、不需要管理员权限**：默认装到 `%LOCALAPPDATA%\Programs\MaaAuto`；向导里也可以选「为所有用户安装」，装到 `Program Files`（这一步会弹 UAC）。
「选择附加任务」页可以选**是否创建开始菜单快捷方式**（默认创建）与桌面图标。

主程序本身需要管理员权限（要点掉游戏的提权窗口），所以**每次启动会弹一次 UAC**——这是预期的。

### 方式二：源码运行

```powershell
cd MaaAutoProject
pip install -r requirements.txt
python main.py
```

> 必须在 `MaaAutoProject` 目录下启动（`main.py` 的相对路径依赖它）。

### 图像资源与模板

仓库自带两张模板：

| 文件 | 用途 |
| --- | --- |
| `resources/maa_start.png` | MAA 界面右下角「Link Start!」 |
| `resources/maaend_start.png` | MaaEnd 界面下方「开始任务」 |

找图会做 **60%~200% 多尺度匹配**，所以 100% / 125% / 150% 缩放一般都能直接命中。
如果仍然找不到（界面语言不同、按钮改版、非整数缩放），**不用改代码**：

1. 设置 → **找图与点击** → **截取模板**；
2. 选目标（MAA / MaaEnd / 自定义文件名）→「开始截取」；
3. 屏幕变暗后框选按钮区域（尽量只框按钮本身）→ 松手即保存到 `config/templates/`；
4. 弹窗会给出自检相似度，低于 0.85 建议重新框选。

`config/templates/` 里的同名文件**优先于**内置资源，所以自截模板会立刻生效。
想先确认当前设置能不能找到，用旁边的「测试找图」——只报告 score / 尺度 / 坐标，不点击。

### 首次配置顺序

> ⚠️ **动手之前先改这两处，否则自动化收不了尾：**
>
> 1. **MAA → 设置 → 启动设置 → 勾选「完成后退出模拟器」**
>    不勾的话任务跑完模拟器还开着，MaaAuto 等不到「模拟器退出」，后续阶段和下次启动都可能失败。
> 2. **MaaEnd → 任务列表 → 在最后添加「关闭程序」或「关闭模拟器」**
>    这条任务是给 MaaAuto 的「MaaEnd 已跑完」信号；没有它 MaaAuto 会一直等到超时（默认 2 小时）。
>
> 程序首次启动会自动弹出「新手教程」，里面也是这两条 + 完整步骤。

1. **先改 MAA / MaaEnd**：见上面的两处设置。
2. **设置 → 路径**：填 MAA、MaaEnd 可执行文件路径（留空则跳过对应阶段）。
3. **设置 → 进程与超时**：模拟器进程名（默认 `MuMuPlayer.exe`）、PC 游戏进程名（默认 `Endfield.exe`）。
4. **设置 → 前台处理**：选策略；黑名单模式可点「从进程列表选择」勾选。
5. **设置 → 找图与点击**：先用默认值；找不到按钮时再调阈值 / 缩放区间或截取模板。**先点「测试找图」**确认能命中。
6. **设置 → 定时与推送**：执行时间、Server酱 SendKey、Webhook、系统通知。
7. **设置 → 外观**：主题 / 强调色 / 语言 / 背景图 / 界面缩放。
8. **设置 → 常规**：开机自启、关闭行为、自动检查更新、自动下载并升级。
9. 回首页点 **▶ 立即执行** 试跑一次；出问题看首页日志或 `logs/` 里当次 `task.log`。

---

## ⚙️ 配置说明

配置存于 `config/config.json`（安装版在安装目录下），程序内修改即时生效。**不要在程序运行时手改此文件**——程序会整文件回写。

| 字段 | 说明 | 默认值 |
| --- | --- | --- |
| `maa_path` | MAA 可执行文件路径，留空跳过 MAA 阶段 | `""` |
| `maaend_path` | MaaEnd 可执行文件路径，留空跳过 MaaEnd 阶段 | `""` |
| `emulator_proc` | 模拟器进程名 | `MuMuPlayer.exe` |
| `pc_game_proc` | PC 端游戏进程名 | `Endfield.exe` |
| `foreground_action` | 前台策略：`none` / `kill_all` / `blacklist` | `none` |
| `blacklist_apps` | 黑名单进程名，逗号分隔 | `""` |
| `enable_schedule` | 启用定时执行 | `false` |
| `schedule_times` | 执行时段列表（如 `["08:00", "20:30"]`）；空 = 用 `execute_time` | `[]` |
| `schedule_weekdays` | 执行日（1=周一…7=周日）；空 = 每天 | `[]` |
| `execute_time` | **旧字段**：单时段时间（`HH:mm`），仅兼容老配置 | `08:00` |
| `last_trigger_date` | 上次触发日期（内部防重复） | `""` |
| `serverchan_key` | Server酱 SendKey | `""` |
| `webhook_url` | 通用 Webhook 地址 | `""` |
| `enable_system_notify` | 任务结束弹系统通知 | `true` |
| `wait_timeout` | 找图超时（秒） | `60` |
| `game_start_timeout` | 等待游戏启动（秒） | `120` |
| `game_exit_timeout` | 等待游戏关闭（秒） | `7200` |
| `retry_times` | 失败重试次数 | `3` |
| `retry_interval` | 重试间隔（秒） | `30` |
| `theme` | `light` / `dark` / `system` | `system` |
| `accent_color` | 强调色（十六进制） | `#3b82f6` |
| `language` | `zh_CN` / `en_US` | `zh_CN` |
| `background_image` | 背景图路径 | `""` |
| `background_opacity` | 背景透明度 0~1 | `0.3` |
| `background_blur` | 背景模糊半径 | `0` |
| `background_mode` | `cover` / `contain` / `stretch` / `tile` | `cover` |
| `show_animation` | 页面切换动画 | `true` |
| `auto_start` | 开机自启 | `false` |
| `minimize_to_tray` | 关闭窗口时最小化到托盘 | `true` |
| `kill_on_exit` | 退出时清理相关进程 | `true` |
| `log_retention_days` | 任务日志保留天数（启动时清理更早的 `logs` 目录；`0` = 不清理） | `90` |
| `auto_check_update` | 启动时检查更新 | `true` |
| `auto_download_update` | 自动下载并升级（免确认） | `false` |
| `update_channel` | `stable` / `beta` | `stable` |
| `search_scope` | 找图范围：`window`（目标窗口客户区）/ `screen`（整屏） | `window` |
| `search_padding` | 搜索区域外扩像素 | `0` |
| `match_threshold` | 相似度阈值（0~1） | `0.80` |
| `match_scale_min` / `match_scale_max` | 模板缩放搜索区间 | `0.60` / `2.00` |
| `match_scale_step` | 缩放步长 | `0.05` |
| `match_interval` | 两次尝试的间隔（秒） | `1.5` |
| `click_mode` | `sendinput`（真实点击）/ `postmessage`（后台点击，实验） | `sendinput` |
| `click_activate` | 点击前把目标窗口切到前台；**关闭后只允许后台点击**（PostMessage），不会发真实点击 | `true` |
| `click_restore_cursor` | 点击后还原鼠标位置 | `true` |
| `click_move_delay_ms` | 移到目标后停顿再按下（毫秒） | `80` |
| `click_offset_x` / `click_offset_y` | 命中点微调（像素） | `0` / `0` |
| `template_dir` | 自定义模板目录（留空 = `config/templates`） | `""` |
| `ui_scale` | 界面缩放（切换即时生效，无需重启） | `1.0` |
| `tutorial_seen` | 新手教程是否已看过（首次启动自动弹） | `false` |
| `announcements_seen` | 已读公告 id 列表（首页红点） | `[]` |
| `announcements_seen_updated` | 上次已读时的公告 `updated`（内容更新会重新提示） | `""` |
| `run_count` / `last_run_time` / `window_geometry` | 运行态数据，自动维护 | — |

> **公告怎么改（不用发版）**：编辑仓库里的 `MaaAutoProject/resources/announcements.json`
> （结构见文件内 `_note`），push 到 `main` 分支即可。客户端启动后会在后台拉取
> `raw.githubusercontent.com`（失败回退 jsDelivr 镜像），成功则缓存到
> `config/announcements_cache.json`。新增条目按 `id` 判为未读；只是修改了内容时
> 请同时更新顶层 `updated`，已读用户会重新看到红点。

---

## 🔔 推送说明

**Server 酱**：填 SendKey 后，任务结束推送带日志的微信消息；设置页可点「测试」验证。

**通用 Webhook**：向指定 URL POST：

```http
Content-Type: application/json

{
  "title": "09-18 | MaaAuto自动成功",
  "content": "任务开始时间：2026-09-18 08:00:00，任务结束时间：2026-09-18 10:23:45\n\n当前日志输出：\n...\n\nMaaAuto 敬上"
}
```

**系统通知**：成功 / 失败 / 中止三种托盘气泡，可在「设置 → 定时与推送」关闭。

---

## 🔄 升级与版本

当前版本 **1.4.3**，变更见 [CHANGELOG.md](CHANGELOG.md)。

任何已安装的 1.x 都可以在程序内一键升级：优先下载 `MaaAuto_delta_v{旧}_to_{新}.zip` 差分包
（通常不到 1 MB，跳版本会自动串链），没有可用补丁时才回退 `MaaAuto_payload_v{版本}.zip` 整包；
失败自动回滚。

升级只替换程序文件，`config/`、`logs/`、`.maaauto.json` 一律保留。失败会回滚并写入 `config/upgrade_failed.flag`，下次启动弹窗提示。

### 更新渠道

「设置 → 常规 → 更新渠道」：

| 渠道 | 行为 |
| --- | --- |
| **稳定版**（默认） | 只看 GitHub `releases/latest`，也就是正式版 |
| **测试版** | 会读取 Release 列表并包含预发布（`1.0.1b1` / `1.0.1rc1`），适合尝鲜 |

> 测试版只影响「能检测到哪些版本」，升级方式与稳定版完全一样；想回退到正式版，等正式版号更高，或下载完整安装包覆盖安装。

---

## 🛠️ 常见问题

**Q1 图像识别总是失败？** 先看 `logs/find_fail_*.png`（超时会自动存一张现场截图），
再用「设置 → 找图与点击 → 测试找图」看 score：
漏检就把「相似度阈值」降到 70、把缩放区间放宽；
命中了但点偏就调「点击偏移」；
界面语言/主题差异太大就用「截取模板」重截一张（存在 `config/templates/`，优先于内置模板）。
排查环境可运行 `python diagnose.py`，会打印屏幕物理分辨率、DPI 感知状态与当前找图参数。

**Q2 错过设定时间才开软件，还会执行吗？** 会。每 10 秒检查一次，当天未执行且已过时间点就补跑一次。

**Q3 任务结束没有推送？** 检查 SendKey / Webhook 是否正确，用设置页的「测试」按钮验证。

**Q4 MAA / MaaEnd 已在运行，会重复启动吗？** 不会。检测到已在运行会拉到前台。

**Q5 界面出来了但按钮点不动？** 多半是任务执行中；看首屏按钮是否显示「■ 结束任务」。

**Q6 怎么彻底退出？** 右上角 X 是最小化到托盘；退出请右键托盘图标 → 退出 MaaAuto。

**Q7 用 Microsoft Store 版 Python 起不来？** 商店版 `sys.executable` 是转发器，权限与路径都异常。换 python.org 安装版即可（`--no-admin` 已废弃，无作用）。

**Q8 升级失败后主程序打不开？** 检查 `config/.upgrading` 是否残留；程序会在 5 分钟后自动清理，也可手动删除该文件。失败详情见 `config/upgrade_failed.flag` 与 `logs/upgrading.log`。

**Q9 检查更新很慢？** 网络请求都在后台线程，不阻塞界面；GitHub API 在部分网络下不稳定，可稍后重试。

**Q10 提示缺少 `serverchan_sdk`？** 安装包不完整，重装完整包，或改用通用 Webhook。

---

## ⚠️ 关于「关闭所有前台程序」

该策略**只有你主动选择时**才会触发：执行前强制关闭所有可见窗口的前台程序（系统进程、模拟器、MAA / MaaEnd 等白名单除外）。

> **未保存的 Word / Excel / 记事本 / 浏览器内容会直接丢失。** 建议只在专用挂机机上使用。

默认策略是「**不做任何操作**」。

---

## ⚠️ 免责声明

- 本项目仅用于学习 Python 自动化、GUI 开发与进程管理。
- 与 MAA、MaaEnd 官方无任何关联，为第三方调度工具。
- 请勿用于商业用途。
- 使用本软件产生的任何直接或间接后果（含游戏账号封禁、数据丢失、系统异常）由使用者自行承担。

---

## 🔌 与安装器的约定

安装版由 [MaaAuto-Installer](https://github.com/mmccz/MaaAuto-Installer) 负责安装、升级与卸载。两边只通过三个文件握手：

| 文件 | 写入方 | 读取方 | 含义 |
| --- | --- | --- | --- |
| `config/.upgrading` | 升级器 | 主程序（启动 + 每秒轮询） | 存在即退出；正常路径由升级器删除，残留 5 分钟后由主程序自动清理 |
| `config/upgrade_failed.flag` | 升级器 | 主程序（启动 300ms 后） | JSON；弹窗提示后由主程序删除 |
| `config/last_launch_args.json` | 主程序 | 升级器 | 重启时恢复 `--autostart` 等参数 |

Release 资产：

| 资产 | 用途 |
| --- | --- |
| `MaaAuto_Setup_v*.exe` | 完整安装包 |
| `MaaAuto_Online_v*.exe` | 在线引导包 |
| `MaaAuto_payload_v*.zip` | 升级器下载的预构建程序包 |
| `SHA256SUMS.txt` | 上述三个构建产物的校验和（自身也是 Release 资产之一） |

> 发版：push 两个仓库后打 `v*` tag，CI 会构建上述 4 个资产并用仓库里的
> `RELEASE_NOTES.md` 作正文**直接发布** Release（预发布 tag 自动标 prerelease）。

`app_info.py` 里的 `APP_UPDATE_API`、`APP_MIN_INSTALLER_VERSION`、`APP_PAYLOAD_ASSET_PREFIX` 与安装器 `installer/contract.py` 是**冻结契约**：改任一值等于协议变更，必须两仓库同时发版（`extra` 只在安装时写入，升级不刷新，改了对老用户不生效）。

---

## 📄 许可证与相关仓库

本项目采用 **MIT License**，见 [LICENSE](LICENSE)。

| 仓库 | 说明 |
| --- | --- |
| [MaaAuto-Tool-works](https://github.com/mmccz/MaaAuto-Tool-works) | 主程序（本仓库） |
| [MaaAuto-Installer](https://github.com/mmccz/MaaAuto-Installer) | 安装器 / 升级器 / 卸载器 |
| [更新日志](CHANGELOG.md) | 按版本记录变更 |
