from __future__ import annotations

import argparse
import asyncio
import os
import sys
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.responses import JSONResponse

from .http_auth import HttpAuthConfig, JwtTokenVerifier, REQUIRED_SCOPE
from .job_manager import interface_state_dir


class ConcurrentRequestLimit:
    def __init__(self, app, limit=8):
        self.app = app
        self.semaphore = asyncio.Semaphore(limit)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if self.semaphore.locked():
            await JSONResponse({"error": "request_limit"}, status_code=429, headers={"Retry-After": "1"})(scope, receive, send)
            return
        async with self.semaphore:
            await self.app(scope, receive, send)


def create_http_app(config: HttpAuthConfig, port: int):
    if not os.environ.get("DREAMSEED_STATE_DIR"):
        os.environ["DREAMSEED_STATE_DIR"] = str(interface_state_dir("http"))
    from . import server as implementation

    @asynccontextmanager
    async def lifespan(_server):
        try:
            yield
        finally:
            implementation.manager.shutdown()

    server = MCPServer(
        "DreamSeed", instructions=implementation.server.instructions,
        auth=AuthSettings(issuer_url=AnyHttpUrl(config.issuer), resource_server_url=AnyHttpUrl(config.resource),
                          required_scopes=[REQUIRED_SCOPE], validate_token_resource=True),
        token_verifier=JwtTokenVerifier(config), lifespan=lifespan,
    )
    for function in implementation.TOOL_FUNCTIONS:
        server.tool()(function)
    external = urlsplit(config.resource)
    application = server.streamable_http_app(
        stateless_http=True, json_response=True, host="127.0.0.1", max_request_body_size=1024 * 1024,
        max_sessions=16, session_idle_timeout=60,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[f"127.0.0.1:{port}", f"localhost:{port}", external.netloc],
            allowed_origins=[f"https://{external.netloc}"],
        ),
    )
    return ConcurrentRequestLimit(application)


def main() -> int:
    parser = argparse.ArgumentParser(description="Authenticated MCP resource server behind a trusted TLS proxy")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    try:
        config = HttpAuthConfig.from_environment()
        application = create_http_app(config, args.port)
    except (ValueError, TypeError) as error:
        print(f"HTTP configuration error: {error}", file=sys.stderr)
        return 2
    import uvicorn

    uvicorn.run(application, host="127.0.0.1", port=args.port, access_log=False, proxy_headers=False,
                limit_concurrency=16, backlog=16, timeout_keep_alive=5, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
