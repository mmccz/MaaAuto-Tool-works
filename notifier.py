import logging
from serverchan_sdk import sc_send

logger = logging.getLogger("MaaAuto")

def send_task_report(send_key, start_time, end_time, status, logs):
    """
    发送任务报告到 Server酱
    :param send_key: Server酱 SendKey
    :param start_time: 任务开始时间 (datetime)
    :param end_time: 任务结束时间 (datetime)
    :param status: 状态字符串 ("成功" 或 "报错")
    :param logs: 日志列表 (list) 或 字符串 (str)
    """
    if not send_key:
        return
        
    title = f"{end_time.strftime('%m-%d')} | MaaAuto自动{status}"
    
    # 处理日志格式，确保美观换行
    if isinstance(logs, list):
        logs_text = "\n".join(logs)
    else:
        logs_text = str(logs)
    
    desp = f"任务开始时间：{start_time.strftime('%Y-%m-%d %H:%M:%S')}，任务结束时间：{end_time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    desp += f"当前日志输出：\n{logs_text}\n\n"
    desp += "MaaAuto 敬上"
    
    try:
        logger.info(f"正在发送 Server酱 推送，标题: {title}...")
        res = sc_send(send_key, title, desp, {"tags": "游戏"})
        logger.info(f"推送发送结果: {res}")
    except Exception as e:
        logger.error(f"推送发送失败: {e}")