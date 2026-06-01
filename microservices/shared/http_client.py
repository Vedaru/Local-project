"""
全局单例 HTTP 客户端 — 连接池复用，消除每请求 TCP/TLS 握手开销。

使用方式（与之前 API 完全兼容）：
    from microservices.shared.http_client import post_json, get_json, close_http_clients

设计要点：
- httpx.AsyncClient 单例，limits 配置连接池上限
- post_json / get_json 保持原有签名不变
- timeout 参数支持 float 或 httpx.Timeout，调用方可按场景精细控制各阶段超时
- close_http_clients() 用于优雅关闭时清理连接池
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional, Union

import httpx

from modules.logging_config import get_logger

_logger = get_logger("HttpClient")

# ── 全局单例 + 连接池配置 ──────────────────────────────────────────────
_client: Optional[httpx.AsyncClient] = None

# 连接池参数：参考生产级微服务最佳实践
_pool_defaults = {
    "max_connections": 100,
    "max_keepalive": 20,
}
try:
    from modules.config import get_yaml_config

    yaml_cfg = get_yaml_config()
    network_cfg = yaml_cfg.get("network", {}) if isinstance(yaml_cfg, dict) else {}
    http_cfg = network_cfg.get("http_client", {}) if isinstance(network_cfg, dict) else {}
    if isinstance(http_cfg, dict):
        _pool_defaults["max_connections"] = int(http_cfg.get("pool_max_connections", _pool_defaults["max_connections"]))
        _pool_defaults["max_keepalive"] = int(http_cfg.get("pool_max_keepalive", _pool_defaults["max_keepalive"]))
except Exception as exc:
    if isinstance(exc, (ImportError, OSError, ValueError, TypeError)):
        _logger.debug("http_client pool sizes: YAML network.http_client unavailable (%s)", exc)
    else:
        _logger.warning("http_client pool sizes: unexpected error reading YAML, using defaults", exc_info=True)

_POOL_MAX_CONNECTIONS = int(os.getenv("HTTP_CLIENT_POOL_MAX", str(_pool_defaults["max_connections"])))
_POOL_MAX_KEEPALIVE = int(os.getenv("HTTP_CLIENT_KEEPALIVE", str(_pool_defaults["max_keepalive"])))

# ── 各场景默认超时 ────────────────────────────────────────────────────
# 连接超时：TCP 握手阶段
_DEFAULT_CONNECT_TIMEOUT = 5.0
# 写超时：发送请求体阶段
_DEFAULT_WRITE_TIMEOUT = 10.0
# 连接池等待超时
_DEFAULT_POOL_TIMEOUT = 3.0


def _as_json_object(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return dict(data)
    return {"data": data}


def _resolve_timeout(timeout: Union[float, httpx.Timeout, None]) -> Union[httpx.Timeout, None]:
    """将调用方传入的 timeout 统一转为 httpx.Timeout 对象。

    - float: 所有阶段共享同一超时值（向后兼容）
    - httpx.Timeout: 直接使用，调用方可精细控制 connect/read/write/pool
    - None: 不覆盖，沿用客户端默认值
    """
    if timeout is None:
        return None
    if isinstance(timeout, httpx.Timeout):
        return timeout
    return httpx.Timeout(
        connect=min(float(timeout), _DEFAULT_CONNECT_TIMEOUT),
        read=float(timeout),
        write=min(float(timeout), _DEFAULT_WRITE_TIMEOUT),
        pool=min(float(timeout), _DEFAULT_POOL_TIMEOUT),
    )


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        limits = httpx.Limits(
            max_connections=_POOL_MAX_CONNECTIONS,
            max_keepalive_connections=_POOL_MAX_KEEPALIVE,
            keepalive_expiry=60.0,
        )
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=_DEFAULT_CONNECT_TIMEOUT,
                read=30.0,
                write=_DEFAULT_WRITE_TIMEOUT,
                pool=_DEFAULT_POOL_TIMEOUT,
            ),
            limits=limits,
            trust_env=False,
            http2=True,
        )
    return _client


async def post_json(
    url: str,
    payload: Mapping[str, Any],
    timeout: Union[float, httpx.Timeout, None] = 15.0,
    headers: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """POST JSON 并返回解析后的 dict。

    timeout 支持两种形式：
      - float: 所有超时阶段共享同一秒数（向后兼容）
      - httpx.Timeout: 精细控制各阶段，例如：
          post_json(url, data, timeout=httpx.Timeout(connect=5, read=180, write=10, pool=3))
    """
    client = _get_client()
    resolved = _resolve_timeout(timeout)
    kwargs: dict[str, Any] = {"json": dict(payload), "headers": dict(headers or {})}
    if resolved is not None:
        kwargs["timeout"] = resolved
    response = await client.post(url, **kwargs)
    response.raise_for_status()
    return _as_json_object(response.json())


async def get_json(
    url: str,
    timeout: Union[float, httpx.Timeout, None] = 5.0,
    headers: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    client = _get_client()
    resolved = _resolve_timeout(timeout)
    kwargs: dict[str, Any] = {"headers": dict(headers or {})}
    if resolved is not None:
        kwargs["timeout"] = resolved
    response = await client.get(url, **kwargs)
    response.raise_for_status()
    return _as_json_object(response.json())


async def close_http_clients() -> None:
    """关闭全局连接池，释放所有 TCP 连接。建议在 shutdown 事件中调用。"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
