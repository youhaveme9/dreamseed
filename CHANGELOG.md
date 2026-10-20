# Changelog

## Unreleased

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
