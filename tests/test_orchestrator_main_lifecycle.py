from __future__ import annotations

import importlib
from types import SimpleNamespace


def _reload_orchestrator_module():
    import microservices.orchestrator.main as orchestrator

    return importlib.reload(orchestrator)


def test_get_core_reuses_cached_instance(monkeypatch) -> None:
    orchestrator = _reload_orchestrator_module()
    orchestrator.reset_core_for_tests()

    cfg = object()

    class _FakeCore:
        instances = 0

        def __init__(self, config):
            self.cfg = config
            _FakeCore.instances += 1

        def shutdown(self):
            return None

    monkeypatch.setattr(orchestrator, "OrchestratorConfig", SimpleNamespace(from_env=lambda: cfg))
    monkeypatch.setattr(orchestrator, "OrchestratorCore", _FakeCore)

    first = orchestrator.get_core()
    second = orchestrator.get_core()

    assert first is second
    assert _FakeCore.instances == 1


def test_reset_core_for_tests_forces_recreation(monkeypatch) -> None:
    orchestrator = _reload_orchestrator_module()
    orchestrator.reset_core_for_tests()

    cfg = object()

    class _FakeCore:
        instances = 0

        def __init__(self, config):
            self.cfg = config
            _FakeCore.instances += 1

        def shutdown(self):
            return None

    monkeypatch.setattr(orchestrator, "OrchestratorConfig", SimpleNamespace(from_env=lambda: cfg))
    monkeypatch.setattr(orchestrator, "OrchestratorCore", _FakeCore)

    orchestrator.get_core()
    orchestrator.reset_core_for_tests()
    orchestrator.get_core()

    assert _FakeCore.instances == 2
