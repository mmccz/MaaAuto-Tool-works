# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/) 规范。

---

## [2.0.0] - 2026-09-18

这是一次大规模重构，UI 全面翻新，新增多项功能。**与 1.x 版本的配置基本兼容**，旧字段全部保留。

### 🎨 UI 全面重构

- **三页面结构**：侧边栏 + 右侧内容区，分别为 **首页 / 设置 / 关于**。
- **滑动切页**：新增 `SlidingStack` 替代 `QStackedWidget`，切页带左右推动画。
- **设置页重做**：单页滚动式分组卡片 + 顶部 chips 快速跳转 + 滚动联动高亮。
- **自动保存**：设置页所有改动即时写入 `config.json`，无需手动保存。
- **背景图**：支持透明度 / 模糊 / 填充 / 适应 / 拉伸 / 平铺 4 种缩放模式。
- **窗口状态记忆**：自动保存并恢复窗口大小与位置。

### ✨ 新增组件

- `Switch`：iOS 风格开关，44×24，主题色自适应，240ms 动画。
- `SegmentedControl`：分段选择器，用于前台处理三选一。
- `ProcessPickerDialog`：进程选择对话框，列举可见窗口进程，支持搜索、系统进程过滤、双击勾选。
- `WheelTimePicker`：单行滚轮时间选择器，点击激活 + 滚轮逐项 + 拖动吸附。
- `IntLineEdit`：替代 `QSpinBox` 的整数输入框（避开 QSS 按钮 hitbox 错位问题）。
- `NoWheelComboBox` / `NoWheelTimeEdit`：屏蔽鼠标滚轮误改值。

### 🎭 主题系统

- 新增 **浅色 / 深色 / 跟随系统** 三态主题，独立 QSS 文件。
- 主题切换带**截图遮罩淡出**过渡动画（260ms）。
- 侧边栏、卡片、日志、设置容器全部半透明，背景图可透出。
- 日志按级别着色：ERROR 红、WARNING 黄、成功绿、分隔线蓝。

### 🌐 国际化

- 新增 JSON 语言包动态加载，内置 **简体中文 / English**。
- 切换语言即时刷新全界面文案，无需重启。
- 新增语言只需在 `i18n/` 放入新的 `<code>.json`。

### 🎛️ 任务控制

- **按钮状态机**：首页按钮在「▶ 立即执行」 / 「■ 结束任务」 / 「正在结束...」三态间切换。
- **随时中止**：任务执行中可点击按钮或托盘菜单中止，长循环内 **1 秒内响应**。
- **中断传播**：`process_utils` 中的 `wait_for_process_start` / `wait_for_process_exit` / `find_and_click` 均支持中断检查。
- **进程清理**：退出时不再粗暴 `terminate()`，改为 `requestInterruption() + wait()`。

### 📬 通知扩展

- **系统通知**：任务结束时弹 Windows 托盘气泡（成功 / 失败 / 中止三态），可在设置页开关。
- **Server酱测试优化**：解析响应，弹窗显示「推送成功 / 失败」，并写入日志。
- **Webhook 测试优化**：成功 / 失败写入日志。

### 🔧 托盘菜单

重构为 **4 项**：

- 显示主界面
- 设置
- 结束任务（仅任务运行时可用）
- 退出 MaaAuto

### 🐛 修复

- 修复设置页与首页内容重叠的问题。
- 修复滚动区背景不跟随主题切换的问题。
- 修复深浅主题切换无动画的问题。
- 修复 `Switch` 缩进错误导致不绘制的问题。
- 修复 `QSpinBox` 在 QSS 下按钮点击区域错位的问题。
- 修复 `theme_transition` 遮罩被 QSS 重刷导致主题切换无效的问题。
- 修复提权失败时静默退出、无界面的问题。
- 修复 DPI 设置 API 过旧导致警告的问题。
- 修复退出程序时 `worker.terminate()` 可能残留子进程的问题。
- 修复首页日志框未接入全局 LogHandler 的问题。

### ⚙️ 配置变更

**新增字段**（旧配置自动补齐默认值）：

- `emulator_proc`：模拟器进程名
- `pc_game_proc`：PC 端游戏进程名（默认 `Endfield.exe`）
- `theme`：主题
- `language`：语言
- `background_image` / `background_opacity` / `background_blur` / `background_mode`
- `show_animation`：页面切换动画开关
- `enable_system_notify`：系统通知开关
- `last_run_time`：上次运行时间
- `window_geometry`：窗口位置大小

**默认值变更**：

- `pc_game_proc`：`Arknights.exe` → `Endfield.exe`