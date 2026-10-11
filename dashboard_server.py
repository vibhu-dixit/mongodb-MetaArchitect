"""Loopback-only dashboard API for HarnessEvolve."""
from __future__ import annotations

import json
import os
import threading
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import harness_evolve

WEB_ROOT = Path(__file__).resolve().parent / "harness_evolve_ui"
STATE_LOCK = threading.Lock()
RUN_STATE: dict = {"status": "idle", "run_id": None, "stage": "idle", "progress": [], "events": [], "result": None, "error": None}


class RunReset(Exception):
    pass


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value):
    if isinstance(value, str):
        for name in ("OPENROUTER_API_KEY", "MONGO_URI", "RAINDROP_API_KEY", "RAINDROP_QUERY_API_KEY"):
            secret = os.getenv(name)
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value


def _safe_error(exc: Exception) -> str:
    return _redact(str(exc))[:400] or exc.__class__.__name__


def _progress(run_id: str, stage: str, details: dict | None = None) -> None:
    item = {"stage": stage, "at": _stamp(), **(details or {})}
    with STATE_LOCK:
        if RUN_STATE.get("run_id") != run_id:
            raise RunReset()
        RUN_STATE["stage"] = stage
        RUN_STATE["progress"].append(item)
        RUN_STATE["progress"] = RUN_STATE["progress"][-80:]


def _event(run_id: str, kind: str, details: dict) -> None:
    item = {"type": kind, "at": _stamp(), "details": details}
    with STATE_LOCK:
        if RUN_STATE.get("run_id") != run_id:
            raise RunReset()
        RUN_STATE["events"].append(item)
        RUN_STATE["events"] = RUN_STATE["events"][-80:]


def _run_worker(run_id: str) -> None:
    with STATE_LOCK:
        if RUN_STATE.get("run_id") != run_id:
            return
        RUN_STATE.update({"status": "running", "stage": "starting"})
    try:
        result = harness_evolve.run_evolution(
            lambda stage, details=None: _progress(run_id, stage, details),
            lambda kind, details: _event(run_id, kind, details),
        )
        with STATE_LOCK:
            if RUN_STATE.get("run_id") == run_id:
                RUN_STATE.update({"status": "complete", "stage": "complete", "result": result})
    except Exception as exc:
        if isinstance(exc, RunReset):
            return
        _event(run_id, "run-error", {"message": _safe_error(exc)})
        with STATE_LOCK:
            if RUN_STATE.get("run_id") == run_id:
                RUN_STATE.update({"status": "error", "stage": "error", "error": _safe_error(exc)})
    finally:
        with STATE_LOCK:
            if RUN_STATE.get("run_id") == run_id:
                RUN_STATE["finished_at"] = _stamp()


def _snapshot() -> dict:
    with STATE_LOCK:
        return _redact(json.loads(json.dumps(RUN_STATE, default=str)))


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "HarnessEvolve/1"

    def log_message(self, format: str, *args) -> None:
        # Keep browser query data and run payloads out of routine console output.
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(_redact(data), default=harness_evolve._json_safe).encode("utf-8"), "application/json; charset=utf-8")

    def _local_request(self) -> bool:
        host = (urlsplit("//" + self.headers.get("Host", "")).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"}:
            return False
        if self.command == "POST":
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host')}":
                return False
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                return False
        return True

    def do_GET(self) -> None:
        if not self._local_request():
            self._json(403, {"error": "Local dashboard requests only"})
            return
        path = urlsplit(self.path).path
        if path == "/api/status":
            try:
                status = harness_evolve.get_dashboard_status()
                status["telemetry_state"] = "key-set; delivery is reported during each run" if status.get("raindrop_configured") else "degraded · Raindrop key missing"
                self._json(200, status)
            except Exception as exc:
                self._json(200, {"ready": False, "atlas_connected": False, "error": _safe_error(exc)})
            return
        if path == "/api/run":
            self._json(200, _snapshot())
            return
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8")}
        if path not in assets:
            self._json(404, {"error": "Not found"})
            return
        filename, content_type = assets[path]
        try:
            self._send(200, (WEB_ROOT / filename).read_bytes(), content_type)
        except OSError:
            self._json(500, {"error": "Dashboard asset is unavailable"})
    
    def do_POST(self) -> None:
        if not self._local_request():
            self._json(403, {"error": "Local dashboard requests only"})
            return
        path = urlsplit(self.path).path
        if path == "/api/reset":
            with STATE_LOCK:
                RUN_STATE.clear()
                RUN_STATE.update({"status": "idle", "run_id": None, "stage": "idle", "progress": [], "events": [], "result": None, "error": None})
            self._json(200, _snapshot())
            return
        if path != "/api/run":
            self._json(404, {"error": "Not found"})
            return
        with STATE_LOCK:
            already_started = RUN_STATE["status"] in {"queued", "running"}
            if not already_started:
                run_id = str(uuid.uuid4())
                RUN_STATE.clear()
                RUN_STATE.update({"status": "queued", "run_id": run_id, "stage": "queued", "progress": [], "events": [], "result": None, "error": None})
            else:
                run_id = RUN_STATE["run_id"]
        if not already_started:
            threading.Thread(target=_run_worker, args=(run_id,), name="harness-evolution", daemon=True).start()
        self._json(202, _snapshot())


def serve(host: str = "127.0.0.1", port: int = 3000) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Dashboard host must be loopback; external binding is disabled")
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.daemon_threads = True
    print(f"HarnessEvolve dashboard: http://127.0.0.1:{port}")
    print("Synthetic returns cases only · no payment connection · Ctrl+C stops the local dashboard")
    threading.Timer(0.8, webbrowser.open, args=(f"http://127.0.0.1:{port}",)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard…")
    finally:
        server.server_close()
