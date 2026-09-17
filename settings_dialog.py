from PySide6.QtWidgets import (QDialog, QVBoxLayout, QTabWidget, QWidget, 
                               QFormLayout, QLineEdit, QPushButton, QFileDialog,
                               QSpinBox, QTimeEdit, QCheckBox, QHBoxLayout, QMessageBox)
from PySide6.QtCore import QTime
from serverchan_sdk import sc_send

class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config.copy() # 操作副本，取消时不影响原配置
        self.setWindowTitle("设置")
        self.resize(500, 400)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        
        # --- Tab 1: 路径设置 ---
        tab_path = QWidget()
        form_path = QFormLayout(tab_path)
        self.maa_edit = QLineEdit(self.config.get("maa_path", ""))
        btn1 = QPushButton("浏览"); btn1.clicked.connect(lambda: self.browse_file(self.maa_edit))
        h1 = QHBoxLayout(); h1.addWidget(self.maa_edit); h1.addWidget(btn1)
        form_path.addRow("MAA 路径:", h1)
        
        self.maaend_edit = QLineEdit(self.config.get("maaend_path", ""))
        btn2 = QPushButton("浏览"); btn2.clicked.connect(lambda: self.browse_file(self.maaend_edit))
        h2 = QHBoxLayout(); h2.addWidget(self.maaend_edit); h2.addWidget(btn2)
        form_path.addRow("MaaEnd 路径:", h2)
        tabs.addTab(tab_path, "路径设置")
        
        # --- Tab 2: 进程与超时 ---
        tab_proc = QWidget()
        form_proc = QFormLayout(tab_proc)
        self.emulator_edit = QLineEdit(self.config.get("emulator_proc", "MuMuPlayer.exe"))
        form_proc.addRow("模拟器进程名:", self.emulator_edit)
        self.pc_game_edit = QLineEdit(self.config.get("pc_game_proc", "Arknights.exe"))
        form_proc.addRow("PC端游戏进程名:", self.pc_game_edit)
        self.timeout_spin = QSpinBox(); self.timeout_spin.setRange(10, 300)
        self.timeout_spin.setValue(self.config.get("wait_timeout", 60))
        form_proc.addRow("找图超时(秒):", self.timeout_spin)
        self.game_start_spin = QSpinBox(); self.game_start_spin.setRange(30, 600)
        self.game_start_spin.setValue(self.config.get("game_start_timeout", 120))
        form_proc.addRow("游戏启动等待(秒):", self.game_start_spin)
        
        # 新增：等待游戏关闭超时
        self.game_exit_spin = QSpinBox(); self.game_exit_spin.setRange(300, 14400)
        self.game_exit_spin.setValue(self.config.get("game_exit_timeout", 7200))
        form_proc.addRow("游戏关闭等待(秒):", self.game_exit_spin)
        
        # 新增：重试次数与间隔
        self.retry_times_spin = QSpinBox(); self.retry_times_spin.setRange(1, 10)
        self.retry_times_spin.setValue(self.config.get("retry_times", 3))
        form_proc.addRow("失败重试次数:", self.retry_times_spin)
        
        self.retry_interval_spin = QSpinBox(); self.retry_interval_spin.setRange(5, 300)
        self.retry_interval_spin.setValue(self.config.get("retry_interval", 30))
        form_proc.addRow("重试间隔(秒):", self.retry_interval_spin)
        tabs.addTab(tab_proc, "进程与超时")
        
        # --- Tab 3: 定时与推送 ---
        tab_sched = QWidget()
        form_sched = QFormLayout(tab_sched)
        
        # 新增：定时开关
        self.enable_schedule_cb = QCheckBox("启用每日定时启动")
        self.enable_schedule_cb.setChecked(self.config.get("enable_schedule", False))
        form_sched.addRow(self.enable_schedule_cb)
        
        self.time_edit = QTimeEdit()
        self.time_edit.setTime(QTime.fromString(self.config.get("execute_time", "08:00"), "HH:mm"))
        form_sched.addRow("每日执行时间:", self.time_edit)
        
        self.sc_edit = QLineEdit(self.config.get("serverchan_key", ""))
        self.sc_edit.setEchoMode(QLineEdit.Password)
        btn_sc = QPushButton("测试推送"); btn_sc.clicked.connect(self.test_serverchan)
        h3 = QHBoxLayout(); h3.addWidget(self.sc_edit); h3.addWidget(btn_sc)
        form_sched.addRow("Server酱 SendKey:", h3)
        tabs.addTab(tab_sched, "定时与推送")
        
        # --- Tab 4: 常规设置 ---
        tab_general = QWidget()
        form_general = QFormLayout(tab_general)
        self.auto_start_cb = QCheckBox("开机自启")
        self.auto_start_cb.setChecked(self.config.get("auto_start", False))
        form_general.addRow(self.auto_start_cb)
        
        self.minimize_tray_cb = QCheckBox("点击关闭(X)时最小化到托盘")
        self.minimize_tray_cb.setChecked(self.config.get("minimize_to_tray", True))
        form_general.addRow(self.minimize_tray_cb)
        
        self.kill_on_exit_cb = QCheckBox("退出程序时强制清理所有相关进程")
        self.kill_on_exit_cb.setChecked(self.config.get("kill_on_exit", True))
        form_general.addRow(self.kill_on_exit_cb)
        tabs.addTab(tab_general, "常规设置")
        
        layout.addWidget(tabs)
        
        # 底部按钮
        btn_box = QHBoxLayout()
        btn_save = QPushButton("保存并关闭")
        btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addStretch()
        btn_box.addWidget(btn_save)
        btn_box.addWidget(btn_cancel)
        layout.addLayout(btn_box)

    def browse_file(self, line_edit):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择可执行文件", "", "Executable Files (*.exe)")
        if file_path: line_edit.setText(file_path)

    def test_serverchan(self):
        key = self.sc_edit.text()
        if key:
            res = sc_send(key, "MaaAuto 测试", "这是一条测试推送消息", {"tags": "测试"})
            QMessageBox.information(self, "测试结果", str(res))
        else:
            QMessageBox.warning(self, "警告", "请先填写 SendKey")

    def get_config(self):
        self.config["maa_path"] = self.maa_edit.text()
        self.config["maaend_path"] = self.maaend_edit.text()
        self.config["emulator_proc"] = self.emulator_edit.text()
        self.config["pc_game_proc"] = self.pc_game_edit.text()
        self.config["execute_time"] = self.time_edit.time().toString("HH:mm")
        self.config["wait_timeout"] = self.timeout_spin.value()
        self.config["serverchan_key"] = self.sc_edit.text()
        self.config["auto_start"] = self.auto_start_cb.isChecked()
        self.config["minimize_to_tray"] = self.minimize_tray_cb.isChecked()
        self.config["kill_on_exit"] = self.kill_on_exit_cb.isChecked()
        self.config["game_start_timeout"] = self.game_start_spin.value()
        self.config["game_exit_timeout"] = self.game_exit_spin.value()
        self.config["retry_times"] = self.retry_times_spin.value()
        self.config["retry_interval"] = self.retry_interval_spin.value()
        self.config["execute_time"] = self.time_edit.time().toString("HH:mm")
        self.config["enable_schedule"] = self.enable_schedule_cb.isChecked() 
        return self.config