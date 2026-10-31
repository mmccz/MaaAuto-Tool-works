# 弹窗视觉一致性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让所有弹窗在深色/浅色两套主题下都清晰可读，并与主界面共用同一套按钮、表头与留白语言，同时不改窗口外壳。

**Architecture:** 先在 `themes/dark.qss` / `themes/light.qss` 补三类缺失规则（弹窗内按钮基样式、`QMessageBox` 文字色、表头实色背景），再把 `TimePickDialog` 从 `QDialogButtonBox` 换成带 i18n 文案的显式按钮，最后统一四个自绘弹窗的留白与最小尺寸。颜色只写在 QSS，Python 不出现内联颜色。

**Tech Stack:** PySide6 / Qt Style Sheets / pytest（offscreen）

**Spec:** `docs/superpowers/specs/2026-10-31-dialog-visual-consistency-design.md`

## Global Constraints

- 只改视觉；不改任何业务流程、i18n 文案键名、版本号（`APP_VERSION` 保持 `1.4.5`）、不加新依赖。
- 颜色只能出现在 `themes/*.qss`；Python 里 `setStyleSheet` 不得出现颜色值（沿用 `test_about_version_tag_uses_qss` 的约束）。
- QSS 里的 px 会被 `ThemeManager._scale_qss` 按界面缩放整体放大：新增数值用整数 px，边框保持 1px。
- 按钮新样式的作用域限定 `QDialog QPushButton, QMessageBox QPushButton`，禁止写成全局 `QPushButton`（会改变主界面尺寸断言）。
- 代码注释/docstring 英文；用户可见文案中文（经 `i18n.t`）。
- 验收命令：`cd MaaAuto-Tool-works && py -m pytest tests -q`，必须 **205 + 新增** 全绿。

## Review Focus

- **深色主题下 `QMessageBox` 文字黑底黑字**：任何弹窗实际弹出时都必须可读；由 Task 1 的 QSS 断言 + Task 4 截图双重覆盖。
- **浅色主题下新按钮的对比度**：浅色主题的按钮背景若沿用深色取值会变成"白底白字"；Task 1 为两套主题分别取值，Task 4 用浅色截图核对。
- **界面缩放 150% 时按钮/表头被裁切**：QSS 数值会被 `_scale_qss` 放大，`min-height` 必须仍在规则内；Task 1 加一条缩放后仍匹配规则的断言。
- **超长提示文字把消息框撑爆或截断**：`MessageDialog` 文本必须换行且宽度不超过 560px；Task 3 断言 `wordWrap` 与 `maximumWidth`。
- **空表时表头仍是白底**（0 行的进程选择框）：白色表头与行数无关；Task 3 用离屏抓图取表头像素，断言深色主题下表头亮度 < 128。

---

### Task 1: 主题层补齐弹窗按钮 / QMessageBox / 表头规则

**Files:**
- Modify: `MaaAutoProject/themes/dark.qss`（在文件末尾新增一节 `/* ============ 弹窗与提示框 ============ */`）
- Modify: `MaaAutoProject/themes/light.qss`（同一节）
- Modify: `MaaAutoProject/themes/dark.qss:198-203`、`MaaAutoProject/themes/light.qss:212-217`（`QHeaderView::section` 改实色）
- Test: `MaaAuto-Tool-works/tests/test_dialogs_and_content.py`（文件末尾新增两节测试）

**Interfaces:**
- Produces: 两套 QSS 中的选择器 `QDialog QPushButton, QMessageBox QPushButton`（含 `border-radius: 8px; min-height: 32px; padding: 6px 16px`）、`QMessageBox QLabel { color: ... }`、`QMessageBox { min-width: 380px }`、`QHeaderView::section { background: <实色>; border-bottom: 1px solid ... }`。
- 不产生任何 Python 接口。

- [ ] **Step 1: 写失败测试**

在 `tests/test_dialogs_and_content.py` 末尾追加：

