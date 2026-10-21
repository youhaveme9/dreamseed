from __future__ import annotations

import argparse
import hmac
import json
import secrets
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any

from pydantic import ValidationError

from .job_manager import JobError, JobManager, interface_state_dir
from .minecraft_verifier import VerifierError
from .schemas import (
    CandidateVerificationRequest, CompareRequest, InspectRequest, MinecraftVerificationRequest,
    RenderSeedMapRequest, SearchRequest, TerrainAnalysisRequest,
)


MAX_BODY = 1024 * 1024


class DreamSeedWebServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, port: int, manager: JobManager):
        self.manager = manager
        self.token = secrets.token_urlsafe(32)
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(("127.0.0.1", port), DreamSeedHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def server_close(self):
        super().server_close()
        self.manager.shutdown()


class DreamSeedHandler(BaseHTTPRequestHandler):
    server_version = "DreamSeed"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format_, *args):
        return

    def _origin_ok(self) -> bool:
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        hosts = self.headers.get_all("Host", [])
        origins = self.headers.get_all("Origin", [])
        return len(hosts) == 1 and hosts[0] in allowed and len(origins) <= 1 and (
            not origins or origins[0] in {f"http://{host}" for host in allowed}
        )

    def _send(self, status: int, payload: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            pass

    def _json(self, status: int, value: Any):
        self._send(status, json.dumps(value, separators=(",", ":")).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        if not self._origin_ok():
            self._json(403, {"ok": False, "error": {"code": "invalid_origin", "message": "local host or origin is not allowed"}})
            return
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8")}
        if self.path not in assets:
            self._json(404, {"ok": False, "error": {"code": "not_found", "message": "route does not exist"}})
            return
        name, mime = assets[self.path]
        data = files("dreamseed_mcp").joinpath("web", name).read_text(encoding="utf-8")
        if name == "index.html":
            data = data.replace("DREAMSEED_SESSION_TOKEN", self.server.token)
        self._send(200, data.encode(), mime)

    def do_POST(self):
        if not self._origin_ok() or not hmac.compare_digest(self.headers.get("X-DreamSeed-Token", "").encode(), self.server.token.encode()):
            self._json(403, {"ok": False, "error": {"code": "invalid_session", "message": "open the local DreamSeed page to obtain a current session"}})
            return
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            self._json(400, {"ok": False, "error": {"code": "invalid_body", "message": "one Content-Length and no transfer encoding are required"}})
            self.close_connection = True
            return
        try:
            length = int(self.headers["Content-Length"])
            if not 0 < length <= MAX_BODY:
                raise ValueError("request body must contain 1 through 1048576 bytes")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type must be application/json")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("request body was truncated")
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError("request body must be a JSON object")
            manager = self.server.manager
            if self.path == "/api/capabilities":
                if body:
                    raise ValueError("capabilities takes an empty object")
                response = {"ok": True, "capabilities": manager.capabilities()}
            elif self.path in {"/api/status", "/api/results", "/api/cancel"}:
                if set(body) != {"job_id"}:
                    raise ValueError("only job_id is accepted")
                function = {"/api/status": manager.status, "/api/results": manager.results, "/api/cancel": manager.cancel}[self.path]
                response = function(body["job_id"])
            else:
                routes = {
                    "/api/search": (SearchRequest, manager.start, None),
                    "/api/inspect": (InspectRequest, manager.inspect, "inspection"),
                    "/api/compare": (CompareRequest, manager.compare, "comparison"),
                    "/api/verify": (MinecraftVerificationRequest, manager.verify_with_minecraft, "verification"),
                    "/api/candidate": (CandidateVerificationRequest, manager.verify_candidate, "verification"),
                    "/api/render": (RenderSeedMapRequest, manager.render, "rendering"),
                    "/api/terrain": (TerrainAnalysisRequest, manager.analyze_terrain, "terrain"),
                }
                if self.path not in routes:
                    self._json(404, {"ok": False, "error": {"code": "not_found", "message": "route does not exist"}})
                    return
                schema, function, key = routes[self.path]
                request = schema.model_validate(body).model_dump(by_alias=True, exclude_none=True)
                value = function(request)
                response = value if key is None else {"ok": True, key: value}
            self._json(200, response)
        except ValidationError as error:
            self._json(400, {"ok": False, "error": {"code": "validation_error", "message": "request validation failed", "details": json.loads(error.json(include_url=False))}})
        except (JobError, VerifierError) as error:
            self._json(400, error.response())
        except (ValueError, UnicodeError, socket.timeout) as error:
            self.close_connection = True
            self._json(400, {"ok": False, "error": {"code": "invalid_request", "message": str(error)}})
        except Exception:
            self._json(500, {"ok": False, "error": {"code": "internal_error", "message": "request failed; inspect the local server installation"}})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local DreamSeed browser application")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    manager = JobManager(state_dir=interface_state_dir("web"))
    try:
        with DreamSeedWebServer(args.port, manager) as application:
            print(f"DreamSeed local app: http://127.0.0.1:{application.server_port}", file=sys.stderr, flush=True)
            application.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        manager.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
