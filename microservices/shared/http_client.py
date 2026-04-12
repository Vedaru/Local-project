"""
全局单例 HTTP 客户端 — 连接池复用，消除每请求 TCP/TLS 握手开销。

使用方式（与之前 API 完全兼容）：
    from microservices.shared.http_client import post_json, get_json, close_http_clients

设计要点：
- httpx.AsyncClient 单例，limits 配置连接池上限
- post_json / get_json 保持原有签名不变
- close_http_clients() 用于优雅关闭时清理连接池
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

import httpx

# ── 全局单例 + 连接池配置 ──────────────────────────────────────────────
_client: Optional[httpx.AsyncClient] = None

# 连接池参数：参考生产级微服务最佳实践
_POOL_MAX_CONNECTIONS = int(os.getenv("HTTP_CLIENT_POOL_MAX", "100"))
_POOL_MAX_KEEPALIVE = int(os.getenv("HTTP_CLIENT_KEEPALIVE", "20"))


def _as_json_object(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return dict(data)
    return {"data": data}


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        limits = httpx.Limits(
            max_connections=_POOL_MAX_CONNECTIONS,
            max_keepalive_connections=_POOL_MAX_KEEPALIVE,
            keepalive_expiry=30.0,
        )
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=5.0),
            limits=limits,
            trust_env=False,
            http2=True,  # 启用 HTTP/2 多路复用（服务端支持时自动协商）
        )
    return _client


async def post_json(
    url: str,
    payload: Mapping[str, Any],
    timeout: float = 15.0,
    headers: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    client = _get_client()
    response = await client.post(url, json=dict(payload), headers=dict(headers or {}), timeout=timeout)
    response.raise_for_status()
    return _as_json_object(response.json())


async def get_json(
    url: str,
    timeout: float = 5.0,
    headers: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    client = _get_client()
    response = await client.get(url, headers=dict(headers or {}), timeout=timeout)
    response.raise_for_status()
    return _as_json_object(response.json())


async def close_http_clients() -> None:
    """关闭全局连接池，释放所有 TCP 连接。建议在 shutdown 事件中调用。"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
