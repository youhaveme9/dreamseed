from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path
from typing import Any

from .minecraft_registry import STRUCTURE_IDS
from .versions import DEFAULT_VERSION, get_version


MAX_CHUNK_BYTES = 8 * 1024 * 1024
MAX_NBT_NODES = 100_000
MAX_NBT_DEPTH = 64
SECTOR_BYTES = 4096


class ChunkDataError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class NbtReader:
    def __init__(self, data: bytes):
        if len(data) > MAX_CHUNK_BYTES:
            raise ChunkDataError("chunk_size_limit", "decompressed chunk exceeds the byte limit")
        self.data = memoryview(data)
        self.offset = 0
        self.nodes = 0

    def take(self, size: int) -> memoryview:
        if size < 0 or size > len(self.data) - self.offset:
            raise ChunkDataError("invalid_nbt", "truncated NBT payload")
        result = self.data[self.offset:self.offset + size]
        self.offset += size
        return result

    def number(self, format_: str) -> int | float:
        return struct.unpack(format_, self.take(struct.calcsize(format_)))[0]

    def string(self) -> str:
        size = self.number(">H")
        try:
            return bytes(self.take(size)).replace(b"\xc0\x80", b"\0").decode("utf-8", "surrogatepass")
        except UnicodeDecodeError as error:
            raise ChunkDataError("invalid_nbt", "invalid NBT string") from error

    def payload(self, tag: int, depth: int = 0) -> Any:
        self.nodes += 1
        if depth > MAX_NBT_DEPTH or self.nodes > MAX_NBT_NODES:
            raise ChunkDataError("nbt_complexity_limit", "NBT nesting or node count exceeds the limit")
        formats = {1: ">b", 2: ">h", 3: ">i", 4: ">q", 5: ">f", 6: ">d"}
        if tag in formats:
            return self.number(formats[tag])
        if tag == 8:
            return self.string()
        if tag in (7, 11, 12):
            count = self.number(">i")
            if tag != 7:
                self.nodes += count
                if count < 0 or self.nodes > MAX_NBT_NODES:
                    raise ChunkDataError("nbt_complexity_limit", "NBT array exceeds the node limit")
            width = {7: 1, 11: 4, 12: 8}[tag]
            raw = self.take(count * width)
            if tag == 7:
                return bytes(raw)
            return tuple(value[0] for value in struct.iter_unpack(">i" if tag == 11 else ">q", raw))
        if tag == 9:
            element_tag = self.number(">B")
            count = self.number(">i")
            if count < 0 or count > MAX_NBT_NODES - self.nodes or not 0 <= element_tag <= 12:
                raise ChunkDataError("invalid_nbt", "invalid or excessive NBT list length or element type")
            if count and element_tag == 0:
                raise ChunkDataError("invalid_nbt", "nonempty NBT list cannot contain end tags")
            return [self.payload(element_tag, depth + 1) for _ in range(count)]
        if tag == 10:
            values: dict[str, Any] = {}
            while True:
                child_tag = self.number(">B")
                if child_tag == 0:
                    return values
                name = self.string()
                if name in values:
                    raise ChunkDataError("invalid_nbt", "duplicate NBT compound key")
                values[name] = self.payload(child_tag, depth + 1)
        raise ChunkDataError("invalid_nbt", f"unsupported NBT tag {tag}")

    def read(self) -> dict[str, Any]:
        if self.number(">B") != 10:
            raise ChunkDataError("invalid_nbt", "chunk NBT root must be a compound")
        self.string()
        result = self.payload(10)
        if self.offset != len(self.data):
            raise ChunkDataError("invalid_nbt", "unexpected trailing NBT data")
        return result


def decompress_chunk(payload: bytes, compression: int) -> bytes:
    if compression == 3:
        if len(payload) > MAX_CHUNK_BYTES:
            raise ChunkDataError("chunk_size_limit", "uncompressed chunk exceeds the byte limit")
        return payload
    if compression not in (1, 2):
        raise ChunkDataError("unsupported_chunk_compression", "only gzip, zlib, and uncompressed chunks are supported")
    decoder = zlib.decompressobj(31 if compression == 1 else 15)
    try:
        data = decoder.decompress(payload, MAX_CHUNK_BYTES + 1)
    except zlib.error as error:
        raise ChunkDataError("invalid_chunk_compression", "chunk decompression failed") from error
    if len(data) > MAX_CHUNK_BYTES or decoder.unconsumed_tail:
        raise ChunkDataError("chunk_size_limit", "decompressed chunk exceeds the byte limit")
    if not decoder.eof or decoder.unused_data:
        raise ChunkDataError("invalid_chunk_compression", "incomplete or trailing compressed chunk data")
    return data


