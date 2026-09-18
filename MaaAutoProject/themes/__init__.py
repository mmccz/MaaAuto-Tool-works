import os
from PySide6.QtCore import QObject, Signal


class ThemeManager(QObject):
    theme_changed = Signal(str)

    def __init__(self, themes_dir):
        super().__init__()
        self.themes_dir = themes_dir
        self.current_theme = "light"

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

    def apply_theme(self, theme, app):
        resolved = self.resolve_theme(theme)
        qss = self._load_file(f"{resolved}.qss")
        app.setStyleSheet(qss)
        # 强制所有顶层窗口重绘（部分 Qt 版本不会自动刷）
        for w in app.topLevelWidgets():
            w.style().unpolish(w)
            w.style().polish(w)
            w.update()
        app.processEvents()
        self.current_theme = resolved
        self.theme_changed.emit(theme)