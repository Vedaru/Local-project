# Vendor / embedded third-party code

Large upstream trees are vendored under `modules/` for offline use and patching.

| Path | Purpose | Upstream / notes |
|------|---------|------------------|
| `modules/gpt_sovits/` | TTS / SoVITS integration | Track upstream GPT-SoVITS version used; local patches should be listed in commit messages. |
| `modules/openmanus/` | Agent tools and orchestration | Derived `config.toml` is generated at runtime from `project_config.yaml`; do not treat as hand-edited source. |

## Maintenance

- Prefer documenting the **exact upstream revision** when importing or updating a vendor tree.
- Keep security-sensitive overrides (e.g. web fetch, browser tools) in project-owned modules where possible, and gate tools via `security.tools` in `project_config.yaml`.

## Upstream sync workflow

1. **Record the source revision** in the merge commit message (e.g. `vendor(openmanus): sync from upstream commit <hash>`).
2. **Diff review**: before merging, skim changes under `modules/openmanus/app/tool/` and `modules/gpt_sovits/api_v2.py` for network, subprocess, or filesystem behavior.
3. **Re-run focused tests** after sync:
   - `python -m pytest tests/test_openmanus_web_search_fetcher.py tests/test_openmanus_tool_collection.py -q`
   - `python -m pytest tests/test_voice_tts_chain.py -q` (if TTS paths touched)
4. **Project-owned integration points** (e.g. `tool_collection.py`, `web_search.py`, `api_v2.py`) remain in CI: `py_compile` plus Ruff fatal rules (`E9,F63,F7,F82`) — extend the file list in `.github/workflows/ci.yml` if new entry modules are added.

## Incremental static checks (vendor)

Vendor roots stay excluded from full Black/Ruff/mypy to avoid churn. For touched files in a PR, maintainers should run the same minimal checks CI uses for integration modules, or rely on the **Syntax check integration modules** / **Ruff sanity check** jobs when those paths change.
