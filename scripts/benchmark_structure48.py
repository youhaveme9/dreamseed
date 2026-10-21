"""Compare identical full seed cohorts with and without placement reuse."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path("build/dreamseed"))
    parser.add_argument("--candidates", type=int, default=100000)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20 or not 1 <= args.candidates <= 10_000_000:
        parser.error("repeats must be 1 to 20; candidates must be 1 to 10000000")
    binary = str(args.binary.resolve())
    report = {"platform": platform.platform(), "processor": platform.processor(), "workloads": []}
    for radius in (64, 500):
        request = {
            "minecraft_version": "1.21.3",
            "hard_constraints": [{"id": "v", "type": "structure_within", "structure": "village", "radius": radius}],
            "budget": {"strategy": "structure48", "sample_seed": "20261020", "workers": 1,
                       "upper_bits_per_structure_seed": 256, "max_candidates": args.candidates, "max_seconds": 120},
            "max_results": 3,
        }
        runs: dict[str, list[dict]] = {"cached": [], "uncached": []}
        expected = None
        for _ in range(args.repeats):
            for label, enabled in (("uncached", False), ("cached", True)):
                request["budget"]["placement_cache"] = enabled
                process = subprocess.run(
                    [binary, "search", "--config", "-"], input=json.dumps(request),
                    capture_output=True, text=True, check=True, timeout=130,
                )
                summary = json.loads(process.stdout)
                if summary["state"] != "completed":
                    raise RuntimeError("benchmark did not exhaust the candidate budget")
                evidence = (summary["results"], summary["matching_seeds_found"])
                if expected is not None and evidence != expected:
                    raise RuntimeError("cache changed seed evaluation results")
                expected = evidence
                runs[label].append(summary)
        workload = {"radius": radius, "candidates": args.candidates, "workers": 1,
                    "upper_bits_per_structure_seed": 256, "identical_results": True}
        for label, summaries in runs.items():
            seconds = [item["elapsed_seconds"] for item in summaries]
            median = statistics.median(seconds)
            workload[label] = {"seconds": seconds, "median_candidates_per_second": args.candidates / median,
                               "placement_filter": summaries[-1]["placement_filter"],
                               "matching_seeds_found": summaries[-1]["matching_seeds_found"]}
        report["workloads"].append(workload)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
