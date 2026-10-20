#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
"$project_dir/build/dreamseed" search --config "$project_dir/examples/benchmark_village.json" |
python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"candidates_evaluated":d["candidates_evaluated"],"elapsed_seconds":d["elapsed_seconds"],"candidates_per_second":round(d["candidates_evaluated"]/d["elapsed_seconds"]),"strategy":d["search_strategy"],"coverage":d["coverage"]},indent=2))'
