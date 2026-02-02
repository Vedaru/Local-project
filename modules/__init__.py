# 初始化模块
from .config import *
from .utils import *
from .llm import *
from .voice import *

# Avatar 模块（可选导入，避免未安装 PyQt6 时报错）
try:
    from .avatar import AvatarWidget, AvatarManager, AvatarBridge
except ImportError:
    pass  # PyQt6 未安装时跳过