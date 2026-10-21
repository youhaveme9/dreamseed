import asyncio
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dreamseed_mcp.minecraft_setup import configured_server_jar, installation_status
from dreamseed_mcp.versions import SUPPORTED_VERSIONS


ROOT = Path(__file__).resolve().parents[1]


class McpIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.state.cleanup()

    def parameters(self):
        return StdioServerParameters(
            command=str(ROOT / ".venv" / "bin" / "python"),
            args=[str(ROOT / "mcp" / "server.py")],
            cwd=str(ROOT),
            env={
                "DREAMSEED_BINARY": os.environ.get("DREAMSEED_BINARY", str(ROOT / "build" / "dreamseed")),
                "DREAMSEED_STATE_DIR": self.state.name,
                "DREAMSEED_MINECRAFT_SERVER_JAR": str(Path(self.state.name) / "missing-server.jar"),
                "DREAMSEED_ACCEPT_MOJANG_EULA": "true",
            },
        )

    def test_modern_stdio_discovery(self):
        asyncio.run(self.run_modern_flow())

    async def run_modern_flow(self):
        async with Client(self.parameters()) as client:
            self.assertEqual(client.protocol_version, "2026-07-28")
            tools = await client.list_tools()
            self.assertEqual(len(tools.tools), 11)
            capabilities = await client.call_tool("get_search_capabilities", {})
            self.assertFalse(capabilities.is_error)
            self.assertEqual(capabilities.structured_content["capabilities"]["engine"], "DreamSeed")
            self.assertTrue(capabilities.structured_content["capabilities"]["job_storage"]["persistent"])
            self.assertEqual(
                capabilities.structured_content["capabilities"]["authoritative_verification"]["source"],
                "official_minecraft_java_server",
            )
            caps = capabilities.structured_content["capabilities"]
            verifier = caps["authoritative_verification"]
            self.assertTrue(verifier["structure_start_inspection"]["supported"])
            self.assertFalse(verifier["structure_start_inspection"]["all_structure_blocks_checked"])
            self.assertEqual(set(verifier["structure_targets"]), set(caps["structure_filters"]["types"]))

    def test_stdio_tools_use_native_engine(self):
        asyncio.run(self.run_flow())

    def test_structure48_metrics_through_mcp(self):
        asyncio.run(self.run_structure48_flow())

    async def run_structure48_flow(self):
        request = json.loads((ROOT / "examples/structure48.json").read_text())
        request["budget"].update(max_candidates=2048, upper_bits_per_structure_seed=64)
        async with Client(self.parameters()) as client:
            await client.list_tools()
            started = await client.call_tool("start_seed_search", {"request": request})
            self.assertTrue(started.structured_content["ok"], started.structured_content)
            job_id = started.structured_content["job_id"]
            for _ in range(200):
                status = await client.call_tool("get_search_status", {"job_id": job_id})
                if status.structured_content["state"] not in {"queued", "running", "cancelling"}:
                    break
                await asyncio.sleep(0.05)
            self.assertEqual(status.structured_content["state"], "completed")
            result = await client.call_tool("get_search_results", {"job_id": job_id})
            data = result.structured_content
            self.assertEqual(data["coverage"], "sampled_structure_seed_batches")
            self.assertGreater(data["placement_filter"]["cache_reuses"], 0)
            self.assertGreater(len(data["results"]), 0)

    def test_job_recovery_across_server_restart(self):
        asyncio.run(self.run_recovery_flow())

    def test_official_structure_starts_through_mcp_when_enabled(self):
        if os.environ.get("DREAMSEED_RUN_MINECRAFT_INTEGRATION") != "1":
            self.skipTest("official Minecraft integration was not requested")
        status = installation_status(verify_hash=True)
        if not status["available"]:
            self.skipTest(status["detail"])
        asyncio.run(self.run_official_structure_flow())

    def test_official_1_21_3_structures_through_mcp_when_enabled(self):
        if os.environ.get("DREAMSEED_RUN_MINECRAFT_INTEGRATION") != "1":
            self.skipTest("official Minecraft integration was not requested")
        status = installation_status(verify_hash=True, minecraft_version="1.21.3")
        if not status["available"]:
            self.skipTest(status["detail"])
        asyncio.run(self.run_official_structure_flow("1.21.3"))

    def test_official_terrain_and_preview_through_mcp_when_enabled(self):
        if os.environ.get("DREAMSEED_RUN_MINECRAFT_INTEGRATION") != "1":
            self.skipTest("official Minecraft integration was not requested")
        self.assertTrue(installation_status(verify_hash=True, minecraft_version="1.21.3")["available"])
        asyncio.run(self.run_official_terrain_flow())

    def test_official_igloo_templates_through_mcp_when_enabled(self):
        if os.environ.get("DREAMSEED_RUN_MINECRAFT_INTEGRATION") != "1":
            self.skipTest("official Minecraft integration was not requested")
        asyncio.run(self.run_official_igloo_flow())

    async def run_official_igloo_flow(self):
        fixture = json.loads((ROOT / "tests/fixtures/igloo_template_blocks.json").read_text())
        params = self.parameters()
        params.env = dict(os.environ) | params.env
        params.env.pop("DREAMSEED_MINECRAFT_SERVER_JAR", None)
        params.env["DREAMSEED_ACCEPT_MOJANG_EULA"] = os.environ.get("DREAMSEED_ACCEPT_MOJANG_EULA", "")
        async with Client(params) as client:
            await client.list_tools()
            for expected in fixture["cases"]:
                with self.subTest(seed=expected["seed"], version=expected["minecraft_version"]):
                    request = json.loads((ROOT / "examples/verify_igloo_blocks.json").read_text())
                    request.update(seed=expected["seed"], minecraft_version=expected["minecraft_version"])
                    response = await client.call_tool("verify_seed_with_minecraft", {"request": request}, read_timeout_seconds=150)
                    self.assertTrue(response.structured_content["ok"], response.structured_content)
                    result = response.structured_content["verification"]
                    self.assertEqual(result["status"], "template_blocks_confirmed", result["failures"])
                    feature = result["locations"][0]
                    self.assertEqual((feature["coordinates"]["x"], feature["coordinates"]["z"]), (expected["x"], expected["z"]))
                    blocks = feature["block_verification"]
                    self.assertEqual(blocks["checked_blocks"], expected["blocks"])
                    self.assertEqual(blocks["matched_blocks"], expected["blocks"])
                    self.assertEqual(blocks["piece_count"], expected["pieces"])
                    self.assertEqual(blocks["rotations"], [expected["rotation"]])
                    self.assertEqual(blocks["mismatch_count"], 0)
                    self.assertEqual(blocks["observed_sha256"], expected["sha256"])
                    self.assertEqual(blocks["expected_sha256"], blocks["observed_sha256"])
                    self.assertFalse(blocks["block_entities_checked"])

    async def run_official_terrain_flow(self):
        params = self.parameters()
        params.env = dict(os.environ) | params.env
        params.env["DREAMSEED_MINECRAFT_SERVER_JAR"] = str(configured_server_jar("1.21.3"))
        params.env["DREAMSEED_ACCEPT_MOJANG_EULA"] = os.environ.get("DREAMSEED_ACCEPT_MOJANG_EULA", "")
        fixture = json.loads((ROOT / "tests/fixtures/java_1_21_3_terrain.json").read_text())
        request = json.loads((ROOT / "examples/analyze_terrain.json").read_text())
        async with Client(params) as client:
            await client.list_tools()
            response = await client.call_tool("analyze_seed_terrain", {"request": request}, read_timeout_seconds=150)
            self.assertTrue(response.structured_content["ok"], response.structured_content)
            terrain = response.structured_content["terrain"]
            self.assertEqual(terrain["grid"]["status"], "generated_terrain_confirmed")
            self.assertEqual(terrain["grid"]["origin"], fixture["origin"])
            self.assertEqual([[cell["surface_y"] for cell in row] for row in terrain["grid"]["rows"]], fixture["surface_y_rows"])
            self.assertTrue(terrain["control_heights_match"])
            self.assertEqual([probe["coordinates"] for probe in terrain["control_probes"]], fixture["control_coordinates"])
            for state in fixture["surface_states"]:
                self.assertEqual(terrain["grid"]["rows"][state["row"]][state["column"]]["surface_block"], state["name"])
            for metric, expected in fixture["metrics"].items():
                self.assertAlmostEqual(terrain["analysis"]["metrics"][metric], expected)
            self.assertAlmostEqual(terrain["analysis"]["score"], fixture["preference_score"])
            self.assertEqual(terrain["preview"]["mesh"]["vertex_count"], fixture["vertex_count"])
            self.assertEqual(terrain["preview"]["mesh"]["triangle_count"], fixture["triangle_count"])
            self.assertTrue(any(block.type == "image" for block in response.content))
            request.update(area={"center": {"x": 1440, "z": 288}, "radius": 0, "sample_step": 16}, preferences=[])
            ocean_response = await client.call_tool("analyze_seed_terrain", {"request": request}, read_timeout_seconds=150)
            self.assertTrue(ocean_response.structured_content["ok"], ocean_response.structured_content)
            ocean = ocean_response.structured_content["terrain"]
            cell = ocean["grid"]["rows"][0][0]
            self.assertEqual(cell["surface_y"], 63)
            self.assertTrue(cell["is_water"])
            self.assertEqual(cell["surface_block"], "minecraft:water")
            self.assertGreater(cell["water_depth"], 0)
            self.assertTrue(ocean["control_heights_match"])
            self.assertFalse(ocean["control_probes"][0]["safe_teleport"])
        params.env["DREAMSEED_MINECRAFT_SERVER_JAR"] = str(configured_server_jar("1.21.1"))
        async with Client(params) as client:
            await client.list_tools()
            request.update(minecraft_version="1.21.1", area={"center": {"x": 48, "z": 16}, "radius": 0, "sample_step": 16})
            response = await client.call_tool("analyze_seed_terrain", {"request": request}, read_timeout_seconds=150)
            self.assertTrue(response.structured_content["ok"], response.structured_content)
            terrain = response.structured_content["terrain"]
            self.assertEqual(terrain["grid"]["rows"][0][0]["surface_y"], 91)
            self.assertEqual(terrain["grid"]["rows"][0][0]["surface_block"], "minecraft:oak_slab")
            self.assertTrue(terrain["control_heights_match"])

    async def run_official_structure_flow(self, minecraft_version="1.21.1"):
        params = self.parameters()
        params.env = dict(os.environ) | params.env
        params.env["DREAMSEED_MINECRAFT_SERVER_JAR"] = str(configured_server_jar(minecraft_version))
        params.env["DREAMSEED_ACCEPT_MOJANG_EULA"] = os.environ.get("DREAMSEED_ACCEPT_MOJANG_EULA", "")
        fixture = json.loads((ROOT / f"tests/fixtures/java_{minecraft_version.replace('.', '_')}_seed_0_structures.json").read_text())
        request = json.loads((ROOT / "examples/verify_all_structures.json").read_text())
        request["minecraft_version"] = minecraft_version
        request.update({
            "include_biome_map": True,
            "map_area": {"center": {"x": 0, "z": 0}, "radius": 512, "sample_step": 64, "y": 64},
        })
        async with Client(params) as client:
            await client.list_tools()
            result = await client.call_tool("verify_seed_with_minecraft", {"request": request}, read_timeout_seconds=330)
            self.assertFalse(result.is_error)
            self.assertTrue(result.structured_content["ok"], result.structured_content)
            verified = result.structured_content["verification"]
            self.assertEqual(verified["status"], "generated_chunks_confirmed", verified["failures"])
            self.assertEqual(verified["failures"], [])
            locations = {location["name"]: location for location in verified["locations"]}
            self.assertEqual(len(locations), 10)
            for expected in fixture["structures"]:
                with self.subTest(name=expected["name"]):
                    location = locations[expected["name"]]
                    self.assertEqual(location["verification_status"], "generated_chunks_confirmed")
                    self.assertEqual((location["coordinates"]["x"], location["coordinates"]["z"]), (expected["x"], expected["z"]))
                    evidence = location["structure_start"]
                    self.assertEqual(evidence["structure_id"], expected["structure_id"])
                    self.assertEqual(evidence["piece_count"], expected["piece_count"])
                    self.assertEqual(evidence["chunk_status"], "minecraft:full")
                    self.assertEqual(evidence["data_version"], fixture["data_version"])
                    self.assertRegex(evidence["chunk_sha256"], r"^[0-9a-f]{64}$")
            self.assertIn("#087f8c", verified["rendering"]["svg"])
            self.assertTrue(any(block.type == "image" for block in result.content))

    def test_official_candidate_constraints_through_mcp_when_enabled(self):
        if os.environ.get("DREAMSEED_RUN_MINECRAFT_INTEGRATION") != "1":
            self.skipTest("official Minecraft integration was not requested")
        status = installation_status(verify_hash=True)
        if not status["available"]:
            self.skipTest(status["detail"])
        asyncio.run(self.run_official_candidate_flow())

    def test_official_1_21_3_candidate_through_mcp_when_enabled(self):
        if os.environ.get("DREAMSEED_RUN_MINECRAFT_INTEGRATION") != "1":
            self.skipTest("official Minecraft integration was not requested")
        status = installation_status(verify_hash=True, minecraft_version="1.21.3")
        if not status["available"]:
            self.skipTest(status["detail"])
        asyncio.run(self.run_official_candidate_flow("1.21.3"))

    async def run_official_candidate_flow(self, minecraft_version="1.21.1"):
        params = self.parameters()
        params.env = dict(os.environ) | params.env
        params.env["DREAMSEED_MINECRAFT_SERVER_JAR"] = str(configured_server_jar(minecraft_version))
        params.env["DREAMSEED_ACCEPT_MOJANG_EULA"] = os.environ.get("DREAMSEED_ACCEPT_MOJANG_EULA", "")
        request = json.loads((ROOT / "examples/verify_seed_candidate.json").read_text())
        request["minecraft_version"] = minecraft_version
        fixture = json.loads((ROOT / f"tests/fixtures/java_{minecraft_version.replace('.', '_')}_candidate_verification.json").read_text())
        async with Client(params) as client:
            await client.list_tools()
            result = await client.call_tool("verify_seed_candidate", {"request": request}, read_timeout_seconds=210)
            self.assertFalse(result.is_error)
            self.assertTrue(result.structured_content["ok"], result.structured_content)
            checked = result.structured_content["verification"]
            self.assertEqual(checked["status"], "verified")
            self.assertTrue(checked["all_hard_constraints_verified"])
            self.assertEqual(checked["validation_scope"], "selected_candidate_witnesses")
            self.assertEqual(len(checked["constraint_checks"]), 6)
            self.assertTrue(all(item["status"] == "verified" for item in checked["constraint_checks"]))
            self.assertEqual(checked["constraint_checks"][1]["required_count"], 2)
            self.assertEqual(checked["constraint_checks"][1]["verified_count"], 3)
            features = {(item["kind"], item["name"], item["coordinates"]["x"], item["coordinates"]["z"]): item for item in checked["features"]}
            self.assertEqual(len(features), len(fixture["features"]))
            for expected in fixture["features"]:
                with self.subTest(expected=expected):
                    feature = features[expected["kind"], expected["name"], expected["x"], expected["z"]]
                    self.assertAlmostEqual(feature["distance_from_reference"], math.hypot(expected["x"], expected["z"]))
                    if expected["kind"] == "biome":
                        self.assertEqual(feature["verification_status"], "minecraft_biome_checked")
                        self.assertTrue(feature["biome_matches"])
                        self.assertEqual(feature["coordinates"]["y"], expected["y"])
                    else:
                        self.assertEqual(feature["verification_status"], "generated_chunks_confirmed")
                        self.assertEqual(feature["structure_start"]["piece_count"], expected["piece_count"])
            for pair in checked["spatial_checks"]:
                self.assertAlmostEqual(pair["measured_distance"], fixture["pair_distances"][pair["constraint_id"]])
            self.assertAlmostEqual(checked["soft_preference_score"], fixture["soft_preference_score"])
            self.assertEqual(checked["failures"], [])

    async def run_recovery_flow(self):
        request = json.loads((ROOT / "examples" / "village_search.json").read_text())
        async with Client(self.parameters()) as first_client:
            started = await first_client.call_tool("start_seed_search", {"request": request})
            job_id = started.structured_content["job_id"]
            for _ in range(200):
                status = await first_client.call_tool("get_search_status", {"job_id": job_id})
                if status.structured_content["state"] == "completed":
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(status.structured_content["state"], "completed")

        async with Client(self.parameters()) as second_client:
            recovered = await second_client.call_tool("get_search_status", {"job_id": job_id})
            self.assertEqual(recovered.structured_content["state"], "completed")
            self.assertTrue(recovered.structured_content["recovered"])
            results = await second_client.call_tool("get_search_results", {"job_id": job_id})
            self.assertEqual(results.structured_content["results"][0]["seed"], "659")

    async def run_flow(self):
        async with stdio_client(self.parameters()) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                self.assertEqual(len(tools.tools), 11)
                by_name = {tool.name: tool for tool in tools.tools}
                self.assertFalse(by_name["start_seed_search"].input_schema["$defs"]["SearchRequest"]["additionalProperties"])
                self.assertFalse(by_name["get_search_results"].output_schema["additionalProperties"])
                verification_schema = by_name["verify_seed_with_minecraft"].input_schema["$defs"]["MinecraftVerificationRequest"]
                self.assertTrue(verification_schema["properties"]["confirm_structure_starts"]["default"])
                self.assertEqual(verification_schema["properties"]["structures"]["maxItems"], 10)
                capabilities = await session.call_tool("get_search_capabilities", {})
                self.assertFalse(capabilities.is_error)
                self.assertEqual(capabilities.structured_content["capabilities"]["minecraft_versions"], list(SUPPORTED_VERSIONS))

                request = json.loads((ROOT / "examples" / "village_cherry_search.json").read_text())
                started = await session.call_tool("start_seed_search", {"request": request})
                job_id = started.structured_content["job_id"]
                for _ in range(200):
                    status = await session.call_tool("get_search_status", {"job_id": job_id})
                    if status.structured_content["state"] not in {"queued", "running", "cancelling"}:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(status.structured_content["state"], "completed")
                results = await session.call_tool("get_search_results", {"job_id": job_id})
                result = results.structured_content["results"][0]
                self.assertEqual(result["seed"], "8009581673339289650")
                self.assertEqual(len(result["satisfied_hard_constraints"]), 4)
                self.assertLessEqual(result["spatial_checks"][0]["measured_distance"], 100)
                self.assertTrue(results.structured_content["persisted"])

                inspection = await session.call_tool("inspect_seed", {"request": {
                    "minecraft_version": "1.21.1",
                    "seed": "7810500614729040739",
                    "area": {"center": {"x": 0, "z": 0}, "radius": 64,
                             "sample_step": 16, "y": 64},
                    "structures": ["village", "pillager_outpost"],
                    "include_biome_map": True,
                }})
                self.assertFalse(inspection.is_error)
                biome_map = inspection.structured_content["inspection"]["biome_map"]
                self.assertEqual((biome_map["width"], biome_map["height"]), (9, 9))

                rendering = await session.call_tool("render_seed_map", {"request": {
                    "minecraft_version": "1.21.1",
                    "seed": "7810500614729040739",
                    "area": {"center": {"x": 0, "z": 0}, "radius": 64,
                             "sample_step": 16, "y": 64},
                    "structures": ["village"],
                }})
                self.assertFalse(rendering.is_error)
                self.assertEqual(rendering.structured_content["rendering"]["format"], "svg")
                self.assertIn("<svg", rendering.structured_content["rendering"]["svg"])
                image_blocks = [block for block in rendering.content if block.type == "image"]
                self.assertEqual(len(image_blocks), 1)
                self.assertEqual(image_blocks[0].mime_type, "image/svg+xml")

                verification = await session.call_tool("verify_seed_with_minecraft", {"request": {
                    "minecraft_version": "1.21.1",
                    "seed": "7810500614729040739",
                    "structures": ["village"],
                    "probe_surfaces": False,
                    "max_seconds": 30,
                }})
                self.assertFalse(verification.is_error)
                self.assertFalse(verification.structured_content["ok"])
                self.assertEqual(
                    verification.structured_content["error"]["code"],
                    "minecraft_verifier_unavailable",
                )
                candidate = await session.call_tool("verify_seed_candidate", {"request": {
                    "minecraft_version": "1.21.1", "seed": "2579",
                    "hard_constraints": [{"id": "v", "type": "structure_within", "structure": "village", "radius": 500}],
                    "probe_surfaces": False, "max_seconds": 30,
                }})
                self.assertFalse(candidate.structured_content["ok"])
                self.assertEqual(candidate.structured_content["error"]["code"], "minecraft_verifier_unavailable")

                comparison = await session.call_tool("compare_seeds", {"request": {
                    "minecraft_version": "1.21.1",
                    "seeds": ["2579", "0"],
                    "hard_constraints": [
                        {"id": "origin", "type": "biome_at", "biome": "plains",
                         "coordinate": {"x": 0, "z": 0}, "y": 64},
                    ],
                }})
                self.assertFalse(comparison.is_error)
                self.assertEqual(comparison.structured_content["comparison"]["comparison_count"], 2)

                long_request = {
                    "minecraft_version": "1.21.1",
                    "hard_constraints": [
                        {"id": "cherry", "type": "biome_within", "biome": "cherry_grove",
                         "radius": 1024, "sample_step": 4, "y": 64},
                    ],
                    "budget": {"strategy": "sequential", "start_seed": "0",
                               "max_candidates": 1000000, "max_seconds": 60, "workers": 1},
                    "max_results": 1,
                }
                running = await session.call_tool("start_seed_search", {"request": long_request})
                cancelled = await session.call_tool(
                    "cancel_seed_search", {"job_id": running.structured_content["job_id"]}
                )
                self.assertEqual(cancelled.structured_content["state"], "cancelled")

                invalid = await session.call_tool("get_search_status", {"job_id": "bad"})
                self.assertFalse(invalid.is_error)
                self.assertFalse(invalid.structured_content["ok"])
                self.assertEqual(invalid.structured_content["error"]["code"], "invalid_job_id")


if __name__ == "__main__":
    unittest.main()
