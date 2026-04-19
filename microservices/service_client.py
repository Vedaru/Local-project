from __future__ import annotations

import os
import queue
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Optional

import httpx

from modules.logging_config import get_logger

_logger = get_logger("MicroserviceClient")


@dataclass
class ServiceCallbacks:
    on_response_ready: Optional[Callable[[str], None]] = None
    on_expression_change: Optional[Callable[[object], None]] = None
    on_status_update: Optional[Callable[[str], None]] = None
    on_speak_request: Optional[Callable[[dict[str, Any]], None]] = None
    on_shutdown: Optional[Callable[[], None]] = None


@asynccontextmanager
async def get_http_session() -> AsyncIterator[httpx.AsyncClient]:
    """Provide a managed async HTTP session for one-shot workflows."""
    session = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=5.0),
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        trust_env=False,
    )
    try:
        yield session
    finally:
        await session.aclose()


class ResourceManager:
    """Track closeable resources and clean them up in reverse order."""

    def __init__(self) -> None:
        self._resources: list[Any] = []
        self._lock = threading.Lock()

    def register(self, resource: Any) -> Any:
        with self._lock:
            self._resources.append(resource)
        return resource

    def cleanup(self) -> None:
        with self._lock:
            resources = list(reversed(self._resources))
            self._resources.clear()

        for resource in resources:
            try:
                if hasattr(resource, "close"):
                    resource.close()
                elif hasattr(resource, "cleanup"):
                    resource.cleanup()
            except Exception:
                _logger.warning("resource cleanup failed", exc_info=True)


def _resolve_client_defaults() -> dict[str, str]:
    """Load gateway URL / user / API key from tuning; on failure use safe built-ins."""
    defaults: dict[str, str] = {
        "gateway_url": "http://127.0.0.1:18080",
        "user_id": "local-gui",
        "api_key": "",
    }
    try:
        from modules.config_tuning import load_tuning

        tuning = load_tuning()
        defaults["gateway_url"] = f"http://127.0.0.1:{tuning.services.gateway_port}"
        defaults["user_id"] = str(tuning.client.user_id or "local-gui")
        defaults["api_key"] = str(tuning.gateway.api_key or "")
    except Exception as exc:
        if isinstance(exc, (ImportError, OSError, ValueError)):
            _logger.debug("client defaults using built-in fallbacks (config unavailable): %s", exc)
        else:
            _logger.warning("client defaults using built-in fallbacks after unexpected error", exc_info=True)
    return defaults


class MicroserviceAIService:
    def __init__(self, callbacks: ServiceCallbacks):
        self.callbacks = callbacks
        defaults = _resolve_client_defaults()
        gateway_port = (os.getenv("GATEWAY_PORT", "") or "").strip()
        if gateway_port:
            default_gateway = f"http://127.0.0.1:{gateway_port}"
        else:
            default_gateway = defaults["gateway_url"]
        self.gateway_url = (os.getenv("MICROSERVICES_GATEWAY_URL", default_gateway) or default_gateway).rstrip("/")
        self.user_id = (os.getenv("LOCAL_GUI_USER_ID", defaults["user_id"]) or "local-gui").strip()
        self.api_key = (os.getenv("GATEWAY_API_KEY", defaults["api_key"]) or "").strip()

        self._input_queue: queue.Queue[Optional[str]] = queue.Queue(maxsize=200)
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._resource_manager = ResourceManager()

        # 持久化 HTTP 客户端（连接复用，消除每次请求的 TCP 握手开销）
        self._http_session: httpx.Client = self._resource_manager.register(
            httpx.Client(
                timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=5.0),
                trust_env=False,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5, keepalive_expiry=30.0),
            )
        )

    def start_background(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def submit(self, text: Optional[str]) -> None:
        try:
            self._input_queue.put_nowait(text)
        except queue.Full:
            self._emit_status("输入队列已满，忽略本次输入")

    def close(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        with self._suppress_queue_full():
            self._input_queue.put_nowait(None)
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        self._resource_manager.cleanup()

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._input_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if item is None:
                break

            text = (item or "").strip()
            if not text:
                continue

            lowered = text.lower()
            if lowered in {"exit", "quit"}:
                self._emit_shutdown()
                continue

            if lowered == "status":
                self._handle_status()
                continue

            self._handle_chat(text)

    def _handle_status(self) -> None:
        self._emit_status("正在查询微服务状态...")
        try:
            payload = self._request("GET", "/v1/status/services", None, timeout=8.0)
            healthy = payload.get("healthy", "?")
            total = payload.get("total", "?")
            self._emit_response(f"微服务状态: {healthy}/{total} healthy")
        except Exception as exc:
            self._emit_response(f"微服务状态查询失败: {exc}")

    def _handle_chat(self, text: str) -> None:
        self._emit_status("思考中...")
        payload = {
            "query": text,
            "user_id": self.user_id,
            "route_to_agent": False,
            "force_chat_only": False,
        }
        try:
            result = self._request("POST", "/v1/chat", payload, timeout=180.0)
            answer = (result.get("answer") or "").strip() or "抱歉，本次未获取到有效回复。"
            self._emit_response(answer)
            self._emit_expression(answer)
            self._emit_status("就绪")

            tts_data = result.get("tts")
            if tts_data and isinstance(tts_data, dict):
                self._emit_speak_request(tts_data, answer)
        except Exception as exc:
            self._emit_response(f"微服务请求失败: {exc}")
            self._emit_status("异常")

    def _request(self, method: str, path: str, payload: Optional[dict], timeout: float) -> dict[str, Any]:
        url = f"{self.gateway_url}{path}"
        headers = {"x-request-id": f"gui-{threading.get_ident()}"}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        if method == "POST":
            response = self._http_session.post(url, json=payload or {}, headers=headers, timeout=timeout)
        else:
            response = self._http_session.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            return dict(data)
        return {"data": data}

    class _suppress_queue_full:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return exc_type is queue.Full

    def _emit_response(self, text: str) -> None:
        if callable(self.callbacks.on_response_ready):
            self.callbacks.on_response_ready(text)

    def _emit_expression(self, value: object) -> None:
        if callable(self.callbacks.on_expression_change):
            self.callbacks.on_expression_change(value)

    def _emit_status(self, text: str) -> None:
        if callable(self.callbacks.on_status_update):
            self.callbacks.on_status_update(text)

    def _emit_speak_request(self, tts_data: dict, answer: str) -> None:
        if callable(self.callbacks.on_speak_request):
            speak_payload = {
                "text": answer,
                "status": "",
                "mode": "",
                "wav_path": "",
                **tts_data,
            }
            self.callbacks.on_speak_request(speak_payload)

    def _emit_shutdown(self) -> None:
        if callable(self.callbacks.on_shutdown):
            self.callbacks.on_shutdown()


def create_ai_service(config, callbacks: ServiceCallbacks) -> MicroserviceAIService:
    _ = config
    return MicroserviceAIService(callbacks)
