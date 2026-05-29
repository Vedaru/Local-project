# 安全说明与威胁面

本文档描述 Project Local 的本地攻击面与缓解建议；**不能替代**你对操作系统与网络环境的安全配置。

## 监听端口与暴露面

默认微服务端口见 [`config/default.yaml`](../config/default.yaml) 中 `services` 段（常见为 18080–18084）。在**可信局域网**以外监听 `0.0.0.0` 时，等同将本机 AI 与控制能力暴露给网络，**务必**仅在内网或本机使用，或通过防火墙限制来源 IP。

### 启动策略（可执行）

- **`gateway.bind_host`**（或环境变量 **`GATEWAY_BIND_HOST`**）应与 `uvicorn microservices.gateway.main:app --host …` **一致**，用于启动时策略判断。
- 当绑定地址**不是**本机回环（`127.0.0.1` / `localhost` / `::1`），包括 `0.0.0.0`、具体局域网 IP 等，**必须**配置 **`gateway.api_key`** 或环境变量 **`GATEWAY_API_KEY`**，否则 Gateway **拒绝启动**（`RuntimeError`）。
- 仅回环监听时，API Key 仍为可选；此时依赖本机网络隔离（见下节）。

参考实现：`microservices/shared/bind_policy.py`、[`microservices/gateway/main.py`](../microservices/gateway/main.py) 启动逻辑。

## Gateway 鉴权

- 若配置了 `gateway.api_key`（或环境变量 `GATEWAY_API_KEY`），对 `/v1/*` 路径的请求需在请求头提供 `x-api-key` 或 `Authorization: Bearer <key>`。
- 未配置 API Key 且仅监听回环时，Gateway 不对请求做强鉴权（依赖本机网络隔离）。

## Agent 能力与高危工具

以下能力可显著放大误用或恶意提示词的影响，请仅在必要时启用，并在配置中限制：

- **桌面自动化**（如 `pyautogui`、窗口控制）：可能误操作应用或泄露屏幕内容。
- **浏览器自动化**（如 Playwright / browser-use）：可访问网页、执行脚本，需配合白名单与人工确认策略。
- **Python / Shell / 文件编辑**：仅在受信任环境下使用。

在 [`config/default.yaml`](../config/default.yaml) 的 **`security.tools`** 段（或本地 `project_config.yaml` 覆盖）可为下列类别设置默认开关（也可用环境变量 **`SECURITY_TOOL_*_ENABLED`** 覆盖，见文件内注释）：

| 类别 | 典型工具名 | 配置键 |
|------|------------|--------|
| 浏览器自动化 | `browser_use`, `crawl4ai` | `browser_automation_enabled` |
| Python 执行 | `python_execute` | `python_execution_enabled` |
| Shell | `bash` | `shell_execution_enabled` |
| 文件编辑 | `str_replace_editor` | `file_editor_enabled` |
| MCP | `mcp` / `mcp_*` | `mcp_enabled` |

OpenManus 工具集中部分工具默认**串行**以降低风险（见主文档「性能加速」一节中的工具列表）。禁用某类工具时，`ToolCollection.execute` 会返回明确错误信息。

## 密钥与配置

- **API Key**（如 `ARK_API_KEY`）应通过环境变量或本地覆盖文件提供，**不要**将含真实密钥的 `project_config.yaml` 提交到版本库。
- 依赖漏洞扫描见 CI 中的 `pip-audit`；建议启用 Dependabot（见 [`.github/dependabot.yml`](../.github/dependabot.yml)）。

### 容器 / Compose

若使用 [`docker/docker-compose.yml`](../docker/docker-compose.yml) 或根目录 [`docker-compose.yml`](../docker-compose.yml) 将 Gateway 暴露到非回环地址，**必须**在 `docker/.env` 或环境中提供 **`GATEWAY_API_KEY`**。镜像定义见 [`docker/Dockerfile.services`](../docker/Dockerfile.services)。

## 日志与隐私

日志目录默认在 `data/logs/`。若包含敏感对话或路径，请避免将日志打包上传至不可信第三方。

## 供应商代码

嵌入的上游目录（如 `gpt_sovits`、`openmanus`）见 [`VENDOR_MODULES.md`](VENDOR_MODULES.md)。
