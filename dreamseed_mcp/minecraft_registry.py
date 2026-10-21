from __future__ import annotations

from .versions import get_version

DATA_VERSION = get_version().data_version
MAX_CANDIDATE_STRUCTURE_TARGETS = 16
MAX_CANDIDATE_BIOME_TARGETS = 16

# Registry entries and tags from the pinned Java 1.21.1 server jar.
STRUCTURE_IDS = {
    "village": (
        "minecraft:village_plains", "minecraft:village_desert", "minecraft:village_savanna",
        "minecraft:village_snowy", "minecraft:village_taiga",
    ),
    "desert_pyramid": ("minecraft:desert_pyramid",),
    "jungle_temple": ("minecraft:jungle_pyramid",),
    "swamp_hut": ("minecraft:swamp_hut",),
    "igloo": ("minecraft:igloo",),
    "ocean_ruin": ("minecraft:ocean_ruin_cold", "minecraft:ocean_ruin_warm"),
    "shipwreck": ("minecraft:shipwreck", "minecraft:shipwreck_beached"),
    "ocean_monument": ("minecraft:monument",),
    "woodland_mansion": ("minecraft:mansion",),
    "pillager_outpost": ("minecraft:pillager_outpost",),
}

STRUCTURE_QUERIES = {
    name: f"#minecraft:{name}" if len(ids) > 1 else ids[0]
    for name, ids in STRUCTURE_IDS.items()
}
