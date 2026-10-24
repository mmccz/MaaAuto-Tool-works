"""公告：安装包内置 + GitHub 在线更新（Pull 拉取 JSON，不发版也能改公告）。

在线源就是本仓库里的 ``MaaAutoProject/resources/announcements.json``：
改完 push 到 ``main``，客户端下次启动就会拉到，不需要发新版本。
国内访问 raw.githubusercontent 不稳，所以再带一个 jsDelivr 镜像，逐个尝试。

加载策略（保证离线可用、不卡界面）：
  1. 启动时先用**上次拉到的缓存**（``config/announcements_cache.json``），
     没有缓存则用安装包内置 ``resources/announcements.json`` —— 秒开；
  2. 后台线程拉在线版本，成功就原子写缓存并刷新首页红点；
  3. 「未读」判定 = 没见过的 id；或 id 都见过但 ``updated`` 变了（内容更新）。
     有未读时首页「公告」按钮显示红点；之前已经看过公告的用户会在启动后
     自动弹一次公告窗口（每轮运行只弹一次）。

文件结构::

    {"updated": "2026-10-24",
     "items": [{"id": "...", "date": "...", "tag": "版本更新",
                "title": {"zh_CN": "...", "en_US": "..."},
                "body":  {"zh_CN": "...", "en_US": "..."}}]}

``body`` 是 Markdown，弹窗里用 ``QTextBrowser.setMarkdown`` 渲染。
"""
import json
import os
import urllib.request

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QListWidget, QListWidgetItem,
                               QTextBrowser)

import app_info
from utils import resource_path

ANNOUNCEMENTS_FILE = "resources/announcements.json"
CACHE_FILE_NAME = "announcements_cache.json"
_UA = "MaaAuto-Announcements/1.0"


# --------------------------------------------------------------------------- #
# 解析 / 读取
# --------------------------------------------------------------------------- #
def parse_announcements(payload):
    """把 dict / bytes / JSON 文本解析成 (updated, items)。

    任何异常都返回 ``("", [])``，绝不把坏数据抛给界面。
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
    """原子写缓存；失败静默（缓存只是加速，不能影响主流程）。"""
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


def initial_announcements(config_dir=None):
    """启动时用的内容：缓存与内置取 updated 更新的那个。"""
    cached_updated, cached_items = load_cached_announcements(config_dir)
    bundled_updated, bundled_items = load_bundled_announcements()
    if cached_items and cached_updated >= bundled_updated:
        return cached_updated, cached_items
    return bundled_updated, bundled_items


# --------------------------------------------------------------------------- #
# 在线拉取
# --------------------------------------------------------------------------- #
def remote_urls():
    urls = list(getattr(app_info, "APP_ANNOUNCEMENTS_URLS", ()) or ())
    return [u for u in urls if u]


def fetch_remote_announcements(urls=None, timeout=8):
    """依次尝试在线源，返回 (updated, items) 或 None。"""
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
# 未读判定
# --------------------------------------------------------------------------- #
def unseen_ids(items, seen_ids):
    """没见过的公告 id。"""
    seen = set(seen_ids or [])
    return [item.get("id", "") for item in items
            if item.get("id") and item["id"] not in seen]


def unread_state(items, updated, seen_ids, seen_updated):
    """首页红点状态。

    ``count`` 含义：
      * >0 且 ``new`` 非空 —— 有新公告（数字 = 新公告条数）；
      * ``updated_changed`` —— id 都看过了但公告内容更新过，记 1 条提示；
      * 0 —— 全看过且没更新。
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
    """取当前语言的标题/正文；缺失时回退到中文再回退到英文。"""
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
    """左侧列表 + 右侧正文的公告板。"""

    def __init__(self, i18n, items, lang="zh_CN", parent=None, updated=""):
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle("MaaAuto")
        self.resize(760, 520)
        self.setMinimumSize(620, 420)

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

        self.list = QListWidget()
        self.list.setObjectName("AnnouncementList")
        self.list.setFixedWidth(300)
        self.list.setWordWrap(True)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        body_row.addWidget(self.list)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.item_title = QLabel("")
        self.item_title.setObjectName("SectionTitle")
        self.item_title.setWordWrap(True)
        right.addWidget(self.item_title)
        self.item_meta = QLabel("")
        self.item_meta.setObjectName("DialogSubtitle")
        right.addWidget(self.item_meta)
        self.browser = QTextBrowser()
        self.browser.setObjectName("AnnouncementBody")
        self.browser.setOpenExternalLinks(True)
        right.addWidget(self.browser, 1)
        body_row.addLayout(right, 1)
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
        self.list.currentRowChanged.connect(self._show_item)
        if self._items:
            self.list.setCurrentRow(0)

    def _show_item(self, row):
        if row < 0 or row >= len(self._items):
            return
        item = self._items[row]
        self.item_title.setText(item["title"])
        self.item_meta.setText(f"{item['date']}  ·  {item['tag']}")
        try:
            self.browser.setMarkdown(item["body"])
            from ui.update_dialog import colorize_links
            colorize_links(self.browser)
        except Exception:
            self.browser.setPlainText(item["body"])
