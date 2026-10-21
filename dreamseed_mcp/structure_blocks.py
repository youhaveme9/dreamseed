from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from .minecraft_chunks import ChunkDataError, NbtReader, decompress_chunk, inspect_structure_start, read_chunk
from .minecraft_setup import configured_server_jar
from .terrain_data import block_at
from .versions import get_version


MAX_TEMPLATE_BLOCKS = 100000
MAX_TEMPLATE_CHUNKS = 64
TEMPLATES = {f"minecraft:igloo/{name}" for name in ("top", "middle", "bottom")}
ROTATIONS = {"NONE": 0, "CLOCKWISE_90": 1, "CLOCKWISE_180": 2, "COUNTERCLOCKWISE_90": 3}


@lru_cache(maxsize=6)
def load_template(minecraft_version: str, name: str) -> dict[str, Any]:
    if name not in TEMPLATES:
        raise ChunkDataError("unsupported_template", "only pinned igloo top, middle, and bottom templates are supported")
    try:
        with ZipFile(configured_server_jar(minecraft_version)) as outer:
            candidates = [item for item in outer.namelist() if item.startswith("META-INF/versions/") and item.endswith(".jar")]
            if len(candidates) != 1:
                raise ChunkDataError("invalid_server_archive", "official server archive has an unexpected version layout")
            with ZipFile(BytesIO(outer.read(candidates[0]))) as inner:
                raw = decompress_chunk(inner.read("data/minecraft/structure/" + name.split(":", 1)[1] + ".nbt"), 1)
    except (OSError, BadZipFile, KeyError) as error:
        raise ChunkDataError("template_unavailable", "could not read a pinned template from the installed official server") from error
    template = NbtReader(raw).read()
    if not isinstance(template.get("size"), list) or len(template["size"]) != 3 or any(type(value) is not int or not 1 <= value <= 64 for value in template["size"]):
        raise ChunkDataError("invalid_template", "template dimensions are unsupported")
    if not isinstance(template.get("palette"), list) or not isinstance(template.get("blocks"), list):
        raise ChunkDataError("invalid_template", "template must contain a single palette and block list")
    return template


def rotate_position(x: int, z: int, size_x: int, size_z: int, turns: int) -> tuple[int, int]:
    return ((x, z), (size_z - 1 - z, x), (size_x - 1 - x, size_z - 1 - z), (z, size_x - 1 - x))[turns]


def rotate_state(state: dict[str, Any], turns: int) -> dict[str, Any]:
    properties = state.get("Properties", {})
    directions = ("north", "east", "south", "west")
    def direction(value):
        return directions[(directions.index(value) + turns) % 4] if value in directions else value
    rotated = {direction(key): direction(value) if key == "facing" else value for key, value in properties.items()}
    if turns % 2 and rotated.get("axis") in {"x", "z"}:
        rotated["axis"] = "z" if rotated["axis"] == "x" else "x"
    if "rotation" in rotated:
        rotated["rotation"] = str((int(rotated["rotation"]) + turns * 4) % 16)
    return {"name": state["Name"], "properties": dict(sorted(rotated.items()))}


