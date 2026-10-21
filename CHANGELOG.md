# Changelog

## Unreleased

No changes yet.

## 0.2.0

21 October 2026. Minecraft Java Edition 1.21.1 and 1.21.3.

### Added

1. Generated structure start confirmation from saved Java 1.21.1 chunks through the official verifier.
2. Official verification for all ten structure types already supported by the native search engine.
3. Structure registry IDs, start chunk coordinates, piece counts, piece bounding boxes, and chunk content hashes in verification results.
4. A bounded Anvil and NBT reader that rejects incomplete chunks, wrong versions, invalid starts, malformed files, and excessive decompression or nesting.
5. Separate `generated_chunks_confirmed` and `partially_verified` statuses, with teal map markers for confirmed starts.
6. An official server regression fixture and MCP integration check covering all ten structure types for seed `0`.
7. Exact candidate verification through a tenth MCP tool, including official biome checks, unique structure counts, radius checks, spatial relations, and recalculated preference scores.
8. A complete 22 milestone roadmap and a second official MCP fixture combining six candidate requirements.
9. Shared native and Python version catalog, explicit Java 1.21.3 support, separate official server installations, and independent official fixtures for that version.
10. Deterministic structure48 cohorts, bounded placement reuse, typed pruning counters, parity tests, and measured cache benchmarks.
11. Generated heightmaps, surface state and biome decoding, water depth, independent control probes, and explicit sampled terrain classifiers.
12. Transparent numeric terrain similarity preferences, SVG heightmaps, and OBJ surface meshes without invented geometry.
13. A local browser application using the actual engine, durable jobs, cancellation, verification, and an interactive surface viewer.
14. Optional authenticated HTTP MCP for one configured owner, with public key JWT verification, resource audience checks, protected metadata, and bounded request handling.
15. Experimental Metal placement filtering, with actual GPU parity checks and measurements that do not claim a speedup.
16. Exact igloo template block state comparisons from the installed official server, including supported rotations and the conditional entrance rule.

### Fixed

1. Shutdown now joins completed job workers before their final storage writes can race directory cleanup, and rejects newly started searches after closing.
2. Schema validation no longer coerces strings or booleans into numeric resource settings.
3. Browser and HTTP defaults use separate job stores, while terrain exports use temporary state instead of touching an active MCP store.
4. Durable job recovery now recognizes structure48 jobs and preserves their pruning metrics.
5. Teleport checks use actual water and lava fluid predicates, including water plants and waterlogged states, with explicit positive and negative controls.
6. Minecraft console buffering is bounded and excessive logging produces an actionable failure instead of unbounded memory growth.
7. Release bundle merging checks the shared version catalog and preserves both supported versions in the combined manifest.
8. Test setup installs optional HTTP dependencies so clean environments exercise the authenticated transport.
9. Native version lookups compile cleanly under GCC warnings as errors on Linux.

### Documentation

1. Reorganized the README around installation, a first search, client setup, and official verification.
2. Added a genuinely verified example and clear explanations of origin distances, validation levels, finite coverage, and experimental features.

## 0.1.0

First public release, 20 October 2026.

### Added

1. Native Cubiomes seed search for Minecraft Java 1.21.1.
2. Strict MCP tools, bounded jobs, cancellation, inspection, and comparison.
3. Ten supported Overworld structures with explicit validation policies.
4. Continuous integration for macOS and Linux.
5. Compiler warning and sanitizer checks.
6. Official MCP Python SDK 2.2.0 support.
7. Durable local job records with completed result recovery after server restart.
8. Bounded palette encoded biome map data through seed inspection.
9. A local installation doctor and expanded MCP acceptance coverage.
10. Optional official Minecraft Java 1.21.1 locate verification with generated surface probing.
11. Static SVG biome map rendering with trusted marker status separation.
12. A pinned server installer with explicit Mojang EULA acceptance and checksum verification.
13. Complete source and native release archives, Python wheels, SHA256 checksums, and validation manifests.
14. Source rebuild and isolated wheel acceptance tests for every MCP tool.

### Fixed

1. Exact biome constraints now survive MCP validation and native search normalization.
2. Native job failures now preserve structured errors and bounded diagnostics.
3. Active native jobs are stopped when the MCP server exits normally.
4. Cubiomes structure results are labeled as predictions rather than block confirmed structures.
5. Official surface probes wait for loaded chunks and visible probe entities, check the correct ground level, and require positive clearance before marking a teleport safe.
6. Native inspection accepts all ten structure types advertised by the MCP schema.
7. Installed Python packages can discover the native executable through PATH.
8. Job manager shutdown stops an active Minecraft verification process and prevents subsequent verifier launches.
9. The C++20 integration isolates Cubiomes interpolation helpers from the GCC math header.
