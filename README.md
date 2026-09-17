# MaaAuto - MAA & MaaEnd 定时自动化控制台

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6-green.svg)](https://pypi.org/project/PySide6/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

基于 PySide6 开发的 Windows 桌面自动化调度工具，用于统一管理 **MAA (MaaAssistantArknights)** 和 **MaaEnd**。支持定时启动、图像识别点击、高危前台清理、失败重试以及 Server酱 微信推送。

## ⚠️ 高危警告（请务必阅读）

**本软件包含“方案A”清理逻辑：在启动任务前，程序会强制关闭所有可见的前台程序（系统进程和模拟器除外）。**

- 如果你有未保存的 Word、Excel、记事本或浏览器页面，**数据将会丢失**！
- 请务必在**专门用于挂机游戏的纯净电脑**上使用本软件。
- 因使用本软件导致的数据丢失、系统崩溃、游戏账号封禁等任何后果，**作者不承担任何责任**。

## ✨ 核心功能

- **每日定时启动**：自定义每日执行时间，到点自动执行；支持一键开启/关闭定时功能。
- **图像识别点击**：基于 `pyautogui` 和 `opencv`，自动识别并点击 MAA 的“Link Start!”和 MaaEnd 的“开始任务”按钮。
- **高频清理与容错**：启动任务前清理无关前台程序；支持自定义重试次数和超时时间，任务卡死自动重试。
- **进程保活与唤醒**：任务完成后自动将 MAA/MaaEnd 最小化到后台；下次执行时自动拉取到前台，**拒绝重复启动导致的多开冲突**。
- **Server酱 微信推送**：任务开始、结束或发生异常时，自动推送详细的日志报告到微信。
- **分类日志存储**：自动在本地生成 `logs/年份/月份/日期/run_次数_时间/task.log`，按执行次数分类，绝不重复输出。

## 🖼️ 界面预览

> ![1789651817624](image/README/1789651817624.png)
> ![1789651840612](image/README/1789651840612.png)
> 主界面（状态监控 + 日志输出）
> 设置界面（路径、进程、定时、推送分类管理）

## 🚀 快速开始

### 1. 环境要求

- **操作系统**：Windows 10 / 11（仅支持 Windows）
- **屏幕分辨率**：推荐 1080P，且系统缩放必须设置为 **100%**（否则图像识别会失败）
- **Python**：3.11 或更高版本
- **依赖软件**：请自行下载并安装 [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights) 和 MaaEnd。

### 2. 安装依赖

pip install -r requirements.txt
requirements.txt 内容如下：

text
PySide6
pyautogui
psutil
opencv-python
pywin32
serverchan-sdk

### 3. 准备图像资源（非常重要）
程序依赖图像识别来点击按钮。请在项目根目录创建 resources 文件夹，并自行截图以下两张图片放入其中：

resources/maa_start.png：MAA 界面右下角的 "Link Start!" 按钮。

resources/maaend_start.png：MaaEnd 界面下方的 "开始任务" 按钮。

截图建议：

在 100% 缩放的 1080P 屏幕下截图。

尽量只截取按钮的文字部分，不要带太多背景，这样识别成功率最高。

如果程序报错“找图超时”，请重新截图并替换。

### 4. 配置与运行
直接运行源码：

bash
python main.py
点击右上角 ⚙️ 设置，填入 MAA 路径、MaaEnd 路径。

填写模拟器进程名（默认 MuMuPlayer.exe）和 PC 端游戏进程名（默认 Arknights.exe）。

填写 Server酱 SendKey（可选，不填则不推送）。

设定每日执行时间，保存配置。


📂 目录结构
text
MaaAutoProject/
├── main.py                 # 程序入口与界面逻辑
├── config_manager.py       # 配置与日志管理
├── automation.py           # 核心自动化流程
├── process_utils.py        # 进程检测、清理与窗口控制
├── notifier.py             # Server酱 推送模块
├── settings_dialog.py      # 设置界面
├── local_utils.py          # 本地工具函数（资源路径等）
├── requirements.txt        # 依赖清单
├── resources/              # 图像资源目录（需自行提供截图）
│   ├── icon.ico
│   ├── maa_start.png
│   └── maaend_start.png
├── config/                 # 自动生成：配置文件夹
└── logs/                   # 自动生成：日志文件夹

### ⚠️ 免责声明
本项目仅供学习 Python 自动化、GUI 开发和进程管理技术使用。

本项目为第三方调度工具，与 MAA、MaaEnd 官方无任何关联。

请勿将本软件用于商业用途。

使用本软件产生的任何直接或间接后果（包括但不限于游戏账号封禁、数据丢失、系统异常），由使用者自行承担。

### 📄 开源协议
本项目采用 MIT License 协议开源。