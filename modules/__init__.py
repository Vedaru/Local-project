# 初始化模块 — 仅导出明确需要的符号，避免命名空间污染
from .config import (  # noqa: F401
    client,
    SOVITS_URL,
    REF_AUDIO,
    PROMPT_TEXT,
    data_dir,
    GPT_SOVITS_PATH,
    MODEL_NAME,
    SYSTEM_PROMPT,
    CONTROLLER_ENABLED,
    CONTROLLER_FAILSAFE,
    CONTROLLER_APP_WHITELIST,
)
from .utils import (  # noqa: F401
    clean_text,
    extract_entities,
    start_gpt_sovits_api,
    check_sovits_service,
    filter_emotion_tags,
)
from .llm import call_llm  # noqa: F401
from .voice import VoiceManager  # noqa: F401

# 错误处理与重试机制
from .resilience import (  # noqa: F401
    retry,
    async_retry,
    RetryStrategy,
    CircuitBreaker,
    LocalProjectError,
    ServiceUnavailableError,
    RateLimitError,
    ConfigurationError,
    safe_call,
    exception_handler,
)

# 健康检查
from .health import (  # noqa: F401
    health_checker,
    HealthStatus,
    HealthCheckResult,
    check_sovits_health,
    check_llm_api_health,
    check_chromadb_health,
    setup_default_checks,
    get_health_summary,
)

# 应用程序启动器
from .launcher import (  # noqa: F401
    app_context,
    initialize_core_services,
    get_startup_info,
    print_startup_banner,
)

# Avatar 模块（可选导入，避免未安装 PyQt6 时报错）
try:
    from .avatar import AvatarWidget, AvatarManager, AvatarBridge  # noqa: F401
except ImportError:
    pass  # PyQt6 未安装时跳过
