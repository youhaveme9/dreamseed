import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get("DREAMSEED_BINARY", str(ROOT / "build" / "dreamseed")))


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

    def test_structured_biome_map(self):
        completed = subprocess.run(
            [BINARY, "inspect", "--config", ROOT / "examples" / "inspect_biome_map.json"],
            text=True, capture_output=True, check=True,
        )
        data = json.loads(completed.stdout)
        biome_map = data["biome_map"]
        self.assertEqual(biome_map["encoding"], "palette_indices")
        self.assertEqual((biome_map["width"], biome_map["height"]), (9, 9))
        self.assertEqual(len(biome_map["rows"]), 9)
        self.assertEqual(
            biome_map["palette"][biome_map["rows"][4][4]],
            data["center_biome"],
        )

    def test_inspection_accepts_every_advertised_structure(self):
        capabilities = json.loads(subprocess.check_output([BINARY, "capabilities"], text=True))
        request = {
            "minecraft_version": "1.21.1", "seed": "0",
            "area": {"radius": 64, "sample_step": 16},
            "structures": capabilities["structure_filters"]["types"],
        }
        completed = subprocess.run(
            [BINARY, "inspect", "--config", "-"], input=json.dumps(request),
            text=True, capture_output=True, check=True,
        )
        self.assertIn("structures", json.loads(completed.stdout))

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
