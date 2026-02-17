# 初始化模块
from .config import *  # noqa: F401,F403
from .utils import *   # noqa: F401,F403
from .llm import *     # noqa: F401,F403
from .voice import *   # noqa: F401,F403

# Avatar 模块（可选导入，避免未安装 PyQt6 时报错）
try:
    from .avatar import AvatarWidget, AvatarManager, AvatarBridge  # noqa: F401
except ImportError:
    pass  # PyQt6 未安装时跳过
