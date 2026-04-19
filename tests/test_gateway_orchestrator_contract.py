"""
Contract tests: Gateway and Orchestrator must agree on /chat JSON payloads.
"""

from __future__ import annotations

from microservices.gateway.main import ChatRequest as GatewayChatRequest
from microservices.orchestrator.main import ChatRequest as OrchestratorChatRequest


def test_gateway_chat_payload_validates_on_orchestrator() -> None:
    """Gateway forwards model_dump(); Orchestrator must accept without extra client fields."""
    payload = GatewayChatRequest(
        query="hello",
        user_id="u1",
        route_to_agent=True,
    ).model_dump()
    parsed = OrchestratorChatRequest.model_validate(payload)
    assert parsed.query == "hello"
    assert parsed.user_id == "u1"
    assert parsed.route_to_agent is True
    assert parsed.force_chat_only is False


def test_orchestrator_extra_field_default_visible_in_schema() -> None:
    """Document: Orchestrator adds optional fields; Gateway omits them (defaults apply)."""
    assert "force_chat_only" in OrchestratorChatRequest.model_fields
    assert "force_chat_only" not in GatewayChatRequest.model_fields


def test_gateway_openapi_contract() -> None:
    """Gateway exposes stable HTTP surface for GUI and tooling."""
    from microservices.gateway.main import app

    schema = app.openapi()
    paths = schema.get("paths", {})
    assert "/health" in paths
    assert "/v1/chat" in paths
    assert "/v1/status/services" in paths
    assert schema.get("info", {}).get("title") == "project-local-gateway"


def test_orchestrator_openapi_contract() -> None:
    from microservices.orchestrator.main import app

    schema = app.openapi()
    paths = schema.get("paths", {})
    assert "/health" in paths
    assert "/chat" in paths
    assert schema.get("info", {}).get("title") == "project-local-orchestrator"
