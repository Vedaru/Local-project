"""
Bind-address policy for microservices exposed on the network.

When the gateway (or other services) listen on a non-loopback address, an API key
should be configured to avoid exposing unauthenticated AI control to the LAN.
"""

from __future__ import annotations


def normalize_bind_host(raw: str | None) -> str:
    """Return a non-empty bind host string; default loopback."""
    h = (raw or "").strip()
    return h if h else "127.0.0.1"


def bind_requires_gateway_api_key(bind_host: str) -> bool:
    """True if listening on this host implies exposure beyond loopback."""
    h = normalize_bind_host(bind_host).lower()
    if h in ("127.0.0.1", "localhost", "::1", "[::1]"):
        return False
    # 0.0.0.0 / :: / specific LAN or public IPs — require authentication
    return True


def validate_gateway_bind_and_api_key(*, bind_host: str, api_key: str) -> None:
    """Raise RuntimeError if policy is violated."""
    key = (api_key or "").strip()
    if bind_requires_gateway_api_key(bind_host) and not key:
        bh = normalize_bind_host(bind_host)
        raise RuntimeError(
            "Gateway bind address "
            f"{bh!r} is not loopback; set gateway.api_key or GATEWAY_API_KEY "
            "before exposing the service on the network."
        )
