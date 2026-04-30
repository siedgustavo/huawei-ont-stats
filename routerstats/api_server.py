#!/usr/bin/env python3
"""Simple HTTP API exposing router status.

Run with:
    python3 api_server.py --host 192.168.18.1 --port 8000

The server listens on *host* and provides a single endpoint:

    GET /status

It returns JSON with the same structure produced by router_info.py
including device, ont, optic, wan, wan_stats, eth, wlan, lan_clients.

Session management:
  - Logs in to the router once at startup.
  - Reuses the same session for subsequent requests.
  - Re-authenticates automatically when the session expires.

Caching:
  - Static data (device info, wlan config): cached 10 minutes.
  - Dynamic data (wan, stats, clients, optic, eth, ont): cached 30 seconds.
"""

import argparse
import json as _json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .router_info import (
    login,
    get_device_info,
    get_ont_state,
    get_optic_info,
    get_wan_status,
    get_wan_stats,
    get_eth_info,
    get_wlan_info,
    get_lan_clients,
)

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
STATIC_TTL = 600   # 10 min – device info, wlan config (rarely change)
DYNAMIC_TTL = 30   # 30 s   – wan, stats, clients, optic, eth, ont
SESSION_TTL = 300  # 5 min  – re-login before the router kills the session


# ---------------------------------------------------------------------------
# Persistent router session with auto-reconnect
# ---------------------------------------------------------------------------
class RouterSession:
    """Keeps a single authenticated session alive and re-logins when needed."""

    def __init__(self, host, username, password):
        self.host = host
        self.username = username
        self.password = password
        self.opener = None
        self.token = None
        self.login_time = 0
        self._lock = threading.Lock()

    def _do_login(self):
        self.opener, self.token = login(self.host, self.username, self.password)
        self.login_time = time.time()
        print(f"[session] Logged in to {self.host}")

    def ensure(self):
        """Return (opener, token), re-logging if the session is stale."""
        with self._lock:
            if self.opener is None or (time.time() - self.login_time) > SESSION_TTL:
                self._do_login()
            return self.opener, self.token

    def invalidate(self):
        """Force a fresh login on the next call to ensure()."""
        with self._lock:
            self.opener = None
            self.token = None
            self.login_time = 0


# ---------------------------------------------------------------------------
# Per-key data cache with individual TTLs
# ---------------------------------------------------------------------------
class DataCache:
    def __init__(self):
        self._data = {}
        self._times = {}
        self._lock = threading.Lock()

    def get(self, key, ttl):
        """Return cached value if younger than *ttl*, else None."""
        with self._lock:
            if key in self._data and (time.time() - self._times.get(key, 0)) < ttl:
                return self._data[key]
        return None

    def put(self, key, value):
        with self._lock:
            self._data[key] = value
            self._times[key] = time.time()


# ---------------------------------------------------------------------------
# Which sections are static vs dynamic
# ---------------------------------------------------------------------------
_SECTION_TTL = {
    "device":      STATIC_TTL,
    "wlan":        STATIC_TTL,
    "ont":         DYNAMIC_TTL,
    "optic":       DYNAMIC_TTL,
    "wan":         DYNAMIC_TTL,
    "wan_stats":   DYNAMIC_TTL,
    "eth":         DYNAMIC_TTL,
    "lan_clients": DYNAMIC_TTL,
}

_FETCHERS = {
    "device":      lambda o, h, t: get_device_info(o, h),
    "ont":         lambda o, h, t: get_ont_state(o, h),
    "optic":       lambda o, h, t: get_optic_info(o, h),
    "wan":         lambda o, h, t: get_wan_status(o, h, t),
    "wan_stats":   lambda o, h, t: get_wan_stats(o, h),
    "eth":         lambda o, h, t: get_eth_info(o, h),
    "wlan":        lambda o, h, t: get_wlan_info(o, h),
    "lan_clients": lambda o, h, t: get_lan_clients(o, h, t),
}

_SECTION_ORDER = ["device", "ont", "optic", "wan", "wan_stats", "eth", "wlan", "lan_clients"]


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class StatusHandler(BaseHTTPRequestHandler):
    """HTTP handler that exposes /status endpoint."""

    def address_string(self):
        # Override: skip reverse DNS lookup (can block 5-10s in Docker)
        return self.client_address[0]

    def do_GET(self):
        if self.path != "/status":
            self.send_error(404, "Not Found")
            return

        try:
            data = self._collect_data()
            body = _json.dumps(data, indent=2, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            msg = f"{exc.__class__.__name__}: {exc}"
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg.encode())
            self.log_error(msg)

    # ── data collection ────────────────────────────────────────────────

    def _collect_data(self):
        session = self.server.session
        cache = self.server.cache
        host = self.server.router_host

        # 1. Read everything that's still fresh in cache
        result = {}
        stale_keys = []
        for key in _SECTION_ORDER:
            cached = cache.get(key, _SECTION_TTL[key])
            if cached is not None:
                result[key] = cached
            else:
                stale_keys.append(key)

        if not stale_keys:
            return result

        # 2. Fetch stale sections in parallel, retry once on session error
        for attempt in range(2):
            try:
                opener, token = session.ensure()
                t0 = time.monotonic()
                errors = {}

                def _fetch(key):
                    return key, _FETCHERS[key](opener, host, token)

                with ThreadPoolExecutor(max_workers=len(stale_keys)) as pool:
                    futures = {pool.submit(_fetch, k): k for k in stale_keys}
                    for fut in as_completed(futures):
                        key = futures[fut]
                        try:
                            _, value = fut.result()
                            cache.put(key, value)
                            result[key] = value
                        except Exception as exc:
                            errors[key] = exc

                elapsed = time.monotonic() - t0
                print(f"[fetch] {len(stale_keys)} sections in {elapsed:.1f}s"
                      f" (parallel) — stale: {stale_keys}")

                if errors:
                    raise list(errors.values())[0]

                return result
            except Exception:
                if attempt == 0:
                    session.invalidate()
                else:
                    raise

    # ── logging ────────────────────────────────────────────────────────

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {time.strftime('%Y-%m-%d %H:%M:%S')} - {fmt % args}")


# ---------------------------------------------------------------------------
# Server bootstrap
# ---------------------------------------------------------------------------
def run_server(host, port, router_host, username, password):
    session = RouterSession(router_host, username, password)
    cache = DataCache()

    # Login immediately so the session is ready for the first request
    print(f"Connecting to router at {router_host} …")
    session.ensure()

    httpd = ThreadingHTTPServer((host, port), StatusHandler)
    httpd.daemon_threads = True
    httpd.router_host = router_host
    httpd.session = session
    httpd.cache = cache

    print(f"API ready → http://{host}:{port}/status")
    print(f"  session TTL {SESSION_TTL}s · static cache {STATIC_TTL}s · dynamic cache {DYNAMIC_TTL}s")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Expose router status via HTTP API")
    parser.add_argument("--host", default="0.0.0.0", help="Interface to bind to (default all)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--router-host", default="192.168.18.1", help="Router IP address")
    parser.add_argument("--user", default="Epadmin", help="Router username")
    parser.add_argument("--pass", dest="password", default="adminEp", help="Router password")
    args = parser.parse_args()

    run_server(args.host, args.port, args.router_host, args.user, args.password)
