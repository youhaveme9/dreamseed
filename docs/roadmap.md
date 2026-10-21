# DreamSeed roadmap

## Milestone checklist

Status is based on implemented and tested behavior in 0.2.0. Experimental and partial features retain their explicit limits. Research items are not capability promises.

| ID | Milestone | Status |
| --- | --- | --- |
| M01 | Native Cubiomes engine and independent CLI | Complete in 0.1.0 |
| M02 | Typed constraints, counts, spatial relations, and scoring | Complete in 0.1.0 |
| M03 | MCP tools, bounded jobs, cancellation, and resource limits | Complete in 0.1.0 |
| M04 | Claude plugin, client instructions, and setup documentation | Complete in 0.1.0 |
| M05 | Durable jobs and structured biome maps | Complete in 0.1.0 |
| M06 | Official locate checks, surface probes, and SVG maps | Complete in 0.1.0 |
| M07 | Release gates, platform packages, and first public release | Complete in 0.1.0 |
| M08 | Generated structure starts and all ten official targets | Complete in 0.2.0 |
| M09 | Exact candidate verification and authoritative constraint checks | Complete in 0.2.0 |
| M10 | Shared version registry and additional pinned Java versions | Complete in 0.2.0 for Java 1.21.1 and 1.21.3 |
| M11 | Stronger lower 48 bit filtering and measured pruning | Complete in 0.2.0 |
| M12 | Complete structure block validation | Implemented for igloo template states; other families unsupported |
| M13 | Heightmap based terrain analysis | Implemented and officially validated locally |
| M14 | Valley and mountain range detection | Experimental sampled detectors implemented; semantic guarantees unsupported |
| M15 | Lake and terrain river analysis | Experimental water component detectors implemented; semantic guarantees unsupported |
| M16 | Transparent scenic similarity evaluators | Numeric profile similarity implemented; beauty and learned visual similarity unsupported |
| M17 | Terrain previews and 3D visualization | SVG, OBJ, and local rotatable surface viewer implemented |
| M18 | GPU seed filtering | Metal placement backend tested on Apple M3; slower than CPU in the measured workload |
| M19 | Bedrock generation support | Blocked on a compatible runtime and independently validated adapter |
| M20 | Remote MCP hosting and authentication | Single owner authenticated HTTP implemented and tested locally; nothing deployed |
| M21 | Standalone web application | Implemented with real HTTP tests; visual review limited by host Chrome errors |
| M22 | Next release validation and packaging | 0.2.0 gates implemented; published bundles require clean commit platform validation; browser visual review remains a disclosed limit |

Every status states its implemented scope rather than silently treating experimental research as complete. A software release does not imply public service deployment. Broader block validators, semantic terrain guarantees, and Bedrock are not claimed complete.

The [local validation record](validation/2026-10-21.md) lists executed commands, observed results, an actual newly discovered and officially verified seed, and remaining external gates.

## Released baseline

Version 0.1.0 introduced the native seed search engine, ten structure types, strict MCP tools, durable jobs, structured biome maps, optional official locate verification, surface safety probes, and SVG maps for Java 1.21.1. Version 0.2.0 adds the scoped capabilities below and Java 1.21.3.

## Generated structure evidence

Included in 0.2.0:

1. Official locate targets for every structure type already supported by search.
2. Full start chunk generation, world flush, and saved structure start inspection.
3. Registry IDs, piece counts, bounding boxes, and observed chunk content hashes.
4. Separate predicted, located, confirmed, and incomplete verification outcomes.
5. Bounded Anvil and NBT parsing without a new dependency.
6. Official server fixtures and actual MCP coverage for all ten structure types.

This milestone verifies structure start metadata, not every structure block, a building entrance, terrain beauty, or world spawn. The existing native search behavior remains unchanged. See [verification semantics](authoritative_validation.md).

## Completed candidate verification milestone

`verify_seed_candidate` derives exact witnesses from the native engine, confirms the selected structure chunks and biome coordinates in Minecraft, and rechecks counts, radii, spatial relations, and scoring. The real MCP fixture verifies six combined requirements. The release candidate gate passed 69 Python tests with no skips, native tests, sanitizers, wheel construction, and strict plugin validation. See [candidate verification](candidate_verification.md).

## Completed version and filtering milestones

1. Java 1.21.1 and 1.21.3 use a shared catalog consumed by CMake, schemas, installer, verifier, and release checks. After explicit EULA acceptance, independent official MCP runs confirmed all ten structure starts and six candidate requirements for 1.21.3. The full gate passed 75 Python tests without skips plus native tests and sanitizers.
2. `structure48` batches complete world seeds by shared placement state, with worker local caches, full seed viability checks, typed filter metrics, and cached versus uncached parity tests. Measured results are recorded in [structure seed batching](structure48.md).

## Current research boundaries

Igloo template states now have [exact block comparisons](structure_blocks.md). Other structure families need their own validated template, processor, or procedural evaluators. Start metadata is never a substitute for those checks.

[Generated terrain inspection](terrain.md) provides real heightmaps and explicit sampled feature heuristics. It cannot prove global valley or lake topology, objective beauty, caves, or complete voxel geometry. SVG and OBJ surfaces are factual sampled previews, not Minecraft client screenshots.

[Metal filtering](gpu_filtering.md) passed parity checks on the actual Apple M3, but was slower than CPU for the recorded small workload. It stays explicit and experimental, not the default search backend.

[Authenticated HTTP and the local app](http_and_web.md) use existing engine logic. No hosting, OAuth provider, account registration, or public deployment was created. Browser API and asset tests pass; Chrome headless visual checks failed with `CVDisplayLinkCreateWithCGDisplay` and host task policy errors, so visual approval is not claimed.

Bedrock remains unsupported. Cubiomes targets Java, and Mojang's [Bedrock server](https://www.minecraft.net/en-us/download/server/bedrock) lists Windows and Ubuntu rather than this Mac host. A compatible runtime and independent Bedrock fixtures are needed before adding an adapter or advertising support. Java algorithms are not silently reused for Bedrock.
