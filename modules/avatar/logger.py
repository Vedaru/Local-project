"""
Avatar 日志模块 - 统一的日志管理
"""

import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional


class AvatarLogger:
    """Avatar 专用日志器"""
    
    _instance: Optional['AvatarLogger'] = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if AvatarLogger._initialized:
            return
        AvatarLogger._initialized = True
        
        # 创建日志目录
        self.log_dir = Path(__file__).parent.parent.parent / "data" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 日志文件名（按日期）
        log_filename = f"avatar_{datetime.now().strftime('%Y%m%d')}.log"
        self.log_file = self.log_dir / log_filename
        
        # 创建 logger
        self.logger = logging.getLogger("Avatar")
        self.logger.setLevel(logging.DEBUG)
        
        # 清除已有的处理器
        self.logger.handlers.clear()
        
        # 文件处理器
        file_handler = logging.FileHandler(
            self.log_file, 
            encoding='utf-8',
            mode='a'
        )
        file_handler.setLevel(logging.DEBUG)
        
        # 格式化器
        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        
        # 记录启动日志
        self.info("=" * 50)
        self.info("Avatar Logger initialized")
        self.info(f"Log file: {self.log_file}")
    
    def debug(self, message: str):
        """调试日志"""
        self.logger.debug(message)
    
    def info(self, message: str):
        """信息日志"""
        self.logger.info(message)
    
    def warning(self, message: str):
        """警告日志"""
        self.logger.warning(message)
    
    def error(self, message: str):
        """错误日志"""
        self.logger.error(message)
    
    def js_log(self, level: str, message: str, line_number: int):
        """JavaScript 日志"""
        self.logger.debug(f"[JS {level}] {message} (line {line_number})")


# 全局日志器实例
_logger: Optional[AvatarLogger] = None


def get_logger() -> AvatarLogger:
    """获取全局日志器"""
    global _logger
    if _logger is None:
        _logger = AvatarLogger()
    return _logger


# 便捷函数
def log_debug(message: str):
    get_logger().debug(message)

def log_info(message: str):
    get_logger().info(message)

def log_warning(message: str):
    get_logger().warning(message)

def log_error(message: str):
    get_logger().error(message)

def log_js(level: str, message: str, line_number: int):
    get_logger().js_log(level, message, line_number)
