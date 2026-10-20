---
name: find-minecraft-seed
description: Find and compare Minecraft Java 1.21.1 seeds from a natural language request by using the DreamSeed MCP tools. Use for supported biome, structure, proximity, inspection, and bounded seed search requests.
---

# Find a Minecraft seed

Use DreamSeed for factual seed evaluation. Never invent a seed, biome, coordinate, score, or validation claim.

## Workflow

1. Call `get_search_capabilities` before constructing a new search.

2. Translate mandatory requirements into `hard_constraints`. Translate wishes such as closer into `soft_preferences`.

3. Use an explicit `reference_point`. Default to X 0 and Z 0 only when the user gives no anchor.

4. Never call origin the world spawn. DreamSeed does not calculate actual world spawn.

5. Use `biome_at` for an exact coordinate. Use `biome_within` for a radius search at an explicit Y level. Explain that this operation samples a deterministic grid and can miss areas between samples.

6. Use `structure_within` only for structure names returned by capabilities. Set `count` when several structures are required.

7. Use `max_distance` with the IDs of two feature constraints when features must be near each other.

8. Use `minimize_distance` preferences to rank closer supported features. Do not translate subjective scenery into a score.

9. Call `start_seed_search`, then poll `get_search_status`. Fetch `get_search_results` when matches appear and once the job ends.

10. If the user stops or replaces a running request, call `cancel_seed_search`.

11. Explain the search strategy, candidate count, coverage, validation status, score breakdown, and caveats with each answer.

12. A zero result bounded search is not proof that no matching seed exists.

13. Use `inspect_seed` with `include_biome_map` only when structured map data helps answer the request. Explain its sample step and do not describe it as continuous terrain.

14. A recovered job with state `interrupted` stopped with its prior MCP server. Return its retained results with that limitation or start a new bounded search when the user wants fresh completion.

15. Treat every `cubiomes_predicted` result as a candidate. When authoritative verification is available, call `verify_seed_with_minecraft` for the best candidates before giving teleport coordinates.

16. Prefer a returned surface coordinate when `safe_teleport` is true. Never invent a Y coordinate. If surface probing fails or reports water or lava, recommend spectator mode or a different candidate.

17. Use `include_biome_map` on verification when a visual summary helps. Green markers are official Minecraft locate results. Orange markers are Cubiomes predictions. Gray markers are client supplied. Do not describe a sampled biome map as rendered terrain.

18. If Minecraft does not locate a required target or its surface is water or lava, verify the next ranked candidate. Rank verified candidates with measured constraints first. Label any AI visual preference as subjective and keep it separate from factual validation.

## Refinement

Keep constraints that the user did not change. Replace only the affected constraint or preference. For two villages, change the village constraint count to 2. For a closer cherry grove, keep the cherry grove requirement and add or strengthen its distance preference. Start a new job after refinement.

## Unsupported requests

Disclose unsupported requirements before searching. Current examples include actual spawn relative checks, terrain shape, valleys, beauty, lakes, rivers as terrain features, block level structure confirmation, Bedrock Edition, and versions other than Java 1.21.1. Official verification initially supports villages, pillager outposts, and listed search biomes.

Desert pyramid, jungle temple, and woodland mansion positions have an exact terrain caveat. Report every structure using the exact status returned by DreamSeed.
