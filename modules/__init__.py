# 初始化模块 — 仅导出明确需要的符号，避免命名空间污染
from .config import (  # noqa: F401
    CONTROLLER_APP_WHITELIST,
    CONTROLLER_ENABLED,
    CONTROLLER_FAILSAFE,
    GPT_SOVITS_PATH,
    MODEL_NAME,
    PROMPT_TEXT,
    REF_AUDIO,
    SOVITS_URL,
    SYSTEM_PROMPT,
    client,
    data_dir,
)

# 健康检查
from .health import (  # noqa: F401
    HealthCheckResult,
    HealthStatus,
    check_chromadb_health,
    check_llm_api_health,
    check_sovits_health,
    get_health_summary,
    health_checker,
    setup_default_checks,
)

# 应用程序启动器
from .launcher import (  # noqa: F401
    app_context,
    get_startup_info,
    initialize_core_services,
    print_startup_banner,
)
from .llm import call_llm  # noqa: F401

# 错误处理与重试机制
from .resilience import (  # noqa: F401
    CircuitBreaker,
    ConfigurationError,
    LocalProjectError,
    RateLimitError,
    RetryStrategy,
    ServiceUnavailableError,
    async_retry,
    exception_handler,
    retry,
    safe_call,
)
from .utils import (  # noqa: F401
    check_sovits_service,
    clean_text,
    extract_entities,
    filter_emotion_tags,
    start_gpt_sovits_api,
)
from .voice import VoiceManager  # noqa: F401

# Avatar 模块（可选导入，避免未安装 PyQt6 时报错）
try:
    from .avatar import AvatarBridge, AvatarManager, AvatarWidget  # noqa: F401
except ImportError:
    pass  # PyQt6 未安装时跳过
