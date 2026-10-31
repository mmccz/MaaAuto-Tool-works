"""Announcements: bundled with the installer and refreshed online from GitHub
(a JSON pull at runtime, so announcements can change without a release).

The online source is ``MaaAutoProject/resources/announcements.json`` in this repo:
push the change to ``main`` and clients pick it up on their next start, no new version
needed. raw.githubusercontent.com is unreliable from mainland China, so a jsDelivr
mirror is tried as well, one source after another.

Loading strategy (offline-safe, never blocks the UI):
  1. On start use the **last fetched cache** (``config/announcements_cache.json``);
     with no cache, fall back to the bundled ``resources/announcements.json`` — instant;
  2. A background thread pulls the online copy; on success it atomically writes the
     cache and refreshes the home-page badge;
  3. "Unread" = an id never seen before; or all ids seen but ``updated`` changed.
     Unread items show a badge on the home-page "Announcements" button; users who
     have read announcements before get one automatic popup after start (once per run).

File format::

    {"updated": "2026-10-24",
     "items": [{"id": "...", "date": "...", "tag": "版本更新",
                "title": {"zh_CN": "...", "en_US": "..."},
                "body":  {"zh_CN": "...", "en_US": "..."}}]}

``body`` is Markdown, rendered in the dialog with ``QTextBrowser.setMarkdown``.
"""
import json
import os
import urllib.request

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QListWidget,
                               QListWidgetItem, QTextBrowser, QWidget)

import app_info
from utils import resource_path

ANNOUNCEMENTS_FILE = "resources/announcements.json"
CACHE_FILE_NAME = "announcements_cache.json"
_UA = "MaaAuto-Announcements/1.0"


# --------------------------------------------------------------------------- #
# Parse / load
# --------------------------------------------------------------------------- #
def parse_announcements(payload):
    """Parse a dict / bytes / JSON text into (updated, items).

    Any exception returns ``("", [])``; bad data never reaches the UI.
    """
    try:
        if isinstance(payload, (bytes, bytearray)):
            data = json.loads(payload.decode("utf-8-sig"))
        elif isinstance(payload, str):
            data = json.loads(payload)
        else:
            data = payload
    except Exception:
        return "", []
    if not isinstance(data, dict):
        return "", []
    items = data.get("items") or []
    if not isinstance(items, list):
        return "", []
    items = [it for it in items if isinstance(it, dict) and it.get("id")]
    return str(data.get("updated") or ""), items


def _read_file(path):
    try:
        with open(path, "rb") as f:
            return parse_announcements(f.read())
    except Exception:
        return "", []


def load_bundled_announcements():
    return _read_file(resource_path(ANNOUNCEMENTS_FILE))


def cache_path(config_dir=None):
    if config_dir is None:
        try:
            from config_manager import CONFIG_DIR as config_dir
        except Exception:
            config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "..", "config")
    return os.path.join(config_dir, CACHE_FILE_NAME)


def load_cached_announcements(config_dir=None):
    return _read_file(cache_path(config_dir))


