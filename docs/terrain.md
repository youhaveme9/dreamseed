# Generated terrain inspection

The `analyze_seed_terrain` tool starts the pinned official Minecraft server, generates the sampled chunks, flushes the world, stops cleanly, and reads saved heightmaps, block state palettes, and biome palettes. Java 1.21.1 and 1.21.3 use the pinned Overworld height of 384 blocks starting at Y negative 64. These dimensions were read from both official server jars.

No neural rendering or model inference generates these measurements. The official server requires Java 21, a separate download, and explicit EULA acceptance. See [setup](authoritative_validation.md).

## Run

Use `examples/analyze_terrain.json` as the MCP request. The same implementation is available without MCP:

```sh
make venv
.venv/bin/dreamseed-terrain --config examples/analyze_terrain.json --output-dir build/terrain-example
```

The output directory must be empty. It receives structured JSON, an SVG heightmap, and an optional OBJ surface mesh. No output path is accepted through MCP.

Requests have an explicit center, radius up to 256, sample step from 4 through 64 in multiples of 4, at most 4225 sampled columns, at most 256 sampled chunks, and a duration from 30 through 300 seconds. These limits combine, so not every radius and step combination is allowed. One official server process runs at a time.

`surface_y` is the first free Y above `MOTION_BLOCKING_NO_LEAVES`. `floor_y` uses `OCEAN_FLOOR`. A surface water or waterlogged state enables the reported depth difference; it is not a complete water volume. Surface states may include buildings or vegetation. Y is not a safe teleport guarantee.

Surface water classification includes kelp, seagrass, bubble columns, and waterlogged states. Official teleport checks separately query fluid predicates and reject those wet targets.

Grid rows increase Z and columns increase X from `origin`, spaced by `sample_step`. Packed long arrays use padded entries within each 64 bit word, with version and length validation. Missing or invalid chunks produce null samples and structured failures, never invented heights. Three distinct diagonal control points, or fewer for small grids, are independently queried through Minecraft commands. Disagreement with decoded heights rejects the response.

Here `radius` is the half span of a square sample area, not a circular feature constraint. If the span is not divisible by the sample step, the last sample falls short of the positive edge. Hard feature proximity constraints elsewhere still use horizontal Euclidean distance.

## Measured properties and experimental classifications

Relief is the maximum sampled surface block Y minus the minimum. Mean slope averages absolute height differences divided by sample spacing over adjacent observed samples. Water and lava fractions use observed surface states. High ground uses surface block Y at least 128.

The following are deliberately labeled heuristic candidates, not hard search constraints:

| Candidate | Explicit rule |
| --- | --- |
| Valley cross section | An interior dry sample has two opposing adjacent samples at least 12 blocks higher |
| High ground component | Samples at block Y at least 128 connected through four neighbors |
| Mountain range candidate | A high ground component has at least 32 blocks of relief and a covariance based axis length of at least 64 blocks |
| Enclosed water candidate | At least four connected water samples, at most 2 blocks of surface variation, no ocean biome sample, and no sampled boundary contact |
| Elongated water candidate | At least four connected water samples, no ocean biome sample, axis ratio at least 3, and axis length at least 64 blocks |

Coarse samples can miss channels, outlets, narrow ridges, or intervening land. A sampled enclosure is not proof of a closed lake. An elongated component is not proof of a river. These classifiers need field evaluation before stronger semantic claims. At most 64 component records are returned, with the untruncated feature count.

## Transparent similarity scoring

Preferences target `relief_blocks`, `mean_slope`, `water_fraction`, `valley_fraction`, or `high_ground_fraction`. Each includes a target, positive tolerance, and weight. Its normalized value is `max(0, 1 - abs(measured - target) / tolerance)`. The final score is 100 times the weighted mean. All measurements and terms are returned. A partial grid receives no preference score.

To compare numeric terrain character, inspect a reference seed and use its measurements as targets for other known candidates. This is measurable profile similarity, not a measure of beauty or a learned visual similarity model. Unsupported subjective hard requirements remain unsupported.

## Actual fixture

`tests/fixtures/java_1_21_3_terrain.json` records an actual official MCP run for seed `-7333811035076652275` around X 48, Z 16, radius 32, step 16. All 25 samples were observed. The sampled surface block relief was 38, mean Y was 87.56, and mean slope was 0.26875. Independent control commands matched all three heights, including Y 91 at X 48, Z 16. The initial run took 14.520 seconds on the local Apple M3.

The same integration test separately checks water at X 1440, Z 288, surface Y 63, positive water depth, and an unsafe teleport result. It runs only with `DREAMSEED_RUN_MINECRAFT_INTEGRATION=1`.

## Previews

The SVG colors sampled surfaces by height, water, and lava. Gray cells are unobserved. The OBJ mesh uses true sampled block heights with no vertical exaggeration. Its horizontal coordinates are relative to its returned origin. Two triangles connect each complete sample quad; quads touching missing samples are omitted. The local browser app provides a rotatable view of this mesh.

These previews interpolate a surface. They do not contain full block geometry, caves, overhangs, or building models. They are not screenshots of an existing Minecraft client. The 5 by 5 fixture produces 25 vertices and 32 triangles, derived from actual samples.

The decoder was checked against [Yarn heightmap mappings](https://maven.fabricmc.net/docs/yarn-1.21.1%2Bbuild.3/net/minecraft/world/Heightmap.html), [packed integer storage](https://maven.fabricmc.net/docs/yarn-1.21.1%2Bbuild.3/net/minecraft/util/collection/PackedIntegerArray.html), and independent official command results. No Minecraft code or world archive is redistributed.
