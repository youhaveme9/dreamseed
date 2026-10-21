---
name: find-minecraft-seed
description: Find and compare supported Minecraft Java seeds from a natural language request using DreamSeed MCP tools. Use for biome, structure, proximity, inspection, and bounded seed search requests.
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

15. Treat every `cubiomes_predicted` result as a candidate. When `candidate_verification.supported` is true, call `verify_seed_candidate` with the best seed and the original reference, hard constraints, and preferences before giving teleport coordinates. This preserves exact witnesses and rechecks counts and distances. Otherwise use `verify_seed_with_minecraft` for supported nearest locate checks, without implying that they validate the original count or pair requirements.

16. Prefer a returned surface coordinate when `safe_teleport` is true. Never invent a Y coordinate. If surface probing fails or reports water or lava, recommend spectator mode or a different candidate.

17. Use `include_biome_map` on verification when a visual summary helps. Teal markers have confirmed generated structure start data. Green markers are official Minecraft locate results. Orange markers are Cubiomes predictions. Gray markers are client supplied. Do not describe a sampled biome map as rendered terrain.

18. If Minecraft does not locate a required target or its surface is water or lava, verify the next ranked candidate. Rank verified candidates with measured constraints first. Label any AI visual preference as subjective and keep it separate from factual validation.

19. `generated_chunks_confirmed` means the full start chunk contains a valid matching start and serialized pieces. Report its registry ID, piece count, and bounding box when useful. It does not prove every structure block or an entrance. A biome from locate remains `minecraft_located`; a successful exact biome check uses `minecraft_biome_checked`. Never upgrade unconfirmed evidence.

20. The locate tool returns one nearest structure per requested type. The candidate tool instead reports `all_hard_constraints_verified`, per constraint checks, and recalculated scores. Only claim authoritative constraint satisfaction when that flag is true. A `not_verified` result does not prove that the seed has no other matches. A `prediction_rejected` result never started Minecraft. Candidate verification checks a bounded set of witnesses, not the whole world.

## Refinement

Keep constraints that the user did not change. Replace only the affected constraint or preference. For two villages, change the village constraint count to 2. For a closer cherry grove, keep the cherry grove requirement and add or strengthen its distance preference. Start a new job after refinement.

## Unsupported requests

Disclose unsupported requirements before searching. Actual spawn checks, semantic terrain guarantees, objective beauty, Bedrock, unlisted versions, and block validation for unlisted structures remain unsupported. The working branch supports Java 1.21.1 and 1.21.3 with independent fixtures. Consult capabilities because release 0.1.0 has narrower support. Use `structure48` only with a structure constraint, and explain that cohorts sample fewer structure layouts rather than searching globally.

When terrain evidence helps refine a result, use `analyze_seed_terrain` on known candidates. Report sample spacing, observed coverage, control checks, actual surface states, and caveats. Valley, mountain range, enclosed water, and elongated water labels are experimental sampled heuristics, not proof of a perfect valley, lake, or river. Numeric target similarity scores do not measure beauty. Meshes interpolate observed surface columns and omit caves and voxel detail. Terrain evidence does not silently add supported native hard constraints.

`confirm_template_blocks` on official verification currently accepts only igloo targets. It compares all non marker block states from pinned templates, with supported rotation and igloo placement rules. Do not infer complete block support for villages or other structures from igloo validation. Metal placement survivors are also unverified until full seed checks pass.

Desert pyramid, jungle temple, and woodland mansion positions have an exact terrain caveat. Report every structure using the exact status returned by DreamSeed.

For a probed teleport, use X plus 0.5 and Z plus 0.5 to center the player in the reported block, with the exact returned Y. Never invent a surface height or treat a failed fluid or clearance check as safe.
