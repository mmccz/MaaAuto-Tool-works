import json
import os
from PySide6.QtCore import QObject, Signal


class I18n(QObject):
    language_changed = Signal(str)

    def __init__(self, i18n_dir):
        super().__init__()
        self.i18n_dir = i18n_dir
        self.current_lang = "zh_CN"
        self.translations = {}

    def available_languages(self):
        langs = []
        if os.path.isdir(self.i18n_dir):
            for fn in sorted(os.listdir(self.i18n_dir)):
                if fn.endswith(".json"):
                    code = fn[:-5]
                    display = code
                    try:
                        with open(os.path.join(self.i18n_dir, fn), "r", encoding="utf-8") as f:
                            data = json.load(f)
                            display = data.get("_meta.name", code)
                    except Exception:
                        pass
                    langs.append((code, display))
        return langs

    def load_language(self, lang_code):
        path = os.path.join(self.i18n_dir, f"{lang_code}.json")
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.translations = json.load(f)
            self.current_lang = lang_code
            self.language_changed.emit(lang_code)
            return True
        except Exception:
            return False

    def t(self, key, **kwargs):
        text = self.translations.get(key, key)
        if kwargs:
            try:
                text = text.format(**kwargs)
            except Exception:
                pass
        return text


_i18n = None


def init_i18n(i18n_dir):
    global _i18n
    _i18n = I18n(i18n_dir)
    return _i18n


def get_i18n():
    return _i18n


def t(key, **kwargs):
    if _i18n is None:
        return key
    return _i18n.t(key, **kwargs)