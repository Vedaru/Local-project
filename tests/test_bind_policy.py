"""Tests for microservices.shared.bind_policy."""

from __future__ import annotations

import pytest

from microservices.shared.bind_policy import (
    bind_requires_gateway_api_key,
    normalize_bind_host,
    validate_gateway_bind_and_api_key,
)


def test_normalize_bind_host_defaults() -> None:
    assert normalize_bind_host(None) == "127.0.0.1"
    assert normalize_bind_host("") == "127.0.0.1"
    assert normalize_bind_host("  10.0.0.5  ") == "10.0.0.5"


def test_bind_requires_gateway_api_key_loopback() -> None:
    assert bind_requires_gateway_api_key("127.0.0.1") is False
    assert bind_requires_gateway_api_key("localhost") is False
    assert bind_requires_gateway_api_key("::1") is False


def test_bind_requires_gateway_api_key_exposed() -> None:
    assert bind_requires_gateway_api_key("0.0.0.0") is True
    assert bind_requires_gateway_api_key("::") is True
    assert bind_requires_gateway_api_key("192.168.1.10") is True


def test_validate_raises_on_lan_without_key() -> None:
    with pytest.raises(RuntimeError, match="not loopback"):
        validate_gateway_bind_and_api_key(bind_host="0.0.0.0", api_key="")


def test_validate_ok_on_lan_with_key() -> None:
    validate_gateway_bind_and_api_key(bind_host="0.0.0.0", api_key="secret")


def test_validate_ok_loopback_without_key() -> None:
    validate_gateway_bind_and_api_key(bind_host="127.0.0.1", api_key="")
