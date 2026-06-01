# 运维与健康检查

在默认端口（见 [`config/default.yaml`](../config/default.yaml) 中 `services`）下，各服务提供 `GET /health`。以下为在本机（bash）快速探测示例（请按实际端口调整）。

```bash
curl -sS "http://127.0.0.1:18080/health" | jq .
curl -sS "http://127.0.0.1:18081/health" | jq .
curl -sS "http://127.0.0.1:18082/health" | jq .
curl -sS "http://127.0.0.1:18083/health" | jq .
curl -sS "http://127.0.0.1:18084/health" | jq .
```

## 本地脚本

| 脚本 | 说明 |
|------|------|
| `scripts/start.bat` / `scripts/start.sh` | 启动微服务 + GUI |
| `scripts/start.bat --start-services-only` | 仅启动微服务 |
| `scripts/check.bat` | Windows 运行时健康检查 |
```bash
curl -sS "http://127.0.0.1:18080/health" | jq .
curl -sS "http://127.0.0.1:18081/health" | jq .
curl -sS "http://127.0.0.1:18082/health" | jq .
curl -sS "http://127.0.0.1:18083/health" | jq .
curl -sS "http://127.0.0.1:18084/health" | jq .
```

Gateway 还提供聚合状态（需服务已启动且网络可达）：

```bash
curl -sS "http://127.0.0.1:18080/v1/status/services" | jq .
```

若配置了 Gateway API Key，请为上述请求增加请求头：`x-api-key: <your-key>`。

Python 侧可选用仓库内 [`microservices/monitor_panel.py`](../microservices/monitor_panel.py) 作为本地监控入口（视环境与依赖而定）。
