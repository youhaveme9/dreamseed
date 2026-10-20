# DreamSeed

DreamSeed finds Minecraft world seeds that satisfy structured biome and structure constraints. An MCP compatible AI client translates natural language into those constraints. DreamSeed performs all seed computation locally with Cubiomes. It contains no model inference, makes no model API calls, and needs no OpenAI or Anthropic API key.

DreamSeed searches for worlds that match a description. It does not recover the exact seed of an existing world from an arbitrary description.

## Status

This repository contains an unreleased release candidate for Minecraft Java Edition 1.21.1. The native engine, command line interface, MCP server, asynchronous job manager, Claude Code plugin, skill, tests, examples, benchmark, and continuous integration are implemented.

The selected version is pinned deliberately. Requests for any other version return an unsupported version error instead of applying the wrong generation rules.

## Architecture

```text
AI client
    |
    | MCP over stdio
    v
Python MCP server and job manager
    |
    | safe argument vector and JSON streams
    v
Native C plus plus engine and CLI
    |
    v
Pinned Cubiomes C library
```

The native library owns validation, filtering, distance measurement, scoring, inspection, and comparison. The CLI and MCP server call the same engine code. The MCP process reserves stdout for protocol messages. Diagnostics go to stderr.

Cubiomes is vendored at commit `e61f90580cbdd883214a8054670dacae655e59c0`. Its MIT license remains in `third_party/cubiomes/LICENSE`. The build fetches nlohmann JSON 3.11.3. See `THIRD_PARTY_NOTICES.md`.

The MCP layer uses the official Python SDK pinned to version 2.2.0.

## Supported operations

| Area | Current support |
| --- | --- |
| Edition | Java Edition |
| Version | 1.21.1 |
| Exact biome | A biome at an explicit X, Y, Z coordinate |
| Nearby biome | A biome found on a deterministic horizontal sample grid |
| Structures | Village, desert pyramid, jungle temple, swamp hut, igloo, ocean ruin, shipwreck, ocean monument, woodland mansion, and pillager outpost |
| Structure count | One through sixteen of one structure type within a radius |
| Spatial checks | Distance from an explicit anchor and maximum distance between two matched features |
| Ranking | Weighted distance minimization with a score from 0 through 100 |
| Search | Sequential defined range or deterministic sampled candidates |
| Inspection | Biome summary and supported structure positions in an area |
| Comparison | Up to 64 complete world seeds under one criteria set |

Supported search biome names are returned by `get_search_capabilities` and `dreamseed capabilities`. They include plains, desert, forest, cherry grove, meadow, grove, snowy slopes, jagged peaks, frozen peaks, stony peaks, and other common biomes.

All distances are horizontal Euclidean distance in blocks. An anchor defaults to X 0 and Z 0. This is the world origin, not the actual world spawn. DreamSeed never describes an origin relative result as spawn relative. Actual spawn checks are unsupported because Cubiomes warns that block material can affect its spawn result.

Minecraft world seeds are accepted and returned as signed 64 bit decimal strings. Structure placement first uses the lower 48 bits where Minecraft does, then biome checks use the complete 64 bit world seed. DreamSeed never returns a partial structure seed as a world seed.

## Validation meaning

A village result has a Cubiomes structure attempt and passes the implemented biome viability check.

A desert pyramid, jungle temple, or woodland mansion result has a Cubiomes structure attempt and passes biome viability plus Cubiomes terrain screening. Cubiomes does not provide the complete modern Overworld surface simulation needed to prove exact terrain generation. These results carry a terrain caveat.

Other supported structures pass their Cubiomes placement and structure specific viability checks. Coordinates identify generation attempt positions rather than building entrances. DreamSeed does not claim block level confirmation.

A nearby biome match is exact at its reported coordinate. The grid can miss a biome between sampled coordinates, so a rejected candidate can be a false negative. Reduce `sample_step` to 4 for denser coverage at greater cost.

## Search behavior

