# 主程序侧答复：MaaAutoInstaller `INTEGRATION.md`（2026-10-17）

> 答复方：`mmccz/MaaAuto-Tool-works`（主程序）
>
> 对象：`MaaAuto-Installer` 维护者
>
> 依据：主程序 `main` @ `14634d6`；安装器 `1.0.0`（逐行核对了 `upgrade_stub.py` / `upgrade_engine.py`）
>
> 性质：决策记录。协议本身不变，本轮只做主程序侧的容错增强与文档修正。

---

## 0. 结论摘要

1. 你们文档里涉及主程序的描述**基本准确**，只有 3 处需要修正（§1）。
2. **R1 属实**，而且成因比文档写的更具体：`perform_upgrade()` 的 `finally` 已经会清标志，漏的是「停不掉主程序」这条路径在进入 `perform_upgrade()` **之前**就返回了（§1.1）。
3. 主程序侧兜底**已实现**（`upgrade_guard.py`），阈值 300s + 进程探测，保守优先（§3）。
4. §12 的 6 个问题全部有明确结论（§2），其中 **Q3 保持现状、Q4 冻结、Q6 接受有窗口**。
5. 安装器侧 P0 已修复，本轮复核通过（§4.1：清标志 + 九条终态统一重启，无重复启动）；下一步按 §4.2 的顺序做 P1。

---

## 1. 核对结果（以主程序代码为准）

| 文档条目 | 核对结论 | 说明 |
| --- | --- | --- |
| R1（P0） | **属实** | 详见 §1.1，且能定位到具体行 |
| §5.2「没有时间戳、不检查 upgrade.exe」 | 属实 | `main.py` 原先只做 `os.path.exists()` |
| §6.1「`--from-main` 缺失时弹提示并退出」 | 小偏差 | 实际 `return 0`（`upgrade_stub.py:1150-1157`），不是错误码 2；不影响调用方 |
| §4 时序「主程序每秒轮询到标志 → 退出」 | 正常路径几乎不触发 | 主程序 `Popen` 后立即 `cleanup_on_exit()` + `QApplication.quit()`；`request_main_exit` 发现已不在运行会直接返回 `True`，**不写标志** |
| §5 表「`.upgrading` 纯文本」 | 属实 | 主程序只看是否存在，内容完全不解析 |
| §7.3「requirements 会剥注释、丢非 ASCII 行」 | 属实，但请注意顺序 | 我方 `#` 注释含中文，均为整行注释；请确保**先剥注释、再筛 ASCII** |
| §7.4「不要打 `release/`」 | 我方 `Source.zip` 已排除 | `publish.py` 的 `EXCLUDE_TOP` 含 `release`；只有从开发目录直接构建时才需要你们排除 |
| §9.1 注册表路径 | **安装器文档正确，我方注释写错** | 正确路径是 `...\Windows NT\CurrentVersion\AppCompatFlags\Layers`；已修正 `main.py` 注释与对接文档 |
| R8（taskkill 丢配置） | 影响低于预期 | 主程序在 `Popen` 之后立即保存窗口几何（内部 `save_config`），且设置项本就逐项即时落盘；`taskkill` 最多丢掉「正在输入但未失焦」的一个值 |
| R2（`--silent` 仍有窗口） | 属实 | `upgrade_stub.py:1170-1171`：`--silent` 且非 `--check-only` 走 `run_ui(mode="silent")` |
| §6.1 退出码语义 | 属实 | `--check-only` 已最新 → 1；完整模式已最新 → 0；错误 → 2 |

### 1.1 R1 的准确位置（建议照此修）

```
upgrade_stub.py:632   if not request_main_exit(...):      ← 这里已经写了 .upgrading
upgrade_stub.py:639       return 2                        ← 直接返回，未清标志
upgrade_stub.py:642   result = perform_upgrade(...)        ← 只有进到这里才有 finally 清标志
```

`upgrade_engine.py:888-895` 的 `finally` 注释写着「★ P1 修复：无论如何，必须清 `.upgrading` 标志」，但它只覆盖 `perform_upgrade()` 内部；`return 2` 发生在调用之前，属于覆盖盲区。

`request_main_exit()` 只在「主程序在运行」时才写标志，所以正常路径（主程序已退出）连标志都不会产生——这解释了为什么平时没问题、只有 taskkill 也杀不掉时才会踩中。

> 2026-10-17：该路径已按上述方案修复并复核通过（见 §4.1）。

---

## 2. 六个问题的答复

### Q1. `.upgrading` 陈旧标志兜底 —— 接受，已实现

**结论**：主程序启动时不再「见到就退」，而是先判定：

| 条件 | 行为 |
| --- | --- |
| 标志不存在 | 正常启动 |
| 写入时间 < `300s` | 视为升级中，退出（保持原语义） |
| 写入 ≥ 300s，且有 `upgrade.exe` / `uninstall.exe` / `MaaAuto_Online_*` / 安装器进程 | 视为升级中，退出（覆盖「升级很慢」） |
| 写入 ≥ 300s，且上述进程都不在 | 判为陈旧：删除标志、写 `logs/upgrading.log`、继续启动 |
| 读不到 mtime / psutil 不可用 / 探测抛异常 | 保守处理，退出 |

实现：`MaaAutoProject/upgrade_guard.py`（含自测 `python upgrade_guard.py`），在 `main.py` 的 `.upgrading` 检查处接入。

**但请仍按 R1 修安装器**：兜底最多把「永久打不开」降级为「最多被挡 5 分钟」，不能替代 `finally` 清理。阈值 300s 而不是 2 小时，是刻意选择——升级全程 `upgrade.exe` 都在跑，超时只在「进程已经没了」时才有意义。

### Q2. 失败标志覆盖范围 —— 「`run_full` 以错误码 2 结束且非用户取消」才写

**结论（2026-10-17 修订）**：

| 终态 | 退出码 | 是否写 `upgrade_failed.flag` |
| --- | --- | --- |
| `--check-only` 的任何结果 | 0 / 1 / 2 | ❌（没有进入升级动作） |
| 已是最新 | 0 / 1 | ❌ |
| 用户取消（下载前 / 下载后 / 升级中） | 0 / 2 | ❌ |
| 缺少 / 读不了 `.maaauto.json` | 2 | ✅ |
| 升级器版本过低 | 2 | ✅ |
| `run_full` 检查更新失败 | 2 | ✅ |
| 下载源码包失败 | 2 | ✅ |
| 无法停止主程序 | 2 | ✅（且必须先清 `.upgrading`） |
| `perform_upgrade` 失败 / 未捕获异常 | 2 | ✅ |

**为什么修订上一版结论**：之前担心「检查失败写标志会导致每次断网都弹窗」。复核后确认不成立——标志只可能在 `upgrade.exe` **真正启动过**（用户已在主程序确认升级，或开启了自动升级）之后写入，是一次性事件；主程序**自身**的启动检查失败根本不会走到这里，也不会写标志。因此统一成「进入 `run_full` 后的失败都写」更简单，也让 `--silent` 失败有唯一可靠的告知渠道。

**保留的例外**：用户取消不是失败，重试/重装后都不该看到「上次升级失败」。

配合这项约定，我方已把弹窗标题从「上次**自动**升级失败」改成「上次**升级**未能完成」。

### Q3. 升级 UI 归属 —— 保持现状（主程序判断 + 升级器复核）

**结论**：主程序**不会**改用 `--check-only`。理由：

1. `--check-only` 的交互模型要求主程序在用户确认前就退出（否则升级时文件被锁），但用户也可能点「取消」——主程序不能为了一个可能不发生的升级先自杀。
2. 若主程序保持运行、轮询升级器状态，就引入了第二套握手（谁写状态、写哪里、超时多少），成本远大于收益。
3. 多一次 GitHub API 请求可以忽略：主程序只在启动 5s 后或用户点按钮时检查，`releases/latest` 未认证限额 60 次/小时，日常远够。
4. **复核是特性不是缺陷**：主程序检查到用户决定升级之间可能隔了几分钟，期间 Release 可能被替换、也可能触发了限流；升级器重新校验能避免「拿旧 URL 升级」。
5. 你们自己的 UI 已经用 `skip_check` + `pre_check_info` 避免了「升级器内部检查两次」。

> 如果将来确实要做「单一 UI」，需要新开一版协议：主程序只负责唤出 `upgrade.exe --check-only` 并**保持不退出**，由升级器在用户确认后回调一个「请退出」信号。本期不做。

