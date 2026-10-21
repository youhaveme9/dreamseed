import hashlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from dreamseed_mcp import minecraft_setup
from dreamseed_mcp.minecraft_setup import eula_accepted, installation_status, record_acceptance
from dreamseed_mcp.minecraft_verifier import (
    MinecraftVerifier,
    ServerConsole,
    VerifierError,
    parse_entity_position,
    parse_locate_output,
)
from dreamseed_mcp.rendering import marker_color, render_seed_map
from dreamseed_mcp.versions import get_version


class MinecraftVerifierTests(unittest.TestCase):
    def test_minecraft_console_log_buffer_is_bounded(self):
        class Process:
            stdout = io.StringIO("log line\n" * 5000)
            stdin = io.StringIO()

            def poll(self):
                return None

        console = ServerConsole(Process())
        console.reader.join(timeout=2)
        self.assertFalse(console.reader.is_alive())
        self.assertEqual(console.lines.qsize(), 4096)
        self.assertTrue(console.overflowed)
        with self.assertRaisesRegex(VerifierError, "buffered log limit"):
            console.wait_ready(time.monotonic() + 1)
        with self.assertRaisesRegex(VerifierError, "buffered log limit"):
            console.command("say test", time.monotonic() + 1)

    def test_generated_start_markers_have_a_distinct_validation_color(self):
        self.assertEqual(marker_color("generated_chunks_confirmed"), "#087f8c")
        self.assertNotEqual(marker_color("generated_chunks_confirmed"), marker_color("minecraft_located"))
        self.assertNotEqual(marker_color("generated_chunks_confirmed"), marker_color("cubiomes_predicted"))

    def test_shutdown_reaps_an_active_process(self):
        verifier = MinecraftVerifier()
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            verifier.process = process
            verifier.shutdown()
            self.assertIsNotNone(process.poll())
            with self.assertRaises(VerifierError) as caught:
                verifier.verify({})
            self.assertEqual(caught.exception.code, "verifier_closed")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()

    def test_structure_locate_output(self):
        parsed = parse_locate_output([
            "[Server thread/INFO]: The nearest #minecraft:village (minecraft:village_plains) is at [48, ~, 16] (50 blocks away)"
        ])
        self.assertEqual(parsed["located_id"], "#minecraft:village (minecraft:village_plains)")
        self.assertEqual((parsed["x"], parsed["y"], parsed["z"]), (48, None, 16))
        self.assertEqual(parsed["reported_distance"], 50)

    def test_biome_locate_output(self):
        parsed = parse_locate_output([
            "[Server thread/INFO]: The nearest minecraft:cherry_grove is at [-96, 96, 160] (186 blocks away)"
        ])
        self.assertEqual(parsed["located_id"], "minecraft:cherry_grove")
        self.assertEqual((parsed["x"], parsed["y"], parsed["z"]), (-96, 96, 160))

    def test_surface_position_output(self):
        position = parse_entity_position([
            "[Server thread/INFO]: Marker has the following entity data: [48.0d, 73.0d, 16.0d]"
        ])
        self.assertEqual(position, (48, 73, 16))

    def test_eula_acceptance_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            jar = Path(temporary) / "server.jar"
            with patch.dict(os.environ, {"DREAMSEED_ACCEPT_MOJANG_EULA": ""}, clear=False):
                self.assertFalse(eula_accepted(jar))
                record_acceptance(jar)
                self.assertTrue(eula_accepted(jar))

    def test_server_download_is_checksum_verified(self):
        content = b"pinned minecraft server fixture"
        with tempfile.TemporaryDirectory() as temporary:
            jar = Path(temporary) / "server.jar"
            with (
                patch.object(minecraft_setup, "get_version", return_value=replace(
                    get_version(), server_size=len(content), server_sha1=hashlib.sha1(content).hexdigest()
                )),
                patch("urllib.request.urlopen", return_value=io.BytesIO(content)),
            ):
                minecraft_setup.download_server(jar)
            self.assertEqual(jar.read_bytes(), content)
            self.assertEqual(jar.stat().st_mode & 0o777, 0o600)

    def test_missing_server_is_actionable(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "server.jar"
            environment = {
                "DREAMSEED_MINECRAFT_SERVER_JAR": str(missing),
                "DREAMSEED_ACCEPT_MOJANG_EULA": "true",
            }
            with patch.dict(os.environ, environment, clear=False):
                with self.assertRaises(VerifierError) as caught:
                    MinecraftVerifier().verify({
                        "minecraft_version": "1.21.1",
                        "seed": "0",
                        "reference_point": {"x": 0, "y": 64, "z": 0},
                        "structures": ["village"],
                        "biomes": [],
                        "probe_surfaces": False,
                        "max_seconds": 30,
                    })
            self.assertEqual(caught.exception.code, "minecraft_verifier_unavailable")
            self.assertIn("setup_command", caught.exception.details)

    def test_static_svg_render(self):
        inspection = {
            "seed": "0",
            "minecraft_version": "1.21.1",
            "area": {"center": {"x": 0, "z": 0}},
            "biome_map": {
                "origin": {"x": -16, "z": -16},
                "width": 3,
                "height": 3,
                "sample_step": 16,
                "y": 64,
                "palette": ["plains", "river"],
                "rows": [[0, 0, 1], [0, 1, 1], [0, 0, 0]],
            },
            "structures": [],
        }
        rendered = render_seed_map(inspection, [{
            "kind": "structure",
            "name": "village",
            "coordinates": {"x": 0, "z": 0},
            "validation_status": "minecraft_located",
        }])
        self.assertEqual(rendered["format"], "svg")
        self.assertEqual(rendered["marker_count"], 1)
        self.assertIn("#18a558", rendered["svg"])
        self.assertNotIn("<script", rendered["svg"])

    def test_official_server_when_explicitly_enabled(self):
        if os.environ.get("DREAMSEED_RUN_MINECRAFT_INTEGRATION") != "1":
            self.skipTest("official Minecraft integration was not requested")
        status = installation_status(verify_hash=True)
        if not status["available"]:
            self.skipTest(status["detail"])
        result = MinecraftVerifier().verify({
            "minecraft_version": "1.21.1",
            "seed": "-7333811035076652275",
            "reference_point": {"x": 0, "y": 64, "z": 0},
            "structures": ["village", "pillager_outpost"],
            "biomes": ["plains", "cherry_grove", "jagged_peaks", "ocean"],
            "probe_surfaces": True,
            "include_biome_map": False,
            "max_seconds": 180,
        })
        self.assertEqual(result["source"], "official_minecraft_java_server")
        self.assertEqual(result["status"], "generated_chunks_confirmed", result["failures"])
        locations = {item["name"]: item for item in result["locations"]}
        for name, location in locations.items():
            self.assertEqual(location["surface"]["status"], "surface_probed", name)
        self.assertEqual(locations["village"]["coordinates"], {"x": 48, "z": 16})
        self.assertEqual(locations["village"]["surface"]["coordinates"]["y"], 91)
        self.assertEqual(locations["pillager_outpost"]["surface"]["coordinates"]["y"], 118)
        self.assertTrue(locations["village"]["surface"]["safe_teleport"])
        self.assertTrue(locations["pillager_outpost"]["surface"]["safe_teleport"])
        self.assertEqual(locations["ocean"]["surface"]["coordinates"]["y"], 63)
        self.assertTrue(locations["ocean"]["surface"]["is_water"])
        self.assertFalse(locations["ocean"]["surface"]["safe_teleport"])
        for name in ("village", "pillager_outpost"):
            self.assertEqual(locations[name]["verification_status"], "generated_chunks_confirmed")
            evidence = locations[name]["structure_start"]
            self.assertEqual(evidence["status"], "confirmed")
            self.assertEqual(evidence["data_version"], 3955)
            self.assertGreater(evidence["piece_count"], 0)
        self.assertEqual(locations["cherry_grove"]["verification_status"], "minecraft_located")

    def test_surface_probe_waits_and_requires_positive_clearance(self):
        class DelayedConsole:
            def __init__(self):
                self.loads = 0
                self.positions = 0

            def command(self, command, deadline):
                if "if loaded" in command and "DREAMSEED_LOADED_" in command:
                    self.loads += 1
                    return [] if self.loads == 1 else [command.rsplit("run say ", 1)[1]]
                if "data get entity" in command:
                    self.positions += 1
                    if self.positions == 1:
                        return ["No entity was found"]
                    return ["Marker has the following entity data: [48.5d, 91.0d, 16.5d]"]
                if "unless predicate" in command and "DREAMSEED_FLUID_" in command:
                    return [command.rsplit("run say ", 1)[1]]
                return []

        console = DelayedConsole()
        result = MinecraftVerifier()._probe_surface(console, 48, 16, time.monotonic() + 5)
        self.assertEqual(result["status"], "surface_probed")
        self.assertEqual(console.loads, 2)
        self.assertEqual(console.positions, 2)
        self.assertFalse(result["safe_teleport"])

    def test_fluid_queries_require_mutually_exclusive_controls(self):
        class Console:
            def __init__(self, positive, negative):
                self.positive, self.negative = positive, negative

            def command(self, command, deadline):
                passes = self.negative if "unless predicate" in command else self.positive
                return [command.rsplit("run say ", 1)[1]] if passes else []

        for positive, negative, expected in ((True, False, True), (False, True, False), (False, False, None), (True, True, None)):
            self.assertIs(MinecraftVerifier._fluid_present(Console(positive, negative), 0, 64, 0, "water", time.monotonic() + 1), expected)

    def test_official_fluid_surface_controls_when_enabled(self):
        if os.environ.get("DREAMSEED_RUN_MINECRAFT_INTEGRATION") != "1":
            self.skipTest("official Minecraft integration was not requested")
        for version in ("1.21.1", "1.21.3"):
            self.assertTrue(installation_status(verify_hash=True, minecraft_version=version)["available"])
            verifier = MinecraftVerifier()
            original = verifier._probe_surface
            controls = []

            def check_controlled_columns(console, x, z, deadline):
                cases = (
                    ("minecraft:stone", "minecraft:stone", False, False, True),
                    ("minecraft:seagrass", "minecraft:stone", True, False, False),
                    ("minecraft:bubble_column", "minecraft:soul_sand", True, False, False),
                    ("minecraft:oak_slab[waterlogged=true,type=bottom]", "minecraft:stone", True, False, False),
                    ("minecraft:lava", "minecraft:stone", False, True, False),
                )
                for index, (block, support, water, lava, safe) in enumerate(cases):
                    cx, cz = 64 + 16 * index, 64
                    verifier._load_chunk(console, cx, cz, deadline)
                    console.command(f"fill {cx} -64 {cz} {cx} 319 {cz} minecraft:air", deadline)
                    console.command(f"setblock {cx} 249 {cz} {support}", deadline)
                    console.command(f"setblock {cx} 250 {cz} {block}", deadline)
                    token = f"DREAMSEED_CONTROL_{index}"
                    present = console.command(f"execute if block {cx} 250 {cz} {block} run say {token}", deadline)
                    self.assertTrue(any(token in line for line in present), (version, block, present))
                    probed = original(console, cx, cz, deadline)
                    self.assertEqual(probed["status"], "surface_probed", (version, block, probed))
                    self.assertEqual(probed["coordinates"]["y"], 251)
                    self.assertEqual(probed["is_water"], water, (version, block, probed))
                    self.assertEqual(probed["is_lava"], lava, (version, block, probed))
                    self.assertEqual(probed["safe_teleport"], safe, (version, block, probed))
                    controls.append(block)
                return original(console, x, z, deadline)

            try:
                with patch.object(verifier, "_probe_surface", side_effect=check_controlled_columns):
                    verifier.verify({
                        "minecraft_version": version, "seed": "0", "reference_point": {"x": 0, "y": 64, "z": 0},
                        "structures": ["village"], "biomes": [], "confirm_structure_starts": False,
                        "probe_surfaces": True, "max_seconds": 120,
                    })
                self.assertEqual(len(controls), 5)
            finally:
                verifier.shutdown()


if __name__ == "__main__":
    unittest.main()
