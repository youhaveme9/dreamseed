from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from .minecraft_chunks import ChunkDataError, read_chunk
from .versions import get_version


MIN_Y = -64
WORLD_HEIGHT = 384
MAX_TERRAIN_CHUNKS = 256
MAX_TERRAIN_POINTS = 4225
WATER_BLOCKS = {f"minecraft:{name}" for name in ("water", "bubble_column", "kelp", "kelp_plant", "seagrass", "tall_seagrass")}


def is_water_state(state: dict[str, Any]) -> bool:
    return state["name"] in WATER_BLOCKS or state["properties"].get("waterlogged") == "true"


def packed_value(data: Any, bits: int, count: int, index: int) -> int:
    if not isinstance(data, tuple) or not 1 <= bits <= 32 or not 0 <= index < count:
        raise ChunkDataError("invalid_packed_array", "invalid packed array parameters")
    per_long = 64 // bits
    if len(data) != (count + per_long - 1) // per_long:
        raise ChunkDataError("invalid_packed_array", "packed array length does not match its layout")
    value = data[index // per_long]
    if not isinstance(value, int):
        raise ChunkDataError("invalid_packed_array", "packed array entries must be integers")
    return (value >> ((index % per_long) * bits)) & ((1 << bits) - 1)


def height_at(chunk: dict[str, Any], name: str, x: int, z: int) -> int:
    maps = chunk.get("Heightmaps")
    data = maps.get(name) if isinstance(maps, dict) else None
    height = packed_value(data, WORLD_HEIGHT.bit_length(), 256, (z % 16) * 16 + x % 16)
    if not 0 <= height <= WORLD_HEIGHT:
        raise ChunkDataError("invalid_heightmap", "heightmap entry exceeds the Overworld height")
    return MIN_Y + height


def section_at(chunk: dict[str, Any], y: int) -> dict[str, Any]:
    sections = chunk.get("sections")
    if not isinstance(sections, list):
        raise ChunkDataError("invalid_sections", "saved chunk contains no section list")
    found = [section for section in sections if isinstance(section, dict) and section.get("Y") == y // 16]
    if len(found) != 1:
        raise ChunkDataError("missing_section", "surface section is missing or duplicated")
    return found[0]


def palette_entry(container: Any, count: int, index: int, min_bits: int) -> Any:
    palette = container.get("palette") if isinstance(container, dict) else None
    if not isinstance(palette, list) or not 1 <= len(palette) <= count:
        raise ChunkDataError("invalid_palette", "saved section has an invalid palette")
    if len(palette) == 1:
        if container.get("data") not in (None, ()):
            raise ChunkDataError("invalid_palette", "single value palette has unexpected packed data")
        return palette[0]
    bits = max(min_bits, (len(palette) - 1).bit_length())
    entry = packed_value(container.get("data"), bits, count, index)
    if entry >= len(palette):
        raise ChunkDataError("invalid_palette_index", "block or biome index is outside the saved palette")
    return palette[entry]


def block_at(chunk: dict[str, Any], x: int, y: int, z: int) -> dict[str, Any]:
    if not MIN_Y <= y < MIN_Y + WORLD_HEIGHT:
        raise ChunkDataError("unsupported_block_height", "requested block is outside the supported Overworld height")
    section = section_at(chunk, y)
    index = (y % 16) * 256 + (z % 16) * 16 + x % 16
    state = palette_entry(section.get("block_states"), 4096, index, 4)
    if not isinstance(state, dict) or not isinstance(state.get("Name"), str) or not state["Name"].startswith("minecraft:"):
        raise ChunkDataError("invalid_block_state", "saved block state lacks a Minecraft registry name")
    properties = state.get("Properties", {})
    if not isinstance(properties, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in properties.items()):
        raise ChunkDataError("invalid_block_state", "saved block state properties must be strings")
    return {"name": state["Name"], "properties": dict(sorted(properties.items()))}


def biome_at(chunk: dict[str, Any], x: int, y: int, z: int) -> str:
    section = section_at(chunk, y)
    index = ((y % 16) // 4) * 16 + ((z % 16) // 4) * 4 + (x % 16) // 4
    biome = palette_entry(section.get("biomes"), 64, index, 1)
    if not isinstance(biome, str) or not biome.startswith("minecraft:"):
        raise ChunkDataError("invalid_biome_state", "saved biome palette lacks a Minecraft registry name")
    return biome


def terrain_grid(area: dict[str, Any]) -> tuple[dict[str, int], int, dict[tuple[int, int], list[tuple[int, int, int, int]]]]:
    radius, step = area["radius"], area["sample_step"]
    center = area["center"]
    origin = {"x": center["x"] - radius, "z": center["z"] - radius}
    width = 2 * radius // step + 1
    grouped: dict[tuple[int, int], list[tuple[int, int, int, int]]] = defaultdict(list)
    for row in range(width):
        for column in range(width):
            x, z = origin["x"] + column * step, origin["z"] + row * step
            grouped[x // 16, z // 16].append((row, column, x, z))
    return origin, width, dict(grouped)


def collect_terrain(world: Path, minecraft_version: str, area: dict[str, Any], deadline: float) -> dict[str, Any]:
    origin, width, grouped = terrain_grid(area)
    if width * width > MAX_TERRAIN_POINTS or len(grouped) > MAX_TERRAIN_CHUNKS:
        raise ChunkDataError("terrain_resource_limit", "terrain area exceeds the sample or chunk limit")
    rows: list[list[dict[str, Any] | None]] = [[None] * width for _ in range(width)]
    failures = []
    confirmed = []
    for (chunk_x, chunk_z), points in sorted(grouped.items()):
        try:
            if time.monotonic() >= deadline:
                raise ChunkDataError("terrain_timeout", "terrain reading exceeded the request time limit")
            chunk, digest = read_chunk(world, chunk_x, chunk_z)
            if chunk.get("DataVersion") != get_version(minecraft_version).data_version:
                raise ChunkDataError("unsupported_chunk_version", "terrain chunk data version does not match the request")
            if chunk.get("Status") != "minecraft:full":
                raise ChunkDataError("chunk_not_fully_generated", "terrain chunk has not reached full generation")
            for row, column, x, z in points:
                surface_y = height_at(chunk, "MOTION_BLOCKING_NO_LEAVES", x, z)
                floor_y = height_at(chunk, "OCEAN_FLOOR", x, z)
                state = block_at(chunk, x, surface_y - 1, z)
                water = is_water_state(state)
                rows[row][column] = {
                    "surface_y": surface_y, "floor_y": floor_y, "surface_block": state["name"],
                    "surface_properties": state["properties"], "biome": biome_at(chunk, x, surface_y - 1, z),
                    "is_water": water, "is_lava": state["name"] == "minecraft:lava",
                    "water_depth": max(0, surface_y - floor_y) if water else 0,
                }
            confirmed.append({"x": chunk_x, "z": chunk_z, "sha256": digest})
        except ChunkDataError as error:
            for row, column, _, _ in points:
                rows[row][column] = None
            failures.append({"chunk": {"x": chunk_x, "z": chunk_z}, "code": error.code, "message": str(error)})
    observed = sum(cell is not None for row in rows for cell in row)
    return {
        "encoding": "surface_sample_rows", "origin": origin, "width": width, "height": width,
        "sample_step": area["sample_step"], "heightmap": "MOTION_BLOCKING_NO_LEAVES",
        "height_semantics": "first_free_y_above_heightmap_surface_not_safe_teleport",
        "rows": rows, "sample_count": width * width, "observed_sample_count": observed,
        "requested_chunk_count": len(grouped), "observed_chunks": confirmed, "failures": failures,
        "status": "generated_terrain_confirmed" if observed == width * width else "partial_terrain" if observed else "terrain_unconfirmed",
    }
