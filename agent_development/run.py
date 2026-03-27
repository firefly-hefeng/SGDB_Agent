#!/usr/bin/env python3
"""
单细胞RNA-seq数据库智能检索系统 v2.0
主程序入口
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.cli import main

if __name__ == '__main__':
    main()