def igloo_plan(world: Path, x: int, z: int, minecraft_version: str, deadline: float) -> dict[str, Any]:
    start = inspect_structure_start(world, "igloo", x, z, minecraft_version)
    if start["status"] != "confirmed":
        raise ChunkDataError(start["code"], start["detail"])
    chunk, _ = read_chunk(world, x // 16, z // 16)
    pieces = chunk["structures"]["starts"]["minecraft:igloo"]["Children"]
    if len(pieces) > 64:
        raise ChunkDataError("template_resource_limit", "igloo exceeds the piece limit")
    expected = {}
    ignored = 0
    trapdoors = set()
    for piece in pieces:
        if time.monotonic() >= deadline:
            raise ChunkDataError("template_timeout", "template planning exceeded the request time limit")
        name, rotation = piece.get("Template"), piece.get("Rot")
        if piece["id"] != "minecraft:iglu" or name not in TEMPLATES or rotation not in ROTATIONS:
            raise ChunkDataError("unsupported_piece", "saved igloo contains an unsupported piece, template, or rotation")
        template = load_template(minecraft_version, name)
        size_x, size_y, size_z = template["size"]
        box, turns = piece["BB"], ROTATIONS[rotation]
        dimensions = (size_z, size_y, size_x) if turns % 2 else (size_x, size_y, size_z)
        if tuple(box[axis + 3] - box[axis] + 1 for axis in range(3)) != dimensions:
            raise ChunkDataError("unsupported_piece_bounds", "piece bounds do not match its rotated template")
        if name == "minecraft:igloo/top":
            rx, rz = rotate_position(3, 5, size_x, size_z, turns)
            trapdoors.add((box[0] + rx, box[1], box[2] + rz))
        for block in template["blocks"]:
            position, palette_index = block.get("pos"), block.get("state")
            if not isinstance(position, list) or len(position) != 3 or any(type(value) is not int for value in position):
                raise ChunkDataError("invalid_template", "template block has an invalid coordinate")
            if any(not 0 <= value < maximum for value, maximum in zip(position, template["size"])):
                raise ChunkDataError("invalid_template", "template block is outside the declared dimensions")
            if type(palette_index) is not int or not 0 <= palette_index < len(template["palette"]):
                raise ChunkDataError("invalid_template", "template block has an invalid palette index")
            state = template["palette"][palette_index]
            if state["Name"] in {"minecraft:structure_block", "minecraft:structure_void"}:
                ignored += 1
                continue
            rx, rz = rotate_position(position[0], position[2], size_x, size_z, turns)
            expected[box[0] + rx, box[1] + position[1], box[2] + rz] = rotate_state(state, turns)
            if len(expected) > MAX_TEMPLATE_BLOCKS:
                raise ChunkDataError("template_resource_limit", "igloo exceeds the template block limit")
    chunks = {(x // 16, z // 16) for x, _, z in expected}
    if not expected:
        raise ChunkDataError("invalid_template", "template plan contains no verifiable blocks")
    if len(chunks) > MAX_TEMPLATE_CHUNKS:
        raise ChunkDataError("template_resource_limit", "igloo exceeds the generated chunk limit")
    return {"expected": expected, "chunks": chunks, "piece_count": len(pieces), "ignored_markers": ignored,
            "rotations": sorted({piece["Rot"] for piece in pieces}), "top_trapdoors": trapdoors}


def igloo_trapdoor_state(expected: dict[str, Any], below: dict[str, Any]) -> dict[str, Any]:
    if below["name"] in {"minecraft:air", "minecraft:cave_air", "minecraft:void_air", "minecraft:ladder"}:
        return expected
    return {"name": "minecraft:snow_block", "properties": {}}


def verify_igloo_blocks(world: Path, x: int, z: int, minecraft_version: str, deadline: float) -> dict[str, Any]:
    evidence = {"status": "unconfirmed", "scope": "all_non_marker_igloo_template_blocks", "checked_blocks": 0,
                "matched_blocks": 0, "mismatch_count": 0, "mismatches": [], "block_entities_checked": False}
    try:
        plan = igloo_plan(world, x, z, minecraft_version, deadline)
        evidence.update({"expected_blocks": len(plan["expected"]), "piece_count": plan["piece_count"],
                         "ignored_markers": plan["ignored_markers"], "rotations": plan["rotations"]})
        expected_digest, observed_digest = hashlib.sha256(), hashlib.sha256()
        for chunk_x, chunk_z in sorted(plan["chunks"]):
            if time.monotonic() >= deadline:
                raise ChunkDataError("template_timeout", "block verification exceeded the request time limit")
            chunk, _ = read_chunk(world, chunk_x, chunk_z)
            if chunk.get("Status") != "minecraft:full":
                raise ChunkDataError("chunk_not_fully_generated", "not every igloo block chunk reached full generation")
            if chunk.get("DataVersion") != get_version(minecraft_version).data_version:
                raise ChunkDataError("unsupported_chunk_version", "igloo block chunk version does not match the request")
            for (bx, by, bz), expected in sorted(plan["expected"].items()):
                if bx // 16 != chunk_x or bz // 16 != chunk_z:
                    continue
                actual = block_at(chunk, bx, by, bz)
                if (bx, by, bz) in plan["top_trapdoors"]:
                    expected = igloo_trapdoor_state(expected, block_at(chunk, bx, by - 1, bz))
                evidence["checked_blocks"] += 1
                expected_digest.update(json.dumps([bx, by, bz, expected], sort_keys=True, separators=(",", ":")).encode())
                observed_digest.update(json.dumps([bx, by, bz, actual], sort_keys=True, separators=(",", ":")).encode())
                if actual == expected:
                    evidence["matched_blocks"] += 1
                else:
                    evidence["mismatch_count"] += 1
                    if len(evidence["mismatches"]) < 16:
                        evidence["mismatches"].append({"coordinates": {"x": bx, "y": by, "z": bz}, "expected": expected, "observed": actual})
        evidence.update({"status": "confirmed" if evidence["mismatch_count"] == 0 else "mismatched",
                         "expected_sha256": expected_digest.hexdigest(), "observed_sha256": observed_digest.hexdigest(),
                         "detail": "Compared every non marker block state in all saved igloo templates, including template air. Entity contents and marker effects are excluded."})
    except (ChunkDataError, ValueError, KeyError, TypeError) as error:
        evidence.update({"code": getattr(error, "code", "unsupported_template"), "detail": str(error)})
    return evidence
