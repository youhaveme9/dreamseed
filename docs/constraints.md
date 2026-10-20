# Constraint reference

Every search request uses Minecraft Java Edition version `1.21.1`. Coordinates are block coordinates. Distance calculations ignore Y and use horizontal Euclidean distance.

## Request shape

```json
{
  "minecraft_version": "1.21.1",
  "reference_point": {"x": 0, "z": 0},
  "hard_constraints": [],
  "soft_preferences": [],
  "budget": {
    "strategy": "sampled",
    "sample_seed": "0",
    "max_candidates": 100000,
    "max_seconds": 10,
    "workers": 4
  },
  "max_results": 10
}
```

Use `start_seed` instead of `sample_seed` for `sequential` strategy. Both values are signed 64 bit decimal strings.

## Biome at a coordinate

```json
{
  "id": "origin_plains",
  "type": "biome_at",
  "biome": "plains",
  "coordinate": {"x": 0, "z": 0},
  "y": 64
}
```

If `coordinate` is omitted, the request reference point is used.

## Biome within a radius

```json
{
  "id": "cherry",
  "type": "biome_within",
  "biome": "cherry_grove",
  "anchor": {"x": 0, "z": 0},
  "radius": 800,
  "y": 96,
  "sample_step": 16
}
```

The engine performs exact biome lookups at grid coordinates inside the circle. A positive result is exact at its reported coordinate. The grid can miss a biome between samples.

## Structure within a radius

```json
{
  "id": "villages",
  "type": "structure_within",
  "structure": "village",
  "anchor": {"x": 0, "z": 0},
  "radius": 1000,
  "count": 3
}
```

Supported structure names are `village`, `desert_pyramid`, `jungle_temple`, `swamp_hut`, `igloo`, `ocean_ruin`, `shipwreck`, `ocean_monument`, `woodland_mansion`, and `pillager_outpost`.

Desert pyramids, jungle temples, and woodland mansions use Cubiomes terrain screening but still carry an exact terrain caveat. Other structures use their Cubiomes placement and structure specific viability checks. All search structure coordinates are predictions at generation attempt positions rather than block accurate entrances. Use `verify_seed_with_minecraft` for an official Minecraft locate check on supported targets.

## Distance between features

```json
{
  "id": "close_pair",
  "type": "max_distance",
  "from": "villages",
  "to": "cherry",
  "max_distance": 300
}
```

`from` and `to` must name feature constraint IDs in the same request.

The engine considers every viable structure attempt and every matching biome sample for this relation. Accepted results include a `spatial_checks` entry with the measured distance and the coordinate pair that satisfied the condition.

The combined biome relation grid is bounded across workers. If a request exceeds that memory bound, reduce worker count or radius, or increase `sample_step`.

## Soft distance preference

```json
{
  "type": "minimize_distance",
  "constraint_id": "villages",
  "weight": 1
}
```

For a radius constraint, closeness is `1 minus distance divided by radius`, clamped from 0 through 1. The final score is the weighted mean multiplied by 100. Ties use signed seed order for deterministic ranking.

## Errors

Validation errors contain `code`, `path`, and `message`. Unsupported requirements use explicit codes such as `unsupported_version`, `unsupported_condition`, `unsupported_biome`, or `unsupported_structure`.

## Structured biome map inspection

Set `include_biome_map` on an inspection request:

```json
{
  "minecraft_version": "1.21.1",
  "seed": "7810500614729040739",
  "area": {
    "center": {"x": 0, "z": 0},
    "radius": 64,
    "sample_step": 16,
    "y": 64
  },
  "structures": ["village", "pillager_outpost"],
  "include_biome_map": true
}
```

The result contains a square grid with an origin, dimensions, sample step, Y level, alphabetic biome palette, and rows of palette indices. Rows increase Z and columns increase X. Every cell is an exact Cubiomes lookup at its grid coordinate. The output is limited to 100,000 cells.

The biome summary continues to use samples inside the circular inspection radius. The structured map covers the square bounding area so clients can render it without inferring missing cells.
