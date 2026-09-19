"""
Server酱推送 SDK（本地实现，无第三方依赖）

支持：
  - Server酱 Turbo 版（SendKey 形如 SCTxxxxxTxxxxx）
  - Server酱³（SendKey 形如 sctp{uid}txxxxx）

对外接口与 PyPI 上的 `serverchan-sdk` 保持一致，
方便将来切换为 pip 版本而不用改调用方代码。

用法：
    from serverchan_sdk import sc_send
    res = sc_send("sctp12345t...", "标题", "内容", {"tags": "测试"})

返回：
    dict，形如：
      成功：{"code": 0, "message": "SUCCESS", "data": {...}}
      失败：{"code": 非0, "message": "错误信息"}
      异常：{"code": -1, "message": "..."}
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
# 内部工具
# --------------------------------------------------------------------------- #
def _detect_url(sendkey: str) -> str:
    """
    根据 SendKey 自动识别 API 端点。
      - sctp{uid}t... → Server酱³
      - 其他          → Server酱 Turbo
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
    """把响应体解析成 dict。失败返回 {'code': -1, 'message': raw}"""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {"code": -1, "message": str(data)}
    except Exception:
        return {"code": -1, "message": raw.strip() or "(空响应)"}


# --------------------------------------------------------------------------- #
# 对外接口
# --------------------------------------------------------------------------- #
def sc_send(sendkey: str, title: str, desp: str = "", options: dict = None) -> dict:
    """
    发送 Server酱推送。

    :param sendkey: SendKey（Turbo 版或 Server酱³）
    :param title:   消息标题
    :param desp:    消息正文（支持 Markdown）
    :param options: 额外参数（如 {"tags": "测试"}）
    :return: dict
        - 成功：{"code": 0, "message": "SUCCESS", "data": {...}}
        - 失败：{"code": 非0, "message": "错误信息"}
        - 异常：{"code": -1, "message": "..."}
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

    # 构造请求体
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