# Remediation Checklist (2026-04-08)

## Scope
This remediation package addresses architecture stability, runtime governance, and regression safety for the microservice pipeline.

## Completed Items
- [x] Hardened orchestrator core lifecycle with lock + app.state cache.
- [x] Added explicit orchestrator test reset hook `reset_core_for_tests()`.
- [x] Hardened memory service engine lifecycle with lock + app.state cache.
- [x] Added explicit memory service test reset hook `reset_engine_for_tests()`.
- [x] Added unified Python runtime guard module `modules/python_runtime_guard.py`.
- [x] Integrated runtime guard into desktop entrypoint and all microservice startup events.
- [x] Upgraded timeout tests to use lifecycle reset hook instead of direct global assignment.
- [x] Added lifecycle regression tests for orchestrator main state management.
- [x] Added lifecycle regression tests for memory service state management.
- [x] Added runtime guard unit tests (supported/unsupported/strict/env parsing).

## New Runtime Guard Environment Variables
- `PROJECT_MIN_PYTHON` (default: `3.10`)
- `PROJECT_MAX_PYTHON_EXCLUSIVE` (default: `3.12`)
- `PROJECT_STRICT_PYTHON_VERSION` (default: `0`)

## Validation Requirement
Run focused regression suite after changes:

```powershell
python -m pytest \
  tests/test_orchestrator_core.py \
  tests/test_microservice_timeouts.py \
  tests/test_service_client_speak_payload.py \
  tests/test_orchestrator_main_lifecycle.py \
  tests/test_memory_service_lifecycle.py \
  tests/test_python_runtime_guard.py -q
```
