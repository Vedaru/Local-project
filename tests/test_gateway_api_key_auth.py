"""Table-driven tests: Gateway /v1 API key middleware."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def gateway_with_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GATEWAY_API_KEY", "test-secret-key")
    import microservices.gateway.main as gw

    yield importlib.reload(gw)
    monkeypatch.delenv("GATEWAY_API_KEY", raising=False)
    importlib.reload(gw)


def test_health_skips_auth_when_api_key_configured(gateway_with_api_key) -> None:
    client = TestClient(gateway_with_api_key.app)
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"


def test_v1_status_requires_api_key_when_configured(gateway_with_api_key) -> None:
    client = TestClient(gateway_with_api_key.app)
    r = client.get("/v1/status/services")
    assert r.status_code == 401
    body = r.json()
    assert body.get("code") == "unauthorized"


@pytest.mark.parametrize(
    "headers,expect_ok",
    [
        ({"x-api-key": "test-secret-key"}, True),
        ({"Authorization": "Bearer test-secret-key"}, True),
        ({"Authorization": "bearer test-secret-key"}, True),
        ({}, False),
        ({"x-api-key": "wrong"}, False),
    ],
)
def test_v1_api_key_acceptance_table(
    gateway_with_api_key,
    headers: dict[str, str],
    expect_ok: bool,
) -> None:
    client = TestClient(gateway_with_api_key.app)
    r = client.get("/v1/status/services", headers=headers)
    if expect_ok:
        assert r.status_code == 200
        assert "healthy" in r.json()
    else:
        assert r.status_code == 401
