# Exact candidate verification

`verify_seed_candidate` rechecks a selected seed against the same criteria used by search. It is available starting with 0.2.0.

## Request

Use `examples/verify_seed_candidate.json` as MCP arguments under `request`. Supply `minecraft_version`, a signed decimal string `seed`, `reference_point`, `hard_constraints`, `soft_preferences`, `probe_surfaces`, and `max_seconds`. The criteria use the same typed constraints and reference validation as search. Search budgets and worker counts are not accepted because this tool evaluates one candidate.

## Evaluation

1. Validate and normalize the criteria through the native engine.
2. Evaluate the single seed with Cubiomes and collect the reported feature and spatial pair witnesses.
3. Deduplicate physical structure starts by type and chunk. Preserve the exact requested Y for every biome witness.
4. Generate the selected chunks in the pinned official server. Structure starts require saved full chunks and valid piece data. Biomes require positive and negative command controls at the exact X, Y, and Z.
5. Recheck counts, radii, and each spatial relation using confirmed evidence only. Recalculate preferences only when all hard requirements are verified.

The verifier does not call nearest structure locate to replace a selected position. Extra spatial witnesses are included even if they were not among the closest structures shown in the original result. Two points in one structure start chunk cannot count as two structures. Each spatial relation is existential and independent; different relations can use different feature instances, just as in native search.

## Results

`verified` means all hard requirements have official witnesses. Each structure uses `generated_chunks_confirmed`; each matching exact biome uses `minecraft_biome_checked`. The result includes target IDs, associated constraint IDs, original requested coordinates, confirmed coordinates, reference distances, structure evidence, optional surfaces, constraint checks, measured spatial checks, score breakdown, and failures.

Structure coordinates are the confirmed start chunk block origin. They are not an entrance or a particular structure piece. Surface coordinates describe the point actually probed, which can differ from a canonical structure coordinate. Distances remain horizontal Euclidean blocks from explicit anchors, never actual world spawn.

`not_verified` means the selected evidence did not prove all requirements. A biome mismatch or unconfirmed structure cannot satisfy a hard constraint. The score is null rather than presenting an unverified candidate as ranked.

`prediction_rejected` means Cubiomes rejected the candidate before Minecraft started. Its source is `cubiomes_prediction_only`. This is not an authoritative rejection of the whole seed, particularly where biome sampling can miss valid areas.

Coverage is always `selected_candidate_witnesses`. A failed witness does not prove that no other match exists. A successful score is based on the closest confirmed selected witnesses, not a proof that those are globally nearest. Structure confirmation is limited to starts and serialized piece data, not every block. Surface safety remains independent of hard constraints.

## Resource limits

The plan is limited to 16 distinct structure targets and 16 distinct biome targets. Oversized plans fail before launching Minecraft with `candidate_verification_limit`; they are never silently truncated. Preparation and verification share a 30 through 300 second request budget. The existing single verifier process and Java heap limits still apply. Clients cannot supply arbitrary console commands, files, or evidence.

## Recorded example

On 21 October 2026, a real MCP call with `examples/verify_seed_candidate.json` verified all six requirements for seed `-7333811035076652275`. The witnesses included three distinct villages, two outposts, plains at X 0, Y 64, Z 0, and cherry grove at X negative 96, Y 96, Z 160.

The confirmed village and outpost pair at X negative 960, Z 80 and X negative 784, Z 16 measured `187.275198571514` horizontal blocks. The village at X 48, Z 16 and cherry grove witness measured `203.64675298172568` blocks. The preference score was `87.04883986736604`. The observed runtime was 21.380 seconds on the local Apple M3, not a general throughput guarantee.

`tests/fixtures/java_1_21_1_candidate_verification.json` records these observed coordinates, piece counts, distances, score, and pinned server checksum. Reproduce the real MCP regression with `DREAMSEED_RUN_MINECRAFT_INTEGRATION=1 make test` after installing the server and accepting its EULA.
