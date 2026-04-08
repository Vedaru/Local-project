import json
import os
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from urllib import error, request


def _resolve_default_ports() -> dict[str, str]:
    defaults = {
        "gateway": "18080",
        "orchestrator": "18081",
        "memory": "18082",
        "agent": "18083",
        "voice": "18084",
    }
    try:
        from modules.config_tuning import load_tuning

        svc = load_tuning().services
        defaults = {
            "gateway": str(svc.gateway_port),
            "orchestrator": str(svc.orchestrator_port),
            "memory": str(svc.memory_service_port),
            "agent": str(svc.agent_service_port),
            "voice": str(svc.voice_service_port),
        }
    except Exception:
        pass
    return defaults


_DEFAULT_PORTS = _resolve_default_ports()

DEFAULT_GATEWAY_PORT = os.getenv("GATEWAY_PORT", _DEFAULT_PORTS["gateway"])
DEFAULT_ORCHESTRATOR_PORT = os.getenv("ORCHESTRATOR_PORT", _DEFAULT_PORTS["orchestrator"])
DEFAULT_MEMORY_PORT = os.getenv("MEMORY_SERVICE_PORT", _DEFAULT_PORTS["memory"])
DEFAULT_AGENT_PORT = os.getenv("AGENT_SERVICE_PORT", _DEFAULT_PORTS["agent"])
DEFAULT_VOICE_PORT = os.getenv("VOICE_SERVICE_PORT", _DEFAULT_PORTS["voice"])


class ServiceMonitorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Project Local - Microservices Monitor")
        self.root.geometry("1080x560")

        self.gateway_base = os.getenv(
            "MONITOR_GATEWAY_URL", f"http://127.0.0.1:{DEFAULT_GATEWAY_PORT}"
        ).rstrip("/")

        self.services = [
            ("gateway", f"http://127.0.0.1:{DEFAULT_GATEWAY_PORT}/health"),
            ("orchestrator", f"http://127.0.0.1:{DEFAULT_ORCHESTRATOR_PORT}/health"),
            ("memory-service", f"http://127.0.0.1:{DEFAULT_MEMORY_PORT}/health"),
            ("agent-service", f"http://127.0.0.1:{DEFAULT_AGENT_PORT}/health"),
            ("voice-service", f"http://127.0.0.1:{DEFAULT_VOICE_PORT}/health"),
        ]

        self.tree = self._build_table()
        self.status_var = tk.StringVar(value="Ready")
        self.auto_refresh = tk.BooleanVar(value=True)
        self.interval_seconds = tk.IntVar(value=3)

        self._build_controls()
        self._refresh_in_progress = False
        self._schedule_next_refresh()

    def _build_table(self) -> ttk.Treeview:
        columns = ("service", "status", "latency", "url", "message", "updated")
        tree = ttk.Treeview(self.root, columns=columns, show="headings", height=18)
        tree.heading("service", text="Service")
        tree.heading("status", text="Status")
        tree.heading("latency", text="Latency(ms)")
        tree.heading("url", text="Health URL")
        tree.heading("message", text="Message")
        tree.heading("updated", text="Updated At")

        tree.column("service", width=130, anchor="w")
        tree.column("status", width=90, anchor="center")
        tree.column("latency", width=100, anchor="center")
        tree.column("url", width=290, anchor="w")
        tree.column("message", width=330, anchor="w")
        tree.column("updated", width=130, anchor="center")

        tree.tag_configure("up", foreground="#0B6E4F")
        tree.tag_configure("down", foreground="#B42318")

        for name, url in self.services:
            tree.insert(
                "",
                "end",
                iid=name,
                values=(name, "UNKNOWN", "-", url, "waiting first probe", "-"),
            )

        tree.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        return tree

    def _build_controls(self) -> None:
        controls = ttk.Frame(self.root)
        controls.pack(fill="x", padx=12, pady=(0, 8))

        ttk.Button(controls, text="Refresh Now", command=self.trigger_refresh).pack(
            side="left"
        )

        ttk.Checkbutton(
            controls,
            text="Auto Refresh",
            variable=self.auto_refresh,
        ).pack(side="left", padx=(12, 6))

        ttk.Label(controls, text="Interval(s):").pack(side="left")
        ttk.Spinbox(
            controls,
            from_=1,
            to=60,
            textvariable=self.interval_seconds,
            width=5,
        ).pack(side="left", padx=(4, 12))

        ttk.Button(controls, text="Quit", command=self.root.destroy).pack(side="right")

        ttk.Label(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            relief="sunken",
        ).pack(fill="x", padx=12, pady=(0, 12))

    def _schedule_next_refresh(self) -> None:
        if not self.auto_refresh.get():
            self.root.after(500, self._schedule_next_refresh)
            return

        interval = max(1, int(self.interval_seconds.get()))
        self.root.after(interval * 1000, self._auto_refresh_callback)

    def _auto_refresh_callback(self) -> None:
        self.trigger_refresh()
        self._schedule_next_refresh()

    def trigger_refresh(self) -> None:
        if self._refresh_in_progress:
            return
        self._refresh_in_progress = True
        self.status_var.set("Refreshing...")
        thread = threading.Thread(target=self._refresh_worker, daemon=True)
        thread.start()

    def _refresh_worker(self) -> None:
        started = time.perf_counter()
        try:
            rows = self._fetch_rows_from_gateway_aggregate()
            if rows is None:
                rows = [self._probe_single(name, url) for name, url in self.services]
        except Exception as exc:
            rows = [
                {
                    "service": name,
                    "url": url,
                    "ok": False,
                    "latency_ms": "-",
                    "message": f"monitor exception: {exc}",
                }
                for name, url in self.services
            ]

        elapsed = round((time.perf_counter() - started) * 1000.0, 1)
        self.root.after(0, lambda: self._render_rows(rows, elapsed))

    def _fetch_rows_from_gateway_aggregate(self):
        endpoint = f"{self.gateway_base}/v1/status/services"
        try:
            payload = self._http_json(endpoint, timeout=3)
        except Exception:
            return None

        services = payload.get("services")
        if not isinstance(services, list):
            return None

        rows = []
        for item in services:
            rows.append(
                {
                    "service": str(item.get("service", "unknown")),
                    "url": str(item.get("url", "")),
                    "ok": bool(item.get("ok", False)),
                    "latency_ms": item.get("latency_ms", "-"),
                    "message": item.get("error", "")
                    or json.dumps(item.get("payload", {}), ensure_ascii=False),
                }
            )
        return rows

    def _probe_single(self, name: str, url: str) -> dict:
        started = time.perf_counter()
        try:
            payload = self._http_json(url, timeout=3)
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            return {
                "service": name,
                "url": url,
                "ok": True,
                "latency_ms": latency_ms,
                "message": json.dumps(payload, ensure_ascii=False),
            }
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            return {
                "service": name,
                "url": url,
                "ok": False,
                "latency_ms": latency_ms,
                "message": str(exc),
            }

    @staticmethod
    def _http_json(url: str, timeout: int = 3) -> dict:
        req = request.Request(url=url, method="GET")
        with request.urlopen(req, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return json.loads(text)

    def _render_rows(self, rows: list[dict], elapsed_ms: float) -> None:
        updated_at = datetime.now().strftime("%H:%M:%S")
        up_count = 0

        for row in rows:
            name = row.get("service", "unknown")
            ok = bool(row.get("ok", False))
            status_text = "UP" if ok else "DOWN"
            tag = "up" if ok else "down"
            if ok:
                up_count += 1

            latency = row.get("latency_ms", "-")
            message = str(row.get("message", ""))
            if len(message) > 120:
                message = message[:117] + "..."

            if self.tree.exists(name):
                self.tree.item(
                    name,
                    values=(
                        name,
                        status_text,
                        latency,
                        row.get("url", ""),
                        message,
                        updated_at,
                    ),
                    tags=(tag,),
                )
            else:
                self.tree.insert(
                    "",
                    "end",
                    iid=name,
                    values=(
                        name,
                        status_text,
                        latency,
                        row.get("url", ""),
                        message,
                        updated_at,
                    ),
                    tags=(tag,),
                )

        self.status_var.set(
            f"Last refresh {updated_at} | healthy {up_count}/{len(rows)} | probe {elapsed_ms} ms"
        )
        self._refresh_in_progress = False


def main() -> None:
    root = tk.Tk()
    app = ServiceMonitorApp(root)
    app.trigger_refresh()
    root.mainloop()


if __name__ == "__main__":
    main()
