from __future__ import annotations

import pytest

from modules.python_runtime_guard import (
    ensure_supported_python_runtime,
    evaluate_python_runtime,
    evaluate_python_runtime_from_env,
)


def test_evaluate_python_runtime_supported() -> None:
    status = evaluate_python_runtime(
        current_version=(3, 11, 9),
        min_inclusive=(3, 10),
        max_exclusive=(3, 12),
    )
    assert status.supported is True
    assert "within supported range" in status.message


def test_evaluate_python_runtime_unsupported() -> None:
    status = evaluate_python_runtime(
        current_version=(3, 13, 0),
        min_inclusive=(3, 10),
        max_exclusive=(3, 12),
    )
    assert status.supported is False
    assert "outside supported range" in status.message


def test_evaluate_python_runtime_from_env_parses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECT_MIN_PYTHON", "invalid")
    monkeypatch.setenv("PROJECT_MAX_PYTHON_EXCLUSIVE", "")

    status = evaluate_python_runtime_from_env(current_version=(3, 10, 1))
    assert status.min_inclusive == (3, 10)
    assert status.max_exclusive == (3, 12)
    assert status.supported is True


def test_ensure_supported_python_runtime_strict_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECT_MIN_PYTHON", "3.10")
    monkeypatch.setenv("PROJECT_MAX_PYTHON_EXCLUSIVE", "3.12")
    monkeypatch.setenv("PROJECT_STRICT_PYTHON_VERSION", "1")

    with pytest.raises(RuntimeError):
        ensure_supported_python_runtime(current_version=(3, 13, 5))


def test_ensure_supported_python_runtime_non_strict_no_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECT_MIN_PYTHON", "3.10")
    monkeypatch.setenv("PROJECT_MAX_PYTHON_EXCLUSIVE", "3.12")
    monkeypatch.setenv("PROJECT_STRICT_PYTHON_VERSION", "0")

    status = ensure_supported_python_runtime(current_version=(3, 13, 5))
    assert status.supported is False
    assert status.strict is False
