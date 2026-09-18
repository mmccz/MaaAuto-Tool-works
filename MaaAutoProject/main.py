import sys, os, ctypes, winreg, atexit, datetime, logging
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QLabel, QPushButton, QTextEdit, 
                               QSystemTrayIcon, QMenu, QMessageBox)
from PySide6.QtCore import QTime, QTimer, Qt, QThread, Signal, QDate
from PySide6.QtGui import QIcon, QAction

from config_manager import load_config, save_config, setup_logger, LOG_DIR
from automation import execute_workflow
from settings_dialog import SettingsDialog
from utils import resource_path, kill_all_related_processes

# ================= 自动获取管理员权限 =================
def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin()
    except: return False

if not is_admin():
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
    sys.exit()

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass
# ========================================================

class Worker(QThread):
    log_signal = Signal(str)
    
    def __init__(self, config, run_log_dir):
        super().__init__()
        self.config = config
        self.run_log_dir = run_log_dir
        
    def run(self):
        logger = logging.getLogger("MaaAuto")
        
        # 【关键修复】清理所有已有的 Handler，防止日志重复
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            
        # 重新添加本次任务的日志文件 Handler
        file_handler = logging.FileHandler(os.path.join(self.run_log_dir, "task.log"), encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)

        class SignalHandler(logging.Handler):
            def __init__(self, signal):
                super().__init__(); self.signal = signal
            def emit(self, record):
                self.signal.emit(self.format(record))
                
        handler = SignalHandler(self.log_signal)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(handler)
        
        try:
            execute_workflow(self.config, logger)
        except Exception as e:
            logger.error(f"执行错误: {str(e)}")
        finally:
            # 【关键修复】任务结束，清理本次添加的 Handler，避免累积
            logger.removeHandler(handler)
            logger.removeHandler(file_handler)
            file_handler.close()
            
            # 重新挂载基础 UI 日志处理器，供下次主界面显示
            from config_manager import LogHandler
            base_handler = LogHandler()
            base_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            logger.addHandler(base_handler)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.logger, self.ui_log_handler = setup_logger()
        self.ui_log_handler.log_signal.connect(self.append_log)
        self.worker = None
        self.is_quitting = False

        self.setWindowTitle("MAA & MaaEnd 控制台")
        self.resize(600, 500)
        self.setWindowIcon(QIcon(resource_path("resources/icon.ico")))
        
        self.setup_ui()
        self.setup_tray()
        self.setup_timer()
        
        atexit.register(self.cleanup_on_exit)
        self.logger.info("程序启动成功")

    def setup_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        top_bar = QHBoxLayout()
        self.status_label = QLabel("状态: 空闲")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px; color: green;")
        top_bar.addWidget(self.status_label); top_bar.addStretch()
        btn_settings = QPushButton("⚙️ 设置"); btn_settings.clicked.connect(self.open_settings)
        top_bar.addWidget(btn_settings)
        self.btn_run = QPushButton("▶️ 立即执行")
        self.btn_run.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 5px 15px;")
        self.btn_run.clicked.connect(self.manual_run)
        top_bar.addWidget(self.btn_run); layout.addLayout(top_bar)
        
        self.log_text = QTextEdit(); self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas;")
        layout.addWidget(self.log_text)

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(resource_path("resources/icon.ico")))
        self.tray_icon.setToolTip("MaaAuto 运行中")
        menu = QMenu()
        menu.addAction(QAction("显示主界面", self, triggered=self.show_normal))
        menu.addAction(QAction("立即执行", self, triggered=self.manual_run))
        menu.addAction(QAction("设置", self, triggered=self.open_settings))
        menu.addSeparator()
        menu.addAction(QAction("彻底退出", self, triggered=self.quit_app))
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(lambda r: self.show_normal() if r == QSystemTrayIcon.DoubleClick else None)
        self.tray_icon.show()

    def setup_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_schedule)
        self.timer.start(10000)  # 每 10 秒检查一次定时任务

    def check_schedule(self):
        # 如果未启用定时启动，直接跳过
        if not self.config.get("enable_schedule", True):
            return
            
        now = QTime.currentTime()
        target_time = QTime.fromString(self.config.get("execute_time", "08:00"), "HH:mm")
        today = QDate.currentDate().toString("yyyy-MM-dd")

        # 【关键修复】改为 大于等于，防止错过设定的那一分钟
        if now >= target_time and self.config.get("last_trigger_date") != today:
            self.logger.info(f"当前时间 {now.toString('HH:mm')} 已达到或超过设定时间 {target_time.toString('HH:mm')}，触发定时任务！")
            self.config["last_trigger_date"] = today
            save_config(self.config)
            self.manual_run()
        
    def open_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            self.config = dialog.get_config()
            save_config(self.config)
            self.set_auto_start()

    def manual_run(self):
        if self.worker and self.worker.isRunning():
            self.logger.info("任务正在执行中，请勿重复启动。")
            return
            
        # 更新执行次数
        self.config["run_count"] = self.config.get("run_count", 0) + 1
        save_config(self.config)
        
        # 【关键修复】生成英文层级日志目录: logs/YYYY/MM/DD/run_X_HHMMSS
        run_id = self.config["run_count"]
        now = datetime.datetime.now()
        year_str = now.strftime("%Y")
        month_str = now.strftime("%m")
        day_str = now.strftime("%d")
        time_str = now.strftime("%H%M%S")
        
        folder_name = f"run_{run_id}_{time_str}"
        run_log_dir = os.path.join(LOG_DIR, year_str, month_str, day_str, folder_name)
        os.makedirs(run_log_dir, exist_ok=True)
        
        self.logger.info(f"========== 开始第 {run_id} 次执行 ==========")
        self.logger.info(f"本次任务日志将保存在: {run_log_dir}")
        
        self.status_label.setText("状态: 执行中...")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px; color: blue;")
        self.btn_run.setEnabled(False)
        
        self.worker = Worker(self.config, run_log_dir)
        self.worker.log_signal.connect(self.append_log)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_worker_finished(self):
        self.btn_run.setEnabled(True)
        self.status_label.setText("状态: 空闲")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px; color: green;")
        self.logger.info("任务执行结束。\n")

    def save_all_config(self):
        save_config(self.config)

    def set_auto_start(self):
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "MaaAuto"; exe_path = os.path.abspath(sys.argv[0])
        if exe_path.endswith(".py"): exe_path = f'python "{exe_path}"'
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            if self.config.get("auto_start"):
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}" --autostart')
            else:
                try: winreg.DeleteValue(key, app_name)
                except FileNotFoundError: pass
            winreg.CloseKey(key)
        except Exception as e:
            self.logger.error(f"设置开机自启失败: {e}")

    def append_log(self, text): self.log_text.append(text)
    def show_normal(self): self.showNormal(); self.activateWindow()

    def cleanup_on_exit(self):
        if self.config.get("kill_on_exit", True): kill_all_related_processes()
        if self.worker and self.worker.isRunning(): self.worker.terminate()

    def quit_app(self):
        self.is_quitting = True
        self.cleanup_on_exit()
        QApplication.quit()

    def closeEvent(self, event):
        if self.is_quitting: event.accept(); return
        if self.config.get("minimize_to_tray", True):
            event.ignore(); self.hide()
            self.tray_icon.showMessage("MaaAuto", "已最小化到托盘，继续后台运行。", QSystemTrayIcon.Information, 2000)
        else:
            self.is_quitting = True; self.cleanup_on_exit()
            event.accept(); QApplication.quit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    if "--autostart" in sys.argv: window.hide()
    else: window.show()
    sys.exit(app.exec())