### Q4. 版本语法与 Asset 名 —— 确认冻结

**结论**：冻结，文法如下（主程序 `publish.py` 已加校验）：

```
APP_VERSION = X.Y.Z [ (a|b|rc)N ] [ .postN ]
```

- ✅ `2.1.0` / `2.2.0b1` / `2.1.0rc2` / `2.1.0.post1`
- ❌ `2.1.0-beta` / `2.1.0.dev1` / `2.1.0+local`
- 约束：`APP_VERSION` 必须等于 tag 去掉前缀 `v`；`MaaAuto_Source.zip` 固定名，永不改名。

补充两点：

- 主程序 `_pick_asset()` 的「含 win / 任意 zip」兜底**只用于展示**，升级器只认精确名——所以「固定名」这条对升级链路是硬约束。
- `releases/latest` **不返回 prerelease**。如果发 `v2.2.0b1`，主程序看不到它——这是 GitHub 语义，不是 bug；预发布只能靠完整包手动安装。

### Q5. 常量同步 —— 建议「机器断言 + 事实冻结」

**结论**：

1. **把三个常量视为冻结**：`APP_UPDATE_API`、`APP_SOURCE_ASSET`、`APP_MIN_INSTALLER_VERSION`。改动等于协议变更，需要双方同时发版。
2. **安装器侧加构建期断言**（比流程约定可靠）：

   ```python
   # 解压源码后，读 <source>/app_info.py，与 manifest 硬编码值逐一比较
   assert app_info["APP_UPDATE_API"] == MANIFEST_EXTRA["update_api"]
   assert app_info["APP_SOURCE_ASSET"] == MANIFEST_EXTRA["source_asset_name"]
   assert app_info["APP_MIN_INSTALLER_VERSION"] == MANIFEST_EXTRA["min_installer_version"]
   # 不一致 → 构建失败，而不是打出一个必然跑偏的包
   ```

3. **为什么必须冻结而不是"记得同步"**：`.maaauto.json` 的 `extra` 是**安装时**由安装器写入的，而 `perform_upgrade()` 只更新 `version` / `requirements_hash` / `installer_version` / `last_upgrade_from` / `source_hash`，**从不刷新 `extra`**。也就是说，一旦改了 `APP_UPDATE_API`，老用户机器上的 `upgrade.exe` 会永远读旧地址——直到用户重装完整包。这种情况下，"同步"根本救不了存量用户。
4. 如果确实必须改（例如仓库改名 / 平台迁移）：按「**必须重装**」发版，并在 Release 说明里写清；同时保留旧 API 地址可用（改名场景用旧仓库继续转发 Release）。
5. 可选改进（不阻塞）：升级器下载到新 `Source.zip` 后，可以读新 `app_info.py` 刷新 manifest 的 `extra`，让**下一次**检查用新值。但它救不了「本次升级」的检查，所以不能替代冻结。

### Q6. 「静默升级」的定义 —— 接受不可交互的进度窗口，但改文案

**结论**：接受。`--silent` 允许显示一个**不可交互、不需要任何人操作、成功即自动关闭**的进度窗。理由：升级要下载 Python、装依赖、跑 PyInstaller，可能几分钟；完全无窗口会让用户以为程序消失了。

配套要求（安装器侧）：

- 窗口不得阻塞升级流程，不得要求点击；失败时也必须自动关闭；
- 失败信息不能只留在窗口里，必须落到 `upgrade_failed.flag`（Q2 的范围）；
- 窗口可以最小化，但**不要** `AlwaysOnTop` 长时间抢占焦点；
- 若将来需要真正无窗口，请加 `--no-ui` 而不是改 `--silent` 的语义（我方会预留传递）。

我方会把设置项文案从「自动下载并升级（静默）」改为「自动下载并升级（免确认）」，避免承诺「静默」却弹窗。

---

## 3. 本轮主程序改动

