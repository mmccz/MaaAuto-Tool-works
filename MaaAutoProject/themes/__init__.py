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


def detect_system_theme():
    """读注册表判断系统是浅色还是深色；失败按浅色。"""
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


def resolve_theme(theme):
    """把 light / dark / system 解析成 light / dark。

    独立函数（而不只是 ThemeManager 的方法）：弹窗、富文本这类「没有
    ThemeManager 引用」的地方也要判断深浅色（比如深色下链接颜色）。
    """
    if theme == "system":
        return detect_system_theme()
    return theme if theme in ("light", "dark") else "light"


def is_dark_theme(theme=None):
    """当前是否深色主题；theme 为空时读配置（system 会解析）。"""
    if theme is None:
        try:
            from config_manager import load_config
            theme = load_config().get("theme", "system")
        except Exception:
            theme = "system"
    return resolve_theme(theme) == "dark"


LINK_COLOR_LIGHT = "#2563eb"
LINK_COLOR_DARK = "#60a5fa"


def link_color(theme=None):
    """富文本链接颜色（QLabel / QTextBrowser 的 <a> 都不跟 QSS 走）。

    Qt 给富文本锚点的默认色是纯蓝 #0000ff —— 深色主题下贴在 #0f1115 背景上
    几乎看不见（1.0.5 实测：关于页的 GitHub / 邮箱链接、升级公告里的链接）。
    """
    return LINK_COLOR_DARK if is_dark_theme(theme) else LINK_COLOR_LIGHT


class ThemeManager(QObject):
    theme_changed = Signal(str)

    def __init__(self, themes_dir):
        super().__init__()
        self.themes_dir = themes_dir
        self.current_theme = "light"      # 解析后的实际主题（light / dark）
        self._requested_theme = "light"   # 用户请求的主题（可能为 system）
        self._accent_color = DEFAULT_ACCENT
        self._ui_scale = 1.0              # 界面缩放（QSS 里的 font-size 按它放大）

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
        return detect_system_theme()

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

    @staticmethod
    def _scale_font_sizes(qss, scale):
        """把 QSS 里所有 ``font-size: Npx`` 按比例缩放。

        为什么必须改 QSS 而不是只改 QApplication 字体
        ------------------------------------------------
        QSS 里的 ``* { font-size: 13px }`` 和一堆具名控件的 ``font-size`` 会
        **覆盖** ``QApplication.setFont()``。1.0.2 的「界面缩放」只调了 app 字体，
        结果在真机上完全看不到变化——就是被 QSS 压住了。
        """
        if abs(scale - 1.0) < 1e-3:
            return qss

        def repl(m):
            px = float(m.group(1))
            return f"font-size: {max(8, int(round(px * scale)))}px"

        return re.sub(r"font-size:\s*(\d+(?:\.\d+)?)px", repl, qss)

    # 同时匹配 ``font-size: 13px``（带前缀）和普通长度 ``14px``。
    _PX_RE = re.compile(r"(font-size\s*:\s*)?(\d+(?:\.\d+)?)px")

    @classmethod
    def _scale_qss(cls, qss, scale):
        """按界面缩放重写 QSS 里的 px 长度（字号 + padding / min-width 等）。

        只放大字号是不够的：``SegmentItem`` 的 ``min-width: 90px`` 不跟着变，
        150% 时 18px 字号的「整个屏幕」塞不进 90px 就直接折成两行（实测截图）；
        输入框的 ``min-height`` / ``padding`` 不放大也会显得局促。

        两条例外：
          * ``font-size`` 保底 8px（再小就看不清了）；
          * 1px 及以下的长度不放大——边框/分隔线保持发丝级，否则界面会「发胖」。
        """
        if abs(scale - 1.0) < 1e-3:
            return qss

        def repl(m):
            prefix = m.group(1) or ""
            px = float(m.group(2))
            if prefix:
                return f"{prefix}{max(8, int(round(px * scale)))}px"
            if px <= 1.0:
                return m.group(0)
            return f"{max(1, int(round(px * scale)))}px"

        return cls._PX_RE.sub(repl, qss)

    # ------------------------------------------------------------------ #
    # 应用主题
    # ------------------------------------------------------------------ #
    def apply_theme(self, theme, app, accent_color=None, ui_scale=None):
        """
        应用主题。
        :param theme:         light / dark / system
        :param app:           QApplication 实例
        :param accent_color:  可选，若提供则更新内部强调色缓存
        :param ui_scale:      界面缩放倍数（1.0 / 1.25 / 1.5…）；None 表示沿用上次
        """
        if accent_color is not None:
            self._accent_color = _normalize_hex(accent_color)
        if ui_scale is not None:
            try:
                self._ui_scale = max(0.75, min(2.0, float(ui_scale)))
            except (TypeError, ValueError):
                self._ui_scale = 1.0

        self._requested_theme = theme
        resolved = self.resolve_theme(theme)
        qss = self._load_file(f"{resolved}.qss")

        mapping = self._build_accent_vars(self._accent_color, resolved)
        qss = self._substitute(qss, mapping)
        qss = self._scale_qss(qss, self._ui_scale)

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