The engine performs structure placement filtering before creating a biome generator. It then runs exact biome checks, structure biome viability checks, nearby biome sampling, spatial relations, and scoring. Failed hard constraints reject a seed immediately.

`sequential` evaluates a contiguous range beginning at `start_seed`. When the complete candidate budget finishes, coverage is `exhaustive_requested_range`. This only describes that finite range.

`sampled` maps each candidate index through SplitMix64 with `sample_seed`. The same request produces the same candidate sequence. It does not prove anything about the global seed space.

Completed candidate budgets are reproducible. A time limited parallel search can finish a slightly different candidate prefix because worker scheduling varies. Use one worker or allow the candidate budget to complete when exact result reproducibility matters.

A timeout, cancellation, or empty bounded result never means that no matching seed exists globally.

## Build

Requirements are CMake 3.20 or newer, a C11 compiler, a C plus plus 20 compiler, Python 3.11 or newer, Git, Make, and internet access for the pinned JSON dependency during initial configuration.

On macOS, install the Xcode command line tools and CMake. On Debian or Ubuntu, install `build-essential`, `cmake`, `git`, `python3`, and `python3-venv`.

```sh
cd /path/to/dreamseed
make build
make venv
make test
```

The native binary is `build/dreamseed`. The Python environment is `.venv`.

## Native CLI

```sh
./build/dreamseed capabilities
./build/dreamseed validate --config examples/village_search.json
./build/dreamseed search --config examples/village_search.json
./build/dreamseed search --config examples/three_villages_search.json
./build/dreamseed search --config examples/desert_pyramid_search.json
./build/dreamseed search --config examples/pillager_outpost_search.json
./build/dreamseed search --config examples/multi_constraint_search.json
./build/dreamseed search --config examples/village_cherry_search.json
./build/dreamseed inspect --config examples/inspect_seed.json
./build/dreamseed compare --config examples/compare_seeds.json
```

Use `--config -` to read JSON from stdin. Use `--events` with search to receive newline delimited progress, match, and completion events. Resource settings live in the request budget and include candidate count, seconds, workers, strategy, and reproducibility seed.

The full constraint format is described in `docs/constraints.md`.

## MCP server

Run the local stdio server directly with:

```sh
DREAMSEED_BINARY=/absolute/path/to/dreamseed/build/dreamseed \
  /absolute/path/to/dreamseed/.venv/bin/python \
  /absolute/path/to/dreamseed/mcp/server.py
```

Do not type into this process manually. Its stdout is an MCP protocol stream.

The tools are `get_search_capabilities`, `start_seed_search`, `get_search_status`, `get_search_results`, `cancel_seed_search`, `inspect_seed`, and `compare_seeds`. Their input and output schemas are generated from strict Pydantic models.

At most two searches run concurrently in one server process. A native child process performs each search. Arguments use a fixed executable and argument vector with no shell. Completed jobs are retained in memory up to the configured job limit.

## Codex setup

Use absolute paths in this command:

```sh
codex mcp add \
  --env DREAMSEED_BINARY=/absolute/path/to/dreamseed/build/dreamseed \
  dreamseed -- \
  /absolute/path/to/dreamseed/.venv/bin/python \
  /absolute/path/to/dreamseed/mcp/server.py

codex mcp list
```

The Codex CLI and IDE extension share MCP configuration. This setup uses only a local stdio process and does not need an OpenAI API key.

## Claude Code setup

For a direct user scoped MCP registration:

```sh
claude mcp add --scope user \
  -e DREAMSEED_BINARY=/absolute/path/to/dreamseed/build/dreamseed \
  dreamseed -- \
  /absolute/path/to/dreamseed/.venv/bin/python \
  /absolute/path/to/dreamseed/mcp/server.py

claude mcp list
```

For plugin development, build the project and its virtual environment, then run:

```sh
claude plugin validate /absolute/path/to/dreamseed --strict
claude --plugin-dir /absolute/path/to/dreamseed
```