```python
# --------------------------------------------------------------------------- #
# Dialog visuals: dark-theme readability (1.4.6)
# --------------------------------------------------------------------------- #
def test_qss_styles_dialog_buttons_and_messagebox():
    import re

    for name in ("dark.qss", "light.qss"):
        with open(os.path.join(APP_DIR, "themes", name), encoding="utf-8") as fh:
            qss = fh.read()

        # A base button style scoped to dialogs: without it QMessageBox falls back to
        # the native grey Windows button while the rest of the app is rounded.
        assert re.search(r"QDialog\s+QPushButton\s*,\s*QMessageBox\s+QPushButton\s*\{",
                         qss), f"{name}: dialog button base rule missing"
        block = re.search(
            r"QDialog\s+QPushButton\s*,\s*QMessageBox\s+QPushButton\s*\{([^}]*)\}", qss).group(1)
        assert "border-radius" in block and "min-height" in block

        # Dark QSS only painted the QDialog background; the text stayed palette-black.
        assert re.search(r"QMessageBox\s+QLabel\s*\{[^}]*color\s*:", qss, re.S), \
            f"{name}: QMessageBox text color missing"

        # A transparent header section shows the light palette through -> white band.
        header = re.search(r"QHeaderView::section\s*\{([^}]*)\}", qss, re.S)
        assert header, f"{name}: QHeaderView::section rule missing"
        assert "background" in header.group(1)
        assert "transparent" not in header.group(1), f"{name}: header must paint a solid colour"


def test_dialog_button_rules_survive_ui_scaling():
    import re

    from themes import ThemeManager

    with open(os.path.join(APP_DIR, "themes", "dark.qss"), encoding="utf-8") as fh:
        qss = fh.read()
    scaled = ThemeManager._scale_qss(qss, 1.5)
    block = re.search(
        r"QDialog\s+QPushButton\s*,\s*QMessageBox\s+QPushButton\s*\{([^}]*)\}", scaled).group(1)
    assert "min-height: 48px" in block, block
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_dialogs_and_content.py::test_qss_styles_dialog_buttons_and_messagebox tests/test_dialogs_and_content.py::test_dialog_button_rules_survive_ui_scaling -v`
Expected: 两条都 FAIL（`dialog button base rule missing` / `AttributeError: 'NoneType'`）

- [ ] **Step 3: 改 `themes/dark.qss`**

`QHeaderView::section`（现约 198 行）改成：

```css
QHeaderView {
    background: transparent;
    border: none;
}
QHeaderView::section {
    background: rgba(255, 255, 255, 0.04);
    border: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    padding: 8px;
    color: #9ca3af;
    font-weight: 600;
}
```

文件末尾新增：

```css
/* ============ 弹窗与提示框 ============ */
QDialog QPushButton, QMessageBox QPushButton {
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 8px;
    min-height: 32px;
    min-width: 76px;
    padding: 6px 16px;
    background: rgba(255, 255, 255, 0.06);
    color: #e5e7eb;
}
QDialog QPushButton:hover, QMessageBox QPushButton:hover {
    background: rgba(255, 255, 255, 0.11);
}
QDialog QPushButton:pressed, QMessageBox QPushButton:pressed {
    background: rgba(255, 255, 255, 0.04);
}
QDialog QPushButton:disabled, QMessageBox QPushButton:disabled {
    color: rgba(229, 231, 235, 0.45);
    background: rgba(255, 255, 255, 0.03);
}
QMessageBox {
    min-width: 380px;
}
QMessageBox QLabel {
    color: #e5e7eb;
}
QMessageBox QPushButton {
    min-width: 88px;
}
```

- [ ] **Step 4: 改 `themes/light.qss`**

同样把 `QHeaderView::section` 改成实色并补 `QHeaderView` 基规则：

