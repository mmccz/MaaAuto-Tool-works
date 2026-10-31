import logging
import json
import urllib.request

# serverchan_sdk is a local project file (serverchan_sdk.py),
# pulled into the exe by build.py's HIDDEN_IMPORTS at packaging time.
# If it is missing, only Server Chan pushing is disabled; the app still starts.
try:
    from serverchan_sdk import sc_send
    HAS_SERVERCHAN = True
except ImportError:
    sc_send = None
    HAS_SERVERCHAN = False

logger = logging.getLogger("MaaAuto")


def send_webhook(webhook_url, title, content):
    """Send a generic webhook (POST JSON: {title, content})."""
    try:
        payload = {
            "title": title,
            "content": content
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info(f"Webhook 推送结果: HTTP {resp.status}")
    except Exception as e:
        logger.error(f"Webhook 推送失败: {e}")


def send_task_report(send_key, start_time, end_time, status, logs, webhook_url=""):
    """Send the task report.

    :param send_key: Server Chan SendKey (empty = skip)
    :param start_time: task start time (datetime)
    :param end_time: task end time (datetime)
    :param status: status string (success / aborted / error)
    :param logs: log lines (list) or a plain string (str)
    :param webhook_url: generic webhook URL (empty = skip)
    """
    title = f"{end_time.strftime('%m-%d')} | MaaAuto自动{status}"

    if isinstance(logs, list):
        logs_text = "\n".join(logs)
    else:
        logs_text = str(logs)

    desp = f"任务开始时间：{start_time.strftime('%Y-%m-%d %H:%M:%S')}，任务结束时间：{end_time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    desp += f"当前日志输出：\n{logs_text}\n\n"
    desp += "MaaAuto 敬上"

    # Server Chan push
    if send_key:
        if not HAS_SERVERCHAN:
            logger.warning("未加载 serverchan_sdk，跳过 Server 酱推送。")
        else:
            try:
                logger.info(f"正在发送 Server酱 推送，标题: {title}...")
                res = sc_send(send_key, title, desp, {"tags": "游戏"})
                logger.info(f"推送发送结果: {res}")
            except Exception as e:
                logger.error(f"推送发送失败: {e}")

    # Generic Webhook push
    if webhook_url:
        logger.info(f"正在发送通用 Webhook 推送: {webhook_url}")
        send_webhook(webhook_url, title, desp)