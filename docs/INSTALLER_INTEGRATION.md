# MaaAuto ↔ MaaAutoInstaller 对接说明

> **版本基线**：MaaAuto `v2.1.0`（仓库 `main` @ `14634d6`）
>
> **读者**：MaaAutoInstaller（安装器 / `upgrade.exe` / `uninstall.exe`）的维护者
>
> **来源**：本文所有结论均来自主程序源码；凡标注「安装器」或「安装器侧」的条目，主程序不实现，必须由安装器承担。
>
> **维护**：主程序改动 §2 / §3 / §4 中任一约定时，必须同步更新本文并通知安装器侧。
>
> **配套**：2026-10-17 与安装器侧的逐条答复见 [INSTALLER_REPLY.md](INSTALLER_REPLY.md)。

**目录**

- [0. 一页纸版本](#0-一页纸版本)
- [1. 安装目录布局](#1-安装目录布局)
- [2. 停止已运行的主程序](#2-停止已运行的主程序升级前必须做)
- [3. `upgrade.exe` 契约](#3-upgradeexe-契约)
- [4. 版本号与 Release 契约](#4-版本号与-release-契约)
- [5. 权限 / UAC / 注册表](#5-权限--uac--注册表)
- [6. 用户数据](#6-用户数据)
- [7. 卸载契约](#7-卸载契约uninstallexe)
- [8. 安装器侧验收清单](#8-安装器侧验收清单)
- [9. 待安装器侧确认的开放问题](#9-待安装器侧确认的开放问题)
- [10. 冻结约定与变更记录](#10-冻结约定与变更记录)

---

## 0. 一页纸版本

| 问题 | 答案 |
| --- | --- |
| 安装器要往安装目录放什么 | `MaaAuto.exe`、`_internal/`、`resources/`、`themes/`、`i18n/`、`requirements.txt`、`README.md`、`LICENSE`，外加 **`upgrade.exe`、`uninstall.exe`** |
| 升级入口在哪 | `<安装目录>/upgrade.exe`，由主程序 `Popen` 调起 |
| 谁让主程序退出 | **安装器**：写 `config/.upgrading` 标志，主程序 1 秒内响应并退出 |
| 谁恢复启动方式 | **安装器**：读 `config/last_launch_args.json` 后重启 |
| 失败怎么告诉用户 | **安装器**：写 `config/upgrade_failed.flag`（JSON），主程序下次启动弹窗并自动删除 |
| 主程序怎么知道有新版本 | 自己请求 GitHub `releases/latest`，与 `app_info.APP_VERSION` 比较 |
| 主程序会不会下载 / 替换文件 | **不会**。主程序只负责「检查 + 展示 + 调起 upgrade.exe」 |
| 最容易被忽略的坑 | 升级完**必须删除** `config/.upgrading`。主程序对「超过 5 分钟且无升级器进程」的残留标志有兜底清理，但 5 分钟内仍会启动即退 |
| 标志残留怎么办 | 主程序启动时判定陈旧（阈值 300s + 进程探测）→ 删除并继续；新鲜标志仍按「升级中」退出 |

---

## 1. 安装目录布局

### 1.1 安装器应产出的内容（PyInstaller onedir）

```
<安装目录>/                       ← sys.executable 所在目录，必须是这个位置
├─ MaaAuto.exe                    ← 主程序（需写入 RUNASADMIN 兼容标志，见 §5.1）
├─ upgrade.exe                    ← 升级器（安装器侧提供，主程序按固定路径查找）
├─ uninstall.exe                  ← 卸载器（安装器侧提供，主程序从不调用）
├─ _internal/                     ← PyInstaller 运行时（python3xx.dll、Qt 等）
├─ resources/
│  ├─ icon.ico
│  ├─ maa_start.png               ← 找图模板，可随版本更换
│  └─ maaend_start.png
├─ themes/  light.qss dark.qss
├─ i18n/    zh_CN.json en_US.json
├─ requirements.txt               ← 随包附带，供用户排查环境
├─ README.md
├─ LICENSE
├─ CHANGELOG.md                   ← 可选，build.py 找不到只告警不报错
└─ _version_info.txt              ← 可选，构建产物
```

`build.py` 生成的 `dist/MaaAuto/` 就是这个结构；安装器打包时直接全量收进去即可。

### 1.2 只有运行时才会生成的文件（安装包**不要**内置）

| 路径 | 生成者 | 说明 |
| --- | --- | --- |
| `config/config.json` | 主程序 | 用户配置，首次启动自动创建 |
| `config/last_launch_args.json` | 主程序 | 每次启动写一次，供升级器恢复启动参数（§3.3） |
| `logs/` | 主程序 | 任务日志，见 §6.3 |
| `config/.upgrading` | **安装器** | 升级互斥标志（§2.2） |
| `config/upgrade_failed.flag` | **安装器** | 升级失败标记（§3.4） |
| `.maaauto.json` | **安装器** | 主程序**从不读、也从不写**，可自由定义（见 §9 开放问题 2） |

### 1.3 升级时「必须保留」与「应当覆盖」

主程序自带部署脚本 `deploy_dev.py` 固化了这份白名单，安装器请保持一致：

| 保留（用户数据 / 第三方组件） | 覆盖（本次版本产物） |
| --- | --- |
| `config/` | `MaaAuto.exe` |
| `logs/` | `_internal/` |
| `.maaauto.json` | `resources/` |
| `upgrade.exe` | `themes/` |
| `uninstall.exe` | `i18n/` |
| | `requirements.txt`、`README.md`、`LICENSE`、`CHANGELOG.md`、`_version_info.txt` |

> 若新版本自带新版 `upgrade.exe`：它正在运行、文件被锁，不能直接覆盖。建议先 `MoveFileEx` 改名，或由新进程延迟替换（安装器侧自行处理）。

### 1.4 写权限

`config/`、`logs/` 在 `import config_manager` 时用 `os.makedirs` 创建，**失败会直接抛异常、主程序连窗口都出不来**。因此：

- 安装目录必须可写（或安装器预创建 `config/`、`logs/` 并授予当前用户/管理员写权限）；
- `RUNASADMIN` 生效时以管理员身份写，通常没问题；
- 不要装到只读介质或受管目录后又不给权限。

---

## 2. 停止已运行的主程序（升级前必须做）

### 2.1 先记住三条事实

1. 主程序 `setQuitOnLastWindowClosed(False)`，关闭主窗口只是**隐藏到托盘**，进程继续跑。
2. 主程序**没有单实例锁**，也没有「把命令行参数转发给已运行实例」的机制。
3. 升级必须替换 `MaaAuto.exe` 与 `_internal/*.dll`，文件被占用时替换一定失败 → **必须先让进程退出**。

### 2.2 推荐方式：`config/.upgrading` 标志文件

**协议（安装器侧实现）**

```
1) 创建/触碰文件： <安装目录>/config/.upgrading
   - 文件内容随意（主程序只看「是否存在」，不看内容）
   - 目录不存在则先创建 config/
2) 等待 MaaAuto.exe 退出（建议轮询 200ms，超时 15s）
3) 超时未退出 → TerminateProcess(pid)，再等 2s
4) 升级完成后，无论成功 / 失败 / 用户取消，都必须删除 .upgrading
```

**主程序侧行为**

| 时机 | 行为 |
| --- | --- |
| 启动最早期（早于 `QApplication`） | 存在**新鲜**标志 → `sys.exit(0)`；存在**陈旧**标志 → 删除后继续启动（见下文） |
| 运行中，`MainWindow` 每 **1000ms** 轮询一次 | 发现存在 → 保存窗口几何 → 中止任务线程（最多等 3s）→ 杀掉 MAA / 模拟器等相关进程 → 退出 |

> ⚠️ **最高优先级注意事项**：`.upgrading` 对主程序是「毒丸」标志，正常路径必须由**安装器**删除。
> 若安装器在成功、回滚、用户取消等任何路径上忘了删，用户会「双击没反应」。
> 建议在安装器的所有 `exit` 路径（含异常 / `finally`）里统一清一次。
>
> ✅ 安装器侧 2026-10-17 已修（D2）：`request_main_exit()` 失败路径清标志、九条终态统一走 `_restart_if_needed()`。
> 但**旧版 `upgrade.exe` 不会随升级更新**（D14），存量用户的升级器仍是旧代码，所以主程序侧的兜底必须保留。

**陈旧标志兜底（`upgrade_guard.py`，随下一版本发布）**

| 条件 | 行为 |
| --- | --- |
| 标志不存在 | 正常启动 |
| 写入时间 < 300s | 视为升级中，退出 |
| 写入 ≥ 300s，且 `upgrade.exe` / `uninstall.exe` / `MaaAuto_Online_*` / 安装器进程仍在运行 | 视为升级中，退出 |
| 写入 ≥ 300s，且上述进程均不存在 | 删除标志、写 `logs/upgrading.log`、继续启动 |
| 读不到 mtime / psutil 不可用 / 探测异常 | 保守处理，退出 |

> 兜底不能替代安装器清理：阈值内用户仍会被挡住，且日志只能证明「发生过」，不能替代正确删除。

### 2.3 备选方式：`--upgrading` 命令行模式

主程序支持 `MaaAuto.exe --upgrading`，行为是：

1. 写 `logs/upgrading.log`；
2. `load_config()` + `save_config()`（把配置落盘）；
3. `kill_all_related_processes()`：强杀 `maa.exe`、`maa-cli.exe`、`maaend.exe`、`MuMuPlayer.exe`、`NemuPlayer.exe`、`dnplayer.exe`；
4. `exit(0)`。

**适用场景**：上一轮异常退出后残留了 MAA / 模拟器进程，需要一次「无 UI 的清理」。

**⚠️ 三个陷阱**

1. 它**不会**关闭另一个正在运行的主程序（没有单实例机制）——你杀掉的是子进程，真正的主程序还在。
2. 它**不会**删除 `.upgrading`。
3. 它走的是「无窗口」分支，根本不会执行 `_write_launch_args`，所以 `--upgrading` 不会污染 `last_launch_args.json`。

> 结论：**停止主程序请用 §2.2 的 `.upgrading`**；`--upgrading` 只当清理工具用。

### 2.4 不要使用的方式

| 方式 | 为什么不行 |
| --- | --- |
| 发送 `WM_CLOSE` | 会被 `closeEvent` 拦下 → 最小化到托盘，进程照跑 |
| 直接 `TerminateProcess` 当默认手段 | 任务线程可能正在写 `task.log`、配置可能写一半；作为超时兜底可以，不要首选 |
| 只删文件不关进程 | `_internal/*.dll` 被锁，替换必失败 |

### 2.5 等待与超时建议

| 阶段 | 建议超时 |
| --- | --- |
| 等待主程序退出（正常路径） | 5s 足够（清理只有「杀进程 + 最多 3s 线程等待」） |
| 等待主程序退出（含任务中止） | 15s（`_shutdown_worker` 最坏 3s + 杀进程） |
| 超时后强杀 → 再等 | `TerminateProcess` + 2s |
| 替换文件遇到 `ERROR_SHARING_VIOLATION` | 退避重试 3 次（0.5s / 1s / 2s），多为杀软扫描 |

---

## 3. `upgrade.exe` 契约

### 3.1 调用方式（主程序 → 升级器）

```python
install_dir = os.path.dirname(os.path.abspath(sys.executable))   # <安装目录>
upgrade_exe = os.path.join(install_dir, "upgrade.exe")
args = [upgrade_exe, "--from-main", "--restart"] + (["--silent"] if silent else [])
subprocess.Popen(args, cwd=install_dir)
# 紧接着：is_quitting=True → 保存窗口几何 → 杀 MAA/模拟器 → QApplication.quit()
```

| 项 | 值 |
| --- | --- |
| 路径 | `<安装目录>/upgrade.exe`（主程序只认这一个位置，可由 `sys.executable` 推导） |
| 工作目录 | `<安装目录>` |
| 父进程 | 就是 `MaaAuto.exe`（可据此判断「等了谁」） |
| 权限 | 继承主程序的**管理员**令牌（主程序带 RUNASADMIN，见 §5.1） |
| 参数 `--from-main` | 恒传。表示「由主程序发起」，此时主程序已在自行退出、并已清理 MAA/模拟器 |
| 参数 `--restart` | 恒传。升级器结束于**任何**终态（成功 / 失败 / 取消 / 无更新）时，只要主程序不在运行就重启；主程序仍在运行则跳过（2026-10-17 起） |
| 参数 `--silent` | 仅自动升级路径传。允许显示不可交互的进度窗口，但不得要求点击（见 §9 开放问题 6） |
| 未传的内容 | **目标版本号、下载 URL、asset 地址都没有传** → `upgrade.exe` 必须自己去 GitHub 查（见 §9 开放问题 3） |

主程序在 `Popen` 成功后立刻退出，**不会**再给升级器任何回调或确认。

### 3.2 升级器必须完成的动作（建议顺序）

```
0. 若本次不是由主程序发起（无 --from-main），且检测到主程序在跑：
      写 config/.upgrading → 等退出（同 §2.2）
1. 等待父进程 / <安装目录>\MaaAuto.exe 退出（15s，超时 TerminateProcess）
2. （保险）若 .upgrading 不存在则创建，覆盖「退出到替换之间被用户再次启动」的窗口
3. 备份旧版本（至少 MaaAuto.exe + _internal/），供回滚
4. 获取新版本 → 校验 → 解压 / 安装
5. 成功：删除 config/.upgrading → 若带 --restart 且主程序不在运行 → 重启（§3.3）
6. 失败：回滚 → 写 config/upgrade_failed.flag（§3.4）→ 删除 config/.upgrading → 重启（同上）
   取消 / 无更新 / 检查失败：同样「清标志 → 重启」，但不写失败标志
7. 退出（建议 0=成功，非 0=失败；主程序不读退出码，但便于日志排查）
```

### 3.3 重启与启动参数恢复

主程序每次启动都会在窗口显示前写一次 `config/last_launch_args.json`（`--upgrading` 与「启动即遇 `.upgrading` 早退」两条路径除外）：

```json
{
  "args": ["--autostart"],
  "written_at": "2026-10-17T20:01:46"
}
```

| 字段 | 说明 |
| --- | --- |
| `args` | 当次启动参数数组，**已剔除 `--upgrading`**；可能为空数组 |
| `written_at` | 本地时间，`YYYY-MM-DDTHH:MM:SS`，仅作参考 |

**安装器侧做法**

> `--restart` 的语义（2026-10-17 起）：升级器结束于**任何**终态（成功 / 失败 / 取消 / 无更新）时，只要主程序不在运行就重启；主程序仍在运行则跳过，避免双开。

1. 读取该文件；不存在或 JSON 非法 → 当作空参数启动；
2. 过滤掉 `--upgrading`（防御性）；
3. `Popen([MaaAuto.exe] + args, cwd=<安装目录>)`；
4. **不要**额外追加 `--autostart`——它决定「启动后隐藏到托盘」，只在用户本来就是这样启动时才该保留，而 `args` 已经记录了这一点。

> 用户手动点「检查更新」升级时，`args` 通常为空 → 升级后应**显示**主窗口。
> 开机自启场景，`args` 为 `["--autostart"]` → 升级后应**隐藏**启动，保持原行为。

### 3.4 失败与回滚：`config/upgrade_failed.flag`

主程序启动后 **300ms** 读取该文件（早于用户操作），弹出警告框，然后**删除文件**。

**文件格式**（UTF-8，可带 BOM，必须是合法 JSON 对象）

```json
{
  "from_version": "2.1.0",
  "to_version": "2.2.0",
  "reason": "下载失败：HTTP 404",
  "log_path": "<安装目录>/logs/upgrade_2026-10-17_200000.log"
}
```

| 字段 | 用途 | 缺失时 |
| --- | --- | --- |
| `from_version` | 弹窗显示「从 X →」 | 显示 `?` |
| `to_version` | 弹窗显示「→ Y」 | 显示 `?` |
| `reason` | 弹窗显示的原因 | 显示「未知」 |
| `log_path` | 指向升级日志，供用户反馈 | 显示「未知」 |

**行为细节**

- JSON 解析失败或读不出来 → 主程序**静默删除**该文件，不弹窗（等于失败信息丢失）；
- **触发范围（2026-10-17 修订）**：`run_full` 以错误码 2 结束且**非用户取消** → 写（含缺少安装信息、检查失败、下载失败、停主程序失败、构建/替换失败）；返回 0/1 的正常终态（无更新、取消、`--check-only` 结果）**不写**；
- 弹窗文案固定提示用户「到 GitHub Releases 手动下载完整安装包」；
- 该检查在 `--upgrading` 模式下**不执行**，在 `--autostart` 模式下**仍会弹模态框**（已知体验问题，主程序侧待改）；
- 删除动作由主程序完成，安装器无需清理。

### 3.5 `upgrade.exe` 缺失时主程序的行为

- 用户手动升级：弹窗「未找到 upgrade.exe，请重新下载完整安装包以启用自动升级功能」，不升级；
- 自动升级（`--silent`）：**静默返回失败**，不弹窗（主程序只在日志里留一行「触发升级」，不会告诉用户具体原因）。

> 因此：**安装器必须保证 `upgrade.exe` 与 `MaaAuto.exe` 同目录**。从 v2.0.1 等旧版手动覆盖安装时，容易漏掉它。

### 3.6 参考时序

```
 MaaAuto.exe                      upgrade.exe                        GitHub
     │                                 │                               │
     ├─ check_update() ───────────────────────────────────────────────▶│ GET /releases/latest
     │◀───────────────────────── {tag_name, assets, body, html_url} ────┤
     │ 用户确认（或 auto_download_update）                              │
     ├─ Popen([upgrade.exe, --from-main, --restart, (--silent)])         │
     ├─ 保存窗口几何                                                     │
     ├─ kill MAA / 模拟器                                                │
     └─ QApplication.quit() → 进程退出        │                         │
                                              ├─ 等待父进程退出          │
                                              ├─ (保险) 写 .upgrading    │
                                              ├─ 下载 / 校验 ───────────▶│
                                              ├─ 备份 → 替换文件          │
                                              │                          │
                          ┌───────────────────┤                          │
                          │ 成功               │ 失败                    │
                          │ 删 .upgrading      │ 回滚 + 写失败标记        │
                          └─ 读 last_launch_args.json                   │
                             Popen(MaaAuto.exe, args, cwd=安装目录)      │
```

---

## 4. 版本号与 Release 契约

### 4.1 版本号唯一来源

- 主程序显示 / 比较的版本：`app_info.py` 的 `APP_VERSION`（当前 `2.1.0`）；
- `build.py` 用它生成 exe 的 `FileVersion / ProductVersion` 与 `_version_info.txt`；
- 安装器展示版本、`Source.zip` 内 `app_info.py` 的 `APP_VERSION`、exe 元数据、Release tag **四者必须一致**，否则升级判断会错乱。

### 4.2 tag 必须是 PEP 440 格式

主程序用 `packaging.version.Version` 解析 tag，解析失败 → **直接判定「检查更新失败」**。

| 可用 | 不可用 |
| --- | --- |
| `v2.1.0`、`v2.2.0`、`v2.1.0b1`、`v2.1.0rc2`、`v2.1.0.post1` | `v2.1.0-beta`、`2.1.0 beta`、`release-2.1.0`、空 |

**已冻结（2026-10-17）**：只允许 `X.Y.Z` / `X.Y.ZaN` / `X.Y.ZbN` / `X.Y.ZrcN` / `X.Y.Z.postN`。
`publish.py` 发布前会校验 `APP_VERSION`，不符合直接告警；`.devN` / `+local` 一律禁止。

> 另注：主程序查的是 GitHub `releases/latest` API，**该接口不返回 draft 与 prerelease**。发 `v2.1.0b1` 这类预发布 tag 时，主程序看不到它（这是预期行为，不是 bug）。

### 4.3 Release asset 命名

主程序侧的挑选优先级（`update_checker._pick_asset`；结果目前没有被任何界面使用，属预留接口）：

1. 文件名**精确等于** `MaaAuto_Source.zip`；
2. 文件名含 `win` 且以 `.zip` 结尾（不区分大小写）；
3. 任意 `.zip`。

发布规范（与 `publish.py` 对齐）：

| asset | 用途 | 由谁生成 |
| --- | --- | --- |
| `MaaAuto_Source.zip` | 升级器使用的源码包 | 本仓库 `python publish.py` |
| `MaaAuto_Online_v{version}-Windows-x64.exe` | 完整安装包（用户手动下载） | 安装器侧 `MaaAutoInstaller/build_installer.py` |

两个 asset 由人工上传到**同一个** Release。

### 4.4 `MaaAuto_Source.zip` 内容契约

- **顶层直接是源码根**（`main.py` / `app_info.py` / `ui/` / `themes/` / `i18n/` …），**不含** `MaaAutoProject/` 这一层；
- 不含 `config/`、`logs/`、`dist/`、`build/`、`release/`、`__pycache__`；
- 不含开发脚本：`publish.py`、`deploy_dev.py`、`diagnose.py`、`selftest.py`（若存在）；
- 不含 `MaaAuto.spec`、`_version_info.txt`（会重新生成）、`.pyc`、`.log`；
- 除上述排除项外，**源码根下的其余文件会被全量收录**；若将来新增 `tools/`、`docs/` 等非运行目录，需要同步修改 `publish.py` 的 `EXCLUDE_TOP`。

> `upgrade.exe` 如何使用这份源码包（是否自带 Python / 是否现场构建）**由安装器侧决定**，本仓库只保证「内容与布局如上」。

### 4.5 最低升级器版本（预留）

`app_info.APP_MIN_INSTALLER_VERSION = "1.0.0"`（注释：升级器低于该版本时提示用户重新下载完整安装包）。

**现状：主程序尚未实际校验该值**，属于预留接口。安装器若需要，可在自身写一份版本声明（如 `.maaauto.json`），后续由主程序读取。

---

## 5. 权限 / UAC / 注册表

### 5.1 `RUNASADMIN` 兼容标志（安装器写入）

安装时为 `MaaAuto.exe` 写入：

```
HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers
    值名：<安装目录>\MaaAuto.exe（完整路径）
    值：  ~ RUNASADMIN        （标准写法，主程序不校验该值）
```

效果与约束：

- 主程序每次启动都会弹 UAC，`IsUserAnAdmin()` 恒为 `True`；
- 主程序**已移除自我提权**（2026-09-20），不再有二次 UAC 弹窗；
- 标志是「按路径」匹配：升级时**原地替换** exe 才会继续生效；换目录需重新写入；
- 卸载时删除该值。

### 5.2 开机自启键（主程序写入 / 卸载器删除）

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
    值名：MaaAuto
    值：  "<安装目录>\MaaAuto.exe" --autostart
    （开发态为：python "<...>\main.py" --autostart）
```

- 写入时机：主程序走「托盘 → 退出 MaaAuto」时，按 `config.json` 的 `auto_start` 同步一次；
  **升级导致的退出不会触发这一步**，所以升级前后注册表通常原样保留；
- `--autostart` 的语义 = 启动后 `window.hide()`，只留托盘图标；
- 卸载器应无条件删除该值。

### 5.3 已废弃参数（安装器请勿再传）

| 参数 | 状态 |
| --- | --- |
| `--no-admin` | 无任何作用（自我提权已移除） |
| `--elevated` | 无任何作用 |

> `README.md` 的 Q7 仍在教用户用 `--no-admin`，属**文档未同步**；以本节为准。
> 主程序对未知参数一律忽略，不会报错。

---

## 6. 用户数据

### 6.1 `config/config.json`

- 读取：`utf-8-sig`（**容忍 BOM**）；写入：UTF-8 **无 BOM**、`indent=4`；
- 读取时与内置默认值合并，缺失键自动补默认值；**多余的未知键会被保留**；
- JSON 损坏 → **静默回退为全默认值**（用户配置等于丢失），下一次保存会覆盖原文件。

字段速查（完整定义见 `config_manager.py` 的 `DEFAULT_CONFIG`）：

| 分组 | 键 |
| --- | --- |
| 路径 | `maa_path`、`maaend_path` |
| 进程 | `emulator_proc`、`pc_game_proc`、`foreground_action`、`blacklist_apps` |
| 超时/重试 | `wait_timeout`、`game_start_timeout`、`game_exit_timeout`、`retry_times`、`retry_interval` |
| 定时 | `enable_schedule`、`execute_time`、`last_trigger_date` |
| 推送 | `serverchan_key`、`webhook_url`、`enable_system_notify` |
| 外观 | `theme`、`accent_color`、`language`、`background_image`、`background_opacity`、`background_blur`、`background_mode`、`show_animation` |
| 常规 | `auto_start`、`minimize_to_tray`、`kill_on_exit`、`auto_check_update`、`auto_download_update` |
| 运行态 | `run_count`、`last_run_time`、`window_geometry`（Qt 几何的 base64） |

### 6.2 安装器不得做的事

| 禁止 | 原因 |
| --- | --- |
| 在主程序运行时写 `config.json` | 主程序每次改设置都整文件重写，会互相覆盖 |
| 写入非原子 / 截断的文件 | 一旦损坏，用户全部配置静默重置 |
| 读取后上传 / 打日志 `serverchan_key` | 是用户微信推送密钥，属敏感信息 |
| 修改 `window_geometry` | 是不透明 base64，改坏只会丢窗口位置 |
| 删除 `logs/` | 用户历史任务记录，README 明确承诺升级保留 |

### 6.3 `logs/` 结构

```
logs/
├─ 2026/
│  └─ 10/
│     └─ 17/
│        ├─ run_1_081500/
│        │  └─ task.log          ← 单次任务完整日志
│        └─ run_2_203000/
│           └─ task.log
└─ upgrading.log                 ← 仅 --upgrading 模式产生
```

- 无自动轮转、无上限（日志上色在 UI 层限制 2000 行，与磁盘文件无关）；
- 升级失败日志建议也放这里（如 `logs/upgrade_YYYYMMDD_HHMMSS.log`），并把路径写进 `upgrade_failed.flag` 的 `log_path`，与既有排障习惯一致。

---

## 7. 卸载契约（`uninstall.exe`）

主程序**从不调用** `uninstall.exe`，也没有约定任何参数（是否需要 `/S` 静默由安装器侧定义）。

卸载器必须处理：

1. **先停主程序**：`config/.upgrading` + 等待 + 超时强杀（§2.2）。否则 exe / dll 被占用；
2. 删除安装目录（`MaaAuto.exe`、`_internal/`、`resources/`、`themes/`、`i18n/`、附带文件）；
3. 删除 `HKCU\...\Run` 的 `MaaAuto` 值（§5.2）；
4. 删除 `AppCompatFlags\Layers` 中对应 `MaaAuto.exe` 的值（§5.1）；
5. 删除开始菜单 / 桌面快捷方式；
6. 询问是否保留 `config/`、`logs/`、`.maaauto.json`（默认建议**保留**，与「升级不清数据」的承诺一致）；
7. `upgrade.exe`、`uninstall.exe` 自删除（临时进程 / `MoveFileEx` 延迟删除）；
8. **若用户在确认框点了取消**：必须删除已写入的 `.upgrading`，否则主程序从此启动即退出。

---

## 8. 安装器侧验收清单

打包 / 发版前逐条打勾：

**安装产物**

- [ ] `<安装目录>/upgrade.exe`、`uninstall.exe` 存在且与 `MaaAuto.exe` 同级
- [ ] `resources/`、`themes/`、`i18n/`、`_internal/` 齐全
- [ ] 安装目录对管理员可写；`config/`、`logs/` 可创建
- [ ] 已写入 `RUNASADMIN` 兼容标志，首次启动弹一次 UAC
- [ ] 没有内置 `config/`、`logs/`

**升级流程**

- [ ] 写 `.upgrading` → 主程序 1s 内开始退出，数秒内进程消失（托盘图标消失、无报错弹窗）
- [ ] 等待退出有超时兜底，强杀后仍继续
- [ ] 成功 / 失败 / 取消 / 异常四条路径**都删除** `config/.upgrading`
- [ ] 失败时 `upgrade_failed.flag` 字段齐全、JSON 合法、UTF-8
- [ ] 升级后读 `last_launch_args.json` 恢复参数；`--autostart` 场景验证启动后是隐藏的
- [ ] 升级后 `config/`、`logs/`、`.maaauto.json`、`upgrade.exe`、`uninstall.exe` 均未被破坏
- [ ] 升级过程中 `config.json` 未被覆盖或截断
- [ ] 覆盖文件遇占用时有重试

**发版**

- [ ] `APP_VERSION`、exe 元数据、tag、`Source.zip` 内 `app_info.py` 四者一致
- [ ] tag 是 PEP 440（`v2.1.0` 而非 `v2.1.0-beta`）；若是预发布，已知主程序看不到
- [ ] Release 含 `MaaAuto_Source.zip` 与 `MaaAuto_Online_v*-Windows-x64.exe`
- [ ] `Source.zip` 顶层是源码根，没有 `MaaAutoProject/` 层，没有 `config/`、`logs/`

**卸载**

- [ ] 能停掉运行中的主程序
- [ ] 清理 `Run` 值与 `AppCompatFlags` 值
- [ ] 取消卸载后主程序仍可正常启动（`.upgrading` 已清）

---

## 9. 待安装器侧确认的开放问题

以下几点本仓库无法单方面定死，需要安装器侧给出结论后回填本文：

> **2026-10-17 状态**：第 2、3、5、7 条已有结论（见 [INSTALLER_REPLY.md](INSTALLER_REPLY.md) §2）；仍开放的是 **1（Source.zip 消费细节）**、**4（旧版升级策略）**、**6（单实例）**。

1. **`upgrade.exe` 如何消费 `MaaAuto_Source.zip`？** 是否自带 Python 运行时、是否现场构建、是否只用其中的 `.py` 替换？这决定 `Source.zip` 里哪些文件是「必要」的。
2. **`.maaauto.json` 的 schema 是什么？** 建议至少包含 `install_version`、`installer_version`、`install_dir`、`installed_at`，便于升级器判断「从哪个版本升」以及 `APP_MIN_INSTALLER_VERSION` 落地。主程序承诺永不读写它。
3. **是否需要主程序把目标版本 / 下载 URL 传给 `upgrade.exe`？** 现状是「什么都不传、升级器自己查 GitHub」；若要改，属于主程序改动，需同步升级本协议 version。
4. **从 `< v2.1.0` 升级的策略**：旧版主程序不认 `.upgrading`，只能强杀 + 全量覆盖。`README` 已建议 v2.0.1 用户手动覆盖安装，安装器是否要自动识别并走「全量安装」分支？
5. **静默升级（`--silent`）失败时是否需要 UI？** 已确认（2026-10-17）：接受不可交互的进度窗口；失败必须落 `upgrade_failed.flag`，不能只显示在窗口里。主程序文案将改为「自动下载并升级（免确认）」。
6. **是否要求主程序做单实例锁？** 现状无锁，理论上可双开；若安装器依赖「唯一实例」假设，需要主程序补。
7. **`uninstall.exe` 的参数约定**（如 `/S`、`/KEEP_DATA`）以及是否注册到「应用和功能」的 `UninstallString`。

---

## 10. 冻结约定与变更记录

| 日期 | 事项 |
| --- | --- |
| 2026-09 | **冻结**：主程序只做「检查 + 展示」，升级交给 `upgrade.exe`（方案 B）；`Source.zip` 顶层为源码根；tag 必须 PEP 440；安装器为 exe 写 `RUNASADMIN` |
| 2026-09-20 | 主程序移除自我提权，`--no-admin` / `--elevated` 废弃 |
| v2.1.0 | 新增：`--upgrading` 模式、`config/.upgrading` 轮询、`last_launch_args.json`、`upgrade_failed.flag` 提示 |
| v2.0.1 | 旧升级器为占位版，不支持本协议；该版本用户需手动覆盖安装 |

**改协议时的流程**：改主程序 → 更新本文对应章节 → 在 Release Notes 标注「安装器协议变更」→ 通知 MaaAutoInstaller 同步。
