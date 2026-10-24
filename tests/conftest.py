"""pytest 公共配置：把 MaaAutoProject 加进 import 路径。

这些测试刻意不碰真实屏幕/鼠标：
* 找图相关测试把 ``vision.grab_gray`` 换成内存里的合成画面；
* 点击相关测试把 ``input_driver.move_cursor`` / ``_send_mouse`` 换成记录器。

这样在 CI（无交互式桌面）里也能跑。
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "MaaAutoProject")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