def save_cache(updated, items, config_dir=None):
    """Atomically write the cache; failures are silent (the cache only speeds things up)."""
    path = cache_path(config_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"updated": updated, "items": items}, f,
                      ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def merge_announcements(base_items, extra_items):
    """Merge announcements by id: same-id entries in ``extra`` override ``base``, newest first.

    Why merge instead of replace: when raw.githubusercontent.com fails we fall back to
    jsDelivr, which caches ``@main`` and may return an **older** JSON (fewer items, earlier
    ``updated``). Replacing outright makes older announcements "disappear" — reported as
    "announcements vanish after a while and come back on restart".
    """
    merged = {}
    order = []
    for item in list(base_items or []) + list(extra_items or []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        ident = item["id"]
        if ident not in merged:
            order.append(ident)
        merged[ident] = item          # later entries override earlier ones

    def sort_key(ident):
        date = str(merged[ident].get("date") or "")
        return (date, ident)

    ids = sorted(merged, key=sort_key, reverse=True)
    return [merged[i] for i in ids]


def pick_best(local_updated, local_items, remote_updated, remote_items):
    """Pick the "more complete" of local and online: newer ``updated``, union of items."""
    merged = merge_announcements(local_items, remote_items)
    updated = max(str(local_updated or ""), str(remote_updated or "")) or ""
    return updated, merged


def initial_announcements(config_dir=None):
    """Content used at startup: whichever of cache and bundle has the newer updated."""
    cached_updated, cached_items = load_cached_announcements(config_dir)
    bundled_updated, bundled_items = load_bundled_announcements()
    if cached_items and bundled_items:
        # Both sides were merged: a stale cache never drops new items, nor a stale bundle new cache entries.
        return pick_best(bundled_updated, bundled_items,
                         cached_updated, cached_items)
    if cached_items:
        return cached_updated, cached_items
    return bundled_updated, bundled_items


# --------------------------------------------------------------------------- #
# Online fetch
# --------------------------------------------------------------------------- #
def remote_urls():
    urls = list(getattr(app_info, "APP_ANNOUNCEMENTS_URLS", ()) or ())
    return [u for u in urls if u]


def fetch_remote_announcements(urls=None, timeout=8):
    """Try the online sources in order; return (updated, items) or None."""
    urls = list(urls) if urls else remote_urls()
    for url in urls:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": _UA,
                              "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                updated, items = parse_announcements(resp.read())
            if items:
                return updated, items
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------- #
# Unread detection
# --------------------------------------------------------------------------- #
def unseen_ids(items, seen_ids):
    """Announcement ids never seen before."""
    seen = set(seen_ids or [])
    return [item.get("id", "") for item in items
            if item.get("id") and item["id"] not in seen]


def unread_state(items, updated, seen_ids, seen_updated):
    """Home-page badge state.

    ``count`` semantics:
      * >0 and ``new`` non-empty — new announcements (count = number of new items);
      * ``updated_changed`` — all ids seen but content was updated; report 1 item;
      * 0 — everything seen and nothing updated.
    """
    new_ids = unseen_ids(items, seen_ids)
    updated_changed = bool(updated) and bool(seen_updated) and updated != seen_updated
    if new_ids:
        count = len(new_ids)
    elif updated_changed:
        count = 1
    else:
        count = 0
    return {"count": count, "new_ids": new_ids,
            "updated_changed": updated_changed}


def localize(item, lang):
    """Title/body for the current language; fall back to Chinese, then English."""
    def pick(field):
        value = item.get(field)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get(lang) or value.get("zh_CN") or value.get("en_US") or ""
        return ""

    return {
        "id": item.get("id", ""),
        "date": item.get("date", ""),
        "tag": item.get("tag", ""),
        "title": pick("title"),
        "body": pick("body"),
    }


class AnnouncementDialog(QDialog):
    """Table of contents on the left, all announcements scrolling continuously on the right (1.3.0).

    The right pane used to render one entry at a time, which read as "old announcements
    are gone". Now every entry is one long document: clicking the left list jumps to that
    section, and the wheel scrolls through all release notes in a single pass.
    """

    def __init__(self, i18n, items, lang="zh_CN", parent=None, updated=""):
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle("MaaAuto")
        self.resize(820, 560)
        self.setMinimumSize(660, 460)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)

        head = QHBoxLayout()
        self.title_label = QLabel(self.i18n.t("announce.title"))
        self.title_label.setObjectName("DialogTitle")
        head.addWidget(self.title_label)
        head.addStretch()
        subtitle = self.i18n.t("announce.subtitle")
        if updated:
            subtitle += f"  ·  {updated}"
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("DialogSubtitle")
        head.addWidget(self.subtitle_label, 0, Qt.AlignBottom)
        root.addLayout(head)

        body_row = QHBoxLayout()
        body_row.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(6)
        self.search = QLineEdit()
        self.search.setObjectName("AnnouncementSearch")
        self.search.setPlaceholderText(self.i18n.t("announce.search"))
        self.search.setClearButtonEnabled(True)
        left.addWidget(self.search)
        self.count_label = QLabel("")
        self.count_label.setObjectName("DialogSubtitle")
        left.addWidget(self.count_label)

        self.list = QListWidget()
        self.list.setObjectName("AnnouncementList")
        self.list.setFixedWidth(300)
        self.list.setWordWrap(True)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        left.addWidget(self.list, 1)
        left_wrap = QWidget()
        left_wrap.setFixedWidth(300)
        left_wrap.setLayout(left)
        body_row.addWidget(left_wrap)

        self.browser = QTextBrowser()
        self.browser.setObjectName("AnnouncementBody")
        self.browser.setOpenExternalLinks(True)
        body_row.addWidget(self.browser, 1)
        root.addLayout(body_row, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_close = QPushButton(self.i18n.t("common.got_it"))
        self.btn_close.setObjectName("PrimaryButton")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.accept)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

        self._items = [localize(it, lang) for it in items]
        for idx, item in enumerate(self._items):
            node = QListWidgetItem(item["title"])
            node.setToolTip(f"{item['date']} · {item['tag']}")
            node.setData(Qt.UserRole, idx)
            self.list.addItem(node)

        self.browser.setHtml(self._build_html())
        self.list.currentRowChanged.connect(self._jump_to)
        self.search.textChanged.connect(self._apply_filter)
        self._apply_filter("")
        if self._items:
            self.list.setCurrentRow(0)

    # ------------------------------------------------------------------ #
    def _haystack(self, item):
        return " ".join([item["title"], item["body"], item["date"],
                         item["tag"], item["id"]]).lower()

    def _apply_filter(self, text):
        """Filter the left-hand table of contents by keyword (the body stays complete for reference)."""
        needle = (text or "").strip().lower()
        visible = 0
        first = -1
        for row in range(self.list.count()):
            node = self.list.item(row)
            item = self._items[row]
            match = (not needle) or (needle in self._haystack(item))
            node.setHidden(not match)
            if match:
                visible += 1
                if first < 0:
                    first = row
        self.count_label.setText(
            self.i18n.t("announce.total", count=self.list.count())
            if not needle else
            self.i18n.t("announce.matched", count=visible))
        if needle and first >= 0:
            self.list.setCurrentRow(first)
            self._jump_to(first)

    # ------------------------------------------------------------------ #
    def _markdown_to_html(self, text):
        """Convert the Markdown body to an HTML fragment (keeping link styling)."""
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        try:
            doc.setMarkdown(text or "")
            return doc.toHtml()
        except Exception:
            return f"<pre>{text}</pre>"

    @staticmethod
    def _strip_doc_wrapper(html):
        """QTextDocument.toHtml() wraps output in <html><body>; take the body for the long document."""
        lower = html.lower()
        begin = lower.find("<body")
        if begin >= 0:
            end = lower.rfind("</body>")
            inner = html[begin:end] if end > begin else html[begin:]
            close = inner.find(">")
            return inner[close + 1:] if close >= 0 else inner
        return html

    def _build_html(self):
        parts = []
        for idx, item in enumerate(self._items):
            title = item["title"]
            meta = f"{item['date']}  ·  {item['tag']}" if item["date"] or item["tag"] else ""
            parts.append(
                f'<a name="ann{idx}"></a>'
                f'<h2 style="margin-top:18px;">{title}</h2>'
                f'<p style="color:#8b97a8;margin-top:-6px;">{meta}</p>'
                + self._strip_doc_wrapper(self._markdown_to_html(item["body"]))
                + '<hr style="border:none;border-top:1px solid #e2e8f0;margin:22px 0;">')
        return "".join(parts)

    def _jump_to(self, row):
        if row < 0:
            return
        try:
            self.browser.scrollToAnchor(f"ann{row}")
        except Exception:
            pass
