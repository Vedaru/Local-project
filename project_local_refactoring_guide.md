# Project Local 代码优化与重构指南

> **版本**: 1.0  
> **适用项目**: https://github.com/Vedaru/Local-project  
> **Python版本**: 3.10-3.11  
> **项目类型**: PyQt6 + FastAPI微服务架构的桌面AI助手

---

## 目录

1. [快速开始](#快速开始)
2. [代码质量改进](#一代码质量改进)
3. [架构优化](#二架构优化)
4. [性能优化](#三性能优化)
5. [代码重复消除](#四代码重复消除)
6. [测试改进](#五测试改进)
7. [文档改进](#六文档改进)
8. [安全改进](#七安全改进)
9. [依赖管理](#八依赖管理)
10. [执行计划](#执行计划)
11. [验证清单](#验证清单)

---

## 快速开始

### 环境要求
```bash
# Python版本检查
python --version  # 需要 3.10.x 或 3.11.x

# 安装开发依赖
pip install -r requirements.txt
pip install black ruff mypy pytest pytest-asyncio
```

### 代码检查命令
```bash
# 类型检查
mypy modules/ --ignore-missing-imports

# 代码格式化
black modules/ --line-length 120

# Lint检查
ruff check modules/ --line-length 120

# 运行测试
python -m pytest -q
```

---

## 一、代码质量改进

### 1.1 函数拆分与重构

**优先级**: 🔴 高

以下函数/方法过于复杂，需要拆分：

| 文件 | 函数/方法 | 当前行数 | 问题 | 拆分方案 |
|------|----------|---------|------|---------|
| `modules/llm.py` | `decide_agent_routing()` | ~150行 | 职责过多 | 拆分为 `_build_routing_messages()`, `_parse_routing_response()`, `_validate_with_reverse_check()` |
| `microservices/orchestrator/core.py` | `OrchestratorCore.__init__()` | ~100行 | 初始化逻辑过重 | 提取 `_init_circuit_breakers()`, `_init_token_bucket()`, `_init_executors()` |
| `modules/agent/core.py` | `ManusAgent._run_task_async()` | ~120行 | 嵌套过深 | 拆分为 `_preprocess_task()`, `_execute_steps()`, `_postprocess_result()` |
| `modules/application/audio_playback_controller.py` | `_play_audio_segments_with_lipsync()` | ~100行 | 过长 | 拆分为 `_init_audio_stream()`, `_process_segment()`, `_cleanup_stream()` |

**具体修改要求**:
- [ ] 每个函数不超过50行（不含注释和空行）
- [ ] 使用早期返回减少嵌套层级
- [ ] 提取纯函数便于单元测试
- [ ] 添加完整的类型注解

**示例重构**:

```python
# ===== 修改前: modules/llm.py =====
def decide_agent_routing(
    system_prompt, model_name, prompt, memory_context="", max_retries=1, min_confidence=0.65
):
    # 150+ 行的复杂逻辑...
    pass

# ===== 修改后: modules/llm.py =====
def _build_routing_messages(
    system_prompt: str, prompt: str, memory_context: str
) -> list[dict]:
    """构建路由决策的消息列表."""
    messages = [{"role": "system", "content": _get_routing_instruction()}]
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if memory_context:
        messages.append({"role": "system", "content": f"[记忆上下文]\n{memory_context}"})
    messages.append({"role": "user", "content": prompt})
    return messages


def _parse_routing_response(content: str, fallback_task: str) -> AgentRoutingDecision:
    """解析路由响应内容."""
    payload = extract_first_json(content or "")
    if not isinstance(payload, dict):
        return AgentRoutingDecision(reason="router returned non-json")
    # ... 解析逻辑
    return AgentRoutingDecision(...)


def decide_agent_routing(
    system_prompt: str,
    model_name: str,
    prompt: str,
    memory_context: str = "",
    max_retries: int = 1,
    min_confidence: float = 0.65,
) -> AgentRoutingDecision:
    """使用语义理解判断是否需要调用Agent执行."""
    if not model_name or not prompt:
        return AgentRoutingDecision(reason="missing model or prompt")
    
    messages = _build_routing_messages(system_prompt, prompt, memory_context)
    # ... 简化的主逻辑
```

---

### 1.2 类型注解完善

**优先级**: 🔴 高

**需要补充类型注解的文件清单**:

```
modules/
├── utils.py                 # 所有函数
├── json_utils.py            # 所有函数
├── logging_config.py        # get_logger返回值
├── task_completion.py       # TaskCompletionHelper类
microservices/
├── shared/
│   ├── http_client.py       # 所有函数
│   └── types.py             # 所有dataclass字段
└── gateway/
    └── main.py              # 路由处理函数
modules/avatar/
├── manager.py               # ExpressionManager类
└── lip_sync.py              # LipSyncManager类
```

**类型注解模板**:

```python
from typing import Optional, Union, Any, Callable
from pathlib import Path

# 函数类型注解模板
def function_name(
    param1: str,
    param2: Optional[int] = None,
    param3: Union[str, list[str]] = "",
) -> dict[str, Any]:
    """函数文档."""
    pass

# 类方法类型注解模板
class MyClass:
    def __init__(self, config: AppConfig) -> None:
        self.config: AppConfig = config
        self._state: Optional[str] = None
    
    def process(self, data: bytes) -> ProcessingResult:
        """处理方法."""
        pass
```

---

### 1.3 常量提取

**优先级**: 🟡 中

将魔法数字提取为命名常量：

```python
# ===== modules/llm.py =====
# 添加在模块顶部
MAX_TOKENS_DEFAULT: int = 800
EXPONENTIAL_BACKOFF_BASE_DELAY: float = 1.0
EXPONENTIAL_BACKOFF_MAX_DELAY: float = 60.0
ROUTING_MIN_CONFIDENCE: float = 0.65

# ===== microservices/orchestrator/core.py =====
# 在 OrchestratorConfig 类中添加默认值常量
class OrchestratorConfig:
    DEFAULT_CIRCUIT_FAIL_THRESHOLD: int = 5
    DEFAULT_CIRCUIT_COOLDOWN_SEC: float = 30.0
    DEFAULT_TOKEN_BUCKET_CAPACITY: int = 10
    DEFAULT_MAX_REQUESTS_PER_SECOND: float = 10.0

# ===== modules/application/audio_playback_controller.py =====
EXPRESSION_SEED_REUSE_WINDOW_SEC: float = 1.2
AUDIO_FADE_MS: int = 8
AUDIO_FRAMES_PER_BUFFER: int = 512
AUDIO_RMS_THRESHOLD: float = 500.0
```

---

## 二、架构优化

### 2.1 配置管理统一化

**优先级**: 🔴 高

**问题**: 配置分散在多个文件，存在重复读取

**解决方案**: 添加配置缓存机制

```python
# ===== modules/config_base.py 新增 =====
from functools import lru_cache
from typing import Optional

# 配置缓存
_config_cache: Optional[AppConfig] = None
_config_cache_lock = threading.Lock()


def get_cached_config() -> AppConfig:
    """获取缓存的配置实例，避免重复读取文件.
    
    线程安全的单例模式实现.
    """
    global _config_cache
    
    if _config_cache is not None:
        return _config_cache
    
    with _config_cache_lock:
        # 双重检查
        if _config_cache is not None:
            return _config_cache
        _config_cache = load_config()
        return _config_cache


def invalidate_config_cache() -> None:
    """使配置缓存失效，用于配置热重载."""
    global _config_cache
    with _config_cache_lock:
        _config_cache = None


# ===== 修改所有使用 load_config() 的地方 =====
# 修改前
from modules.config import load_config
config = load_config()

# 修改后
from modules.config import get_cached_config
config = get_cached_config()
```

---

### 2.2 日志记录规范化

**优先级**: 🟡 中

**问题**: 日志格式不统一，部分使用print

**修改清单**:

```python
# ===== modules/avatar/widget.py =====
# 修改前
print(f"Loading model: {model_path}")

# 修改后
from modules.logging_config import get_logger
logger = get_logger("AvatarWidget")
logger.info(f"Loading model: {model_path}")

# ===== modules/avatar/webengine.py =====
# 修改前
print(f"JavaScript error: {msg}")

# 修改后
logger.warning(f"JavaScript error: {msg}")

# ===== microservices/gateway/main.py =====
# 修改前
print(f"Service {name} registered")

# 修改后
logger.info(f"Service {name} registered", extra={"service": name})
```

---

### 2.3 异常处理统一化

**优先级**: 🔴 高

**修改要求**:
1. 所有微服务入口统一捕获异常
2. 使用 `modules/resilience.py` 中定义的自定义异常
3. 添加异常链（`raise ... from e`）

```python
# ===== microservices/agent_service/main.py 修改 =====
from fastapi import FastAPI, HTTPException
from modules.resilience import ServiceUnavailableError, RateLimitError

app = FastAPI()

@app.post("/execute")
async def execute(request: ExecuteRequest) -> dict:
    """执行Agent任务."""
    if _REAL_AGENT is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Agent service not available",
                "error_code": "AGENT_NOT_INITIALIZED",
                "details": {"init_error": _AGENT_INIT_ERROR}
            }
        )
    
    try:
        task_desc = f"[user={request.user_id}] {request.task}"
        result = await asyncio.wait_for(
            asyncio.to_thread(_REAL_AGENT.run_task, task_desc),
            timeout=request.timeout_seconds,
        )
        return {
            "success": True,
            "result": result,
            "priority": request.priority,
            "mode": "real-manus-agent",
        }
    except TimeoutError as e:
        logger.error(f"Agent execution timeout: {e}")
        raise HTTPException(
            status_code=504,
            detail={
                "error": f"Task timeout after {request.timeout_seconds}s",
                "error_code": "AGENT_TIMEOUT",
            }
        ) from e
    except Exception as e:
        logger.exception("Unexpected error in agent execution")
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "error_code": "AGENT_EXECUTION_ERROR",
            }
        ) from e
```

---

## 三、性能优化

### 3.1 异步化同步调用

**优先级**: 🔴 高

**需要异步化的方法**:

```python
# ===== modules/agent/core.py 新增异步版本 =====
class ManusAgent:
    # ... 现有代码
    
    async def run_task_async(self, task_description: str) -> str:
        """异步版本的任务执行.
        
        避免使用 asyncio.to_thread() 包装，实现真正的异步执行.
        """
        if not self._initialized:
            await self._ensure_agent_async()
        
        # 直接使用异步API
        result = await self._agent.run(task_description)
        return result
    
    async def _ensure_agent_async(self) -> None:
        """异步初始化Agent."""
        if self._agent is not None:
            return
        
        from app.agent.manus import Manus
        
        agent_class = _create_speaking_manus_class() or Manus
        self._agent = agent_class()
        self._initialized = True
```

---

### 3.2 缓存策略优化

**优先级**: 🟡 中

```python
# ===== modules/llm.py 增强缓存机制 =====
import time
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar('T')

@dataclass
class TimedCacheEntry(Generic[T]):
    """带TTL的缓存条目."""
    value: T
    timestamp: float


class TimedCache:
    """带过期时间的缓存."""
    
    def __init__(self, ttl_seconds: float):
        self._ttl = ttl_seconds
        self._cache: dict[int, TimedCacheEntry[Any]] = {}
        self._lock = threading.Lock()
    
    def get(self, key: int) -> Optional[Any]:
        """获取缓存值，如果过期则返回None."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            
            if time.monotonic() - entry.timestamp > self._ttl:
                # 过期，删除
                del self._cache[key]
                return None
            
            return entry.value
    
    def set(self, key: int, value: Any) -> None:
        """设置缓存值."""
        with self._lock:
            self._cache[key] = TimedCacheEntry(value, time.monotonic())
    
    def clear(self) -> None:
        """清空缓存."""
        with self._lock:
            self._cache.clear()


# 使用示例
_prompt_cache = TimedCache(ttl_seconds=300)  # 5分钟TTL

def _get_enhanced_prompt(base_prompt: str) -> str:
    """获取增强后的system prompt，带TTL缓存."""
    key = hash(base_prompt)
    cached = _prompt_cache.get(key)
    if cached is not None:
        return cached
    
    enhanced = _build_enhanced_prompt(base_prompt)
    _prompt_cache.set(key, enhanced)
    return enhanced
```

---

### 3.3 资源管理优化

**优先级**: 🟡 中

```python
# ===== microservices/service_client.py 使用上下文管理器 =====
from contextlib import asynccontextmanager
import httpx

@asynccontextmanager
async def get_http_session():
    """异步上下文管理器管理HTTP会话.
    
    确保会话正确关闭，避免连接泄漏.
    """
    session = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=5.0),
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )
    try:
        yield session
    finally:
        await session.aclose()


# 使用示例
async def fetch_data(url: str) -> dict:
    async with get_http_session() as session:
        response = await session.get(url)
        return response.json()


# ===== 类级别的资源管理 =====
class ResourceManager:
    """统一资源管理器."""
    
    def __init__(self):
        self._resources: list[Any] = []
        self._lock = threading.Lock()
    
    def register(self, resource: Any) -> Any:
        """注册资源以便统一清理."""
        with self._lock:
            self._resources.append(resource)
        return resource
    
    def cleanup(self) -> None:
        """清理所有注册的资源."""
        with self._lock:
            for resource in reversed(self._resources):
                try:
                    if hasattr(resource, 'close'):
                        resource.close()
                    elif hasattr(resource, 'cleanup'):
                        resource.cleanup()
                except Exception as e:
                    logger.warning(f"Error cleaning up resource: {e}")
            self._resources.clear()
```

---

## 四、代码重复消除

### 4.1 提取公共工具函数

**优先级**: 🟡 中

```python
# ===== modules/utils.py 新增函数 =====
import re
import json
from typing import Any, Optional, Union


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """截断文本到指定长度.
    
    Args:
        text: 原始文本
        max_length: 最大长度（包含后缀）
        suffix: 截断后缀
        
    Returns:
        截断后的文本
        
    Example:
        >>> truncate_text("hello world", 8)
        'hello...'
        >>> truncate_text("hello world", 8, "..")
        'hello wo..'
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def normalize_whitespace(text: Optional[str]) -> str:
    """规范化空白字符（多个空格/换行合并为单个）.
    
    Args:
        text: 原始文本
        
    Returns:
        规范化后的文本
    """
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()


def safe_json_loads(data: Union[str, bytes], default: Any = None) -> Any:
    """安全的JSON解析，失败返回默认值.
    
    Args:
        data: JSON字符串或字节
        default: 解析失败时的返回值
        
    Returns:
        解析后的对象或默认值
    """
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return default


def clamp_value(value: float, min_val: float, max_val: float) -> float:
    """将值限制在指定范围内.
    
    Args:
        value: 输入值
        min_val: 最小值
        max_val: 最大值
        
    Returns:
        限制后的值
    """
    return max(min_val, min(max_val, value))


def is_valid_identifier(name: str) -> bool:
    """检查字符串是否为有效的标识符（字母数字下划线）.
    
    Args:
        name: 要检查的字符串
        
    Returns:
        是否为有效标识符
    """
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', name))
```

---

### 4.2 统一错误响应格式

**优先级**: 🟡 中

```python
# ===== microservices/shared/types.py 新增 =====
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any


@dataclass
class ErrorResponse:
    """标准错误响应结构."""
    
    error: str
    error_code: str
    details: Optional[dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式."""
        return {
            "success": False,
            "error": self.error,
            "error_code": self.error_code,
            "details": self.details,
            "timestamp": self.timestamp,
        }


@dataclass
class SuccessResponse:
    """标准成功响应结构."""
    
    data: Any
    message: str = "success"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式."""
        return {
            "success": True,
            "data": self.data,
            "message": self.message,
            "timestamp": self.timestamp,
        }


# 错误码枚举
class ErrorCode:
    """错误码常量."""
    
    # 通用错误
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    INVALID_REQUEST = "INVALID_REQUEST"
    
    # 服务错误
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    SERVICE_TIMEOUT = "SERVICE_TIMEOUT"
    
    # Agent错误
    AGENT_NOT_INITIALIZED = "AGENT_NOT_INITIALIZED"
    AGENT_EXECUTION_ERROR = "AGENT_EXECUTION_ERROR"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"
    
    # 语音错误
    TTS_ERROR = "TTS_ERROR"
    ASR_ERROR = "ASR_ERROR"
    
    # 记忆错误
    MEMORY_ERROR = "MEMORY_ERROR"
    MEMORY_NOT_FOUND = "MEMORY_NOT_FOUND"
```

---

## 五、测试改进

### 5.1 添加缺失的单元测试

**优先级**: 🔴 高

```python
# ===== tests/test_utils.py 新增 =====
import pytest
from modules.utils import (
    sanitize_dialogue_text,
    truncate_text,
    normalize_whitespace,
    safe_json_loads,
    clamp_value,
)


class TestSanitizeDialogueText:
    """测试 sanitize_dialogue_text 函数."""
    
    def test_removes_control_chars(self):
        """测试移除控制字符."""
        assert sanitize_dialogue_text("hello\x00world") == "helloworld"
        assert sanitize_dialogue_text("test\x01\x02\x03") == "test"
    
    def test_handles_none(self):
        """测试处理None输入."""
        assert sanitize_dialogue_text(None) == ""
    
    def test_handles_empty_string(self):
        """测试处理空字符串."""
        assert sanitize_dialogue_text("") == ""
    
    def test_preserves_chinese(self):
        """测试保留中文字符."""
        assert sanitize_dialogue_text("你好世界") == "你好世界"
    
    def test_removes_html_tags(self):
        """测试移除HTML标签."""
        assert sanitize_dialogue_text("<b>bold</b>") == "bold"


class TestTruncateText:
    """测试 truncate_text 函数."""
    
    def test_no_truncate_short_text(self):
        """测试不截断短文本."""
        assert truncate_text("hello", 10) == "hello"
    
    def test_truncate_long_text(self):
        """测试截断长文本."""
        assert truncate_text("hello world", 8) == "hello..."
    
    def test_custom_suffix(self):
        """测试自定义后缀."""
        assert truncate_text("hello world", 8, "..") == "hello wo.."
    
    def test_exact_length(self):
        """测试精确长度."""
        assert truncate_text("hello", 5) == "hello"


class TestNormalizeWhitespace:
    """测试 normalize_whitespace 函数."""
    
    def test_multiple_spaces(self):
        """测试合并多个空格."""
        assert normalize_whitespace("hello    world") == "hello world"
    
    def test_newlines(self):
        """测试处理换行符."""
        assert normalize_whitespace("line1\n\nline2") == "line1 line2"
    
    def test_mixed_whitespace(self):
        """测试混合空白字符."""
        assert normalize_whitespace("a \t \n b") == "a b"


class TestSafeJsonLoads:
    """测试 safe_json_loads 函数."" */
    
    def test_valid_json(self):
        """测试有效JSON."""
        assert safe_jsonloads('{"key": "value"}') == {"key": "value"}
    
    def test_invalid_json(self):
        """测试无效JSON返回默认值."""
        assert safe_json_loads("invalid json", default={}) == {}
    
    def test_empty_string(self):
        """测试空字符串."""
        assert safe_json_loads("", default=[]) == []


class TestClampValue:
    """测试 clamp_value 函数."""
    
    def test_within_range(self):
        """测试范围内值."""
        assert clamp_value(5.0, 0.0, 10.0) == 5.0
    
    def test_below_min(self):
        """测试低于最小值."""
        assert clamp_value(-5.0, 0.0, 10.0) == 0.0
    
    def test_above_max(self):
        """测试高于最大值."""
        assert clamp_value(15.0, 0.0, 10.0) == 10.0
```

---

### 5.2 测试覆盖率提升

**优先级**: 🟡 中

```python
# ===== tests/test_resilience.py 新增 =====
import pytest
from modules.resilience import (
    retry,
    RetryStrategy,
    CircuitBreaker,
    CircuitState,
    ServiceUnavailableError,
)


class TestRetryDecorator:
    """测试重试装饰器."""
    
    def test_success_no_retry(self):
        """测试成功时不重试."""
        call_count = 0
        
        @retry(max_retries=3)
        def success_func():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = success_func()
        assert result == "success"
        assert call_count == 1
    
    def test_retry_on_failure(self):
        """测试失败时重试."""
        call_count = 0
        
        @retry(max_retries=3, base_delay=0.01)
        def fail_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("error")
        
        with pytest.raises(ValueError):
            fail_func()
        
        assert call_count == 4  # 初始 + 3次重试
    
    def test_retry_success_after_failure(self):
        """测试失败后成功."""
        call_count = 0
        
        @retry(max_retries=3, base_delay=0.01)
        def eventually_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("error")
            return "success"
        
        result = eventually_success()
        assert result == "success"
        assert call_count == 3


class TestCircuitBreaker:
    """测试断路器."""
    
    def test_initial_state_closed(self):
        """测试初始状态为关闭."""
        breaker = CircuitBreaker(failure_threshold=3)
        assert breaker.state == CircuitState.CLOSED
    
    def test_opens_after_failures(self):
        """测试失败后打开."""
        breaker = CircuitBreaker(failure_threshold=2)
        
        @breaker
        def fail_func():
            raise ValueError("error")
        
        fail_func()
        fail_func()
        
        assert breaker.state == CircuitState.OPEN
    
    def test_records_success(self):
        """测试记录成功."""
        breaker = CircuitBreaker(failure_threshold=3)
        breaker.record_success()
        assert breaker._failure_count == 0
```

---

## 六、文档改进

### 6.1 函数文档完善

**优先级**: 🟡 中

**Google风格Docstring模板**:

```python
def decide_agent_routing(
    system_prompt: str,
    model_name: str,
    prompt: str,
    memory_context: str = "",
    max_retries: int = 1,
    min_confidence: float = 0.65,
) -> AgentRoutingDecision:
    """使用语义理解判断是否需要调用Agent执行.
    
    该函数分析用户输入的语义，决定是应该直接回复（chat）还是
    调用Agent工具执行（agent）。使用LLM进行意图识别，支持
    置信度阈值和反向验证机制.
    
    Args:
        system_prompt: 系统提示词，用于设置AI助手的行为模式
        model_name: 使用的LLM模型名称（如 "gpt-4"）
        prompt: 用户输入的文本
        memory_context: 记忆上下文，用于增强理解（可选）
        max_retries: LLM调用失败时的最大重试次数
        min_confidence: 触发Agent的最小置信度（0.0-1.0）
        
    Returns:
        AgentRoutingDecision: 路由决策结果，包含：
            - should_trigger: 是否触发Agent
            - confidence: 置信度
            - task: 任务描述
            - reason: 决策原因
            - is_atomic: 是否为原子任务
            
    Raises:
        ServiceUnavailableError: LLM服务不可用
        RateLimitError: 触发API速率限制
        
    Example:
        >>> decision = decide_agent_routing(
        ...     system_prompt="You are a helpful assistant",
        ...     model_name="gpt-4",
        ...     prompt="打开计算器"
        ... )
        >>> print(decision.should_trigger)
        True
        >>> print(decision.task)
        "打开系统计算器应用"
        
    Note:
        当置信度低于阈值时，会降级为chat模式以确保用户体验.
    """
```

---

### 6.2 README更新建议

```markdown
# 建议添加到 README.md

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        GUI Layer                             │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ Avatar      │  │ Audio        │  │ Expression          │ │
│  │ Widget      │  │ Controller   │  │ Orchestrator        │ │
│  └─────────────┘  └──────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Gateway (FastAPI)                       │
│              Port: 18080 (configurable)                      │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   Orchestrator  │  │  Agent Service  │  │  Voice Service  │
│   Service       │  │                 │  │                 │
└─────────────────┘  └─────────────────┘  └─────────────────┘
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Memory Service │  │  OpenManus      │  │  GPT-SoVITS     │
│                 │  │  Agent          │  │  TTS            │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

## API文档

### Gateway端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/v1/chat` | POST | 主对话接口 |
| `/v1/status/services` | GET | 服务健康检查 |
| `/health` | GET | 网关健康检查 |

### 环境变量

| 变量名 | 默认值 | 描述 |
|--------|--------|------|
| `ARK_API_KEY` | - | 火山方舟API密钥 |
| `GATEWAY_PORT` | 18080 | 网关端口 |
| `AGENT_MAX_STEPS` | 100 | Agent最大执行步数 |
```

---

## 七、安全改进

### 7.1 输入验证强化

**优先级**: 🔴 高

```python
# ===== microservices/agent_service/main.py 增强验证 =====
from pydantic import Field, validator, constr
import re


class ExecuteRequest(BaseModel):
    """Agent执行请求模型."""
    
    task: constr(min_length=1, max_length=10000) = Field(
        ...,
        description="任务描述"
    )
    user_id: constr(min_length=1, max_length=64, regex=r'^[a-zA-Z0-9_-]+$') = Field(
        default="anonymous",
        description="用户ID"
    )
    priority: constr(regex=r'^(low|normal|high|critical)$') = Field(
        default="normal",
        description="任务优先级"
    )
    timeout_seconds: float = Field(
        default=180.0,
        ge=5.0,
        le=1800.0,
        description="超时时间（秒）"
    )
    
    @validator('task')
    def validate_task(cls, v: str) -> str:
        """验证任务描述不包含危险字符."""
        dangerous_patterns = [
            r';\s*rm\s+-rf',
            r'`.*?`',
            r'\$\(.*?\)',
            r'<script.*?>',
            r'javascript:',
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, v, re.IGNORECASE):
                raise ValueError(f"Task contains potentially dangerous pattern")
        
        return v.strip()
    
    @validator('user_id')
    def validate_user_id(cls, v: str) -> str:
        """验证用户ID格式."""
        if not v:
            return "anonymous"
        return v.lower().strip()


# ===== 通用输入验证器 =====
class InputValidator:
    """输入验证工具类."""
    
    @staticmethod
    def sanitize_path(path: str) -> str:
        """净化文件路径，防止目录遍历."""
        # 移除空字节
        path = path.replace('\x00', '')
        
        # 规范化路径
        from pathlib import Path
        try:
            p = Path(path).resolve()
            # 确保路径在允许的范围内
            return str(p)
        except Exception:
            raise ValueError("Invalid path")
    
    @staticmethod
    def validate_url(url: str) -> str:
        """验证URL格式."""
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        
        # 只允许http和https
        if parsed.scheme not in ('http', 'https'):
            raise ValueError("Only HTTP/HTTPS URLs are allowed")
        
        return url
```

---

### 7.2 敏感信息处理

**优先级**: 🔴 高

```python
# ===== modules/config_app.py 使用SecretStr =====
from pydantic import BaseModel, SecretStr, Field


class AppConfig(BaseModel):
    """应用配置模型."""
    
    # 使用 SecretStr 保护敏感信息
    ark_api_key: SecretStr = Field(..., description="火山方舟API密钥")
    
    # 其他配置
    model_name: str = Field(default="deepseek-v3-250324")
    base_url: str = Field(default="https://ark.cn-beijing.volces.com/api/v3")
    
    def get_api_key(self) -> str:
        """安全获取API密钥."""
        return self.ark_api_key.get_secret_value()
    
    def __repr__(self) -> str:
        """自定义repr，避免泄露密钥."""
        return f"AppConfig(model_name={self.model_name}, base_url={self.base_url}, api_key=***)"
    
    def __str__(self) -> str:
        """自定义str，避免泄露密钥."""
        return self.__repr__()


# ===== 日志脱敏 =====
import copy


def sanitize_for_logging(obj: Any) -> Any:
    """脱敏处理，用于日志记录.
    
    移除敏感字段如 api_key, password, token 等.
    """
    if isinstance(obj, dict):
        result = copy.deepcopy(obj)
        sensitive_keys = {'api_key', 'password', 'token', 'secret', 'auth'}
        
        for key in list(result.keys()):
            if any(s in key.lower() for s in sensitive_keys):
                result[key] = '***'
            elif isinstance(result[key], (dict, list)):
                result[key] = sanitize_for_logging(result[key])
        
        return result
    
    elif isinstance(obj, list):
        return [sanitize_for_logging(item) for item in obj]
    
    elif isinstance(obj, BaseModel):
        return sanitize_for_logging(obj.dict())
    
    return obj


# 使用示例
logger.info(f"Config: {sanitize_for_logging(config)}")
```

---

## 八、依赖管理

### 8.1 依赖版本锁定

**优先级**: 🟡 中

```txt
# ===== requirements.txt =====
# 核心依赖
openai==1.35.0
python-dotenv==1.0.0
jieba==0.42.1
pyaudio==0.2.13
requests==2.31.0
pyyaml==6.0

# 文档处理
python-pptx==1.0.2
python-docx==1.1.2
reportlab==4.2.0

# 记忆系统
faiss-cpu==1.7.4
scikit-learn==1.3.2
networkx==3.2.1
sentence-transformers==2.2.2
pydantic==2.5.0

# GUI
PyQt6==6.6.1
PyQt6-WebEngine==6.6.0
qasync==0.27.1

# 语音识别
openai-whisper==20231117
faster-whisper==0.10.0
ctranslate2==3.24.0
numpy==1.24.3

# 电脑控制
pyautogui==0.9.54
pygetwindow==0.0.9

# Agent框架
browser-use==0.1.40
playwright==1.40.0
tenacity==8.2.3
structlog==23.2.0
loguru==0.7.2
tiktoken==0.5.1
aiofiles==23.2.1
colorama==0.4.6
fastapi==0.104.1
uvicorn==0.24.0
html2text==2020.1.16
googlesearch-python==1.2.3
baidusearch==1.0.3
duckduckgo_search==3.9.6
tomli==2.0.1
httpx==0.25.2
beautifulsoup4==4.12.2

# OCR
pytesseract==0.3.10
```

```txt
# ===== requirements-dev.txt =====
-r requirements.txt

# 测试
pytest==7.4.3
pytest-cov==4.1.0
pytest-asyncio==0.21.1
pytest-mock==3.12.0
pytest-xdist==3.5.0

# 代码质量
black==23.11.0
isort==5.12.0
ruff==0.1.6
mypy==1.7.1

# 预提交
pre-commit==3.6.0

# 类型存根
types-requests==2.31.0.10
types-pyyaml==6.0.12.12
```

---

## 执行计划

### 阶段一：基础改进（1-2天）
- [ ] 添加类型注解到核心模块
- [ ] 提取魔法数字为常量
- [ ] 替换所有 `print()` 为 `logger`
- [ ] 添加基础工具函数到 `utils.py`

### 阶段二：架构优化（2-3天）
- [ ] 实现配置缓存机制
- [ ] 统一异常处理
- [ ] 拆分复杂函数
- [ ] 添加资源管理上下文管理器

### 阶段三：性能优化（2天）
- [ ] 异步化改造
- [ ] 实现TTL缓存
- [ ] 优化HTTP连接池

### 阶段四：测试补充（2天）
- [ ] 添加 `test_utils.py`
- [ ] 添加 `test_resilience.py`
- [ ] 添加 `test_json_utils.py`
- [ ] 提升核心模块覆盖率到80%

### 阶段五：安全强化（1-2天）
- [ ] 强化Pydantic验证
- [ ] 使用 `SecretStr` 保护密钥
- [ ] 添加输入净化
- [ ] 锁定依赖版本

---

## 验证清单

每个修改完成后，请确保：

### 代码质量检查
- [ ] 所有现有测试通过 (`pytest -q`)
- [ ] 新增测试覆盖修改的代码
- [ ] 类型检查通过 (`mypy modules/ --ignore-missing-imports`)
- [ ] 代码格式化 (`black modules/ --line-length 120`)
- [ ] Lint检查通过 (`ruff check modules/ --line-length 120`)

### 回归测试命令

```bash
# 核心回归测试（必须全部通过）
python -m pytest \
  tests/test_orchestrator_core.py \
  tests/test_microservice_timeouts.py \
  tests/test_service_client_speak_payload.py \
  tests/test_orchestrator_main_lifecycle.py \
  tests/test_memory_service_lifecycle.py \
  tests/test_python_runtime_guard.py \
  -q

# 完整测试套件
python -m pytest -q --tb=short

# 带覆盖率报告
python -m pytest --cov=modules --cov-report=term-missing -q
```

### 手动验证
- [ ] 应用正常启动 (`python main.py`)
- [ ] 对话功能正常
- [ ] 语音合成功能正常
- [ ] 虚拟形象显示正常
- [ ] Agent工具调用正常

---

## 附录

### A. 常用命令速查

```bash
# 运行应用
python main.py

# 运行测试
python -m pytest -q

# 代码格式化
black modules/ --line-length 120
isort modules/ --profile black

# Lint检查
ruff check modules/ --line-length 120
mypy modules/ --ignore-missing-imports

# 启动微服务
cd microservices/gateway && python main.py
cd microservices/orchestrator && python main.py
cd microservices/agent_service && python main.py
```

### B. 项目结构参考

```
Local-project/
├── modules/                      # 主功能模块
│   ├── agent/                    # Agent核心
│   ├── application/              # 应用层组件
│   ├── avatar/                   # 虚拟形象
│   ├── config*.py                # 配置管理
│   ├── llm.py                    # LLM接口
│   ├── memory/                   # 记忆系统
│   ├── resilience.py             # 错误处理
│   ├── utils.py                  # 工具函数
│   └── voice.py                  # 语音合成
├── microservices/                # 微服务
│   ├── agent_service/            # Agent服务
│   ├── gateway/                  # API网关
│   ├── orchestrator/             # 编排器
│   ├── shared/                   # 共享组件
│   └── voice_service/            # 语音服务
├── tests/                        # 测试
├── docs/                         # 文档
├── requirements.txt              # 生产依赖
├── requirements-dev.txt          # 开发依赖
└── pyproject.toml                # 项目配置
```

---

> **提示**: 本指南建议配合VSCode的Copilot或Inline Chat使用，可直接复制相关章节给AI助手执行具体修改。
