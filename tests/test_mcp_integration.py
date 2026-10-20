import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


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
            self.assertEqual(len(tools.tools), 9)
            capabilities = await client.call_tool("get_search_capabilities", {})
            self.assertFalse(capabilities.is_error)
            self.assertEqual(capabilities.structured_content["capabilities"]["engine"], "DreamSeed")
            self.assertTrue(capabilities.structured_content["capabilities"]["job_storage"]["persistent"])
            self.assertEqual(
                capabilities.structured_content["capabilities"]["authoritative_verification"]["source"],
                "official_minecraft_java_server",
            )

    def test_stdio_tools_use_native_engine(self):
        asyncio.run(self.run_flow())

    def test_job_recovery_across_server_restart(self):
        asyncio.run(self.run_recovery_flow())

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
                self.assertEqual(len(tools.tools), 9)
                by_name = {tool.name: tool for tool in tools.tools}
                self.assertFalse(by_name["start_seed_search"].input_schema["$defs"]["SearchRequest"]["additionalProperties"])
                self.assertFalse(by_name["get_search_results"].output_schema["additionalProperties"])
                capabilities = await session.call_tool("get_search_capabilities", {})
                self.assertFalse(capabilities.is_error)
                self.assertEqual(capabilities.structured_content["capabilities"]["minecraft_versions"], ["1.21.1"])

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
