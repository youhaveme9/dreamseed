# Landing page assets

The hero is an illustration. The biome map and surface preview are derived from actual engine data. These are deliberately labeled separately on the page.

## Landscape illustration

`dream-world.webp` was generated with the built in image generation tool on October 21, 2026, then encoded as WebP with `cwebp -q 86`. It depicts an imagined world, not a verified Minecraft seed or an in game screenshot. It uses no supplied reference artwork.

Generation prompt:

> Use case: stylized-concept. Asset type: hero landscape for the DreamSeed open source Minecraft seed finder landing page. Create a polished, cinematic Minecraft inspired voxel landscape, wide 3:2 composition. A small inviting oak and stone village with blocky roofs sits on green plains in the foreground, pink cherry grove on the middle hillside, a winding blue river, and tall jagged snowy mountains beyond. Every terrain surface and tree is recognizably built from crisp cubic blocks with pixel textures. Elevated three quarter camera, warm morning sunlight, soft atmospheric distance, gentle clouds, vivid natural greens and pinks with pale blue sky. The environment fills the composition; clear village focal point, rich detail but calm atmosphere. No text, no logo, no characters, no interface, no watermarks. This is illustrative artwork, not a screenshot of a particular seed.

## Actual biome map

`verified-inspection.json` is unmodified JSON output from the released DreamSeed 0.2.0 native engine, using the inspection request in `scripts/build_site_assets.py`. It contains 4225 Cubiomes biome samples for full world seed `-3989987067671208281`, Java 1.21.3, at Y 64 with sample step 16.

`verified-biome-map.svg` renders those samples. Its village marker at X 32, Z 0 comes from the official verification recorded in [the release validation record](https://github.com/youhaveme9/dreamseed/blob/v0.2.0/docs/validation/2026-10-21.md). Only that village marker is shown. The other structure prediction in the JSON was not independently checked for this page. The map itself is Cubiomes output, not a claim that every biome sample was checked by the official server.

Palette colors are visualization choices from DreamSeed's renderer, not Minecraft textures. North is up. X increases right and Z increases down. Every displayed distance uses the world origin, not actual world spawn.

## Observed surface mesh

`terrain-samples.json` preserves the actual official server export recorded during release validation, originally at `build/terrain-export-final-20261021/terrain.json`. It contains 25 observed columns and three successful independent control comparisons for seed `-7333811035076652275`, Java 1.21.3.

`terrain-preview.svg` projects the observed surface block heights into an isometric view with no vertical exaggeration. Its 32 triangles interpolate between samples, and colors represent height. The faint reference grid is at the lowest sampled surface height. This is not a full voxel render; structures, caves, and unsampled columns are not reconstructed. Surface block height is the saved heightmap Y minus one.

Rebuild both SVGs from the committed data:

```sh
python3 scripts/build_site_assets.py
```

Refresh the biome data using the compiled engine:

```sh
python3 scripts/build_site_assets.py --engine build/dreamseed
```

The sprout mark is an original SVG. Landing page source and assets are distributed under the repository's MIT license. Minecraft names belong to their respective owners. DreamSeed is not affiliated with Mojang Studios or Microsoft.
