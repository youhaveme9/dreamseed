import asyncio
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import httpx2
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from dreamseed_mcp.http_auth import HttpAuthConfig, JwtTokenVerifier


ROOT = Path(__file__).resolve().parents[1]


class HttpAuthTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        self.config = HttpAuthConfig("https://issuer.example", "https://dreamseed.example/mcp", "owner", self.public)

    def token(self, **overrides):
        claims = {"iss": self.config.issuer, "aud": self.config.resource, "sub": "owner", "client_id": "test-client",
                  "scope": "dreamseed:use", "iat": int(time.time()) - 1, "exp": int(time.time()) + 120}
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm="EdDSA")

    def test_signature_identity_scope_expiry_and_audience(self):
        verifier = JwtTokenVerifier(self.config)
        accepted = asyncio.run(verifier.verify_token(self.token()))
        self.assertEqual(accepted.subject, "owner")
        self.assertEqual(accepted.resource, self.config.resource)
        for invalid in ({"iss": "https://other.example"}, {"aud": "https://other.example/mcp"}, {"sub": "other-owner"},
                        {"scope": "read"}, {"exp": int(time.time()) - 1}, {"iat": int(time.time()) + 600},
                        {"client_id": 123}, {"scope": ["dreamseed:use"]}, {"exp": None}, {"exp": True}):
            with self.subTest(invalid=invalid):
                self.assertIsNone(asyncio.run(verifier.verify_token(self.token(**invalid))))
        attacker = jwt.encode({"sub": "owner"}, "not-a-public-key-but-at-least-32-bytes-long", algorithm="HS256")
        for token in (attacker, "invalid", "a" * 17000, self.token()[:-5] + "AAAAA"):
            self.assertIsNone(asyncio.run(verifier.verify_token(token)))

    def test_unsafe_or_incomplete_configuration_is_rejected(self):
        for changes in ({"issuer": "http://issuer.example"}, {"resource": "https://dreamseed.example/not-mcp"},
                        {"resource": "https://name:password@example.com/mcp"}, {"subject": ""}, {"algorithm": "HS256"}):
            values = dict(issuer=self.config.issuer, resource=self.config.resource, subject="owner", public_key=self.public)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                HttpAuthConfig(**(values | changes))

    def test_authenticated_http_tools_use_actual_engine(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        with tempfile.TemporaryDirectory() as state:
            env = dict(os.environ, DREAMSEED_HTTP_ISSUER=self.config.issuer, DREAMSEED_HTTP_RESOURCE=self.config.resource,
                       DREAMSEED_HTTP_SUBJECT="owner", DREAMSEED_HTTP_PUBLIC_KEY=self.public, DREAMSEED_STATE_DIR=state,
                       DREAMSEED_BINARY=str(ROOT / "build/dreamseed"), DREAMSEED_MINECRAFT_SERVER_JAR=str(Path(state) / "missing.jar"))
            process = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "dreamseed_mcp.http_server", "--port", str(port)],
                                       cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(process.communicate()[1])
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                            break
                    except OSError:
                        time.sleep(0.05)
                asyncio.run(self.http_flow(port))
            finally:
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate(timeout=5)
                self.assertNotIn(self.token(), stdout + stderr)

    async def http_flow(self, port):
        url = f"http://127.0.0.1:{port}/mcp"
        async with httpx2.AsyncClient() as client:
            denied = await client.post(url, json={}, headers={"Accept": "application/json, text/event-stream"})
            self.assertEqual(denied.status_code, 401)
            self.assertIn("resource_metadata", denied.headers["www-authenticate"])
            metadata = await client.get(f"http://127.0.0.1:{port}/.well-known/oauth-protected-resource/mcp")
            self.assertEqual(metadata.status_code, 200)
            self.assertEqual(metadata.json()["resource"], self.config.resource)
            denied = await client.post(url, json={}, headers={"Authorization": f"Bearer {self.token(sub='other-owner')}", "Accept": "application/json, text/event-stream"})
            self.assertEqual(denied.status_code, 401)
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {self.token()}"}) as http:
            async with streamable_http_client(url, http_client=http) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as client:
                    await client.initialize()
                    tools = await client.list_tools()
                    self.assertEqual(len(tools.tools), 11)
                    capabilities = await client.call_tool("get_search_capabilities", {})
                    self.assertTrue(capabilities.structured_content["ok"], capabilities.structured_content)
                    inspected = await client.call_tool("inspect_seed", {"request": {"minecraft_version": "1.21.3", "seed": "0", "area": {"radius": 0}}})
                    self.assertTrue(inspected.structured_content["ok"], inspected.structured_content)
                    self.assertEqual(inspected.structured_content["inspection"]["center_biome"], "river")
                    request = json.loads((ROOT / "examples/village_search.json").read_text())
                    started = await client.call_tool("start_seed_search", {"request": request})
                    self.assertTrue(started.structured_content["ok"], started.structured_content)
                    job_id = started.structured_content["job_id"]
                    for _ in range(100):
                        status = await client.call_tool("get_search_status", {"job_id": job_id})
                        if status.structured_content["state"] not in {"queued", "running", "cancelling"}:
                            break
                        await asyncio.sleep(0.02)
                    result = await client.call_tool("get_search_results", {"job_id": job_id})
                    self.assertEqual(result.structured_content["results"][0]["seed"], "659")


if __name__ == "__main__":
    unittest.main()
