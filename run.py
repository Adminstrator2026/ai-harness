"""
DeepHub MAX 启动入口 —— PyInstaller 分析起点
==============================================
不要直接 python run.py 发布，发布用 PyInstaller 打包出来的 exe。
"""

import sys
import os

# 确保顶层 app 包可 import（源码运行和 frozen 模式都走这里）
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from app.server import main

if __name__ == "__main__":
    main()
