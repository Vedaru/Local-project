"""
统一的日志配置模块
将所有日志输出重定向到文件，同时在控制台显示重要信息
"""
import os
import logging
import sys
from datetime import datetime
from pathlib import Path


class ColoredFormatter(logging.Formatter):
    """日志格式化器（控制台输出）"""
    
    def format(self, record):
        # 简单格式：不使用颜色代码，直接输出
        return super().format(record)


def setup_logging(log_dir: str = None, level: int = logging.DEBUG) -> logging.Logger:
    """
    设置统一的日志系统
    
    Args:
        log_dir: 日志文件存储目录，默认为 data/logs
        level: 日志级别
    
    Returns:
        配置好的 logger 对象
    """
    # 确定日志目录
    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'logs')
    
    # 创建日志目录
    os.makedirs(log_dir, exist_ok=True)
    
    # 日志文件路径
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(log_dir, f'project_local_{timestamp}.log')
    
    # 创建或获取 logger
    logger = logging.getLogger('ProjectLocal')
    logger.setLevel(level)
    logger.propagate = False  # 禁用日志传播
    
    # 清除已有的处理器（避免重复）
    logger.handlers.clear()
    
    # 文件处理器 - 记录所有日志
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        fmt='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    
    # 控制台处理器 - 仅记录 INFO 及以上级别
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = ColoredFormatter(
        fmt='[%(name)s] %(levelname)s %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    
    # 添加处理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # 记录日志文件位置
    logger.info(f"日志文件已创建: {log_file}")
    
    return logger


# 全局 logger 实例
_logger = None


def get_logger(name: str = 'ProjectLocal') -> logging.Logger:
    """
    获取或创建 logger
    
    Args:
        name: logger 名称
    
    Returns:
        logger 对象
    """
    global _logger
    if _logger is None:
        _logger = setup_logging()
    
    # 为子模块创建独立的 logger
    if name != 'ProjectLocal':
        child_logger = logging.getLogger(f'ProjectLocal.{name}')
        # 关键：不设置 handlers，让子 logger 继承父 logger 的 handlers
        child_logger.propagate = True
        return child_logger
    return _logger


# 便捷函数
def log_debug(msg: str, **kwargs):
    """记录 DEBUG 级别日志"""
    get_logger().debug(msg, **kwargs)


def log_info(msg: str, **kwargs):
    """记录 INFO 级别日志"""
    get_logger().info(msg, **kwargs)


def log_warning(msg: str, **kwargs):
    """记录 WARNING 级别日志"""
    get_logger().warning(msg, **kwargs)


def log_error(msg: str, **kwargs):
    """记录 ERROR 级别日志"""
    get_logger().error(msg, **kwargs)


def log_critical(msg: str, **kwargs):
    """记录 CRITICAL 级别日志"""
    get_logger().critical(msg, **kwargs)
