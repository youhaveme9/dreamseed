from __future__ import annotations

import argparse
import json
import platform
import random
import statistics
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Measure CPU and Metal placement filtering over identical full seeds")
    parser.add_argument("--binary", type=Path, default=Path("build/dreamseed"))
    parser.add_argument("--candidates", type=int, default=50000)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.candidates <= 100000 or not 1 <= args.repeats <= 20:
        parser.error("candidates must be 1 to 100000; repeats must be 1 to 20")
    binary = str(args.binary.resolve())
    capabilities = json.loads(subprocess.check_output([binary, "capabilities"], text=True))
    randomizer = random.Random(20261020)
    request = {"minecraft_version": "1.21.3", "seeds": [str(randomizer.randrange(-(1 << 63), 1 << 63)) for _ in range(args.candidates)],
               "hard_constraints": [{"id": "v", "type": "structure_within", "structure": "village", "radius": 500}], "max_seconds": 120}
    report = {"platform": platform.platform(), "device": capabilities["placement_prefilter"]["metal_device"],
              "candidates": args.candidates, "radius": 500, "results": {}, "timing_includes_metal_pipeline_initialization": True}
    expected = None
    for backend, available in capabilities["placement_prefilter"]["backends"].items():
        if not available:
            continue
        timings = []
        for _ in range(args.repeats):
            request["backend"] = backend
            result = subprocess.run([binary, "filter", "--config", "-"], input=json.dumps(request), capture_output=True,
                                    text=True, timeout=130, check=True)
            result = json.loads(result.stdout)
            if result["state"] != "completed":
                raise RuntimeError("benchmark did not exhaust the provided seeds")
            if expected is not None and result["survivor_seeds"] != expected:
                raise RuntimeError("CPU and GPU placement decisions disagree")
            expected = result["survivor_seeds"]
            timings.append(result["elapsed_seconds"])
        report["results"][backend] = {"seconds": timings, "median_candidates_per_second": args.candidates / statistics.median(timings),
                                      "placement_survivors": len(expected)}
    report["identical_results"] = True
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
