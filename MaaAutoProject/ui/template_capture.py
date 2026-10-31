"""截取模板：用户在自己机器上重截按钮图，适配分辨率与缩放。

背景
----
内置模板（``resources/maa_start.png``）是在某台机器、某个缩放比下截的。
虽然 :mod:`vision` 会用多尺度匹配覆盖 60%~200%，但分辨率差异很大、或者
按钮文案/皮肤改版时，自截模板是最稳的解法。这个对话框就是入口：

1. 选模板名（Link Start / 开始任务 / 自定义）；
2. 窗口隐藏，抓一张当前屏幕；
3. 全屏半透明覆盖层上拖框选中按钮；
4. 按屏幕 DPI 换算成物理像素裁切、存到 ``config/templates/``；
5. 再抓一张屏幕做自检，报告相似度——低于 0.85 就是框得不准。

注意坐标换算：Qt 的控件几何是**逻辑像素**（受 DPI 缩放影响），而
``vision.grab`` 拿到的是**物理像素**。两者之间差一个 ``devicePixelRatio``。
"""

import logging
import os
import traceback

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

import vision

logger = logging.getLogger("MaaAuto")

KNOWN_TEMPLATES = [
    ("maa_start.png", "MAA · Link Start!"),
    ("maaend_start.png", "MaaEnd · 开始任务"),
]
CUSTOM_NAME = "__custom__"
MIN_SELECT_PX = 8


class _Selector(QWidget):
    """全屏半透明覆盖层：拖框选区，Esc 取消。

    背景直接画开始截取时抓到的屏幕截图，所以用户看到的画面是「冻住」的，
    拖动选框期间目标不会跑。
    """

    finished = Signal()        # 选区结束（取消也会发）

    def __init__(self, screen, captured_bgr):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setCursor(Qt.CrossCursor)
        self._screen = screen
        self.setGeometry(screen.geometry())
        self._origin = QPoint()
        self._current = QPoint()
        self._dragging = False
        self._done = False
        self.selection = None      # 逻辑像素 QRect

        self._pixmap = None
        if captured_bgr is not None:
            self._pixmap = QPixmap(_pixmap_from_bgr(captured_bgr))

    # ------------------------------------------------------------------ #
    def paintEvent(self, _):
        p = QPainter(self)
        if self._pixmap is not None and not self._pixmap.isNull():
            p.drawPixmap(self.rect(), self._pixmap)

        # 整体压暗，突出选区
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))

        if self._dragging or self.selection is not None:
            sel = self._current_rect()
            cut = sel.normalized()
            # 把选区里的原图再画一遍（抵消压暗）
            if self._pixmap is not None and not self._pixmap.isNull() and cut.width() > 0:
                p.drawPixmap(cut, self._pixmap, self._source_rect(cut))
            p.setPen(QPen(QColor(59, 130, 246), 2))
            p.drawRect(cut)

    def _source_rect(self, logical_rect):
        """选区（逻辑像素）→ 原图（物理像素）里的对应矩形。"""
        dpr = max(0.5, float(self._screen.devicePixelRatio()))
        img_w = self._pixmap.width()
        img_h = self._pixmap.height()
        x = int(round(logical_rect.x() * dpr))
        y = int(round(logical_rect.y() * dpr))
        w = int(round(logical_rect.width() * dpr))
        h = int(round(logical_rect.height() * dpr))
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = max(1, min(w, img_w - x))
        h = max(1, min(h, img_h - y))
        return QRect(x, y, w, h)

    def _current_rect(self):
        if self.selection is not None:
            return self.selection
        return QRect(self._origin, self._current)

    # ------------------------------------------------------------------ #
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._origin = e.position().toPoint()
            self._current = self._origin
            self._dragging = True
            self.update()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._current = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self._dragging:
            return
        self._dragging = False
        self._current = e.position().toPoint()
        rect = QRect(self._origin, self._current).normalized()
        if rect.width() >= MIN_SELECT_PX and rect.height() >= MIN_SELECT_PX:
            self.selection = rect
            self._finish()
        else:
            # 太小的点选当作误触，取消
            self.selection = None
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.selection = None
            self._finish()

    def _finish(self):
        if self._done:
            return
        self._done = True
        self.finished.emit()
        self.close()


