# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Layered configuration under `config/` (`default.yaml`, `development.yaml`, `production.yaml`) with merge into `modules/config_base.py`.
- `scripts/` directory for install/start/check (Windows `.bat` + Linux/macOS `.sh`); root batch files kept as thin wrappers.
- Enhanced Docker stack under `docker/` (multi-stage `Dockerfile.services`, health checks, `docker/Makefile`).
- Root `Makefile` for lint/test/docker shortcuts; expanded `.pre-commit-config.yaml` hooks.
- HTTP middleware on Gateway, Orchestrator, Memory/Agent/Voice services sets logging `request_id` context and echoes `x-request-id` on responses.
- Table-driven tests for Gateway `/v1` API key auth and expanded `security.tools` coverage.
- [`docs/RELEASE.md`](docs/RELEASE.md) describing versioning and release checklist.
- Gateway startup policy: non-loopback bind addresses (`GATEWAY_BIND_HOST` / `gateway.bind_host`) require `gateway.api_key` or `GATEWAY_API_KEY`.
- `security.tools` in `project_config.yaml` and env overrides `SECURITY_TOOL_*_ENABLED` for OpenManus tool gating (`modules/security_tools.py`).
- `microservices/shared/bind_policy.py` for shared bind/API-key validation.
- OpenAPI contract tests for Gateway and Orchestrator (`tests/test_gateway_orchestrator_contract.py`).
- `.pre-commit-config.yaml` aligned with CI lint tool versions.
- `docs/VENDOR_MODULES.md` describing embedded third-party trees.
- Optional `Dockerfile.microservices` and `docker-compose.yml` for backend stack (requires `GATEWAY_API_KEY` when exposing Gateway to non-loopback).

### Changed

- Config/HTTP fallback paths log at debug vs warning with stack traces for unexpected failures (`microservices/service_client.py`, `microservices/shared/http_client.py`, `microservices/gateway/main.py`, `modules/security_tools.py`).
- Memory service uses `get_logger` for centralized JSON logging.
- Coverage gate remains at 45% (`fail_under` in `pyproject.toml`); new tests added toward future increases.
- Mypy: stricter overrides for `microservices.shared.http_client`, `microservices.shared.types`, `microservices.gateway.main`, `microservices.orchestrator.main`.
- Vendor maintenance: expanded [`docs/VENDOR_MODULES.md`](docs/VENDOR_MODULES.md) with sync workflow and CI incremental checks.
- Manual interactive scripts moved under `tests/manual/`; pytest ignores that directory.
- PyPI metadata URLs updated in `pyproject.toml` (replace placeholder repository).
