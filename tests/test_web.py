import http.client
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from dreamseed_mcp.job_manager import JobManager
from dreamseed_mcp.web_server import DreamSeedWebServer


ROOT = Path(__file__).resolve().parents[1]


class WebTests(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        manager = JobManager(str(ROOT / "build/dreamseed"), state_dir=self.state.name)
        self.server = DreamSeedWebServer(0, manager)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.state.cleanup()

    def call(self, path, body=None, headers=None, method=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        default = {"X-DreamSeed-Token": self.server.token, "Content-Type": "application/json"}
        connection.request(method or ("POST" if body is not None else "GET"), path,
                           json.dumps(body) if body is not None else None, default | (headers or {}))
        response = connection.getresponse()
        status, fields, data = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, fields, data

    def test_static_assets_session_and_security_headers(self):
        status, headers, data = self.call("/")
        self.assertEqual(status, 200)
        self.assertIn(self.server.token.encode(), data)
        self.assertNotIn(b"DREAMSEED_SESSION_TOKEN", data)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        ids = set(re.findall(rb'id="([^"]+)"', data))
        _, _, javascript = self.call("/app.js")
        for identifier in re.findall(rb'\$\("([^"]+)"\)', javascript):
            self.assertIn(identifier, ids)
        for asset in ("/app.js", "/style.css"):
            self.assertEqual(self.call(asset)[0], 200)
        self.assertEqual(self.call("/../../pyproject.toml")[0], 404)

    def test_cross_origin_rebinding_and_missing_token_are_denied(self):
        for headers in ({"X-DreamSeed-Token": ""}, {"Origin": "https://attacker.example"},
                        {"Host": "attacker.example"}, {"X-DreamSeed-Token": "é"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.call("/api/capabilities", {}, headers)[0], 403)
        self.assertEqual(self.call("/", headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.call("/api/capabilities", {}, {"Content-Type": "text/plain"})[0], 400)

    def test_real_search_inspection_and_comparison(self):
        status, _, body = self.call("/api/capabilities", {})
        self.assertEqual(status, 200)
        self.assertIn("1.21.3", json.loads(body)["capabilities"]["minecraft_versions"])
        request = json.loads((ROOT / "examples/village_search.json").read_text())
        _, _, body = self.call("/api/search", request)
        started = json.loads(body)
        self.assertTrue(started["ok"], started)
        for _ in range(100):
            _, _, body = self.call("/api/status", {"job_id": started["job_id"]})
            if json.loads(body)["state"] not in {"queued", "running", "cancelling"}:
                break
            time.sleep(0.01)
        _, _, body = self.call("/api/results", {"job_id": started["job_id"]})
        results = json.loads(body)
        self.assertEqual(results["state"], "completed")
        self.assertEqual(results["results"][0]["seed"], "659")
        status, _, body = self.call("/api/inspect", {"minecraft_version": "1.21.3", "seed": "0", "area": {"radius": 0}})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["inspection"]["center_biome"], "river")
        status, _, body = self.call("/api/compare", json.loads((ROOT / "examples/compare_seeds.json").read_text()))
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["comparison"]["results"][0]["seed"], "2579")

    def test_strict_schema_errors_are_json(self):
        status, _, body = self.call("/api/search", {"minecraft_version": "1.21.3", "hard_constraints": [], "command": "rm"})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "validation_error")
        self.assertEqual(self.call("/api/status", {"job_id": 123})[0], 400)
        self.assertEqual(self.call("/api/capabilities", {"command": "x"})[0], 400)
        self.assertEqual(self.call("/api/unknown", {})[0], 404)

    def test_javascript_search_refinement_and_mesh_with_actual_engine(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable for browser client unit tests")
        process = subprocess.run([node, str(ROOT / "tests/web_client.test.cjs"), f"http://127.0.0.1:{self.server.server_port}"],
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertTrue(report["actual_engine_search"])
        self.assertTrue(report["criteria_preserved"])
        self.assertEqual(report["surface_triangles"], 32)


if __name__ == "__main__":
    unittest.main()