def _pixmap_from_bgr(bgr):
    """BGR ndarray → QPixmap（不经文件，避免临时文件与编码问题）。"""
    if vision.HAS_CV2:
        rgb = vision.cv2.cvtColor(bgr, vision.cv2.COLOR_BGR2RGB)
    else:
        rgb = bgr
    h, w = rgb.shape[:2]
    from PySide6.QtGui import QImage
    img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
    return QPixmap.fromImage(img.copy())      # copy()：底层 buffer 是 np 的


class TemplateCaptureDialog(QDialog):
    """截取模板的主对话框，用法同普通 QDialog。"""

    def __init__(self, i18n, config, parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self.config = dict(config or {})
        self._saved_file = None
        self._saved_dir = None
        self._saved_score = 0.0

        self.setWindowTitle(self.i18n.t("capture.title"))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        self.title_label = QLabel(self.i18n.t("capture.title"))
        self.title_label.setObjectName("PageTitle")
        layout.addWidget(self.title_label)

        self.hint_label = QLabel(self.i18n.t("capture.hint"))
        self.hint_label.setWordWrap(True)
        self.hint_label.setObjectName("SettingDesc")
        layout.addWidget(self.hint_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.name_combo = QComboBox()
        for filename, display in KNOWN_TEMPLATES:
            self.name_combo.addItem(f"{display}  ({filename})", filename)
        self.name_combo.addItem(self.i18n.t("capture.custom"), CUSTOM_NAME)
        self.name_combo.currentIndexChanged.connect(self._on_name_changed)
        row.addWidget(self.name_combo, 1)

        self.custom_edit = QLineEdit("")
        self.custom_edit.setPlaceholderText("my_button.png")
        self.custom_edit.setVisible(False)
        row.addWidget(self.custom_edit, 1)
        layout.addLayout(row)

        self.name_label = QLabel(self.i18n.t("capture.name"))
        self.name_label.setObjectName("SettingDesc")
        layout.addWidget(self.name_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_start = QPushButton(self.i18n.t("capture.start"))
        self.btn_start.setObjectName("PrimaryButton")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._start_capture)
        btns.addWidget(self.btn_start)
        self.btn_close = QPushButton(self.i18n.t("common.cancel"))
        self.btn_close.setObjectName("GhostButton")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.reject)
        btns.addWidget(self.btn_close)
        layout.addLayout(btns)

    # ------------------------------------------------------------------ #
    def saved_dir(self):
        return self._saved_dir

    def saved_file(self):
        return self._saved_file

    def saved_score(self):
        return self._saved_score

    # ------------------------------------------------------------------ #
    def _on_name_changed(self, *_):
        is_custom = self.name_combo.currentData() == CUSTOM_NAME
        self.custom_edit.setVisible(is_custom)

    def _target_filename(self):
        data = self.name_combo.currentData()
        if data == CUSTOM_NAME:
            name = (self.custom_edit.text() or "").strip()
            if not name:
                return None
            name = os.path.basename(name.replace("\\", "/"))
            if not name.lower().endswith(".png"):
                name += ".png"
            return name
        return data

    def _target_dir(self):
        try:
            import automation
            return automation._user_template_dir(self.config)
        except Exception:
            return os.path.join(os.getcwd(), "config", "templates")

    # ------------------------------------------------------------------ #
    def _start_capture(self):
        filename = self._target_filename()
        if not filename:
            QMessageBox.warning(self, self.i18n.t("common.warning"),
                                self.i18n.t("capture.no_name"))
            return

        target_dir = self._target_dir()
        target = os.path.join(target_dir, filename)
        if os.path.exists(target):
            if QMessageBox.question(
                    self, self.i18n.t("capture.title"),
                    self.i18n.t("capture.overwrite", file=filename)) != \
                    QMessageBox.Yes:
                return

        # 目标窗口先在屏幕上看一眼，免得用户以为「点了没反应」
        proc = self._target_process(filename)
        if proc:
            self.status_label.setText(
                self.i18n.t("capture.foreground", process=proc))

        # 先把对话框藏起来，免得它出现在截图里
        self.hide()
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        QTimer.singleShot(260, lambda: self._do_capture(filename, target_dir, target))

    # ------------------------------------------------------------------ #
    # 1.4.5：截取前把 MAA / MaaEnd 窗口弄到最前面
    #
    # 旧实现直接抓当前屏幕：用户从设置页点「截取模板」时，MAA 往往压在
    # MaaAuto 主窗口后面甚至最小化，抓到的画面里根本没有 Link Start，
    # 框出来的模板自然对不上。
    # ------------------------------------------------------------------ #
    def _target_process(self, filename):
        """模板对应的进程名；自定义模板返回空串（自己负责摆好窗口）。"""
        try:
            import automation
            return automation.template_process(filename, self.config)
        except Exception:
            return ""

    def _bring_target_front(self, filename):
        proc = self._target_process(filename)
        if not proc:
            return ""
        try:
            from process_utils import bring_process_to_front, interruptible_sleep
            if bring_process_to_front([proc]):
                interruptible_sleep(0.5)
                return proc
        except Exception as e:
            logger.warning(f"把 {proc} 窗口前置失败: {e}")
        return ""

    def _do_capture(self, filename, target_dir, target):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        dpr = max(0.5, float(screen.devicePixelRatio()))
        geom = screen.geometry()
        region = (int(round(geom.x() * dpr)), int(round(geom.y() * dpr)),
                  int(round((geom.x() + geom.width()) * dpr)),
                  int(round((geom.y() + geom.height()) * dpr)))

        self._bring_target_front(filename)
        captured = vision.grab(region)
        if captured is None:
            self.show()
            QMessageBox.critical(self, self.i18n.t("common.error"),
                                 self.i18n.t("capture.failed", err="截屏失败"))
            return

        self._selector = _Selector(screen, captured)
        self._selector.finished.connect(
            lambda: self._on_selection_done(captured, dpr, target_dir, target, filename))
        self._selector.showFullScreen()
        self._selector.raise_()
        self._selector.activateWindow()

    def _on_selection_done(self, captured, dpr, target_dir, target, filename):
        selector = self._selector
        self._selector = None
        rect = selector.selection if selector is not None else None
        if rect is None:
            self.show()
            return
        # 覆盖层在 finished 之后才真正关闭，稍等它从屏幕上消失再自检，
        # 否则自检截到的画面里还压着半透明遮罩，分数会莫名其妙偏低。
        QTimer.singleShot(
            180, lambda: self._crop_and_save(captured, rect, dpr,
                                             target_dir, target, filename))

    def _crop_and_save(self, captured, rect, dpr, target_dir, target, filename):
        # 整段都包起来：这里是 windowed 程序，异常不会有人看到，
        # 用户只会看到「什么都没发生」——这正是 1.0.2 的反馈。
        try:
            x = max(0, int(round(rect.x() * dpr)))
            y = max(0, int(round(rect.y() * dpr)))
            w = max(1, int(round(rect.width() * dpr)))
            h = max(1, int(round(rect.height() * dpr)))

            crop = captured[y:y + h, x:x + w]
            if crop.size == 0:
                self.show()
                QMessageBox.warning(self, self.i18n.t("common.warning"),
                                    self.i18n.t("capture.empty"))
                return

            os.makedirs(target_dir, exist_ok=True)
            vision.save_png(crop, target)

            score = self._self_check(target)
            self._saved_file = target
            self._saved_dir = target_dir
            self._saved_score = score

            logger.info(f"已保存模板 {target} ({w}x{h} @dpr={dpr:.2f})，"
                        f"自检相似度 {score:.3f}")
            self.status_label.setText(self.i18n.t(
                "capture.saved_detail", file=filename, size=f"{w}×{h}",
                score=f"{score:.3f}", dir=target_dir))
            # 不自动关窗：让用户亲眼看到保存路径和自检分数（1.0.2 弹窗一闪即逝）
            self.btn_start.setText(self.i18n.t("capture.again"))
            self.btn_close.setText(self.i18n.t("common.close"))
            self.show()
            self.raise_()
            self.activateWindow()
        except Exception as e:
            logger.error(f"截取模板失败: {e}\n{traceback.format_exc()}")
            self.show()
            QMessageBox.critical(self, self.i18n.t("common.error"),
                                 self.i18n.t("capture.failed", err=str(e)))

    def _self_check(self, path):
        """再抓一张屏幕验证模板可用：能找回同一个按钮才算成功。

        分数低有两种可能：框得不准，或者目标被本对话框挡住了——所以只报告
        分数，不做硬性拦截，用户自己判断要不要重截。
        """
        try:
            match = vision.find(path, threshold=0.30, scale_min=0.8, scale_max=1.3)
        except Exception as e:
            logger.debug(f"模板自检失败: {e}")
            return 0.0
        return float(match.score) if match is not None else 0.0
