"""
微服务共享类型 — 统一的错误响应、请求/响应模型

所有微服务应使用此模块中定义的类型，
保证跨服务的错误格式和响应结构一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, Field


# ===================== 统一错误响应 =====================


@dataclass(frozen=True)
class ErrorResult:
    """
    统一的错误响应数据类。

    所有微服务在非 HTTPException 场景（如 circuit breaker skip,
    graceful degradation）下都应返回此结构，而非随意拼 dict。

    Attributes:
        status: 固定为 "error"
        code: 错误码（如 "circuit_open", "service_unavailable", "timeout"）
        message: 人类可读的错误描述
        request_id: 追踪 ID（如有）
        extra: 额外上下文信息
    """

    status: str = "error"
    code: str = "unknown_error"
    message: str = ""
    request_id: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化的字典。"""
        d: dict[str, Any] = {
            "status": self.status,
            "code": self.code,
            "message": self.message,
        }
        if self.request_id:
            d["request_id"] = self.request_id
        if self.extra:
            d.update(self.extra)
        return d

    @classmethod
    def service_unavailable(
        cls,
        service_name: str,
        reason: str = "",
        request_id: Optional[str] = None,
        **kwargs: Any,
    ) -> "ErrorResult":
        """快捷构造：服务不可用。"""
        return cls(
            status="error",
            code="service_unavailable",
            message=f"{service_name} unavailable{': ' + reason if reason else ''}",
            request_id=request_id,
            extra={"service": service_name, **kwargs},
        )

    @classmethod
    def circuit_open(
        cls,
        circuit_name: str,
        request_id: Optional[str] = None,
    ) -> "ErrorResult":
        """快捷构造：熔断器开启（服务被跳过）。"""
        return cls(
            status="skipped",
            code="circuit_open",
            message=f"circuit '{circuit_name}' is open, request skipped",
            request_id=request_id,
            extra={"circuit": circuit_name},
        )

    @classmethod
    def timeout(
        cls,
        operation: str,
        timeout_sec: float,
        request_id: Optional[str] = None,
    ) -> "ErrorResult":
        """快捷构造：超时。"""
        return cls(
            status="error",
            code="timeout",
            message=f"{operation} timed out after {timeout_sec}s",
            request_id=request_id,
            extra={"timeout_sec": timeout_sec},
        )

    @classmethod
    def voice_fallback(
        cls,
        mode: str,
        reason: str,
        wav_path: str = "",
        request_id: Optional[str] = None,
    ) -> "ErrorResult":
        """快捷构造：语音降级（无 TTS 输出）。"""
        return cls(
            status="skipped",
            code=f"voice_{mode}",
            message=reason,
            request_id=request_id,
            extra={"mode": mode, "wav_path": wav_path},
        )


# ===================== 通用请求/响应模型 =====================


class ChatRequest(BaseModel):
    """Gateway → Orchestrator 的聊天请求。"""

    query: str = Field(min_length=1)
    user_id: str = Field(default="anonymous")
    route_to_agent: bool = Field(default=False)


class ChatResponse(BaseModel):
    """Orchestrator → Gateway 的聊天响应。"""

    answer: str = ""
    tts: Optional[dict] = None
    expression: Optional[dict] = None
    request_id: str = ""


class ServiceHealthItem(BaseModel):
    """单个服务的健康检查项。"""

    service: str = ""
    url: str = ""
    ok: bool = False
    latency_ms: float = 0.0
    error: str = ""
