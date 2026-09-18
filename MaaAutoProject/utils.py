import os
import sys
import psutil
import logging

logger = logging.getLogger("MaaAuto")

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def kill_all_related_processes():
    """强制清理所有相关进程"""
    targets = ["maa.exe", "maa-cli.exe", "maaend.exe", "mumuplayer.exe", "nemuplayer.exe", "dnplayer.exe"]
    logger.info("正在清理残留进程...")
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'].lower() in targets:
                logger.info(f"强制关闭残留进程: {proc.info['name']}")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass