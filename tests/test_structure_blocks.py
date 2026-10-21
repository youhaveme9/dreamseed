import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from dreamseed_mcp.minecraft_chunks import ChunkDataError
from dreamseed_mcp.schemas import MinecraftVerificationRequest
from dreamseed_mcp.structure_blocks import igloo_trapdoor_state, load_template, rotate_position, rotate_state, verify_igloo_blocks


class StructureBlockTests(unittest.TestCase):
    def test_rotations_preserve_footprint_and_block_properties(self):
        expected = ((1, 2), (5, 1), (5, 5), (2, 5))
        for turns in range(4):
            self.assertEqual(rotate_position(1, 2, 7, 8, turns), expected[turns])
        state = {"Name": "minecraft:oak_trapdoor", "Properties": {"facing": "north", "half": "top", "open": "false"}}
        for turns, direction in enumerate(("north", "east", "south", "west")):
            rotated = rotate_state(state, turns)
            self.assertEqual(rotated["properties"]["facing"], direction)
            self.assertEqual(rotated["properties"]["half"], "top")
        self.assertEqual(state["Properties"]["facing"], "north")

    def test_official_conditional_trapdoor_rule(self):
        trapdoor = {"name": "minecraft:oak_trapdoor", "properties": {"facing": "north"}}
        for name in ("air", "cave_air", "void_air", "ladder"):
            self.assertEqual(igloo_trapdoor_state(trapdoor, {"name": "minecraft:" + name}), trapdoor)
        self.assertEqual(igloo_trapdoor_state(trapdoor, {"name": "minecraft:stone"}), {"name": "minecraft:snow_block", "properties": {}})

    def test_unsupported_structure_requests_and_template_names_are_rejected(self):
        request = {"minecraft_version": "1.21.3", "seed": "0", "confirm_template_blocks": True}
        for structures in (["village"], ["igloo", "village"], []):
            with self.assertRaises(ValidationError):
                MinecraftVerificationRequest.model_validate(request | {"structures": structures})
        with self.assertRaises(ValidationError):
            MinecraftVerificationRequest.model_validate(request | {"structures": ["igloo"], "confirm_structure_starts": False})
        with self.assertRaises(ChunkDataError):
            load_template("1.21.3", "../../other")

    def test_mismatch_missing_data_and_deadline_cannot_confirm(self):
        expected = {"name": "minecraft:stone", "properties": {}}
        plan = {"expected": {(0, 70, 0): expected}, "chunks": {(0, 0)}, "piece_count": 1,
                "ignored_markers": 0, "rotations": ["NONE"], "top_trapdoors": set()}
        chunk = {"DataVersion": 4082, "Status": "minecraft:full"}
        with tempfile.TemporaryDirectory() as directory:
            world = Path(directory)
            with patch("dreamseed_mcp.structure_blocks.igloo_plan", return_value=copy.deepcopy(plan)), \
                 patch("dreamseed_mcp.structure_blocks.read_chunk", return_value=(chunk, "0" * 64)), \
                 patch("dreamseed_mcp.structure_blocks.block_at", return_value={"name": "minecraft:air", "properties": {}}):
                result = verify_igloo_blocks(world, 0, 0, "1.21.3", time.monotonic() + 1)
                self.assertEqual(result["status"], "mismatched")
                self.assertEqual(result["mismatch_count"], 1)
                self.assertNotEqual(result["expected_sha256"], result["observed_sha256"])
                expired = verify_igloo_blocks(world, 0, 0, "1.21.3", 0)
                self.assertEqual(expired["status"], "unconfirmed")
            missing = verify_igloo_blocks(world, 0, 0, "1.21.3", time.monotonic() + 1)
            self.assertEqual(missing["status"], "unconfirmed")


if __name__ == "__main__":
    unittest.main()
