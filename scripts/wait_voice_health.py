"""
Wait until voice-service /health/live responds (stdlib only — no project imports).

Used by scripts/start.bat so startup is not blocked by heavy /health probes or
bat inline-python quoting issues on Windows paths.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.request

_DEFAULT_NO_PROXY = "127.0.0.1,localhost,::1"


def _ensure_local_no_proxy_env() -> None:
    for key in ("NO_PROXY", "no_proxy"):
        current = (os.environ.get(key) or "").strip()
        parts = [p.strip() for p in current.split(",") if p.strip()]
        for marker in ("127.0.0.1", "localhost", "::1"):
            if marker not in parts:
                parts.append(marker)
        os.environ[key] = ",".join(parts) if parts else _DEFAULT_NO_PROXY


def _probe(url: str, timeout: float) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url=url, method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(getattr(response, "status", 200) or 200) == 200
    except urllib.error.HTTPError as exc:
        return 200 <= int(exc.code) < 300
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Wait for voice-service live health endpoint")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18084)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--max-wait", type=int, default=120)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    _ensure_local_no_proxy_env()
    url = f"http://{args.host}:{args.port}/health/live"
    deadline = time.monotonic() + max(1, int(args.max_wait))
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        if _probe(url, max(0.5, float(args.timeout))):
            print(f"[OK] voice-service ready ({url}, attempt={attempt})")
            return 0
        time.sleep(max(0.2, float(args.interval)))

    print(f"[WARN] voice-service not ready within {args.max_wait}s ({url})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
