"""
记忆系统日志配置
"""
import os
import logging
from pathlib import Path
from datetime import datetime

# ==================== 日志配置 ====================
# 使用项目的 data/logs 目录
LOG_DIR = Path(__file__).parent.parent.parent / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = str(LOG_DIR)

# 创建日志文件（按日期命名）
log_filename = os.path.join(LOG_DIR, f'memory_{datetime.now().strftime("%Y%m%d")}.log')

# 配置日志记录器
memory_logger = logging.getLogger('HumanLikeMemory')
memory_logger.setLevel(logging.DEBUG)
memory_logger.propagate = False  # 不传播到根日志器

# 文件处理器（详细日志）
file_handler = logging.FileHandler(log_filename, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%H:%M:%S'
))
memory_logger.addHandler(file_handler)

# 控制台处理器（仅显示重要信息）
CONSOLE_LOG_LEVEL = logging.WARNING  # 默认只显示警告及以上
console_handler = logging.StreamHandler()
console_handler.setLevel(CONSOLE_LOG_LEVEL)
console_handler.setFormatter(logging.Formatter('[Memory] %(message)s'))
memory_logger.addHandler(console_handler)


def get_logger():
    """获取记忆系统日志器"""
    return memory_logger


def get_log_path():
    """获取日志文件路径"""
    return log_filename


def get_log_dir():
    """获取日志目录路径"""
    return LOG_DIR
