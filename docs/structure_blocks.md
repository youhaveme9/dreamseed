# Scoped igloo block validation

Version 0.2.0 adds optional exact block state comparison for igloos. This is a deliberately limited implementation of the broader structure block validation milestone. It does not imply block completeness support for villages, outposts, or the other structure families.

## Request

Call `verify_seed_with_minecraft` with `examples/verify_igloo_blocks.json`. `confirm_template_blocks` defaults to false. Enabling it requires only `igloo` in the structure list and `confirm_structure_starts` enabled. Other combinations return an explicit unsupported validation response.

The official server jar is installed separately after EULA acceptance. DreamSeed reads igloo top, middle, and bottom templates directly from that version's checksum pinned jar at runtime. Templates, bytecode, and complete Minecraft worlds are never bundled in DreamSeed packages.

## What is checked

1. Locate the igloo and confirm its full saved start chunk.
2. Read every serialized igloo piece and validate its template name, rotation, and bounding dimensions.
3. Construct the expected block state at each declared template coordinate, applying rotation and placement offsets from the saved piece bounds.
4. Apply the vanilla top entrance rule: retain the trapdoor over air or a ladder, otherwise expect snow. This rule was checked against the pinned official server behavior and bytecode.
5. Generate every horizontal chunk needed by the plan, flush, and stop the server cleanly.
6. Compare every expected non marker state, including declared template air, against saved full chunk block palettes of the requested data version.

Rotation handles the properties present in these pinned igloo templates. At most 64 pieces, 100000 expected blocks, and 64 target chunks are accepted. Unsupported templates, malformed bounds, missing data, and expired deadlines cannot produce confirmation.

`template_blocks_confirmed` means all planned block states matched. `block_verification` includes expected and checked counts, piece count, rotations, ignored marker count, mismatch count, and canonical expected and observed SHA256 digests. Only the first sixteen mismatches are included, while the total count remains exact. A mismatch preserves generated start evidence and returns partial verification, not a global claim that the seed lacks a valid structure.

## Scope exclusions

Structure blocks and structure void markers are not placed template blocks and are excluded. Coordinates omitted from templates are not expected voxels. Entity contents, loot, villagers, block entity NBT, marker effects, external terrain, and safe entrances are not verified. Dynamic environmental changes can cause a comparison mismatch. The tool is intended for a fresh isolated vanilla world, not an arbitrary modified save.

Broader template processors, jigsaw pools, terrain adaptations, carving, and procedural structures still require structure specific evaluators. Unsupported families remain unsupported rather than receiving a metadata based claim of block completeness.

## Actual regressions

`tests/fixtures/igloo_template_blocks.json` records observed official MCP results. Java 1.21.1 and 1.21.3 seed `0` matched all 455 planned blocks over six pieces. Java 1.21.3 seeds `1`, `2`, and `3` each matched 152 blocks for surface variants, covering snow replacement and a preserved trapdoor. Seed `8` matched 515 blocks over ten pieces with clockwise rotation. Together these cases exercise all four rotations, signed coordinates, basements, and surface igloos.

These checks are repeated by the optional official integration gate. Unit tests separately reject mismatches, unsupported target families, missing chunks, invalid templates, and expired deadlines. Default verification still checks only start metadata unless the template flag is explicitly enabled.
