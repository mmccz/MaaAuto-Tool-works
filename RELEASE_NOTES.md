# MaaAuto v1.4.6

> **小更新** · 修深色主题下弹窗看不清，统一弹窗按钮 / 表头 / 留白 · 新增中英文使用者手册 · 2026-11-01

## 本版要点

- **深色主题下弹窗终于能看清了**：以前「提示 / 警告 / 确认」这类弹窗是黑底黑字，
  按钮还是系统灰白样式；现在文字用主题色、按钮与主界面同一套圆角样式。
- **时间选择弹窗说中文**：不再是英文 `OK` / `Cancel`，改成「确定 / 取消」，按钮跟着主题走。
- **进程选择表格表头不再发白**：深色主题下表头原来是一条白带（样式用了透明背景，
  透出了浅色 palette），现在是实色表头。
- **弹窗留白统一**：消息框、公告右栏、教程右侧、进程选择边距对齐，150% 缩放下统计文案
  不再被截断。
- **中英文文档**：新增 `docs/guide/zh-CN.md`、`docs/guide/en-US.md` 使用者手册，以及
  `README.en.md`；中英文 README 顶部可互相切换。

## 现象

1. 深色主题下弹出「MAA 仍在运行，请先退出后重试」这类提示，文字几乎是黑的，几乎看不清；
   按钮是 Windows 经典灰白样式，与主界面完全不搭。
2. 设置 → 定时与推送 → 添加时段，弹窗底部是英文 `OK` / `Cancel`。
3. 设置 → 进程与窗口 → 选择进程，表格表头在深色主题下是一条白底深字的横带。

## 原因

- 主题样式只给 `QDialog` 设了深色背景，**没有**给 `QMessageBox` 的文字色与按钮样式：
  文字沿用系统 palette 的黑色，按钮沿用系统原生样式。
- `QHeaderView::section` 用了 `background: transparent`，在深色下透出的是浅色 palette。
- 时间选择弹窗用的是 `QDialogButtonBox`，文案来自 Qt 自带翻译（此处未加载），
  样式也未被主题接管。

## 修复

- `themes/dark.qss` / `light.qss`：
  - 新增 `QDialog QPushButton, QMessageBox QPushButton` 基样式（圆角 8px、32px 高、
    hover / pressed / disabled），**作用域限定弹窗**，不影响主界面尺寸与布局；
  - `QMessageBox QLabel` 文字色（深色 `#e5e7eb`、浅色 `#1f2937`）；
  - `QHeaderView` + `QHeaderView::section` 改为实色背景，空表也不发白。
- `ui/schedule_editor.py`：时间选择弹窗改用显式按钮，文案 `common.ok` / `common.cancel`，
  主按钮 / 次按钮样式与其它弹窗一致，补内边距。
- `ui/pages/process_picker.py`：边距 18 → 20、最小宽度 560、统计文案允许换行。
- `ui/announcements.py`：右栏 `setDocumentMargin(14)`；`ui/tutorial_dialog.py`：内容右边距 26 → 34。
- `ui/update_dialog.py`：消息框留白 24/20、间距 10。

## 测试

- 主程序 **205 → 214**（新增 7 条）：其中两条是像素级回归——
  深色主题下 `QMessageBox` 必须存在「亮像素」（防止再退回黑底黑字）、
  空表（0 行）表头区域多数像素必须是深色（防止再退回白表头）；
  另有时间选择弹窗中文按钮、弹窗边距 / 最小宽 / 文档边距 / 统计文案换行等断言。
- 安装器 **98**（无改动，同步发版）。
- CI：`tests` workflow 在 Python 3.15 上全绿；本版 Release 由 `release` workflow 构建，
  构建后自动跑安装 / 卸载 smoke。

## 升级

- 已安装的 1.x 可在程序内直接升级（优先差分包，通常几百 KB）；
- 配置、日志、`.maaauto.json` 一律保留；
- 本版无契约变更，不需要重装完整包。

## 文档

- 使用者手册：[中文](docs/guide/zh-CN.md) ｜ [English](docs/guide/en-US.md)
- README：[中文](README.md) ｜ [English](README.en.md)
