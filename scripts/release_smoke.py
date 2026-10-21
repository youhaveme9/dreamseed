from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters


TOOLS = {
    "get_search_capabilities", "start_seed_search", "get_search_status",
    "get_search_results", "cancel_seed_search", "inspect_seed", "compare_seeds",
    "verify_seed_with_minecraft", "verify_seed_candidate", "render_seed_map", "analyze_seed_terrain",
}


async def main() -> None:
    import dreamseed_mcp
    from dreamseed_mcp.versions import SUPPORTED_VERSIONS

    package_file = Path(dreamseed_mcp.__file__).resolve()
    if "site-packages" not in package_file.parts:
        raise RuntimeError("release smoke test did not import the installed wheel")
    params = StdioServerParameters(command=str(Path(sys.executable).parent / "dreamseed-mcp"), env=dict(os.environ))
    async with Client(params) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} == TOOLS

        async def call(name: str, arguments: dict) -> dict:
            result = await client.call_tool(name, arguments)
            assert not result.is_error, (name, result)
            content = result.structured_content
            assert content["ok"], (name, content)
            return content

        caps = (await call("get_search_capabilities", {}))["capabilities"]
        assert caps["engine_version"] == dreamseed_mcp.__version__
        assert caps["minecraft_versions"] == list(SUPPORTED_VERSIONS)
        verification_caps = caps["authoritative_verification"]
        assert verification_caps["structure_start_inspection"]["supported"]
        assert set(verification_caps["structure_targets"]) == set(caps["structure_filters"]["types"])
        request = {
            "minecraft_version": "1.21.1",
            "hard_constraints": [
                {"id": "plains", "type": "biome_at", "biome": "plains", "y": 64},
                {"id": "village", "type": "structure_within", "structure": "village", "radius": 500},
            ],
            "budget": {"strategy": "sequential", "start_seed": "2579", "max_candidates": 1, "workers": 1, "max_seconds": 5},
            "max_results": 1,
        }
        job = await call("start_seed_search", {"request": request})
        for _ in range(200):
            status = await call("get_search_status", {"job_id": job["job_id"]})
            if status["state"] not in {"queued", "running", "cancelling"}:
                break
            await asyncio.sleep(0.05)
        assert status["state"] == "completed", status
        results = await call("get_search_results", {"job_id": job["job_id"]})
        assert results["results"][0]["seed"] == "2579"
        assert results["results"][0]["validation_status"] == "cubiomes_predicted"
        inspect_request = {
            "minecraft_version": "1.21.1", "seed": "2579",
            "area": {"radius": 64, "sample_step": 16, "y": 64},
            "structures": caps["structure_filters"]["types"], "include_biome_map": True,
        }
        inspection = (await call("inspect_seed", {"request": inspect_request}))["inspection"]
        assert inspection["biome_map"]["width"] == 9
        comparison = await call("compare_seeds", {"request": {
            "minecraft_version": "1.21.1", "seeds": ["2579", "0"],
            "hard_constraints": request["hard_constraints"],
        }})
        assert comparison["comparison"]["results"][0]["seed"] == "2579"
        render = await call("render_seed_map", {"request": {
            "minecraft_version": "1.21.1", "seed": "2579",
            "area": {"radius": 64, "sample_step": 16}, "structures": ["village"],
        }})
        assert render["rendering"]["svg"].startswith("<svg")
        running = await call("start_seed_search", {"request": {
            "minecraft_version": "1.21.1",
            "hard_constraints": [{"id": "cherry", "type": "biome_within", "biome": "cherry_grove", "radius": 1024, "sample_step": 4}],
            "budget": {"strategy": "sequential", "start_seed": "0", "max_candidates": 1_000_000, "max_seconds": 60, "workers": 1},
            "max_results": 1,
        }})
        cancelled = await call("cancel_seed_search", {"job_id": running["job_id"]})
        assert cancelled["state"] == "cancelled"
        verification = await client.call_tool("verify_seed_with_minecraft", {"request": {
            "minecraft_version": "1.21.1", "seed": "2579", "structures": ["village"], "max_seconds": 30,
        }})
        assert not verification.structured_content["ok"]
        assert verification.structured_content["error"]["code"] == "minecraft_verifier_unavailable"
        candidate = await client.call_tool("verify_seed_candidate", {"request": {
            "minecraft_version": "1.21.1", "seed": "2579",
            "hard_constraints": request["hard_constraints"], "probe_surfaces": False, "max_seconds": 30,
        }})
        assert not candidate.structured_content["ok"]
        assert candidate.structured_content["error"]["code"] == "minecraft_verifier_unavailable"
        terrain = await client.call_tool("analyze_seed_terrain", {"request": {
            "minecraft_version": "1.21.3", "seed": "2579", "area": {"radius": 0}, "max_seconds": 30,
        }})
        assert not terrain.structured_content["ok"]
        assert terrain.structured_content["error"]["code"] == "minecraft_verifier_unavailable"
    async with Client(params) as client:
        recovered = await client.call_tool("get_search_results", {"job_id": job["job_id"]})
        assert recovered.structured_content["results"][0]["seed"] == "2579"
        assert recovered.structured_content["recovered"]
    print(json.dumps({"ok": True, "version": dreamseed_mcp.__version__, "tools_tested": len(TOOLS), "seed": "2579", "job_recovery": True}))


if __name__ == "__main__":
    asyncio.run(main())
