import os
import re
import colorsys
from PySide6.QtCore import QObject, Signal


DEFAULT_ACCENT = "#3b82f6"     # default accent color (blue)


def _normalize_hex(value):
    """Normalize the given color string to lowercase #rrggbb; fall back to the default on invalid input."""
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
    """Read the registry to decide light vs dark; assume light on failure."""
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
    """Resolve light / dark / system into light / dark.

    A standalone function (not just a ThemeManager method): dialogs and rich text hold
    no ThemeManager reference but still need the light/dark decision (e.g. link color).
    """
    if theme == "system":
        return detect_system_theme()
    return theme if theme in ("light", "dark") else "light"


def is_dark_theme(theme=None):
    """Whether the current theme is dark; reads config when theme is empty (system is resolved)."""
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
    """Rich-text link color (QLabel / QTextBrowser ``<a>`` does not follow QSS).

    Qt's default anchor color is pure blue #0000ff — nearly invisible on the #0f1115
    dark background (1.0.5: GitHub / mail links on the About page, links in release notes).
    """
    return LINK_COLOR_DARK if is_dark_theme(theme) else LINK_COLOR_LIGHT


class ThemeManager(QObject):
    theme_changed = Signal(str)

    def __init__(self, themes_dir):
        super().__init__()
        self.themes_dir = themes_dir
        self.current_theme = "light"      # resolved theme actually in effect (light / dark)
        self._requested_theme = "light"   # theme the user requested (may be "system")
        self._accent_color = DEFAULT_ACCENT
        self._ui_scale = 1.0              # UI scale (QSS font-size is scaled by it)

    # ------------------------------------------------------------------ #
    # Files / system theme
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
    # Accent color derivation
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_accent_vars(base_hex, resolved_theme):
        """
        Derive a set of QSS placeholder values from the base accent color + resolved theme.
        Light theme: use the user color as-is; darken hover / pressed, lighten soft.
        Dark theme: brighten the whole set one step to avoid a dull look on dark backgrounds.
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
        Replace only ``{identifier}`` placeholders; brace pairs in the QSS itself (no
        identifier) and keys missing from mapping are left untouched.
        """
        def repl(m):
            key = m.group(1)
            return mapping.get(key, m.group(0))
        return re.sub(r"\{(\w+)\}", repl, qss)

    @staticmethod
    def _scale_font_sizes(qss, scale):
        """Scale every ``font-size: Npx`` in the QSS by the given ratio.

        Why the QSS must change, not just the QApplication font
        ------------------------------------------------------
        The QSS ``* { font-size: 13px }`` and the per-widget ``font-size`` rules
        **override** ``QApplication.setFont()``. 1.0.2's "UI scale" only adjusted the app
        font, so nothing changed on real machines — the QSS won.
        """
        if abs(scale - 1.0) < 1e-3:
            return qss

        def repl(m):
            px = float(m.group(1))
            return f"font-size: {max(8, int(round(px * scale)))}px"

        return re.sub(r"font-size:\s*(\d+(?:\.\d+)?)px", repl, qss)

    # Matches both ``font-size: 13px`` (with prefix) and bare lengths such as ``14px``.
    _PX_RE = re.compile(r"(font-size\s*:\s*)?(\d+(?:\.\d+)?)px")

    @classmethod
    def _scale_qss(cls, qss, scale):
        """Rewrite px lengths in the QSS by the UI scale (font size + padding / min-width etc.).

        Scaling the font size alone is not enough: ``SegmentItem`` has ``min-width: 90px``,
        and at 150% the 18px "Entire screen" label no longer fits 90px and wraps onto two
        lines (measured); input ``min-height`` / ``padding`` also look cramped unscaled.

        Two exceptions:
          * ``font-size`` bottoms out at 8px; anything smaller is unreadable;
          * lengths of 1px or less are left alone so borders stay hairline, not fat.
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
    # Apply theme
    # ------------------------------------------------------------------ #
    def apply_theme(self, theme, app, accent_color=None, ui_scale=None):
        """
        Apply the theme.
        :param theme:         light / dark / system
        :param app:           QApplication instance
        :param accent_color:  optional; when given, updates the cached accent color
        :param ui_scale:      UI scale factor (1.0 / 1.25 / 1.5...); None keeps the last value
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
        # Force all top-level windows to repaint (some Qt versions do not refresh on their own)
        for w in app.topLevelWidgets():
            w.style().unpolish(w)
            w.style().polish(w)
            w.update()
        app.processEvents()

        self.current_theme = resolved
        self.theme_changed.emit(theme)

    def apply_accent(self, accent_color, app):
        """Re-apply the stylesheet only (accent color changed); do not switch theme."""
        self.apply_theme(self._requested_theme, app, accent_color=accent_color)

    def current_accent(self):
        return self._accent_color