import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "build" / "dreamseed"


class CliTests(unittest.TestCase):
    def test_capabilities_are_json(self):
        completed = subprocess.run([BINARY, "capabilities"], text=True, capture_output=True, check=True)
        data = json.loads(completed.stdout)
        self.assertEqual(data["minecraft_versions"], ["1.21.1"])
        self.assertEqual(len(data["structure_filters"]["types"]), 10)
        self.assertIn("pillager_outpost", data["structure_filters"]["types"])
        self.assertEqual(completed.stderr, "")

    def test_invalid_request_is_machine_readable(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as config:
            json.dump({"minecraft_version": "1.20.6", "hard_constraints": []}, config)
            config.flush()
            completed = subprocess.run(
                [BINARY, "search", "--config", config.name], text=True, capture_output=True, check=False
            )
        self.assertEqual(completed.returncode, 2)
        error = json.loads(completed.stdout)["error"]
        self.assertEqual(error["code"], "unsupported_version")
        self.assertIn("path", error)

    def test_inspect_fixture(self):
        completed = subprocess.run(
            [BINARY, "inspect", "--config", ROOT / "examples" / "inspect_seed.json"],
            text=True, capture_output=True, check=True,
        )
        data = json.loads(completed.stdout)
        self.assertEqual(data["seed"], "0")
        self.assertEqual(data["center_biome"], "river")
        self.assertGreater(data["biome_sampling"]["sample_count"], 1000)

    def test_compare_ranking(self):
        completed = subprocess.run(
            [BINARY, "compare", "--config", ROOT / "examples" / "compare_seeds.json"],
            text=True, capture_output=True, check=True,
        )
        data = json.loads(completed.stdout)
        self.assertEqual(data["results"][0]["seed"], "2579")
        self.assertTrue(data["results"][0]["meets_all_hard_constraints"])

    def test_spatial_relation_output(self):
        completed = subprocess.run(
            [BINARY, "search", "--config", ROOT / "examples" / "village_cherry_search.json"],
            text=True, capture_output=True, check=True,
        )
        data = json.loads(completed.stdout)
        result = data["results"][0]
        self.assertEqual(result["seed"], "8009581673339289650")
        self.assertEqual(len(result["spatial_checks"]), 1)
        self.assertLessEqual(result["spatial_checks"][0]["measured_distance"], 100)


if __name__ == "__main__":
    unittest.main()
