import logging
import json
import urllib.request
from serverchan_sdk import sc_send

logger = logging.getLogger("MaaAuto")

def send_webhook(webhook_url, title, content):
    """发送通用 Webhook（POST JSON: {title, content}）"""
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
    """
    发送任务报告
    :param send_key: Server酱 SendKey（为空则跳过）
    :param start_time: 任务开始时间 (datetime)
    :param end_time: 任务结束时间 (datetime)
    :param status: 状态字符串 ("成功" 或 "报错")
    :param logs: 日志列表 (list) 或 字符串 (str)
    :param webhook_url: 通用 Webhook 地址（为空则跳过）
    """
    title = f"{end_time.strftime('%m-%d')} | MaaAuto自动{status}"

    if isinstance(logs, list):
        logs_text = "\n".join(logs)
    else:
        logs_text = str(logs)

    desp = f"任务开始时间：{start_time.strftime('%Y-%m-%d %H:%M:%S')}，任务结束时间：{end_time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    desp += f"当前日志输出：\n{logs_text}\n\n"
    desp += "MaaAuto 敬上"

    # Server酱推送
    if send_key:
        try:
            logger.info(f"正在发送 Server酱 推送，标题: {title}...")
            res = sc_send(send_key, title, desp, {"tags": "游戏"})
            logger.info(f"推送发送结果: {res}")
        except Exception as e:
            logger.error(f"推送发送失败: {e}")

    # 通用 Webhook 推送
    if webhook_url:
        logger.info(f"正在发送通用 Webhook 推送: {webhook_url}")
        send_webhook(webhook_url, title, desp)