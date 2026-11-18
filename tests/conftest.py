"""测试默认关掉环境预检。

单测用 fake 设备 / 桩 tesseract，不依赖开发机 PATH 里真有 adb 和 tesseract；
生产路径（未设 PDDCHECK_SKIP_PREFLIGHT）仍然跑旧 pdd.sh 那两道闸：缺 adb → rc69、
缺 tesseract → 先推一条再 rc78。
"""

import os

os.environ.setdefault("PDDCHECK_SKIP_PREFLIGHT", "1")
