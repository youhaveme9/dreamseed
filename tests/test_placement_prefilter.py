import json
import os
import random
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get("DREAMSEED_BINARY", ROOT / "build/dreamseed"))


class PlacementPrefilterTests(unittest.TestCase):
    def run_filter(self, request, valid=True):
        completed = subprocess.run([BINARY, "filter", "--config", "-"], input=json.dumps(request),
                                   text=True, capture_output=True, timeout=40)
        self.assertEqual(completed.returncode, 0 if valid else 2, completed.stdout)
        return json.loads(completed.stdout)

    def test_cpu_results_are_only_placements_and_keep_full_world_seeds(self):
        request = json.loads((ROOT / "examples/filter_placements.json").read_text())
        request["backend"] = "cpu"
        result = self.run_filter(request)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["candidates_evaluated"], len(request["seeds"]))
        self.assertEqual(result["validation_status"], "placement_only_not_verified")
        self.assertIn("2579", result["survivor_seeds"])
        self.assertTrue(set(result["survivor_seeds"]).issubset(request["seeds"]))

    def test_gpu_matches_cubiomes_for_all_ten_rules_and_signed_coordinates(self):
        capabilities = json.loads(subprocess.check_output([BINARY, "capabilities"], text=True))
        if not capabilities["placement_prefilter"]["backends"]["metal"]:
            request = json.loads((ROOT / "examples/filter_placements.json").read_text())
            self.assertEqual(self.run_filter(request, valid=False)["error"]["code"], "backend_unavailable")
            return
        randomizer = random.Random(20261020)
        seeds = ["0", "-1", "-9223372036854775808", "9223372036854775807"]
        seeds += [str(randomizer.randrange(-(1 << 63), 1 << 63)) for _ in range(1000)]
        for version in capabilities["minecraft_versions"]:
            for structure in capabilities["structure_filters"]["types"]:
                for anchor, radius, count in (({"x": 0, "z": 0}, 500, 1), ({"x": -12345, "z": -10001}, 2000, 2)):
                    with self.subTest(version=version, structure=structure, anchor=anchor):
                        request = {"minecraft_version": version, "seeds": seeds, "max_seconds": 30,
                                   "hard_constraints": [{"id": "target", "type": "structure_within", "structure": structure,
                                                         "anchor": anchor, "radius": radius, "count": count}]}
                        cpu = self.run_filter(request | {"backend": "cpu"})
                        gpu = self.run_filter(request | {"backend": "metal"})
                        self.assertEqual(gpu["backend"], "metal")
                        self.assertEqual(gpu["state"], "completed")
                        self.assertEqual(gpu["survivor_seeds"], cpu["survivor_seeds"])

    def test_filter_rejects_biomes_duplicates_unknown_backend_and_invalid_seeds(self):
        base = json.loads((ROOT / "examples/filter_placements.json").read_text()) | {"backend": "cpu"}
        invalid = [base | {"seeds": ["0", "0"]}, base | {"seeds": [0]}, base | {"seeds": ["9223372036854775808"]},
                   base | {"backend": "cuda"}, base | {"hard_constraints": [{"id": "b", "type": "biome_at", "biome": "plains"}]}]
        for request in invalid:
            with self.subTest(request=request):
                self.assertIn("error", self.run_filter(request, valid=False))


if __name__ == "__main__":
    unittest.main()
