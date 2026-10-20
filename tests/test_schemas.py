import unittest

from pydantic import ValidationError

from dreamseed_mcp.schemas import (
    InspectRequest,
    MinecraftVerificationRequest,
    RenderSeedMapRequest,
    SearchRequest,
    parse_seed,
)


class SchemaTests(unittest.TestCase):
    def test_signed_seed_boundaries(self):
        self.assertEqual(parse_seed("-9223372036854775808"), -(1 << 63))
        self.assertEqual(parse_seed("9223372036854775807"), (1 << 63) - 1)
        for value in ("9223372036854775808", "-9223372036854775809", "1.5", "+1"):
            with self.assertRaises(ValueError):
                parse_seed(value)

    def test_schema_rejects_extra_and_unsupported(self):
        request = {
            "minecraft_version": "1.21.1",
            "hard_constraints": [
                {"id": "x", "type": "biome_at", "biome": "plains", "unknown": True}
            ],
        }
        with self.assertRaises(ValidationError):
            SearchRequest.model_validate(request)

    def test_cross_constraint_references(self):
        request = {
            "minecraft_version": "1.21.1",
            "hard_constraints": [
                {"id": "v", "type": "structure_within", "structure": "village", "radius": 100},
                {"id": "d", "type": "max_distance", "from": "v", "to": "missing", "max_distance": 5},
            ],
        }
        with self.assertRaises(ValidationError):
            SearchRequest.model_validate(request)

    def test_phase_two_structures_are_typed(self):
        request = SearchRequest.model_validate({
            "minecraft_version": "1.21.1",
            "hard_constraints": [
                {
                    "id": "outpost", "type": "structure_within",
                    "structure": "pillager_outpost", "radius": 1000,
                }
            ],
        })
        self.assertEqual(request.hard_constraints[0].structure, "pillager_outpost")
        inspection = InspectRequest.model_validate({
            "minecraft_version": "1.21.1",
            "seed": "0",
            "structures": [
                "village", "desert_pyramid", "jungle_temple", "swamp_hut",
                "igloo", "ocean_ruin", "shipwreck", "ocean_monument",
                "woodland_mansion", "pillager_outpost",
            ],
        })
        self.assertEqual(len(inspection.structures), 10)

    def test_relation_grid_memory_is_bounded(self):
        request = {
            "minecraft_version": "1.21.1",
            "hard_constraints": [
                {
                    "id": "a", "type": "biome_within", "biome": "plains",
                    "radius": 1024, "sample_step": 4,
                },
                {
                    "id": "b", "type": "biome_within", "biome": "forest",
                    "radius": 1024, "sample_step": 4,
                },
                {
                    "id": "near", "type": "max_distance", "from": "a", "to": "b",
                    "max_distance": 100,
                },
            ],
            "budget": {"workers": 64},
        }
        with self.assertRaises(ValidationError):
            SearchRequest.model_validate(request)

    def test_biome_map_size_is_bounded(self):
        with self.assertRaises(ValidationError):
            InspectRequest.model_validate({
                "minecraft_version": "1.21.1",
                "seed": "0",
                "area": {"radius": 2048, "sample_step": 4},
                "include_biome_map": True,
            })

        request = InspectRequest.model_validate({
            "minecraft_version": "1.21.1",
            "seed": "0",
            "area": {"radius": 64, "sample_step": 16},
            "include_biome_map": True,
        })
        self.assertTrue(request.include_biome_map)

    def test_radius_area_stays_inside_coordinate_bounds(self):
        with self.assertRaises(ValidationError):
            SearchRequest.model_validate({
                "minecraft_version": "1.21.1",
                "hard_constraints": [{
                    "id": "edge", "type": "structure_within", "structure": "village",
                    "anchor": {"x": 30_000_000, "z": 0}, "radius": 1,
                }],
            })
        with self.assertRaises(ValidationError):
            InspectRequest.model_validate({
                "minecraft_version": "1.21.1",
                "seed": "0",
                "area": {"center": {"x": 30_000_000, "z": 0}, "radius": 1},
            })

    def test_minecraft_verification_requires_targets(self):
        with self.assertRaises(ValidationError):
            MinecraftVerificationRequest.model_validate({
                "minecraft_version": "1.21.1",
                "seed": "0",
            })
        request = MinecraftVerificationRequest.model_validate({
            "minecraft_version": "1.21.1",
            "seed": "-7333811035076652275",
            "structures": ["village", "pillager_outpost"],
            "biomes": ["cherry_grove"],
        })
        self.assertEqual(request.reference_point.y, 64)

    def test_render_map_size_is_bounded(self):
        with self.assertRaises(ValidationError):
            RenderSeedMapRequest.model_validate({
                "minecraft_version": "1.21.1",
                "seed": "0",
                "area": {"radius": 2048, "sample_step": 16},
            })
        with self.assertRaises(ValidationError):
            RenderSeedMapRequest.model_validate({
                "minecraft_version": "1.21.1",
                "seed": "0",
                "markers": [{
                    "kind": "structure",
                    "name": "village",
                    "coordinates": {"x": 0, "z": 0},
                    "validation_status": "minecraft_located",
                }],
            })


if __name__ == "__main__":
    unittest.main()
