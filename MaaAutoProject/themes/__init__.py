import os
import re
import colorsys
from PySide6.QtCore import QObject, Signal


DEFAULT_ACCENT = "#3b82f6"     # 默认强调色（蓝）


def _normalize_hex(value):
    """把用户传进来的颜色字符串规整为小写 #rrggbb，非法输入回退到默认色。"""
    if not isinstance(value, str):
        return DEFAULT_ACCENT
    v = value.strip()
    if not re.match(r"^#?[0-9a-fA-F]{6}$", v):
        return DEFAULT_ACCENT
    if not v.startswith("#"):
        v = "#" + v
    return v.lower()


def _hex_to_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _rgb_to_hex(r, g, b):
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(round(r)))),
        max(0, min(255, int(round(g)))),
        max(0, min(255, int(round(b)))),
    )


class ThemeManager(QObject):
    theme_changed = Signal(str)

    def __init__(self, themes_dir):
        super().__init__()
        self.themes_dir = themes_dir
        self.current_theme = "light"      # 解析后的实际主题（light / dark）
        self._requested_theme = "light"   # 用户请求的主题（可能为 system）
        self._accent_color = DEFAULT_ACCENT

    # ------------------------------------------------------------------ #
    # 文件 / 系统主题
    # ------------------------------------------------------------------ #
    def _load_file(self, name):
        path = os.path.join(self.themes_dir, name)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def detect_system_theme(self):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return "light" if value == 1 else "dark"
        except Exception:
            return "light"

    def resolve_theme(self, theme):
        if theme == "system":
            return self.detect_system_theme()
        return theme

    # ------------------------------------------------------------------ #
    # 强调色派生
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_accent_vars(base_hex, resolved_theme):
        """
        根据基础强调色 + 已解析主题（light / dark），生成一组 QSS 占位符值。
        浅色主题：直接用用户色，hover / pressed 变深，soft 变浅。
        深色主题：整体提亮一档，避免在深背景上视觉沉闷。
        """
        base_hex = _normalize_hex(base_hex)
        r, g, b = _hex_to_rgb(base_hex)
        h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)

        def make(lightness):
            lightness = max(0.0, min(1.0, lightness))
            rr, gg, bb = colorsys.hls_to_rgb(h, lightness, s)
            return _rgb_to_hex(rr * 255, gg * 255, bb * 255)

        if resolved_theme == "dark":
            accent = make(l + 0.08)
            hover = make(l + 0.14)
            pressed = make(l + 0.02)
            soft = make(l + 0.28)
            deep = make(l - 0.15)
        else:
            accent = make(l)
            hover = make(l - 0.08)
            pressed = make(l - 0.16)
            soft = make(l + 0.25)
            deep = make(l - 0.25)

        ar, ag, ab = _hex_to_rgb(accent)
        return {
            "accent": accent,
            "accent_rgb": f"{ar}, {ag}, {ab}",
            "accent_hover": hover,
            "accent_pressed": pressed,
            "accent_soft": soft,
            "accent_deep": deep,
        }

    @staticmethod
    def _substitute(qss, mapping):
        """
        只替换 {identifier} 形式的占位符；QSS 规则本身的大括号（无识别符）
        以及未在 mapping 中的键都会保持原样。
        """
        def repl(m):
            key = m.group(1)
            return mapping.get(key, m.group(0))
        return re.sub(r"\{(\w+)\}", repl, qss)

    # ------------------------------------------------------------------ #
    # 应用主题
    # ------------------------------------------------------------------ #
    def apply_theme(self, theme, app, accent_color=None):
        """
        应用主题。
        :param theme:         light / dark / system
        :param app:           QApplication 实例
        :param accent_color:  可选，若提供则更新内部强调色缓存
        """
        if accent_color is not None:
            self._accent_color = _normalize_hex(accent_color)

        self._requested_theme = theme
        resolved = self.resolve_theme(theme)
        qss = self._load_file(f"{resolved}.qss")

        mapping = self._build_accent_vars(self._accent_color, resolved)
        qss = self._substitute(qss, mapping)

        app.setStyleSheet(qss)
        # 强制所有顶层窗口重绘（部分 Qt 版本不会自动刷）
        for w in app.topLevelWidgets():
            w.style().unpolish(w)
            w.style().polish(w)
            w.update()
        app.processEvents()

        self.current_theme = resolved
        self.theme_changed.emit(theme)

    def apply_accent(self, accent_color, app):
        """只重新应用样式表（强调色变化），不切换主题。"""
        self.apply_theme(self._requested_theme, app, accent_color=accent_color)

    def current_accent(self):
        return self._accent_color