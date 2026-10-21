import gzip
import hashlib
import struct
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from dreamseed_mcp.minecraft_chunks import (
    ChunkDataError, NbtReader, decompress_chunk, inspect_structure_start, read_chunk,
)
from dreamseed_mcp.minecraft_verifier import MinecraftVerifier


def text(value):
    encoded = value.encode("utf-8", "surrogatepass")
    return struct.pack(">H", len(encoded)) + encoded


def compound(values):
    return b"".join(bytes([tag]) + text(name) + payload for tag, name, payload in values) + b"\0"


def integer(name, value):
    return 3, name, struct.pack(">i", value)


def string(name, value):
    return 8, name, text(value)


def chunk_nbt(x=0, z=0, version=3955, status="minecraft:full", start_id="minecraft:pillager_outpost",
              start_x=None, pieces=True, structure_key="minecraft:pillager_outpost", valid_box=True):
    box = (0, 64, 0, 15, 80, 15) if valid_box else (15, 64, 0, 0, 80, 15)
    piece = compound([
        string("id", "minecraft:jigsaw"),
        (11, "BB", struct.pack(">i6i", 6, *box)),
    ])
    children = b"\x0a" + struct.pack(">i", int(pieces)) + (piece if pieces else b"")
    start = compound([
        string("id", start_id), integer("ChunkX", x if start_x is None else start_x),
        integer("ChunkZ", z), (9, "Children", children),
    ])
    return b"\x0a\0\0" + compound([
        integer("DataVersion", version), integer("xPos", x), integer("zPos", z), string("Status", status),
        (10, "structures", compound([(10, "starts", compound([(10, structure_key, start)]))])),
    ])


def write_region(world, raw, x=0, z=0, compression=2):
    payload = {1: gzip.compress, 2: zlib.compress, 3: lambda value: value}[compression](raw)
    record = struct.pack(">I", len(payload) + 1) + bytes([compression]) + payload
    sectors = (len(record) + 4095) // 4096
    header = bytearray(8192)
    struct.pack_into(">I", header, 4 * ((z % 32) * 32 + x % 32), (2 << 8) | sectors)
    path = world / "region" / f"r.{x // 32}.{z // 32}.mca"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + record.ljust(sectors * 4096, b"\0"))
    return path


class NbtReaderTests(unittest.TestCase):
    def test_numeric_tags_arrays_and_modified_utf8(self):
        values = [
            (1, "byte", struct.pack(">b", -128)), (2, "short", struct.pack(">h", -300)),
            integer("int", -(1 << 31)), (4, "long", struct.pack(">q", -(1 << 63))),
            (5, "float", struct.pack(">f", 1.5)), (6, "double", struct.pack(">d", -2.5)),
            (7, "bytes", struct.pack(">i", 2) + b"\x80\xff"),
            (8, "nul", b"\0\x04a\xc0\x80b"),
            (9, "list", b"\x03" + struct.pack(">i2i", 2, 1, -1)),
            (11, "ints", struct.pack(">i2i", 2, 1, -1)),
            (12, "longs", struct.pack(">i2q", 2, 1, -(1 << 63))),
        ]
        parsed = NbtReader(b"\x0a\0\0" + compound(values)).read()
        self.assertEqual(parsed["byte"], -128)
        self.assertEqual(parsed["long"], -(1 << 63))
        self.assertEqual(parsed["float"], 1.5)
        self.assertEqual(parsed["double"], -2.5)
        self.assertEqual(parsed["bytes"], b"\x80\xff")
        self.assertEqual(parsed["nul"], "a\0b")
        self.assertEqual(parsed["list"], [1, -1])
        self.assertEqual(parsed["ints"], (1, -1))
        self.assertEqual(parsed["longs"], (1, -(1 << 63)))

    def test_invalid_and_truncated_nbt_is_rejected(self):
        valid = chunk_nbt()
        cases = [
            b"", b"\x03\0\0\0\0\0\0", valid[:-1], valid + b"extra",
            b"\x0a\0\0" + compound([integer("a", 1), integer("a", 2)]),
            b"\x0a\0\0" + compound([(7, "array", struct.pack(">i", -1))]),
            b"\x0a\0\0" + compound([(9, "list", b"\0\0\0\0\x01")]),
            b"\x0a\0\0" + compound([(9, "list", b"\x03\xff\xff\xff\xff")]),
            b"\x0a\0\0" + compound([(13, "unknown", b"")]),
        ]
        for raw in cases:
            with self.subTest(raw=raw[:30]), self.assertRaises(ChunkDataError):
                NbtReader(raw).read()

    def test_nbt_depth_and_nodes_are_bounded(self):
        nested = b"\0"
        for _ in range(66):
            nested = compound([(10, "nested", nested)])
        with self.assertRaises(ChunkDataError):
            NbtReader(b"\x0a\0\0" + nested).read()
        with patch("dreamseed_mcp.minecraft_chunks.MAX_NBT_NODES", 2):
            with self.assertRaises(ChunkDataError):
                NbtReader(chunk_nbt()).read()

    def test_compression_is_bounded_and_checked(self):
        raw = chunk_nbt()
        for compression, encode in ((1, gzip.compress), (2, zlib.compress), (3, lambda value: value)):
            self.assertEqual(decompress_chunk(encode(raw), compression), raw)
        for data, compression in ((b"bad", 2), (zlib.compress(raw)[:-1], 2), (zlib.compress(raw) + b"extra", 2), (b"", 4)):
            with self.subTest(compression=compression), self.assertRaises(ChunkDataError):
                decompress_chunk(data, compression)
        with patch("dreamseed_mcp.minecraft_chunks.MAX_CHUNK_BYTES", 100):
            for compression, data in ((2, zlib.compress(b"x" * 100_000)), (3, b"x" * 101)):
                with self.assertRaises(ChunkDataError):
                    decompress_chunk(data, compression)


