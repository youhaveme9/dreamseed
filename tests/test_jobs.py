import json
import os
import stat
import tempfile
import time
import threading
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from dreamseed_mcp.job_manager import JobManager, SearchJob, interface_state_dir


ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get("DREAMSEED_BINARY", str(ROOT / "build" / "dreamseed")))


class JobTests(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.manager = JobManager(str(BINARY), max_concurrent=2, state_dir=self.state.name)

    def tearDown(self):
        self.manager.shutdown()
        self.state.cleanup()

    def wait(self, job_id, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.manager.status(job_id)
            if status["state"] not in {"queued", "running", "cancelling"}:
                return status
            time.sleep(0.01)
        self.fail("job did not finish")

    def test_job_lifecycle_and_results(self):
        request = json.loads((ROOT / "examples" / "village_search.json").read_text())
        started = self.manager.start(request)
        status = self.wait(started["job_id"])
        self.assertEqual(status["state"], "completed")
        results = self.manager.results(started["job_id"])
        self.assertEqual(results["results"][0]["seed"], "659")
        self.assertEqual(results["coverage"], "exhaustive_requested_range")

    def test_shutdown_joins_completed_workers_before_returning(self):
        finished = threading.Event()
        thread = threading.Thread(target=lambda: (time.sleep(0.05), finished.set()))
        job = SearchJob(job_id="a" * 32, request={}, state="completed", thread=thread)
        self.manager.jobs[job.job_id] = job
        thread.start()
        self.manager.shutdown()
        self.assertTrue(finished.is_set())
        self.assertFalse(thread.is_alive())

    def test_shutdown_rejects_new_searches(self):
        self.manager.shutdown()
        request = json.loads((ROOT / "examples/village_search.json").read_text())
        with self.assertRaisesRegex(Exception, "job manager has shut down"):
            self.manager.start(request)

    def test_interface_defaults_do_not_share_the_stdio_store(self):
        with patch.dict(os.environ, {"DREAMSEED_STATE_DIR": ""}), \
             patch("dreamseed_mcp.job_manager.default_state_dir", return_value=Path(self.state.name) / "jobs"):
            self.assertEqual(interface_state_dir("web"), Path(self.state.name) / "web-jobs")
            self.assertEqual(interface_state_dir("http"), Path(self.state.name) / "http-jobs")
        with patch.dict(os.environ, {"DREAMSEED_STATE_DIR": self.state.name}):
            self.assertEqual(interface_state_dir("web"), Path(self.state.name).resolve())
        with self.assertRaises(ValueError):
            interface_state_dir("../other")

    def test_terrain_cli_does_not_recover_or_modify_another_job_store(self):
        job = SearchJob(job_id="b" * 32, request={"budget": {"strategy": "sampled", "max_candidates": 100}}, state="running")
        with self.manager.lock:
            self.manager.jobs[job.job_id] = job
            self.manager._persist_locked(job, force=True)
        job_file = Path(self.state.name) / f"{job.job_id}.json"
        original = job_file.read_bytes()
        process = subprocess.run([str(ROOT / ".venv/bin/python"), "-m", "dreamseed_mcp.terrain_cli", "--config", str(ROOT / "examples/analyze_terrain.json")],
                                 env=dict(os.environ, DREAMSEED_STATE_DIR=self.state.name, DREAMSEED_MINECRAFT_SERVER_JAR=str(Path(self.state.name) / "missing.jar")),
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(json.loads(process.stdout)["error"]["code"], "minecraft_verifier_unavailable")
        self.assertEqual(job_file.read_bytes(), original)

    def test_job_cancellation(self):
        request = {
            "minecraft_version": "1.21.1",
            "hard_constraints": [
                {
                    "id": "cherry", "type": "biome_within", "biome": "cherry_grove",
                    "radius": 1024, "sample_step": 4, "y": 64,
                }
            ],
            "budget": {
                "strategy": "sequential", "start_seed": "0", "max_candidates": 1000000,
                "max_seconds": 60, "workers": 1,
            },
            "max_results": 1,
        }
        started = self.manager.start(request)
        cancelled = self.manager.cancel(started["job_id"])
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertTrue(self.manager.results(started["job_id"])["search_complete"])

    def test_native_job_error_is_actionable(self):
        job = SearchJob(job_id="0" * 32, request={
            "minecraft_version": "1.21.1",
            "reference_point": {"x": 0, "z": 0},
            "hard_constraints": [
                {
                    "id": "origin", "type": "biome_at", "biome": "plains",
                    "coordinate": {"x": 0, "z": 0, "y": 64},
                }
            ],
            "soft_preferences": [],
            "budget": {
                "strategy": "sequential", "start_seed": "0", "max_candidates": 1,
                "max_seconds": 1, "workers": 1,
            },
            "max_results": 1,
        })
        self.manager._worker(job)
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.error["code"], "unknown_field")
        self.assertEqual(job.error["path"], "/hard_constraints/0/coordinate/y")
        self.assertEqual(job.error["details"]["return_code"], 2)

    def test_completed_job_survives_manager_restart(self):
        request = json.loads((ROOT / "examples" / "village_search.json").read_text())
        started = self.manager.start(request)
        self.wait(started["job_id"])
        job_file = Path(self.state.name) / f"{started['job_id']}.json"
        self.assertEqual(stat.S_IMODE(job_file.stat().st_mode), 0o600)

        recovered = JobManager(str(BINARY), max_concurrent=2, state_dir=self.state.name)
        status = recovered.status(started["job_id"])
        results = recovered.results(started["job_id"])
        self.assertEqual(status["state"], "completed")
        self.assertTrue(status["recovered"])
        self.assertTrue(status["persisted"])
        self.assertEqual(results["results"][0]["seed"], "659")

    def test_active_job_is_marked_interrupted_after_restart(self):
        job = SearchJob(
            job_id="1" * 32,
            request={"budget": {"strategy": "sampled", "max_candidates": 10}},
            state="running",
            started_at=time.time(),
        )
        with self.manager.lock:
            self.manager.jobs[job.job_id] = job
            self.manager._persist_locked(job, force=True)

        recovered = JobManager(str(BINARY), state_dir=self.state.name)
        status = recovered.status(job.job_id)
        self.assertEqual(status["state"], "interrupted")
        self.assertEqual(status["error"]["code"], "server_restarted")
        self.assertTrue(recovered.results(job.job_id)["search_complete"])

    def test_raw_render_request_uses_optional_defaults(self):
        request = json.loads((ROOT / "examples" / "render_seed_map.json").read_text())
        rendering = self.manager.render(request)
        self.assertEqual(rendering["format"], "svg")
        self.assertIn("<svg", rendering["svg"])
        self.assertGreater(rendering["marker_count"], 0)

    def test_prediction_rejection_does_not_claim_official_verification(self):
        result = self.manager.verify_candidate({
            "minecraft_version": "1.21.1", "seed": "262", "reference_point": {"x": 0, "z": 0},
            "hard_constraints": [{"id": "plains", "type": "biome_at", "biome": "plains", "y": 64}],
            "soft_preferences": [], "probe_surfaces": False, "max_seconds": 30,
        })
        self.assertEqual(result["status"], "prediction_rejected")
        self.assertEqual(result["source"], "cubiomes_prediction_only")
        self.assertFalse(result["all_hard_constraints_verified"])
        self.assertEqual(result["features"], [])


if __name__ == "__main__":
    unittest.main()