def read_chunk(world: Path, chunk_x: int, chunk_z: int) -> tuple[dict[str, Any], str]:
    region = world / "region" / f"r.{chunk_x // 32}.{chunk_z // 32}.mca"
    try:
        with region.open("rb") as stream:
            stream.seek(4 * ((chunk_z % 32) * 32 + chunk_x % 32))
            location = stream.read(4)
            if len(location) != 4:
                raise ChunkDataError("invalid_region", "truncated region location table")
            entry = int.from_bytes(location, "big")
            sector, sectors = entry >> 8, entry & 255
            if not entry:
                raise ChunkDataError("chunk_not_saved", "target chunk has no saved region entry")
            if sector < 2 or not sectors:
                raise ChunkDataError("invalid_region", "invalid chunk sector allocation")
            stream.seek(0, 2)
            if (sector + sectors) * SECTOR_BYTES > stream.tell():
                raise ChunkDataError("invalid_region", "chunk sector allocation exceeds the region file")
            stream.seek(sector * SECTOR_BYTES)
            header = stream.read(5)
            if len(header) != 5:
                raise ChunkDataError("invalid_region", "truncated chunk header")
            length = int.from_bytes(header[:4], "big")
            if length < 1 or length > sectors * SECTOR_BYTES - 4:
                raise ChunkDataError("invalid_region", "chunk length exceeds allocated sectors")
            if header[4] & 128:
                raise ChunkDataError("external_chunk_unsupported", "external chunk storage is not supported")
            payload = stream.read(length - 1)
    except OSError as error:
        raise ChunkDataError("chunk_not_saved", "target region file could not be read") from error
    raw = decompress_chunk(payload, header[4])
    chunk = NbtReader(raw).read()
    if chunk.get("xPos") != chunk_x or chunk.get("zPos") != chunk_z:
        raise ChunkDataError("chunk_coordinate_mismatch", "saved chunk coordinates do not match the requested chunk")
    return chunk, hashlib.sha256(raw).hexdigest()


def inspect_structure_start(world: Path, name: str, x: int, z: int, minecraft_version: str = DEFAULT_VERSION) -> dict[str, Any]:
    chunk_x, chunk_z = x // 16, z // 16
    evidence: dict[str, Any] = {
        "status": "unconfirmed", "chunk": {"x": chunk_x, "z": chunk_z}, "piece_count": 0,
    }
    try:
        chunk, digest = read_chunk(world, chunk_x, chunk_z)
        evidence.update({
            "data_version": chunk.get("DataVersion"),
            "chunk_status": chunk.get("Status"),
            "chunk_sha256": digest,
        })
        if chunk.get("DataVersion") != get_version(minecraft_version).data_version:
            raise ChunkDataError("unsupported_chunk_version", f"saved chunk does not use the pinned Java {minecraft_version} data version")
        if chunk.get("Status") != "minecraft:full":
            raise ChunkDataError("chunk_not_fully_generated", "structure start chunk has not reached full generation")
        structures = chunk.get("structures")
        starts = structures.get("starts") if isinstance(structures, dict) else None
        if not isinstance(starts, dict):
            raise ChunkDataError("structure_start_missing", "saved chunk contains no structure start table")
        candidates = [(key, starts[key]) for key in STRUCTURE_IDS[name] if key in starts]
        for key, start in candidates:
            if not isinstance(start, dict) or start.get("id") != key:
                continue
            if start.get("ChunkX") != chunk_x or start.get("ChunkZ") != chunk_z:
                continue
            pieces = start.get("Children")
            if not isinstance(pieces, list) or not pieces:
                continue
            boxes = []
            for piece in pieces:
                box = piece.get("BB") if isinstance(piece, dict) else None
                piece_id = piece.get("id") if isinstance(piece, dict) else None
                if (
                    not isinstance(piece_id, str) or not piece_id.startswith("minecraft:")
                    or not isinstance(box, tuple) or len(box) != 6
                    or any(not isinstance(value, int) for value in box)
                    or any(box[axis] > box[axis + 3] for axis in range(3))
                ):
                    break
                boxes.append(box)
            if len(boxes) != len(pieces):
                continue
            bounds = tuple(min(box[axis] for box in boxes) for axis in range(3)) + tuple(
                max(box[axis] for box in boxes) for axis in range(3, 6)
            )
            evidence.update({
                "status": "confirmed", "structure_id": key, "piece_count": len(pieces),
                "piece_ids": sorted({piece["id"] for piece in pieces}),
                "bounding_box": dict(zip(("min_x", "min_y", "min_z", "max_x", "max_y", "max_z"), bounds)),
                "detail": "The fully generated start chunk contains a valid structure start with serialized pieces and bounding boxes.",
            })
            return evidence
        raise ChunkDataError("structure_start_unconfirmed", "no matching valid structure start with pieces was found in the located chunk")
    except ChunkDataError as error:
        evidence.update({"code": error.code, "detail": str(error)})
        return evidence