class StructureChunkTests(unittest.TestCase):
    def test_region_coordinates_include_negative_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = Path(temporary)
            for x, z in ((0, 0), (31, 31), (32, 32), (-1, -1), (-32, -32), (-33, 31)):
                with self.subTest(x=x, z=z):
                    raw = chunk_nbt(x=x, z=z)
                    write_region(world, raw, x, z)
                    chunk, digest = read_chunk(world, x, z)
                    self.assertEqual((chunk["xPos"], chunk["zPos"]), (x, z))
                    self.assertEqual(digest, hashlib.sha256(raw).hexdigest())

    def test_full_start_with_pieces_can_be_confirmed(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = Path(temporary)
            write_region(world, chunk_nbt())
            evidence = inspect_structure_start(world, "pillager_outpost", 8, 8)
            self.assertEqual(evidence["status"], "confirmed")
            self.assertEqual(evidence["structure_id"], "minecraft:pillager_outpost")
            self.assertEqual(evidence["piece_count"], 1)
            self.assertEqual(evidence["bounding_box"]["max_y"], 80)
            self.assertEqual(evidence["piece_ids"], ["minecraft:jigsaw"])

    def test_references_and_invalid_starts_cannot_confirm(self):
        cases = [
            {"start_id": "INVALID"}, {"start_x": 1}, {"pieces": False}, {"valid_box": False},
            {"structure_key": "minecraft:village_plains"}, {"status": "minecraft:structure_starts"},
            {"version": 3953},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            world = Path(temporary)
            for options in cases:
                with self.subTest(options=options):
                    write_region(world, chunk_nbt(**options))
                    evidence = inspect_structure_start(world, "pillager_outpost", 8, 8)
                    self.assertEqual(evidence["status"], "unconfirmed")
                    self.assertIn("code", evidence)
            raw = b"\x0a\0\0" + compound([
                integer("DataVersion", 3955), integer("xPos", 0), integer("zPos", 0),
                string("Status", "minecraft:full"),
                (10, "structures", compound([
                    (10, "References", compound([(12, "minecraft:pillager_outpost", struct.pack(">iq", 1, 0))])),
                ])),
            ])
            write_region(world, raw)
            self.assertEqual(inspect_structure_start(world, "pillager_outpost", 0, 0)["code"], "structure_start_missing")

    def test_missing_or_malformed_regions_are_actionable(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = Path(temporary)
            self.assertEqual(inspect_structure_start(world, "village", 0, 0)["code"], "chunk_not_saved")
            for location, length, compression in ((0, 1, 2), (0x101, 1, 2), (0x201, 4093, 2), (0x201, 1, 130)):
                path = write_region(world, chunk_nbt())
                content = bytearray(path.read_bytes())
                struct.pack_into(">I", content, 0, location)
                struct.pack_into(">I", content, 8192, length)
                content[8196] = compression
                path.write_bytes(content)
                with self.subTest(location=location, length=length, compression=compression):
                    self.assertEqual(inspect_structure_start(world, "village", 0, 0)["status"], "unconfirmed")

    def test_mismatched_saved_coordinates_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = Path(temporary)
            write_region(world, chunk_nbt(x=1))
            with self.assertRaises(ChunkDataError) as caught:
                read_chunk(world, 0, 0)
            self.assertEqual(caught.exception.code, "chunk_coordinate_mismatch")

    def test_confirmation_does_not_upgrade_biomes_or_unsaved_worlds(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = Path(temporary)
            write_region(world, chunk_nbt())
            locations = [
                {"kind": "structure", "name": "pillager_outpost", "coordinates": {"x": 0, "z": 0}, "verification_status": "minecraft_located"},
                {"kind": "biome", "name": "plains", "coordinates": {"x": 0, "z": 0}, "verification_status": "minecraft_located"},
            ]
            failures = []
            MinecraftVerifier._confirm_starts(world, locations, failures, False, time.monotonic() + 5)
            self.assertEqual(locations[0]["verification_status"], "minecraft_located")
            self.assertEqual(failures[0]["stage"], "structure_start")
            self.assertEqual(failures[0]["code"], "chunk_save_unconfirmed")
            failures.clear()
            MinecraftVerifier._confirm_starts(world, locations, failures, True, time.monotonic() + 5)
            self.assertEqual(locations[0]["verification_status"], "generated_chunks_confirmed")
            self.assertNotIn("structure_start", locations[1])
            self.assertEqual(locations[1]["verification_status"], "minecraft_located")
            self.assertEqual(failures, [])

    def test_expired_confirmation_does_not_read_a_chunk(self):
        locations = [{"kind": "structure", "name": "village", "coordinates": {"x": -1, "z": -1}}]
        failures = []
        MinecraftVerifier._confirm_starts(Path("/missing"), locations, failures, True, time.monotonic() - 1)
        self.assertEqual(locations[0]["structure_start"]["chunk"], {"x": -1, "z": -1})
        self.assertEqual(failures[0]["code"], "verification_timeout")


if __name__ == "__main__":
    unittest.main()
