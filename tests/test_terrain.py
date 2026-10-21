import copy
import json
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from dreamseed_mcp.minecraft_chunks import ChunkDataError
from dreamseed_mcp.schemas import TerrainAnalysisRequest, TerrainArea
from dreamseed_mcp.terrain_analysis import analyze_grid, components
from dreamseed_mcp.terrain_data import biome_at, block_at, collect_terrain, height_at, is_water_state, packed_value, terrain_grid
from dreamseed_mcp.terrain_rendering import render_terrain
from dreamseed_mcp.terrain_cli import write_export


def pack(values, bits):
    per_long = 64 // bits
    result = [0] * ((len(values) + per_long - 1) // per_long)
    for index, value in enumerate(values):
        result[index // per_long] |= value << ((index % per_long) * bits)
    return tuple(value if value < 1 << 63 else value - (1 << 64) for value in result)


def grid(heights, water=None):
    water = set() if water is None else water
    rows = [[{"surface_y": value + 1, "floor_y": value - 2 if (r, c) in water else value + 1,
              "surface_block": "minecraft:water" if (r, c) in water else "minecraft:stone", "surface_properties": {},
              "biome": "minecraft:plains", "is_water": (r, c) in water, "is_lava": False,
              "water_depth": 3 if (r, c) in water else 0}
             for c, value in enumerate(row)] for r, row in enumerate(heights)]
    return {"rows": rows, "height": len(rows), "width": len(rows[0]), "sample_step": 16, "origin": {"x": -32, "z": -32}}


class TerrainDataTests(unittest.TestCase):
    def test_water_plants_bubble_columns_and_waterlogged_states_are_water(self):
        for name in ("water", "kelp", "kelp_plant", "seagrass", "tall_seagrass", "bubble_column"):
            self.assertTrue(is_water_state({"name": "minecraft:" + name, "properties": {}}))
        self.assertTrue(is_water_state({"name": "minecraft:oak_slab", "properties": {"waterlogged": "true"}}))
        self.assertFalse(is_water_state({"name": "minecraft:oak_slab", "properties": {"waterlogged": "false"}}))

    def test_export_refuses_to_overwrite_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "surface.obj"
            write_export(path, "original content")
            with self.assertRaises(FileExistsError):
                write_export(path, "replacement content")
            self.assertEqual(path.read_text(), "original content")

    def test_padded_long_boundaries_and_signed_entries(self):
        values = [index % 385 for index in range(256)]
        data = pack(values, 9)
        self.assertEqual(len(data), 37)
        for index, value in enumerate(values):
            self.assertEqual(packed_value(data, 9, 256, index), value)
        self.assertEqual(packed_value((-1,) * 256, 32, 512, 1), (1 << 32) - 1)
        for wrong in ((data[:-1], 9, 256, 0), (data, 0, 256, 0), (data, 9, 256, 256)):
            with self.assertRaises(ChunkDataError):
                packed_value(*wrong)

    def test_heightmap_uses_bottom_offset_and_x_fastest(self):
        values = [64] * 256
        values[31] = 155
        chunk = {"Heightmaps": {"MOTION_BLOCKING_NO_LEAVES": pack(values, 9)}}
        self.assertEqual(height_at(chunk, "MOTION_BLOCKING_NO_LEAVES", -1, 1), 91)
        self.assertEqual(height_at(chunk, "MOTION_BLOCKING_NO_LEAVES", 0, 0), 0)
        values[0] = 511
        chunk["Heightmaps"]["MOTION_BLOCKING_NO_LEAVES"] = pack(values, 9)
        with self.assertRaises(ChunkDataError):
            height_at(chunk, "MOTION_BLOCKING_NO_LEAVES", 0, 0)

    def test_block_and_biome_palette_indices_include_negative_coordinates(self):
        values = [0] * 4096
        values[15 * 256 + 15 * 16 + 15] = 1
        chunk = {"sections": [{"Y": -1, "block_states": {
            "palette": [{"Name": "minecraft:air"}, {"Name": "minecraft:water", "Properties": {"level": "0"}}],
            "data": pack(values, 4)}, "biomes": {"palette": ["minecraft:plains"]}}]}
        self.assertEqual(block_at(chunk, -1, -1, -1)["name"], "minecraft:water")
        self.assertEqual(block_at(chunk, -16, -16, -16)["name"], "minecraft:air")
        self.assertEqual(biome_at(chunk, -1, -1, -1), "minecraft:plains")
        for y in (-65, 320, 0):
            with self.assertRaises(ChunkDataError):
                block_at(chunk, 0, y, 0)
        values[0] = 15
        chunk["sections"][0]["block_states"]["data"] = pack(values, 4)
        with self.assertRaises(ChunkDataError):
            block_at(chunk, 0, -16, 0)

    def test_missing_wrong_version_and_timeout_never_create_terrain(self):
        area = {"center": {"x": 0, "z": 0}, "radius": 0, "sample_step": 16}
        with tempfile.TemporaryDirectory() as temporary:
            result = collect_terrain(Path(temporary), "1.21.3", area, time.monotonic() + 1)
            self.assertEqual(result["status"], "terrain_unconfirmed")
            self.assertIsNone(result["rows"][0][0])
            timed = collect_terrain(Path(temporary), "1.21.3", area, 0)
            self.assertEqual(timed["failures"][0]["code"], "terrain_timeout")
            with patch("dreamseed_mcp.terrain_data.read_chunk", return_value=({"DataVersion": 3955}, "0" * 64)):
                wrong = collect_terrain(Path(temporary), "1.21.3", area, time.monotonic() + 1)
            self.assertEqual(wrong["failures"][0]["code"], "unsupported_chunk_version")

    def test_schema_bounds_and_grid_coordinates(self):
        for area in ({"radius": 257}, {"radius": 256, "sample_step": 4}, {"radius": 256, "sample_step": 16},
                     {"sample_step": 5}, {"radius": 32, "center": {"x": 30000000, "z": 0}}):
            with self.subTest(area=area), self.assertRaises(ValidationError):
                TerrainArea.model_validate(area)
        origin, width, grouped = terrain_grid(TerrainArea(radius=32).model_dump())
        self.assertEqual(origin, {"x": -32, "z": -32})
        self.assertEqual(width, 5)
        self.assertEqual(len(grouped), 25)
        request = {"minecraft_version": "1.21.3", "seed": "0"}
        for extra in ({"include_mesh": True, "include_preview": False}, {"include_mesh": "true"},
                      {"preferences": [{"metric": "water_fraction", "target": 2, "tolerance": 1}]}, {"seed": 0}):
            with self.assertRaises(ValidationError):
                TerrainAnalysisRequest.model_validate(request | extra)


class TerrainAnalysisTests(unittest.TestCase):
    def test_valley_and_flat_surface_are_distinguished_by_explicit_rule(self):
        valley = grid([[90, 80, 60, 80, 90]] * 5)
        kinds = [feature["kind"] for feature in analyze_grid(valley, [])["features"]]
        self.assertIn("valley_cross_section_candidate", kinds)
        self.assertEqual(analyze_grid(grid([[70] * 5 for _ in range(5)]), [])["features"], [])

    def test_high_ground_and_range_candidates_use_measured_relief(self):
        ridge = grid([[140 + r * 10] * 7 for r in range(7)])
        features = analyze_grid(ridge, [])["features"]
        self.assertIn("mountain_range_candidate", [feature["kind"] for feature in features])
        self.assertEqual(features[0]["classification"], "sampled_terrain_heuristic")
        self.assertEqual(features[0]["metrics"]["relief_blocks"], 60)

    def test_lake_boundary_ocean_and_elongated_water_rules(self):
        levels = [[70] * 9 for _ in range(9)]
        lake = {(3, 3), (3, 4), (4, 3), (4, 4)}
        kinds = lambda value: {item["kind"] for item in analyze_grid(value, [])["features"]}
        self.assertIn("enclosed_water_candidate", kinds(grid(levels, lake)))
        self.assertNotIn("enclosed_water_candidate", kinds(grid(levels, {(0, c) for c in range(6)})))
        self.assertIn("elongated_water_candidate", kinds(grid(levels, {(4, c) for c in range(9)})))
        ocean = grid(levels, lake)
        for r, c in lake:
            ocean["rows"][r][c]["biome"] = "minecraft:ocean"
        self.assertNotIn("enclosed_water_candidate", kinds(ocean))
        self.assertEqual(len(components([[True, False], [False, True]])), 2)

    def test_similarity_scoring_and_partial_data(self):
        data = grid([[60, 70], [80, 90]])
        preference = {"metric": "relief_blocks", "target": 40, "tolerance": 20, "weight": 2}
        analysis = analyze_grid(data, [preference])
        self.assertEqual(analysis["score"], 50)
        self.assertEqual(analysis["score_breakdown"][0]["measured_value"], 30)
        data["rows"][0][0] = None
        self.assertIsNone(analyze_grid(data, [preference])["score"])
        self.assertEqual(analyze_grid(data, [preference])["metrics"]["coverage_fraction"], 0.75)

    def test_preview_and_mesh_preserve_actual_samples_and_holes(self):
        data = grid([[60, 70, 80], [80, 90, 100], [100, 110, 120]])
        preview = render_terrain(data, "0", "1.21.3", True)
        ET.fromstring(preview["svg"])
        mesh = preview["mesh"]
        self.assertEqual(mesh["vertex_count"], 9)
        self.assertEqual(mesh["triangle_count"], 8)
        self.assertIn("v 0 60 0", mesh["obj"])
        self.assertIn("v 32 120 32", mesh["obj"])
        hole = copy.deepcopy(data)
        hole["rows"][1][1] = None
        mesh = render_terrain(hole, "0", "1.21.3", True)["mesh"]
        self.assertEqual(mesh["vertex_count"], 8)
        self.assertEqual(mesh["triangle_count"], 0)
        self.assertIsNone(render_terrain(data, "0", "1.21.3", False)["mesh"])


if __name__ == "__main__":
    unittest.main()
