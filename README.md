# DreamSeed

Find Minecraft seeds for the world you want to play in.

> Find a Java 1.21.3 world with plains at the origin, a nearby village, and a cherry grove within 1000 blocks.

Your AI client turns the request into search constraints. DreamSeed searches real seeds locally with [Cubiomes](https://github.com/Cubitect/cubiomes), ranks the matches, and can check them with the official Minecraft server. You can also use the CLI or local browser app without an AI client.

No model API key, local LLM, Docker, or hosted service is required by DreamSeed. Your chosen AI client has its own access requirements.

[Download 0.2.0](https://github.com/youhaveme9/dreamseed/releases/tag/v0.2.0) · [Release notes](docs/releases/0.2.0.md) · [Examples](examples) · [Roadmap](docs/roadmap.md)

Supports **Minecraft Java Edition 1.21.1 and 1.21.3**. Bedrock and other versions are not supported.

**The origin at X 0, Z 0 is not the actual world spawn.** All proximity measurements use horizontal X/Z distances from the stated reference point.

## Quick start

You need Python 3.11 or newer, CMake 3.20 or newer, Git, Make, and C11 and C++20 compilers. Initial installation needs internet access for pinned dependencies. Java is optional unless you want official verification or terrain previews.

On macOS, install the Xcode command line tools and CMake. On Ubuntu, install `build-essential`, `cmake`, `git`, `python3`, and `python3-venv`.

```sh
git clone --branch v0.2.0 https://github.com/youhaveme9/dreamseed.git
cd dreamseed
make build
make venv
make doctor
```

Run a small search:

```sh
./build/dreamseed search --config examples/multi_constraint_search.json
```

This searches seeds 0 through 9999 for plains at X 0, Y 64, Z 0 and a village within 600 blocks. Results are JSON. The pinned engine finds candidate seed `2579`, with a predicted village attempt at the origin. A prediction is not yet official Minecraft confirmation.

Prefer a browser? Start the local app, then open <http://127.0.0.1:8765>:

```sh
.venv/bin/dreamseed-web --port 8765
```

The app supports search, progress, cancellation, inspection, comparison, and optional verification and terrain previews. It runs on your computer, not a public website.

To avoid compiling, see [installing release downloads](docs/native_install.md). The Python wheel needs a separate native binary. There is no published PyPI installation claimed here.

## Connect an AI client

MCP lets an AI client call DreamSeed's local tools. DreamSeed handles world generation, not language understanding or conversational memory.

Run one of the commands below after building. Replace `/absolute/path/to/dreamseed` with your checkout location, and keep paths quoted if they contain spaces. Restart the client or reconnect its MCP server after an upgrade.

### Codex

```sh
codex mcp add dreamseed \
  --env "DREAMSEED_BINARY=/absolute/path/to/dreamseed/build/dreamseed" -- \
  "/absolute/path/to/dreamseed/.venv/bin/dreamseed-mcp"
codex mcp list
```

Official verification can take longer than a client's default tool timeout. For Codex, set `tool_timeout_sec = 360` inside the existing `[mcp_servers.dreamseed]` table in `~/.codex/config.toml`. See the [official MCP configuration guide](https://developers.openai.com/codex/mcp/).

### Claude Code

```sh
claude mcp add dreamseed --scope user --transport stdio \
  -e "DREAMSEED_BINARY=/absolute/path/to/dreamseed/build/dreamseed" -- \
  "/absolute/path/to/dreamseed/.venv/bin/dreamseed-mcp"
claude mcp list
```

Alternatively, load the repository as a local plugin. It includes the MCP configuration and a reusable seed finding skill:

```sh
claude plugin validate /absolute/path/to/dreamseed --strict
claude --plugin-dir /absolute/path/to/dreamseed
```

Choose direct registration or the plugin to avoid duplicate servers. The plugin needs `build/dreamseed` and `.venv` inside its directory. It is not a portable marketplace installer. See [Claude's MCP guide](https://code.claude.com/docs/en/mcp).

### Try this prompt

> Use DreamSeed. First check its capabilities. Find three Java 1.21.3 seeds with plains at X 0, Y 64, Z 0 and a village within 500 blocks of the origin. Prefer the closest village. Use sampled strategy, sample seed 20261020, 50000 candidates, 30 seconds, and 4 workers. Monitor the search until it finishes. Return full seeds, coordinates, distances, scores, validation status, and coverage. Do not call the origin the world spawn.

Then refine it: “Keep those requirements, but require two villages.” The AI client should preserve the other criteria. Adding large biome radius constraints can make searches much slower.

## Verify before choosing a world

Search uses fast Cubiomes predictions. For stronger evidence, DreamSeed can generate a private temporary world with the pinned official server. This requires Java 21 or newer and your explicit acceptance of the [Minecraft EULA](https://www.minecraft.net/en-us/eula).

Only run this if you accept those terms:

```sh
.venv/bin/dreamseed-minecraft-setup --minecraft-version 1.21.3 --download --accept-mojang-eula
.venv/bin/dreamseed-minecraft-setup --minecraft-version 1.21.3 --json
```

Use `--minecraft-version 1.21.1` separately if you need that version. Each installation is checksum verified and has its own acceptance record. Minecraft jars and worlds are never bundled with DreamSeed.

Ask your client:

> Verify the highest ranked seed with verify_seed_candidate using the same version, reference point, constraints, and preferences. Enable surface probes. Explain any failed checks before recommending it.

`verify_seed_candidate` checks the selected coordinates, biome samples, structure counts, spatial pairs, and score. `verify_seed_with_minecraft` instead locates nearby features and can confirm their generated starts. It does not automatically recheck an earlier search's complete requirements.

| Result status | What it establishes |
| --- | --- |
| `cubiomes_predicted` | Placement and supported biome viability checks passed |
| `cubiomes_predicted_with_terrain_caveat` | Prediction passed supported screening, with remaining terrain uncertainty |
| `minecraft_located` | The official server returned a locate result |
| `generated_chunks_confirmed` | Saved full start chunk contains a valid structure start and piece metadata |
| `template_blocks_confirmed` | Igloo only: declared template block states matched generated chunks |
| Candidate `verified` | All original hard requirements passed the implemented official checks |

Generated start confirmation does not prove every building block, loot item, or entrance. A structure X/Z position is not a safe teleport destination. Surface probes return an observed Y and check clearance and fluid hazards, but do not guarantee safety from every hazard. See [verification details](docs/authoritative_validation.md) and [candidate checks](docs/candidate_verification.md).

### An actual verified example

For **Java 1.21.3**, seed **`-3989987067671208281`** was found by `examples/structure48.json` and checked through the official server:

| Property | Observed result |
| --- | --- |
| Origin biome | Plains at X 0, Y 64, Z 0 |
| Village start | X 32, Z 0, with 177 serialized pieces |
| Village distance | 32 horizontal blocks from the origin, not world spawn |
| Score | 93.6 out of 100 for village proximity within 500 blocks |
| Candidate validation | `verified`, with both hard requirements confirmed |
| Village surface probe | Y 74, with fluid and clearance checks passing |

The exact request is in [verify_structure48_candidate.json](examples/verify_structure48_candidate.json). See the [validation record](docs/validation/2026-10-21.md) for the executed search and caveats. The village's complete block contents were not validated.

## What you can search for

| Requirement | Supported behavior |
| --- | --- |
| Biome at a point | Exact biome at a specified X, Y, Z |
| Biome nearby | A matching sample inside a radius at a specified Y |
| Structure nearby | One or more of a supported type within a radius |
| Feature pairs | At least one matching pair within a maximum distance |
| Preferences | Weighted closeness scores from 0 through 100 |
| Inspection | Biomes, structures, and optional palette encoded biome maps |
| Comparison | Rank up to 64 full world seeds against the same criteria |
| Terrain inspection | Official saved heightmaps, surface blocks, water depth, and biomes |

Structures: village, desert pyramid, jungle temple, swamp hut, igloo, ocean ruin, shipwreck, ocean monument, woodland mansion, and pillager outpost. Ask `get_search_capabilities` for exact names, biome filters, limits, and verifier availability.

Biome radius checks use a deterministic grid. A positive match is exact at its sampled coordinate, but the grid can miss a biome between samples. Structure coordinates are generation attempt positions rather than entrances. All seeds are complete signed 64 bit values encoded as decimal strings in JSON.

### Bounded searches, not global promises

Choose `sequential` for a finite contiguous range, `sampled` for deterministic full seed sampling, or `structure48` for sampled cohorts sharing placement state. Every accepted result still uses a complete world seed. Structure48 can help tight placement constraints but explores fewer distinct layouts.

An empty result means the **specified budget** found nothing, not that no matching seed exists. Candidate budgets are reproducible when they finish. Time limited parallel runs can end at different points because scheduling varies. Searches have time, candidate, worker, memory, and result limits, and can be cancelled.

Completed job records survive restarts. Active jobs become `interrupted`; they do not resume automatically. Each server process should own its own state directory. See [constraint schemas](docs/constraints.md) and [structure48 behavior](docs/structure48.md).

## More ways to use DreamSeed

```sh
./build/dreamseed capabilities
./build/dreamseed inspect --config examples/inspect_biome_map.json
./build/dreamseed compare --config examples/compare_seeds.json
./build/dreamseed search --config examples/structure48.json
```

Use `--config -` for JSON from stdin, or `search --events` for JSON progress events. The CLI and MCP tools share the same native engine and validation rules.

| Tools | Purpose |
| --- | --- |
| `get_search_capabilities` | Discover supported versions, constraints, and limits |
| `start_seed_search`, `get_search_status`, `get_search_results`, `cancel_seed_search` | Run and manage bounded searches |
| `inspect_seed`, `compare_seeds` | Inspect or rank known seeds |
| `verify_seed_with_minecraft`, `verify_seed_candidate` | Check predictions with the official server |
| `analyze_seed_terrain`, `render_seed_map` | Inspect generated terrain or render sampled biome maps |

Optional features have separate guides:

* [Terrain inspection and previews](docs/terrain.md): SVG heightmaps, OBJ surfaces, a rotatable sampled mesh, and numeric similarity preferences. These are not complete Minecraft scenes or proof of scenic beauty.
* [HTTP MCP and browser setup](docs/http_and_web.md): local app configuration and optional authenticated HTTP for one owner behind an external TLS proxy and OAuth provider. No remote hosting is included.
* [Igloo block checks](docs/structure_blocks.md): exact declared template states, with explicit exclusions.
* [Experimental Metal filtering](docs/gpu_filtering.md): placement only, not the default search backend. It was slower than CPU in the measured local workload.

## Development and testing

```sh
make test
make release-candidate
```

`make test` builds the engine, installs test dependencies including the optional HTTP extra, then runs native and Python tests against the actual engine. `make release-candidate` adds sanitizer, package, metadata, and available Claude plugin checks. It does not publish anything.

Official server tests are separate and require installed jars for both versions and explicit EULA acceptance:

```sh
DREAMSEED_RUN_MINECRAFT_INTEGRATION=1 make release-candidate
```

Without that flag, official integration tests are reported as skipped. They are not replaced by fabricated successful results. See [validation evidence](docs/validation/2026-10-21.md), [contributing](CONTRIBUTING.md), [security](SECURITY.md), and [release procedure](docs/releasing.md).

Performance depends heavily on the constraints. A measured Apple M3 run evaluated 500000 village only candidates in 8.082 seconds with four workers. Nearby biome sampling and official world generation cost much more. Run `make benchmark` to measure your own machine; [batching benchmarks](docs/structure48.md) explain the newer strategy's tradeoffs.

## Limits and next steps

DreamSeed finds worlds matching descriptions. It does not recover an existing world's exact seed from an arbitrary description. Actual world spawn constraints, Bedrock, unlisted Java versions, guaranteed valley or lake topology, objective beauty, and full block validation outside the documented igloo scope are unsupported.

Terrain classifiers, surface meshes, and Metal filtering are experimental. Browser API and client tests pass, but a visual browser review was unavailable on the validation host. Native predictions can be false positives, and all searches have finite coverage. See the [22 milestone roadmap](docs/roadmap.md) for completed work and remaining research.

## Architecture and license

The AI client handles conversation. The Python MCP server handles strict schemas and bounded jobs. The C++ engine uses Cubiomes for fast generation checks. An optional isolated official Java server supplies stronger generation evidence. Standard MCP transport is local stdio, with protocol output kept separate from diagnostic logs.

Cubiomes is pinned to `e61f90580cbdd883214a8054670dacae655e59c0`, nlohmann JSON to 3.11.3, and the official Python MCP SDK to 2.2.0. Licenses and notices are preserved in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

DreamSeed is MIT licensed. Minecraft is a trademark of Microsoft. DreamSeed is not affiliated with Mojang Studios or Microsoft.
