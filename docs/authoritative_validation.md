# Official Minecraft validation

DreamSeed uses Cubiomes as its fast search engine. Cubiomes results are predictions. The optional verifier starts the pinned official Minecraft Java 1.21.1 server for one candidate seed and asks Minecraft to locate requested targets.

## Setup

DreamSeed does not redistribute Minecraft. Read the [Minecraft EULA](https://www.minecraft.net/en-us/eula). If you accept it, run:

```sh
make venv
.venv/bin/dreamseed-minecraft-setup --download --accept-mojang-eula
```

The installer uses the pinned official server object and verifies both its size and SHA1. Run `.venv/bin/dreamseed-minecraft-setup --json` to inspect setup without downloading.

## Verification request

The MCP tool is `verify_seed_with_minecraft`. See `examples/verify_seed_with_minecraft.json` for a complete request.

Supported structure targets are `village` and `pillager_outpost`. All biome names listed by `get_search_capabilities` can be located. The reference contains explicit X, Y, and Z coordinates. Returned distances are horizontal Euclidean distances from that reference, not distances from actual world spawn.

When surface probing is enabled, the verifier waits for the target chunk and probe entity to become available, then obtains a height from Minecraft's `motion_blocking_no_leaves` heightmap. `safe_teleport` requires explicit confirmation of clear space for the player's feet and head, plus ground support excluding air, water, lava, and powder snow. It does not guarantee protection from cliffs, fire, hostile mobs, or every other possible hazard. The probe may reject a point under leaves or surface vegetation even when a nearby point is suitable.

The official integration fixture uses seed `-7333811035076652275`. Minecraft Java 1.21.1 reports village X 48, Z 16 with surface Y 91 and outpost X 256, Z 256 with surface Y 118. The ocean probe at X 1440, Z 288 returns surface Y 63, reports water, and rejects the teleport. These values were recorded from the official server and are tested only when the real server integration is explicitly enabled.

## Status model

| Status | Meaning |
| --- | --- |
| `cubiomes_predicted` | Cubiomes placement and viability prediction |
| `cubiomes_predicted_with_terrain_caveat` | Cubiomes prediction with incomplete terrain screening |
| `minecraft_located` | The official server returned a locate result |
| `partially_located` | Minecraft located some requested targets |
| `not_located` | Minecraft located none of the requested targets within its locate behavior |
| `surface_probed` | Minecraft returned a generated surface position |

DreamSeed does not currently use `generated_chunks_confirmed`. That future status requires authoritative inspection of generated chunk structure start data.

## Rendering

`render_seed_map` returns a bounded static SVG based on the structured Cubiomes biome map. Its MCP response contains structured SVG data and an image content block. Orange markers are Cubiomes predictions. Gray markers are client supplied and cannot claim verification. When `include_biome_map` is enabled on `verify_seed_with_minecraft`, verified locations are rendered internally in green.

The SVG is a sampled biome map. It is not a terrain screenshot, heightmap, or proof of scenic quality. An AI client may describe visible relationships or provide a subjective ranking, but factual biome and structure claims must come from the engine or official verifier output.

## Resource and security limits

Only one verifier process runs at a time in each MCP server process. Requests are bounded to 30 through 300 seconds and the Java heap is capped at 1024 MiB. The Java server binds to loopback, uses offline mode, disables remote console and query access, and runs in a temporary directory. DreamSeed uses fixed commands and does not accept arbitrary Minecraft console input.
