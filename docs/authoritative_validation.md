# Official Minecraft validation

DreamSeed uses Cubiomes as its fast search engine. Cubiomes results are predictions. The optional verifier starts the official server pinned for the explicitly requested Minecraft version and asks Minecraft to locate targets. Version 0.2.0 supports Java 1.21.1 and 1.21.3; historical release 0.1.0 supports only 1.21.1.

## Setup

DreamSeed does not redistribute Minecraft. Read the [Minecraft EULA](https://www.minecraft.net/en-us/eula). If you accept it, run:

```sh
make venv
.venv/bin/dreamseed-minecraft-setup --download --accept-mojang-eula
```

The installer uses the pinned official server object and verifies both its size and SHA1. Run `.venv/bin/dreamseed-minecraft-setup --json` to inspect setup without downloading.

For Java 1.21.3, add `--minecraft-version 1.21.3` to setup and readiness commands. Acceptance is recorded per version, not copied from an older installation. The shared catalog in `dreamseed_mcp/minecraft_versions.json` drives both the native build and Python schemas. No unlisted version alias is accepted.

## Verification request

The MCP tool is `verify_seed_with_minecraft`. See `examples/verify_seed_with_minecraft.json` for a complete request.

Supported structure targets are `village`, `desert_pyramid`, `jungle_temple`, `swamp_hut`, `igloo`, `ocean_ruin`, `shipwreck`, `ocean_monument`, `woodland_mansion`, and `pillager_outpost`. All biome names listed by `get_search_capabilities` can be located. The reference contains explicit X, Y, and Z coordinates. Returned distances are horizontal Euclidean distances from that reference, not distances from actual world spawn.

This locate tool returns the nearest target for each requested type. It does not validate every predicted feature in a search result or verify a multiple structure count. Use [`verify_seed_candidate`](candidate_verification.md) to confirm selected candidate coordinates, counts, exact biome witnesses, and spatial relations against the original criteria.

## Generated structure starts

Version 0.2.0 adds saved structure start inspection. `confirm_structure_starts` defaults to true. Set it to false to retain locate and optional surface checks without start confirmation.

For each located structure, DreamSeed loads its start chunk, waits for full generation, flushes the world, stops the server cleanly, then reads the saved region entry. Confirmation requires the requested version's data version (`3955` for 1.21.1, `4082` for 1.21.3), matching chunk coordinates, status `minecraft:full`, a valid matching structure registry ID, matching start coordinates, and at least one serialized piece with a valid bounding box. Structure references alone do not qualify.

Confirmed features use `generated_chunks_confirmed`. Their `structure_start` field includes the start chunk coordinates, structure ID, data version, piece count, unique piece IDs, combined piece bounding box, and a SHA256 hash of the observed decompressed chunk NBT. The hash identifies that observation; timestamps and other saved state mean it is not a stable seed fingerprint.

This confirms the generated start chunk and its piece metadata. It does not generate every intersecting chunk or inspect every expected structure block. A locate point can lie outside a piece bounding box and is never interpreted as a building entrance. Surface safety remains a separate check. Biome features remain `minecraft_located`.

When confirmation fails, the feature retains `minecraft_located`, `structure_start.status` is `unconfirmed`, and the failure includes `stage: structure_start` with a machine readable code. A timeout or unsupported chunk format cannot upgrade a feature. An overall `generated_chunks_confirmed` result means every requested structure was confirmed and all requested targets were located; it does not upgrade biome validation or imply safe teleportation.

## Surface checks

When surface probing is enabled, the verifier waits for the target chunk and probe entity to become available, then obtains a height from Minecraft's `motion_blocking_no_leaves` heightmap. `safe_teleport` requires explicit confirmation of clear space for the player's feet and head, plus ground support excluding air, water, lava, and powder snow. It does not guarantee protection from cliffs, fire, hostile mobs, or every other possible hazard. The probe may reject a point under leaves or surface vegetation even when a nearby point is suitable.

Water and lava are checked as fluid states, not just block names. This includes source and flowing fluids, seagrass, bubble columns, and waterlogged blocks. Both positive and negative controls must agree; an unknown response cannot produce a safe teleport. Real integration tests use explicitly constructed control columns in temporary worlds for this predicate check, separately from naturally generated seed fixtures. For a player teleport, use the center of the reported block, X plus 0.5 and Z plus 0.5, with the reported Y.

The final clearance command also tests fluid absence in the same command, so an earlier dry observation alone cannot approve a target that becomes wet before clearance is checked.

The official integration fixture uses seed `-7333811035076652275`. Minecraft Java 1.21.1 reports village X 48, Z 16 with surface Y 91 and outpost X 256, Z 256 with surface Y 118. The ocean probe at X 1440, Z 288 returns surface Y 63, reports water, and rejects the teleport. These values were recorded from the official server and are tested only when the real server integration is explicitly enabled.

## Status model

| Status | Meaning |
| --- | --- |
| `cubiomes_predicted` | Cubiomes placement and viability prediction |
| `cubiomes_predicted_with_terrain_caveat` | Cubiomes prediction with incomplete terrain screening |
| `minecraft_located` | The official server returned a locate result |
| `generated_chunks_confirmed` | A full saved start chunk contains a valid matching start with serialized pieces |
| `partially_verified` | Targets were located but at least one requested start confirmation failed |
| `partially_located` | Minecraft located some requested targets |
| `not_located` | Minecraft located none of the requested targets within its locate behavior |
| `surface_probed` | Minecraft returned a generated surface position |

## Reproducible fixture

`examples/verify_all_structures.json` requests all ten structure types for seed `0` from reference X 0, Y 64, Z 0. On 20 October 2026, a real MCP call using the pinned official server located and confirmed all ten starts in 27.642 seconds on the local Apple M3. This is an observed validation runtime, not a general performance guarantee.

`tests/fixtures/java_1_21_1_seed_0_structures.json` records the resulting coordinates, exact registry IDs, piece counts, and server SHA1. For example, the village is at X 272, Z 944 with 105 pieces, and the woodland mansion is at X negative 3536, Z negative 832 with 531 pieces. No Minecraft executable or complete world is included.

The independent Java 1.21.3 fixture is `tests/fixtures/java_1_21_3_seed_0_structures.json`. A real MCP run confirmed all ten starts in 23.642 seconds on this machine, with data version 4082. The candidate verification fixture for that version also passes all six requirements. Both versions run in the optional official integration gate.

Run the real server regressions, including MCP transport and confirmed map markers, after accepting the EULA and installing the pinned server:

```sh
DREAMSEED_RUN_MINECRAFT_INTEGRATION=1 make test
```

## Rendering

`render_seed_map` returns a bounded static SVG based on the structured Cubiomes biome map. Its MCP response contains structured SVG data and an image content block. Orange markers are Cubiomes predictions. Gray markers are client supplied and cannot claim verification. When `include_biome_map` is enabled on `verify_seed_with_minecraft`, locate answers are green and confirmed generated starts are teal. Client supplied markers cannot claim either verification status.

The SVG is a sampled biome map. It is not a terrain screenshot, heightmap, or proof of scenic quality. An AI client may describe visible relationships or provide a subjective ranking, but factual biome and structure claims must come from the engine or official verifier output.

## Resource and security limits

Only one verifier process runs at a time in each MCP server process. Requests are bounded to 30 through 300 seconds and the Java heap is capped at 1024 MiB. The Java server binds to loopback, uses offline mode, disables remote console and query access, and runs in a temporary directory. DreamSeed uses fixed commands and does not accept arbitrary Minecraft console input.

The console queue holds at most 4096 lines. Overflow causes an explicit verification error, and the reader does not block indefinitely during process cleanup.

The chunk reader accesses only that temporary world. MCP arguments cannot select files. Decompressed chunks are limited to 8 MiB, NBT nesting to 64 levels, and parsed nodes and array elements to 100,000. Region allocation and chunk length checks run before decompression. Only standard gzip, zlib, and uncompressed region records are accepted. External chunk storage and other compression formats produce explicit unconfirmed results. Temporary worlds are removed after verification.
