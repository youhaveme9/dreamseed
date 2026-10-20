import asyncio
import json
import unittest
from pathlib import Path

from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


class McpIntegrationTests(unittest.TestCase):
    def parameters(self):
        return StdioServerParameters(
            command=str(ROOT / ".venv" / "bin" / "python"),
            args=[str(ROOT / "mcp" / "server.py")],
            cwd=str(ROOT),
            env={"DREAMSEED_BINARY": str(ROOT / "build" / "dreamseed")},
        )

    def test_modern_stdio_discovery(self):
        asyncio.run(self.run_modern_flow())

    async def run_modern_flow(self):
        async with Client(self.parameters()) as client:
            self.assertEqual(client.protocol_version, "2026-07-28")
            tools = await client.list_tools()
            self.assertEqual(len(tools.tools), 7)
            capabilities = await client.call_tool("get_search_capabilities", {})
            self.assertFalse(capabilities.is_error)
            self.assertEqual(capabilities.structured_content["capabilities"]["engine"], "DreamSeed")

    def test_stdio_tools_use_native_engine(self):
        asyncio.run(self.run_flow())

    async def run_flow(self):
        async with stdio_client(self.parameters()) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                self.assertEqual(len(tools.tools), 7)
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


if __name__ == "__main__":
    unittest.main()