```css
QHeaderView {
    background: transparent;
    border: none;
}
QHeaderView::section {
    background: #f3f4f6;
    border: none;
    border-bottom: 1px solid #e5e7eb;
    padding: 8px;
    color: #4b5563;
    font-weight: 600;
}
```

末尾新增同一节，取值换浅色：

```css
/* ============ 弹窗与提示框 ============ */
QDialog QPushButton, QMessageBox QPushButton {
    border: 1px solid #d1d5db;
    border-radius: 8px;
    min-height: 32px;
    min-width: 76px;
    padding: 6px 16px;
    background: #ffffff;
    color: #1f2937;
}
QDialog QPushButton:hover, QMessageBox QPushButton:hover {
    background: #f3f4f6;
}
QDialog QPushButton:pressed, QMessageBox QPushButton:pressed {
    background: #e5e7eb;
}
QDialog QPushButton:disabled, QMessageBox QPushButton:disabled {
    color: #9ca3af;
    background: #f9fafb;
}
QMessageBox {
    min-width: 380px;
}
QMessageBox QLabel {
    color: #1f2937;
}
QMessageBox QPushButton {
    min-width: 88px;
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `py -m pytest tests/test_dialogs_and_content.py -v`
Expected: 全部 PASS（含新增两条）

- [ ] **Step 6: 提交**

```bash
git add MaaAutoProject/themes/dark.qss MaaAutoProject/themes/light.qss tests/test_dialogs_and_content.py
git commit -m "ui: 弹窗按钮/QMessageBox 文字/表头补齐主题规则，修深色下看不清"
```

---

### Task 2: 时间选择弹窗换成本项目按钮与中文文案

**Files:**
- Modify: `MaaAutoProject/ui/schedule_editor.py:23-51`（`TimePickDialog`）
- Test: `MaaAuto-Tool-works/tests/test_dialogs_and_content.py`

**Interfaces:**
- Consumes: Task 1 的 `QDialog QPushButton` 基样式（无需显式引用）。
- Produces: `TimePickDialog.value() -> str` 行为不变；按钮为 `QPushButton`，文案 `i18n.t("common.ok")` / `i18n.t("common.cancel")`，objectName 分别为 `PrimaryButton` / `GhostButton`。

- [ ] **Step 1: 写失败测试**

```python
def test_time_pick_dialog_uses_localized_buttons(qapp, i18n):
    from PySide6.QtWidgets import QDialogButtonBox, QPushButton

    from ui.schedule_editor import TimePickDialog

    dlg = TimePickDialog(i18n, "08:00")
    try:
        assert dlg.findChildren(QDialogButtonBox) == []
        texts = [b.text() for b in dlg.findChildren(QPushButton)]
        assert texts == [i18n.t("common.ok"), i18n.t("common.cancel")]
        assert [b.objectName() for b in dlg.findChildren(QPushButton)] == [
            "PrimaryButton", "GhostButton"]
        assert all(b.styleSheet() == "" for b in dlg.findChildren(QPushButton))
    finally:
        dlg.deleteLater()
```

- [ ] **Step 2: 运行确认失败**

Run: `py -m pytest tests/test_dialogs_and_content.py::test_time_pick_dialog_uses_localized_buttons -v`
Expected: FAIL（找到 `QDialogButtonBox`，文案是 `OK` / `Cancel`）

- [ ] **Step 3: 改 `ui/schedule_editor.py`**

把 `QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)` 那三行替换为：

```python
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.btn_ok = QPushButton(self.i18n.t("common.ok"))
        self.btn_ok.setObjectName("PrimaryButton")
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.clicked.connect(self.accept)
        buttons.addWidget(self.btn_ok)
        self.btn_cancel = QPushButton(self.i18n.t("common.cancel"))
        self.btn_cancel.setObjectName("GhostButton")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(self.btn_cancel)
        root.addLayout(buttons)
