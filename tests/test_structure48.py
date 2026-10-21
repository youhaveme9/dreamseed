import copy
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from pydantic import ValidationError

from dreamseed_mcp.job_manager import JobManager
from dreamseed_mcp.schemas import ResultsResponse, SearchRequest, StatusResponse


ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get("DREAMSEED_BINARY", ROOT / "build/dreamseed"))


class Structure48Tests(unittest.TestCase):
    def request(self):
        return {
            "minecraft_version": "1.21.3",
            "hard_constraints": [
                {"id": "v", "type": "structure_within", "structure": "village", "radius": 500},
                {"id": "p", "type": "biome_at", "biome": "plains"},
            ],
            "soft_preferences": [{"type": "minimize_distance", "constraint_id": "v", "weight": 1}],
            "budget": {"strategy": "structure48", "sample_seed": "20261020", "workers": 1,
                       "upper_bits_per_structure_seed": 64, "max_candidates": 2048, "max_seconds": 10},
            "max_results": 20,
        }

    def native(self, command, request, success=True):
        completed = subprocess.run([BINARY, command, "--config", "-"], input=json.dumps(request),
                                   capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0 if success else 2, completed.stdout)
        return json.loads(completed.stdout)

    def test_cached_uncached_and_parallel_results_are_identical(self):
        request = self.request()
        cached = self.native("search", request)
        request["budget"]["placement_cache"] = False
        uncached = self.native("search", request)
        request["budget"].update(placement_cache=True, workers=4)
        parallel = self.native("search", request)
        for result in (cached, uncached, parallel):
            self.assertEqual(result["state"], "completed")
            self.assertEqual(result["coverage"], "sampled_structure_seed_batches")
            self.assertEqual(result["candidates_evaluated"], 2048)
            self.assertEqual(result["results"], cached["results"])
            self.assertEqual(result["matching_seeds_found"], cached["matching_seeds_found"])
        self.assertGreater(cached["matching_seeds_found"], 0)
        self.assertEqual(cached["placement_filter"]["placement_computations"], 32)
        self.assertEqual(cached["placement_filter"]["cache_reuses"], 2016)
        self.assertEqual(uncached["placement_filter"]["placement_computations"], 2048)
        criteria = {key: value for key, value in request.items() if key not in {"budget", "max_results"}}
        criteria["seeds"] = [result["seed"] for result in cached["results"]]
        compared = self.native("compare", criteria)
        self.assertTrue(all(item["meets_all_hard_constraints"] for item in compared["results"]))
        self.assertEqual(len(set(criteria["seeds"])), len(criteria["seeds"]))
        lower_seeds = {int(seed) & ((1 << 48) - 1) for seed in criteria["seeds"]}
        self.assertLess(len(lower_seeds), len(criteria["seeds"]))

    def test_all_placement_rules_preserve_full_seed_results(self):
        capabilities = json.loads(subprocess.check_output([BINARY, "capabilities"], text=True))
        for structure in capabilities["structure_filters"]["types"]:
            with self.subTest(structure=structure):
                request = self.request()
                request["hard_constraints"] = [{"id": "v", "type": "structure_within", "structure": structure, "radius": 2000}]
                request["budget"].update(max_candidates=32, upper_bits_per_structure_seed=8)
                cached = self.native("search", request)
                request["budget"]["placement_cache"] = False
                uncached = self.native("search", request)
                self.assertEqual(cached["results"], uncached["results"])
                if cached["results"]:
                    criteria = {key: value for key, value in request.items() if key not in {"budget", "max_results"}}
                    criteria["seeds"] = [item["seed"] for item in cached["results"]]
                    compared = self.native("compare", criteria)
                    self.assertTrue(all(item["meets_all_hard_constraints"] for item in compared["results"]))

    def test_invalid_strategy_settings_are_rejected_by_both_layers(self):
        request = self.request()
        invalid = []
        for budget in ({"upper_bits_per_structure_seed": 0}, {"upper_bits_per_structure_seed": 65537},
                       {"strategy": "sampled"}, {"start_seed": "0"}):
            item = copy.deepcopy(request)
            item["budget"].update(budget)
            invalid.append(item)
        item = copy.deepcopy(request)
        item["hard_constraints"] = [item["hard_constraints"][1]]
        item["soft_preferences"] = []
        invalid.append(item)
        for item in invalid:
            with self.subTest(budget=item["budget"]):
                with self.assertRaises(ValidationError):
                    SearchRequest.model_validate(item)
                self.assertIn("error", self.native("validate", item, success=False))
        normalized = self.native("validate", request)["normalized_request"]
        self.assertEqual(self.native("validate", normalized)["normalized_request"], normalized)

    def test_job_results_retain_typed_filter_metrics(self):
        with tempfile.TemporaryDirectory() as state:
            manager = JobManager(str(BINARY), state_dir=state)
            try:
                job_id = manager.start(self.request())["job_id"]
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    status = StatusResponse.model_validate(manager.status(job_id))
                    if status.state not in {"queued", "running", "cancelling"}:
                        break
                    time.sleep(0.01)
                self.assertEqual(status.state, "completed")
                results = ResultsResponse.model_validate(manager.results(job_id))
                self.assertGreater(results.placement_filter.cache_reuses, 0)
                self.assertEqual(status.placement_filter, results.placement_filter)
            finally:
                manager.shutdown()

    def test_batched_job_results_survive_restart(self):
        with tempfile.TemporaryDirectory() as state:
            manager = JobManager(str(BINARY), state_dir=state)
            job_id = manager.start(self.request())["job_id"]
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and manager.status(job_id)["state"] in {"queued", "running", "cancelling"}:
                time.sleep(0.01)
            original = manager.results(job_id)
            manager.shutdown()
            self.assertEqual(original["state"], "completed")
            recovered = JobManager(str(BINARY), state_dir=state)
            try:
                result = recovered.results(job_id)
                self.assertTrue(result["recovered"])
                self.assertEqual(result["coverage"], "sampled_structure_seed_batches")
                self.assertEqual(result["placement_filter"], original["placement_filter"])
                self.assertEqual(result["results"], original["results"])
            finally:
                recovered.shutdown()


if __name__ == "__main__":
    unittest.main()
