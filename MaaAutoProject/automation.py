import time
import subprocess
import os
import sys
import datetime
import pyautogui
import logging
from utils import resource_path
from process_utils import (kill_foreground_apps, is_process_running, 
                           wait_for_process_exit, wait_for_process_start,
                           minimize_process_windows, bring_process_to_front)
from notifier import send_task_report  # <--- 引入独立的推送模块

logger = logging.getLogger("MaaAuto")

def find_and_click(image_name, timeout=60):
    """寻找目标图像并点击"""
    image_path = resource_path(os.path.join("resources", image_name))
    if not os.path.exists(image_path):
        logger.error(f"【严重错误】找不到图像文件: {image_path}！")
        return False
        
    logger.info(f"开始寻找目标按钮: {image_name} (超时 {timeout} 秒)")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            location = pyautogui.locateCenterOnScreen(image_path, confidence=0.75, grayscale=True)
            if location:
                logger.info(f"找到目标按钮，执行点击... (图片: {image_name})")
                pyautogui.click(location)
                return True
        except pyautogui.ImageNotFoundException:
            pass
        time.sleep(2)
        
    raise TimeoutError(f"找图超时，未能找到: {image_name}")

def run_maa_phase(config, logger):
    """执行 MAA 阶段（如果未填写路径则跳过）"""
    maa_path = config.get("maa_path", "").strip()
    if not maa_path:
        logger.info("未配置 MAA 启动地址，跳过 MAA 阶段。")
        return False
        
    emulator_proc = config.get("emulator_proc", "MuMuPlayer.exe")
    maa_procs = ["maa.exe", "maa-cli.exe"]

    if is_process_running(maa_procs):
        logger.info("检测到 MAA 已在运行，正在拉取到前台...")
        bring_process_to_front(maa_procs)
        time.sleep(3)
    else:
        if not os.path.exists(maa_path):
            raise FileNotFoundError(f"MAA 路径无效: {maa_path}")
        logger.info(f"MAA 未运行，正在启动新进程: {maa_path}")
        subprocess.Popen(maa_path, shell=True)
        time.sleep(5)

    logger.info("正在尝试点击 MAA 的【Link Start!】按钮...")
    find_and_click("maa_start.png", config.get("wait_timeout", 60))

    wait_for_process_start([emulator_proc], config.get("game_start_timeout", 120))
    
    logger.info("MAA 正在运行，等待模拟器关闭...")
    wait_for_process_exit([emulator_proc], config.get("game_exit_timeout", 7200), check_interval=15)
    
    logger.info("模拟器已关闭，正在将 MAA 最小化到后台备用...")
    minimize_process_windows(maa_procs)
    time.sleep(3)
    return True

def run_maaend_phase(config, logger):
    """执行 MaaEnd 阶段（如果未填写路径则跳过）"""
    maaend_path = config.get("maaend_path", "").strip()
    if not maaend_path:
        logger.info("未配置 MaaEnd 启动地址，跳过 MaaEnd 阶段。")
        return False

    pc_game_proc = config.get("pc_game_proc", "Arknights.exe")
    maaend_procs = ["maaend"]

    if is_process_running(maaend_procs):
        logger.info("检测到 MaaEnd 已在运行，正在拉取到前台...")
        bring_process_to_front(maaend_procs)
        time.sleep(3)
    else:
        if not os.path.exists(maaend_path):
            raise FileNotFoundError(f"MaaEnd 路径无效: {maaend_path}")
        logger.info(f"MaaEnd 未运行，正在启动新进程: {maaend_path}")
        subprocess.Popen(maaend_path, shell=True)
        time.sleep(10)

    logger.info("正在尝试点击 MaaEnd 的【开始任务】按钮...")
    find_and_click("maaend_start.png", config.get("wait_timeout", 60))

    wait_for_process_start([pc_game_proc], config.get("game_start_timeout", 120))

    logger.info("PC端游戏已启动，等待游戏关闭...")
    wait_for_process_exit([pc_game_proc], config.get("game_exit_timeout", 7200), check_interval=15)
    
    logger.info("PC端游戏已关闭，正在将 MaaEnd 最小化到后台备用...")
    minimize_process_windows(maaend_procs)
    time.sleep(3)
    return True

def execute_workflow(config, logger):
    start_time = datetime.datetime.now()
    
    # ================= 1. 动态捕获本次任务的日志 =================
    task_logs = []
    class CaptureHandler(logging.Handler):
        def emit(self, record):
            task_logs.append(self.format(record))
            
    capture_handler = CaptureHandler()
    capture_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(capture_handler)

    overall_status = "成功"
    send_key = config.get("serverchan_key", "")
    retry_times = config.get("retry_times", 3)
    retry_interval = config.get("retry_interval", 30)

    try:
        logger.info("开始清理前台程序...")
        kill_foreground_apps()

        # ================= MAA 阶段 =================
        maa_path = config.get("maa_path", "").strip()
        if maa_path:
            for attempt in range(1, retry_times + 1):
                try:
                    logger.info(f"========== 开始 MAA 阶段 (尝试 {attempt}/{retry_times}) ==========")
                    run_maa_phase(config, logger)
                    break
                except Exception as e:
                    logger.error(f"MAA 阶段发生异常: {e}")
                    if attempt < retry_times:
                        logger.info(f"将在 {retry_interval} 秒后重试 MAA 阶段...")
                        if is_process_running(["maa.exe", "maa-cli.exe"]):
                            bring_process_to_front(["maa.exe", "maa-cli.exe"])
                        time.sleep(retry_interval)
                    else:
                        logger.error("MAA 阶段重试次数已达上限，跳过该阶段。")
                        overall_status = "报错"
        else:
            logger.info("未配置 MAA 启动地址，跳过 MAA 阶段。")

        # ================= MaaEnd 阶段 =================
        maaend_path = config.get("maaend_path", "").strip()
        if maaend_path:
            for attempt in range(1, retry_times + 1):
                try:
                    logger.info(f"========== 开始 MaaEnd 阶段 (尝试 {attempt}/{retry_times}) ==========")
                    run_maaend_phase(config, logger)
                    break
                except Exception as e:
                    logger.error(f"MaaEnd 阶段发生异常: {e}")
                    if attempt < retry_times:
                        logger.info(f"将在 {retry_interval} 秒后重试 MaaEnd 阶段...")
                        if is_process_running(["maaend.exe"]):
                            bring_process_to_front(["maaend.exe"])
                        time.sleep(retry_interval)
                    else:
                        logger.error("MaaEnd 阶段重试次数已达上限。")
                        overall_status = "报错"
        else:
            logger.info("未配置 MaaEnd 启动地址，跳过 MaaEnd 阶段。")

    except Exception as global_e:
        logger.error(f"执行过程中发生未知严重错误: {global_e}")
        overall_status = "报错"
    finally:
        logger.removeHandler(capture_handler) # 移除捕获器

    # ================= 2. 调用独立的推送模块 =================
    end_time = datetime.datetime.now()
    # 只有在配置了 send_key 时才发送，notifier 内部也会做二次校验
    send_task_report(send_key, start_time, end_time, overall_status, task_logs)
    
    logger.info("整个自动化流程结束！")