```

同时把 `root.setContentsMargins(18, 16, 18, 14)` 改为 `root.setContentsMargins(20, 18, 20, 16)`，`root.setSpacing(10)` 改为 `root.setSpacing(12)`；模块顶部 import 去掉不再使用的 `QDialogButtonBox`，补 `QPushButton`（若已导入则只删 `QDialogButtonBox`）。

- [ ] **Step 4: 运行确认通过**

Run: `py -m pytest tests/test_dialogs_and_content.py::test_time_pick_dialog_uses_localized_buttons tests/test_schedule.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add MaaAutoProject/ui/schedule_editor.py tests/test_dialogs_and_content.py
git commit -m "ui: 时间选择弹窗改用中文按钮，补内边距"
```

---

### Task 3: 四个自绘弹窗的留白与最小尺寸基线

**Files:**
- Modify: `MaaAutoProject/ui/pages/process_picker.py:80-84`（`_setup_ui` 边距）
- Modify: `MaaAutoProject/ui/announcements.py:292-294`（右栏文档边距）
- Modify: `MaaAutoProject/ui/tutorial_dialog.py:63`（滚动内容右边距）
- Modify: `MaaAutoProject/ui/update_dialog.py:95-96`（`MessageDialog` 边距与间距）
- Test: `MaaAuto-Tool-works/tests/test_dialogs_and_content.py`

**Interfaces:**
- Produces: `ProcessPickerDialog.minimumWidth() == 560`、`ProcessPickerDialog.layout().contentsMargins().left() == 20`；`AnnouncementDialog.browser.document().documentMargin() == 14`；`TutorialDialog.vbox.contentsMargins().right() == 34`；`MessageDialog.text_label.wordWrap() is True` 且 `MessageDialog.maximumWidth() == 560`。

- [ ] **Step 1: 写失败测试**

```python
def test_process_picker_padding_and_min_width(qapp, i18n):
    from ui.pages.process_picker import ProcessPickerDialog

    dlg = ProcessPickerDialog(i18n, "")
    try:
        assert dlg.minimumWidth() == 560
        m = dlg.layout().contentsMargins()
        assert (m.left(), m.top(), m.right(), m.bottom()) == (20, 20, 20, 20)
    finally:
        dlg.deleteLater()


def test_process_picker_header_is_dark_in_dark_theme(qapp, i18n):
    """An empty table (0 rows) still shows the header: it must not show the light palette."""
    from PySide6.QtGui import QColor

    from themes import ThemeManager
    from ui.pages.process_picker import ProcessPickerDialog

    tm = ThemeManager(os.path.join(APP_DIR, "themes"))
    tm.apply_theme("dark", qapp)
    dlg = ProcessPickerDialog(i18n, "")
    try:
        dlg.resize(640, 400)
        dlg.show()
        qapp.processEvents()
        header = dlg.table.horizontalHeader()
        y = header.height() // 2
        img = header.grab().toImage()
        color = QColor(img.pixel(img.width() // 2, y))
        assert (color.red() + color.green() + color.blue()) / 3 < 128, color.name()
    finally:
        dlg.close()
        dlg.deleteLater()
        tm.apply_theme("light", qapp)   # leave the module-wide qapp in a known state


def test_announcement_body_document_margin(qapp, i18n):
    from ui.announcements import AnnouncementDialog

    with open(os.path.join(RES, "announcements.json"), encoding="utf-8") as fh:
        items = json.load(fh)["items"]
    dlg = AnnouncementDialog(i18n, items)
    try:
        assert dlg.browser.document().documentMargin() == 14
    finally:
        dlg.deleteLater()


def test_tutorial_right_gutter_and_message_wrap(qapp, i18n):
    from ui.tutorial_dialog import TutorialDialog
    from ui.update_dialog import MessageDialog

    tut = TutorialDialog(i18n)
    try:
        assert tut.vbox.contentsMargins().right() == 34
    finally:
        tut.deleteLater()

    box = MessageDialog(i18n, "标题", "很长的提示文字 " * 40)
    try:
        assert box.text_label.wordWrap() is True
        assert box.maximumWidth() == 560
    finally:
        box.deleteLater()
```

- [ ] **Step 2: 运行确认失败**

Run: `py -m pytest tests/test_dialogs_and_content.py -k "process_picker_padding or header_is_dark or document_margin or right_gutter" -v`
Expected: FAIL —— 最小宽/边距、空表表头、公告文档边距、教程右边距四条红；`MessageDialog` 的两条断言本来就成立，用于防回归

- [ ] **Step 3: 实现**

- `process_picker.py` `_setup_ui`：`self.setMinimumWidth(560)`，`layout.setContentsMargins(20, 20, 20, 20)`。
- `announcements.py`：`self.browser.document().setDocumentMargin(14)`（放在 `setOpenExternalLinks` 之后）。
- `tutorial_dialog.py`：`self.vbox.setContentsMargins(26, 8, 34, 20)`。
- `update_dialog.py` `MessageDialog`：`root.setContentsMargins(24, 20, 24, 20)`，`root.setSpacing(10)`。

- [ ] **Step 4: 运行确认通过**

Run: `py -m pytest tests/test_dialogs_and_content.py tests/test_ui_scaling_and_pages.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add MaaAutoProject/ui/pages/process_picker.py MaaAutoProject/ui/announcements.py \
        MaaAutoProject/ui/tutorial_dialog.py MaaAutoProject/ui/update_dialog.py \
        tests/test_dialogs_and_content.py
git commit -m "ui: 统一弹窗留白与最小尺寸，修空表表头白底"
```

---

### Task 4: 视觉验收与回归

**Files:**
- Create: `Desktop/Lib/MAAPJF/tests/ui-audit-2026-10-31/after/`（截图）
- Modify: `Desktop/Lib/MAAPJF/开发进度.md` §8（追加一行）
- 无源码改动；若截图发现问题，回到对应 Task 修。

**Interfaces:**
- Consumes: Task 1–3 的成品。
- Produces: 8 张 after 截图（dark/light × tutorial/announcements/update/message/process_picker/time_pick）+ 回归结论。

- [ ] **Step 1: 重跑渲染脚本，落 after 截图**

使用本机已存在的渲染脚本（`%TEMP%\maa_dialog_shots.py`；若已清理，按 `MAAPJF\tests\ui-audit-2026-10-31\` 里的实现重建），把输出目录改为 `after/`：

Run: `cd MaaAutoProject && py "%TEMP%\maa_dialog_shots.py"`
Expected: 生成 dark/light 各 7 张 + `dark_qmessagebox.png`；把 `dialog_shots/*.png` 复制到 `MAAPJF/tests/ui-audit-2026-10-31/after/`

- [ ] **Step 2: 人工比对 before/after**

逐张看：深色 `qmessagebox` 文字是否浅色可读、表头是否深色、时间选择按钮是否中文圆角、公告右栏是否留出内边距、教程右侧是否不再贴边。
Expected: 五项全部改善；无新出现的裁切

- [ ] **Step 3: 全量回归**

Run: `cd MaaAuto-Tool-works && py -m pytest tests -q`
Expected: `212 passed`（205 + 7 条新增：Task 1 两条、Task 2 一条、Task 3 四条）；若数字不同，以实际为准并记录到结果里

- [ ] **Step 4: 自检**

Run: `py "Desktop\Lib\MAAPJF\tests\maaauto_selfcheck.py"`
Expected: 失败 0

- [ ] **Step 5: 提交文档与截图**

```bash
git add docs/superpowers/specs docs/superpowers/plans
git commit -m "docs: 弹窗视觉一致性设计与实施计划"
```

- [ ] **Step 6: 更新本地文档中心**

在 `MAAPJF/开发进度.md` §8 追加一行（含提交号、205→212、截图目录、未发版），不推送版本 tag。