| 文件 | 改动 | 回归关注点 |
| --- | --- | --- |
| `MaaAutoProject/upgrade_guard.py` | 新增：陈旧 `.upgrading` 判定 / 清理；纯标准库 + 可选 psutil；自带自测 | 启动路径、无 Qt 依赖 |
| `MaaAutoProject/main.py` | 接入 `resolve_upgrade_flag()`；注册表注释补 `Windows NT`；失败弹窗文案改为「上次升级未能完成」 | 正常启动 / `--upgrading` / `.upgrading` 三条路径 |
| `MaaAutoProject/app_info.py` | 补充契约注释（行首正则、版本子集、三常量冻结） | 无行为变化；`APP_VERSION` 行格式不变 |
| `MaaAutoProject/publish.py` | 新增 `VERSION_RE` 与发布前 `APP_VERSION` 校验 | 发布流程多一行检查 |
| `docs/INSTALLER_INTEGRATION.md` | §0 / §2.2 / §3.4 / §4.2 / §5.1 同步本次结论 | — |

**未改**：`APP_VERSION` 仍为 `2.1.0`（未发版）；协议版本仍为 v1；未改动任何命令行参数。

已验证：`upgrade_guard.py` 自测通过；`main.py` / `publish.py` / `app_info.py` 编译通过（本机无 PySide6，未做 GUI 实跑）。

> 2026-10-17 复核轮：仅核对安装器 P0 修复，主程序本轮无新增代码改动。

---

## 4. P0 复核与后续优先级

### 4.1 P0 已修复（2026-10-17，已核对安装器代码）

| 检查点 | 结论 |
| --- | --- |
| 停不掉主程序时清标志 | ✅ `upgrade_engine.py:461-468`：taskkill 失败与异常两条分支都调用 `clear_upgrading_flag()` |
| `run_full` 停止失败再兜一次 | ✅ `upgrade_stub.py:686-690` |
| 终态重启只有一个入口 | ✅ 全仓仅 `_restart_if_needed()` 内调用 `restart_main()`（`upgrade_stub.py:519`），旧的成功后直接重启已移除，**不会双开** |
| 九条终态都接入 | ✅ 缺少安装信息 / 检查失败 / 无更新 / 取消 ×2 / 下载失败 / 停止失败 / 升级异常 / 成功 / 失败 |
| 用户取消不写失败标志 | ✅ `upgrade_stub.py:760-773` |
| 安装 / 覆盖安装清残留 | ✅ `progress.py:276-284` |

**仍有 3 个残余风险，建议顺手处理**

1. `_restart_if_needed()` 忽略了 `clear_upgrading_flag()` 的删除失败。若文件被占用或权限拒绝，升级器已经退出、重启的主程序却会立刻退出，用户再次「双击没反应」。建议重启前 `Path.exists()` 复核一次，失败则**不重启**并写日志（或先 `os.replace` 成 `.upgrading.old` 再删）。
2. `progress.py` 的清理是**无条件**的：如果同时有另一个 `upgrade.exe` 正在升级，会删掉对方的标志，可能让主程序在替换文件期间启动。建议加「主程序未运行且无 `upgrade.exe` 进程」的前置判断。
3. **存量用户拿不到这次修复**（D14）：升级不重建 `upgrade.exe`，所以 2.1.0 老用户的升级器仍是旧代码。主程序的 300s 兜底正是为这批人保留的，不能因为「已修」就删掉。

### 4.2 P1/P2 优先级建议（对 D1–D14 的排序）

| 顺序 | 事项 | 理由 |
| --- | --- | --- |
| 1 | **D1 超时 5s→15s + D3 部署前无条件写标志** | 改动最小，直接封住 P0 复发窗口；5s 对「3s 线程等待 + 杀进程 + Qt 退出」偏紧 |
| 2 | **D4 复制占用重试** | 几行代码，避免杀软扫描导致整轮回滚 |
| 3 | **D7 失败标志全路径**（规则见 Q2 修订），顺带 D8 把失败日志也复制到 `logs/upgrade/` | 让 `--silent` 失败有唯一可靠告知渠道 |
| 4 | **D9 + D10 + D12 + D13 卸载器** | 用户可见的正确性：优雅停止、取消清标志、删 `Run` 键、删 `AppCompatFlags`、真正实现 `/S`。必须作为一组做，否则「宣传支持但不支持」继续存在 |
| 5 | **D14 stub 随升级更新** | 杠杆最高但工作量最大，建议单独立项；短期靠 Release Notes 要求老用户跑一次完整安装包 |
| — | 不属于 P1 | `--silent` 的 UI 形态（Q6 已定：接受不可交互窗口）；卸载默认值（建议默认**保留** `config/`、`logs/`，`/REMOVE_DATA` 才删） |

