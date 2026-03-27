"""
工具函数模块
===========
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


def setup_logging(log_dir: str = "logs", log_name: str = "collection.log") -> logging.Logger:
    """配置日志记录"""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / log_name
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


def load_checkpoint(checkpoint_file: str) -> Dict[str, Any]:
    """加载检查点"""
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Failed to load checkpoint: {e}")
    return {
        'processed': [],
        'failed': [],
        'stats': {},
        'timestamp': datetime.now().isoformat()
    }


def save_checkpoint(checkpoint_file: str, data: Dict[str, Any]):
    """保存检查点"""
    os.makedirs(os.path.dirname(checkpoint_file), exist_ok=True)
    with open(checkpoint_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def ensure_dir(path: str) -> Path:
    """确保目录存在"""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def format_number(n: int) -> str:
    """格式化数字显示"""
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def safe_get(d: Dict, *keys, default=None):
    """安全获取嵌套字典值"""
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
        if d is None:
            return default
    return d
