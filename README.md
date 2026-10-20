# DreamSeed

DreamSeed finds Minecraft world seeds that satisfy structured biome and structure constraints. An MCP compatible AI client translates natural language into those constraints. DreamSeed performs all seed computation locally with Cubiomes. It contains no model inference, makes no model API calls, and needs no OpenAI or Anthropic API key.

DreamSeed searches for worlds that match a description. It does not recover the exact seed of an existing world from an arbitrary description.

## Status

DreamSeed 0.1.0 is the first public release for Minecraft Java Edition 1.21.1. The native engine, command line interface, MCP server, asynchronous job manager, Claude Code plugin, official Minecraft verifier, map renderer, tests, and examples are implemented. See the [release notes](docs/releases/0.1.0.md) for scope and limitations, or [download the release](https://github.com/youhaveme9/dreamseed/releases/tag/v0.1.0).

The selected version is pinned deliberately. Requests for any other version return an unsupported version error instead of applying the wrong generation rules.

## Architecture

```text
AI client
    |
    | MCP over stdio
    v
Python MCP server and job manager
    |                         |
    | JSON streams            | optional isolated process
    v                         v
Native C plus plus engine     Official Minecraft Java 1.21.1 server
    |
    v
Pinned Cubiomes C library
```

The native library owns fast prediction, filtering, distance measurement, scoring, inspection, and comparison. The optional official server verifier confirms locate results and probes generated surface height. The CLI and MCP server call the same native engine. The MCP process reserves stdout for protocol messages. Diagnostics go to stderr.

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
| Inspection | Biome summary, optional structured biome map, and supported structure positions in an area |
| Comparison | Up to 64 complete world seeds under one criteria set |

Supported search biome names are returned by `get_search_capabilities` and `dreamseed capabilities`. They include plains, desert, forest, cherry grove, meadow, grove, snowy slopes, jagged peaks, frozen peaks, stony peaks, and other common biomes.

All distances are horizontal Euclidean distance in blocks. An anchor defaults to X 0 and Z 0. This is the world origin, not the actual world spawn. DreamSeed never describes an origin relative result as spawn relative. Actual spawn checks are unsupported because Cubiomes warns that block material can affect its spawn result.

Minecraft world seeds are accepted and returned as signed 64 bit decimal strings. Structure placement first uses the lower 48 bits where Minecraft does, then biome checks use the complete 64 bit world seed. DreamSeed never returns a partial structure seed as a world seed.

## Validation levels

A village search result is a Cubiomes structure attempt that passes its biome viability check. Its status is `cubiomes_predicted`. This is a fast world generation prediction, not generated block confirmation.

A desert pyramid, jungle temple, or woodland mansion prediction also passes Cubiomes terrain screening. Cubiomes does not provide the complete modern Overworld surface simulation needed to prove exact terrain generation. These results use `cubiomes_predicted_with_terrain_caveat`.

Other supported structures pass their Cubiomes placement and structure specific viability checks. Coordinates identify generation attempt positions rather than building entrances.

The optional `verify_seed_with_minecraft` tool starts an isolated official Minecraft Java 1.21.1 server with the candidate seed. It asks Minecraft itself to locate villages, pillager outposts, and supported biomes. Successful locations use `minecraft_located`. It can also generate the target chunk, query the `motion_blocking_no_leaves` surface height, and reject water or lava as a safe teleport target. This is stronger than a Cubiomes prediction, but a locate result is still not a block accurate building entrance.

DreamSeed does not currently inspect chunk structure start data, so it does not use the status `generated_chunks_confirmed`. The distinction is deliberate.

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
git clone https://github.com/youhaveme9/dreamseed.git
cd dreamseed
make build
make venv
make test
```

The native binary is `build/dreamseed`. The Python environment is `.venv`.

Release downloads include a complete source archive, a Python wheel, and a native archive for each validated platform. The wheel contains the MCP server; it also needs the native executable. See [installation from release files](docs/native_install.md).

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
./build/dreamseed inspect --config examples/inspect_biome_map.json
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

The tools are `get_search_capabilities`, `start_seed_search`, `get_search_status`, `get_search_results`, `cancel_seed_search`, `inspect_seed`, `compare_seeds`, `verify_seed_with_minecraft`, and `render_seed_map`. Their input and output schemas are generated from strict Pydantic models.

At most two searches run concurrently in one server process. A native child process performs each search. Arguments use a fixed executable and argument vector with no shell. The server finds the engine through `DREAMSEED_BINARY`, a local `build/dreamseed`, or `PATH`, in that order.

Job metadata and ranked results are saved atomically. Completed jobs remain available after an MCP server restart when the client retains the job ID. A search that was active when the server stopped is recovered as `interrupted`; it is never presented as completed and does not resume automatically.

Set `DREAMSEED_STATE_DIR` to select the job directory. The default is `~/Library/Application Support/DreamSeed/jobs` on macOS and `$XDG_STATE_HOME/dreamseed/jobs` or `~/.local/state/dreamseed/jobs` on Linux. One server process should own a state directory at a time.

Validate the local installation with:

```sh
make doctor
```

## Official Minecraft verification

The verifier is optional. DreamSeed does not bundle or redistribute Minecraft. Java 21 or newer is required. First read the [Minecraft EULA](https://www.minecraft.net/en-us/eula). If you accept it, install the pinned official server jar with an explicit acceptance flag:

```sh
make venv
.venv/bin/dreamseed-minecraft-setup --download --accept-mojang-eula
```

The installer downloads the official Java 1.21.1 server from Mojang, verifies the pinned SHA1 `59353fb40c36d304f2035d51e7d6e6baa98dc05c`, and records the acceptance locally. It never places the jar in this repository or Python package.

Check readiness without downloading anything:

```sh
.venv/bin/dreamseed-minecraft-setup --json
```

For a manually managed jar, configure the MCP process with `DREAMSEED_MINECRAFT_SERVER_JAR` and set `DREAMSEED_ACCEPT_MOJANG_EULA=true` only after accepting the EULA. `get_search_capabilities` reports whether verification is available.

Call `verify_seed_with_minecraft` with the shape in `examples/verify_seed_with_minecraft.json`. Only villages and pillager outposts are accepted as structure targets in this first verifier version. Search biome names are accepted as biome targets. Verification is bounded to one active server process and 30 through 300 seconds.

Set `include_biome_map` to true to receive a static SVG map in the same verified response. The MCP response includes both structured SVG data and an image content block for capable clients. Green markers come only from the official verifier. Orange markers are Cubiomes predictions. Gray markers in the standalone renderer are client supplied. The SVG shows sampled biome cells and is not a terrain screenshot.

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

## Deterministic Cubiomes example

The committed sequential example examines seeds 0 through 9999. On the current pinned engine it finds seed `2579` with plains at X 0, Y 64, Z 0 and a Cubiomes predicted village placement at X 0, Z 0. Both hard constraints pass the Cubiomes stage and the distance preference score is 100.

Reproduce it with:

```sh
./build/dreamseed search --config examples/multi_constraint_search.json
```

The structure coordinate is the Cubiomes generation attempt position at the chunk origin. It is not a block accurate building entrance.

## Tests

`make test` runs native CTest coverage and Python unit plus integration coverage. The suite checks seed boundaries, serialization, biome filters, structure filters, spatial distance, multiple constraints, scoring, timeout, cancellation, durable job recovery, biome map encoding, SVG rendering, Minecraft locate parsing, surface parsing, verifier setup gates, strict schemas, CLI JSON, unsupported requests, comparison, and actual MCP stdio sessions using both modern discovery and the legacy initialization handshake.

The official Minecraft integration test runs only when a valid local server jar and explicit EULA acceptance are present. DreamSeed does not replace that test with a fake production result when the proprietary server is unavailable.

`make release-check` also enables compiler warnings as errors and checks the Python environment. `make sanitize` builds and runs native tests with address and undefined behavior sanitizers. GitHub Actions runs the release and package checks on macOS and Linux with Python 3.11 and 3.12, plus the sanitizer job on Linux.

Before preparing a release, run `make release-candidate`. It combines the release checks, sanitizers, wheel construction, Python bytecode compilation, and strict Claude plugin validation when the Claude CLI is installed. It creates local artifacts but does not tag, publish, or push anything.

`make release` also builds complete source, wheel, and native archives, rebuilds the extracted source, and exercises all nine MCP tools from a clean wheel installation. It produces checksums and a validation manifest under `dist/0.1.0`. Publication is a separate step. See the [release procedure](docs/releasing.md).

The deterministic fixtures are exercised through direct Cubiomes calls in the engine. The biome suite also checks the [public Cubiomes example](https://github.com/Cubitect/cubiomes#biome-generator) where seed `262` has mushroom fields at the origin, and confirms it under the pinned target version. No fixture bypass or production mock exists.

## Performance

The committed benchmark checks 500,000 sequential seeds for a village within 500 blocks.

```sh
make benchmark
```

Measured on 20 October 2026 on an Apple M3 with 8 GB memory, Apple Clang 21, Release mode, and four workers:

| Workload | Candidates | Seconds | Candidates per second |
| --- | ---: | ---: | ---: |
| Village within 500 blocks | 500,000 | 8.082 | 61,869 |

Biome radius searches are much slower because each candidate can require many exact biome samples. Results vary by compiler, processor, radius, sample step, and constraint order.

## Security and limits

Both Python and native layers reject unknown fields or unsupported conditions. Coordinates, radii, result counts, workers, candidate budgets, durations, area sample counts, relation grid memory, concurrent jobs, and retained jobs are bounded. Searches can be cancelled and have native deadlines. The server offers no arbitrary command execution and no client selected filesystem path.

Minecraft verification uses a fixed Java argument vector, fixed command templates, an isolated temporary world, a loopback only server socket, offline mode, no remote console, one process at a time, and a bounded deadline. The jar checksum must match the pinned Mojang release.

## Known limitations

Actual world spawn constraints, terrain shape, valleys, mountain range topology, scenic quality, lakes, terrain rivers, block accurate structure entrance coordinates, Bedrock Edition, and Java versions other than 1.21.1 are unsupported.

Biome proximity uses a sample grid. Cubiomes structure predictions can be false positives. Official verification currently supports locate checks only for villages, pillager outposts, and search biomes. Surface probing identifies height, water, and lava, but it does not prove that every teleport is harmless. Searches cover only their stated range or sample budget. Active jobs do not resume after an MCP server restart, though their last durable state and results remain inspectable.

## Roadmap

Broader structure support, durable job recovery, structured biome maps, official locate verification, surface probing, and static SVG maps are implemented. The next work is generated chunk structure start inspection, more official verifier targets, additional pinned Java versions through the version table, and stronger 48 bit candidate generation. Later work can add valley and mountain range detection, lakes and rivers, scenic similarity, terrain previews, GPU filters, Bedrock support, remote MCP transport, and a standalone web application.

## License

DreamSeed is available under the MIT License. Minecraft is a trademark of Microsoft. DreamSeed is not affiliated with Mojang Studios or Microsoft.