> 结论：**继续做 P1，但先做 1–3（预计半天内），再动卸载器。**

### 4.3 第二轮：口径回填（2026-10-17 晚）

安装器侧复核后发现 Q2 的**修订版口径没有落地**：代码只给「下载 / 停止 / 升级」写 flag，
缺 manifest、版本过低、检查更新失败这三条 `run_full → 2` 的路径只重启不写；两份安装器
文档（`INTEGRATION.md` R4 / §12、`INSTALLER_RESPONSE.md` D7 / §5）也把口径写回了修订前。

已按本文件 §2 的表格修正：

- `upgrade_stub.py`：`_do_check()` 记录失败原因，`run_full` 在 `code == 2` 与
  skip_check 缺 manifest 两处补 `_write_failure()`；`--check-only` 仍不进 `run_full`。
- 安装器文档同步为「`run_full` 以 2 结束且非取消都写」。
- 顺带修掉 `resolve_python_mirror()` 的镜像回落：未知 key（含 PyPI 的 tuna/aliyun/ustc/pypi）
  改为按 `auto` 处理，不再回落到 python.org。

主程序侧本轮另修：`build.py` 不再排除 numpy、`publish.py` 版本校验改为阻断、
`resource_path()` 去掉 CWD 依赖、Worker 不再摘除全局日志 handler、
定时撞上运行中任务不再吞掉当天、开机自启命令改为 `sys.executable` 且开关即时生效、
背景图按参数缓存避免重复解码。

---

## 5. 联调用例（主程序侧可执行）

```powershell
$I = "D:\MaaAuto"

# 1) 陈旧标志：应正常开窗，并写 logs\upgrading.log
New-Item -ItemType File -Force "$I\config\.upgrading" | Out-Null
(Get-Item "$I\config\.upgrading").LastWriteTime = (Get-Date).AddHours(-1)
# 确认没有 upgrade.exe / uninstall.exe 在跑
Start-Process "$I\MaaAuto.exe"
Get-Content "$I\logs\upgrading.log" -Tail 5
Test-Path "$I\config\.upgrading"        # 期望 False

# 2) 新鲜标志：应直接退出（无窗口）
New-Item -ItemType File -Force "$I\config\.upgrading" | Out-Null
Start-Process "$I\MaaAuto.exe" -Wait
Test-Path "$I\config\.upgrading"        # 期望 True（仍需安装器清理）

# 3) 失败标志：应弹窗、关闭后文件消失
@'
{"from_version":"2.1.0","to_version":"2.2.0","reason":"联调测试","log_path":"C:\\temp\\x.log"}
'@ | Set-Content -Encoding utf8 "$I\config\upgrade_failed.flag"
Start-Process "$I\MaaAuto.exe"
Test-Path "$I\config\upgrade_failed.flag"   # 期望 False

# 4) 启动参数恢复：args 含 --autostart 时升级后应只出托盘
Get-Content "$I\config\last_launch_args.json" -Raw
```

另外：

```powershell
python MaaAutoProject\upgrade_guard.py     # 自带自测
```

---

## 6. 遗留问题（供知悉，不阻塞本次对接）

1. **`build.py` 排除 `numpy` 但打包 `cv2`**：`opencv-python-headless` 依赖 numpy，排除后打包版大概率 `import cv2` 失败 → 自动降级为精确像素匹配。安装器构建也走这份 `build.py`，所以会在安装包上复现。我方下一轮修（移除 `numpy` 排除或改打包策略），修完会告知。
2. **README Q7 仍写 `--no-admin`**：该参数自 2026-09-20 已空操作，属文档未同步。
3. **主程序无单实例锁**：双开会各自跑一套任务；若安装器假设「唯一实例」，需我方补（当前不补）。
4. **R3**：升级不更新 `upgrade.exe` / `uninstall.exe`，旧升级器会一直沿用——同你们的判断，属安装器侧设计取舍。
5. **`DisplayVersion` 不随升级刷新**：仅「应用和功能」展示问题；主程序「关于」页读的是编译期 `APP_VERSION`，不受影响。