The plugin manifest is `.claude-plugin/plugin.json`. Its `.mcp.json` uses `CLAUDE_PLUGIN_ROOT`, and the skill is `skills/find-minecraft-seed/SKILL.md`. The plugin expects `build/dreamseed` and `.venv` inside its root.

For local use, the validated repository directory is the plugin package, so no archive step is required. A portable marketplace archive would need separate native binaries and Python environments for each platform and is not claimed by this MVP.

## Example conversation

Ask the client: `Find a Java 1.21.1 seed with plains at the origin and a village within 600 blocks. Prefer the closest village.`

The client should consult capabilities, construct the constraints, start a job, poll status, fetch results, and explain the returned validation status. If you then ask for two villages, it should change the village count while preserving the plains condition.

## Verified example

The committed sequential example examines seeds 0 through 9999. On the current pinned engine it finds seed `2579` with plains at X 0, Y 64, Z 0 and a biome viable village placement at X 0, Z 0. Both hard constraints are satisfied and the distance preference score is 100.

Reproduce it with:

```sh
./build/dreamseed search --config examples/multi_constraint_search.json
```

The structure coordinate is the Cubiomes generation attempt position at the chunk origin. It is not a block accurate building entrance.

## Tests

`make test` runs native CTest coverage and Python unit plus integration coverage. The suite checks seed boundaries, serialization, biome filters, structure filters, spatial distance, multiple constraints, scoring, timeout, cancellation, job lifecycle, strict schemas, CLI JSON, unsupported requests, comparison, and actual MCP stdio sessions using both modern discovery and the legacy initialization handshake.

`make release-check` also enables compiler warnings as errors and checks the Python environment. `make sanitize` builds and runs native tests with address and undefined behavior sanitizers. GitHub Actions runs the release check on macOS and Linux with Python 3.11 and 3.12, plus the sanitizer job on Linux.

The deterministic fixtures are exercised through direct Cubiomes calls in the engine. The biome suite also checks the [public Cubiomes example](https://github.com/Cubitect/cubiomes#biome-generator) where seed `262` has mushroom fields at the origin, and confirms it under the pinned target version. No fixture bypass or production mock exists.

## Performance

The committed benchmark checks 500,000 sequential seeds for a village within 500 blocks.

```sh
make benchmark
```

Measured on 20 October 2026 on an Apple M3 with 8 GB memory, Apple Clang 21, Release mode, and four workers:

| Workload | Candidates | Seconds | Candidates per second |
| --- | ---: | ---: | ---: |
| Village within 500 blocks | 500,000 | 8.028 | 62,282 |

Biome radius searches are much slower because each candidate can require many exact biome samples. Results vary by compiler, processor, radius, sample step, and constraint order.

## Security and limits

Both Python and native layers reject unknown fields or unsupported conditions. Coordinates, radii, result counts, workers, candidate budgets, durations, area sample counts, relation grid memory, concurrent jobs, and retained jobs are bounded. Searches can be cancelled and have native deadlines. The server offers no arbitrary command execution and no client selected filesystem path.

## Known limitations

Actual world spawn constraints, terrain shape, valleys, mountain range topology, scenic quality, heightmaps, lakes, terrain rivers, rendering, Bedrock Edition, and Java versions other than 1.21.1 are unsupported.

Biome proximity uses a sample grid. Desert pyramids, jungle temples, and woodland mansions can be terrain false positives. Structures are confirmed only through their documented Cubiomes placement and viability checks. Searches cover only their stated range or sample budget. Job state is process local and is lost when the MCP server exits.

## Roadmap

Phase two has started with broader structure support and individual validation policies. The next work is exact terrain height validation, saved job state, additional pinned Java versions through the version table, stronger 48 bit candidate generation, and structured biome map data. Later work can add valley and mountain range detection, lakes and rivers, scenic similarity, terrain previews, GPU filters, Bedrock support, remote MCP transport, and a standalone web application.

## License

DreamSeed is available under the MIT License. Minecraft is a trademark of Microsoft. DreamSeed is not affiliated with Mojang Studios or Microsoft.
