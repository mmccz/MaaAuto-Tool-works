"""Server Chan push SDK (local implementation, no third-party dependency).

Supports:
  - Server Chan Turbo (SendKey looks like SCTxxxxxTxxxxx)
  - Server Chan 3 (SendKey looks like sctp{uid}txxxxx)

The public interface matches the `serverchan-sdk` package on PyPI, so switching to
the pip version later needs no change in the callers.

Usage:
    from serverchan_sdk import sc_send
    res = sc_send("sctp12345t...", "title", "content", {"tags": "test"})

Returns:
    a dict shaped like:
      success: {"code": 0, "message": "SUCCESS", "data": {...}}
      failure: {"code": non-zero, "message": "error text"}
      error:   {"code": -1, "message": "..."}
"""

import re
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger("MaaAuto")

DEFAULT_TIMEOUT = 15
USER_AGENT = "MaaAuto-ServerChan/1.0"


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _detect_url(sendkey: str) -> str:
    """Detect the API endpoint from the SendKey.
      - sctp{uid}t... -> Server Chan 3
      - anything else -> Server Chan Turbo
    """
    sendkey = (sendkey or "").strip()
    if not sendkey:
        raise ValueError("SendKey 为空")

    if sendkey.lower().startswith("sctp"):
        m = re.match(r"sctp(\d+)t", sendkey, re.IGNORECASE)
        if not m:
            raise ValueError(f"无效的 Server酱³ SendKey: {sendkey[:20]}...")
        uid = m.group(1)
        return f"https://{uid}.push.ft07.com/send/{sendkey}.send"

    return f"https://sctapi.ftqq.com/{sendkey}.send"


def _parse_response(raw: str) -> dict:
    """Parse the response body into a dict. On failure returns {'code': -1, 'message': raw}."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {"code": -1, "message": str(data)}
    except Exception:
        return {"code": -1, "message": raw.strip() or "(空响应)"}


# --------------------------------------------------------------------------- #
# Public interface
# --------------------------------------------------------------------------- #
def sc_send(sendkey: str, title: str, desp: str = "", options: dict = None) -> dict:
    """Send a Server Chan push.

    :param sendkey: SendKey (Turbo or Server Chan 3)
    :param title:   message title
    :param desp:    message body (Markdown supported)
    :param options: extra parameters (e.g. {"tags": "test"})
    :return: dict
        - success: {"code": 0, "message": "SUCCESS", "data": {...}}
        - failure: {"code": non-zero, "message": "error text"}
        - error:   {"code": -1, "message": "..."}
    """
    if options is None:
        options = {}

    if not sendkey or not str(sendkey).strip():
        return {"code": -1, "message": "SendKey 为空"}
    if not title:
        return {"code": -1, "message": "标题为空"}

    try:
        url = _detect_url(str(sendkey).strip())
    except Exception as e:
        logger.error(f"SendKey 解析失败: {e}")
        return {"code": -1, "message": str(e)}

    # Build the request body
    payload = {"title": title, "desp": desp or ""}
    for k, v in (options or {}).items():
        if k not in ("title", "desp"):
            payload[k] = v

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            result = _parse_response(raw)
            if result.get("code") == 0 and not result.get("message"):
                result["message"] = "SUCCESS"
            return result

    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", errors="replace")
            result = _parse_response(raw)
            if not result.get("message"):
                result["message"] = f"HTTP {e.code}: {e.reason}"
            result.setdefault("code", e.code)
            return result
        except Exception:
            return {"code": e.code, "message": f"HTTP {e.code}: {e.reason}"}

    except urllib.error.URLError as e:
        logger.error(f"Server酱网络错误: {e}")
        return {"code": -1, "message": f"网络错误: {e.reason}"}

    except Exception as e:
        logger.error(f"Server酱未知错误: {e}")
        return {"code": -1, "message": f"未知错误: {e}"}