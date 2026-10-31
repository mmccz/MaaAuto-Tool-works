# 弹窗视觉一致性 · 设计（2026-10-31）

## 意图与缘由

用户反馈"有些弹窗比较难看、与主界面风格不一致"。审计（离屏渲染 8 个弹窗 × 2 主题）确认这是可复现的缺陷，而非口味问题：

1. **深色主题下 `QMessageBox` 文字不可读**：QSS 只给 `QMainWindow, QDialog` 设了深色底，文字仍用浅色 palette 的黑字；按钮落在系统灰白经典样式上。全应用 24 处调用。
2. **`TimePickDialog` 用 `QDialogButtonBox`**：英文 `OK`/`Cancel` + 灰白按钮 + 无内边距。
3. **`ProcessPickerDialog` 表头在深色下白底深字**：`QHeaderView::section` 写了 `background: transparent`，实际透出浅色 palette。
4. **自绘弹窗之间缺少统一基线**：消息框留白过大、公告右栏文字顶到边、教程内容贴右边缘、进程选择窄屏下挤。
5. 所有弹窗用系统标题栏，主窗口也是 —— 自绘外壳会让弹窗比主界面更"现代"，反而更不一致。

## 目标 / 非目标

**目标**：深色与浅色下弹窗都清晰可读；弹窗内按钮、表头、留白与主界面同一套视觉语言；颜色只存在于 QSS。

**非目标**：无边框外壳、圆角窗口、阴影、自绘标题栏、主窗口改版、把原生文件选择器换成 Qt 自绘。

## 约束

- PySide6；QSS 在 `themes/dark.qss`、`themes/light.qss`，占位符 `{accent}` 等由 `ThemeManager` 替换，px 长度会被 `_scale_qss` 按界面缩放整体放大。
- 现有测试 `test_about_version_tag_uses_qss` 禁止在 Python 里内联颜色 —— 颜色只能进 QSS。
- 用户可见文案中文；代码注释/docstring 英文。
- 不改版本号、不发版；改动只进 main。

## 方案比较

| 方案 | 内容 | 取舍 |
| --- | --- | --- |
| **A（选定）** | 主题层补通用弹窗按钮 / `QMessageBox` / 表头规则，再逐个修弹窗留白与时间选择按钮 | 改动约 120 行、风险低、立即解决"看不清"和"违和"；窗口外壳仍是系统样式（主窗口本来就如此，一致） |
| B | A + 把 24 处 `QMessageBox` 换成自绘 `MessageDialog` | 视觉更统一，但要改 24 个调用点与相关测试，收益主要是"图标语义"，性价比低 |
| C | A + 自绘无边框外壳（圆角、阴影、自绘标题栏） | 需处理拖动 / 缩放 / 高 DPI / 高对比度 / 多屏，且必须同时改主窗口，属独立项目 |

选 A：先消灭不可读与违和，外壳改造留作后续独立课题。

## 已决定的实现

- **按钮基线作用域限定在弹窗内**：`QDialog QPushButton, QMessageBox QPushButton`（不用全局 `QPushButton`），避免影响主界面既有布局与尺寸断言。
- `QMessageBox` 文字色在两种主题各写一次；`QMessageBox` 最小宽度 380px，按钮最小宽度 88px。
- `QHeaderView { background: transparent; border: none }` + `QHeaderView::section` 改为**实色**表面（深色 `rgba(255,255,255,0.04)`，浅色 `#f3f4f6`）+ 1px 底边线。
- `TimePickDialog` 用两个显式 `QPushButton`（`PrimaryButton` / `GhostButton`），文案取 `common.ok` / `common.cancel`。
- 留白基线：弹窗内容边距 22–24px；公告右栏用 `QTextDocument.setDocumentMargin(14)` 补内边距；教程滚动内容右侧加 8px；进程选择边距 20、最小宽度 560。

## 留给实现者

具体 QSS 数值微调、`QMessageBox` 图标与文字间距、以及是否需要给公告列表项加 `padding`（QSS 已有 `::item` 规则时可只调数值）。视觉验收以 before/after 截图为准。
