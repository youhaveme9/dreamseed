import copy
import unittest
from unittest.mock import patch

from dreamseed_mcp.candidate_verification import CandidatePlanError, build_candidate_targets, recheck_candidate


def criteria():
    return {
        "reference_point": {"x": 0, "z": 0},
        "hard_constraints": [
            {"id": "villages", "type": "structure_within", "structure": "village", "radius": 100, "count": 2},
            {"id": "cherry", "type": "biome_within", "biome": "cherry_grove", "radius": 100, "y": 96},
            {"id": "pair", "type": "max_distance", "from": "villages", "to": "cherry", "max_distance": 50},
        ],
        "soft_preferences": [
            {"type": "minimize_distance", "constraint_id": "villages", "weight": 1},
            {"type": "minimize_distance", "constraint_id": "cherry", "weight": 1},
        ],
    }


def evidence():
    return [
        {"target_id": "a", "constraint_ids": ["villages"], "kind": "structure", "name": "village",
         "coordinates": {"x": 0, "z": 0}, "verification_status": "generated_chunks_confirmed"},
        {"target_id": "b", "constraint_ids": ["villages"], "kind": "structure", "name": "village",
         "coordinates": {"x": 80, "z": 0}, "verification_status": "generated_chunks_confirmed"},
        {"target_id": "c", "constraint_ids": ["cherry"], "kind": "biome", "name": "cherry_grove",
         "coordinates": {"x": 50, "z": 0, "y": 96}, "verification_status": "minecraft_biome_checked"},
    ]


class CandidateVerificationTests(unittest.TestCase):
    def test_counts_pair_distance_and_scoring(self):
        checked = recheck_candidate(criteria(), evidence())
        self.assertTrue(checked["all_hard_constraints_verified"])
        self.assertEqual(checked["constraint_checks"][0]["verified_count"], 2)
        self.assertEqual(checked["spatial_checks"][0]["measured_distance"], 30)
        self.assertEqual(checked["soft_preference_score"], 75)
        self.assertEqual(len(checked["score_breakdown"]), 2)

    def test_one_start_cannot_count_twice(self):
        features = evidence()
        features[1]["coordinates"] = {"x": 1, "z": 1}
        checked = recheck_candidate(criteria(), features)
        self.assertFalse(checked["all_hard_constraints_verified"])
        self.assertEqual(checked["constraint_checks"][0]["verified_count"], 1)
        self.assertIsNone(checked["soft_preference_score"])

    def test_unconfirmed_or_wrong_features_never_satisfy_constraints(self):
        for change in (
            {"verification_status": "unconfirmed"}, {"name": "pillager_outpost"},
            {"coordinates": {"x": 101, "z": 0}},
        ):
            features = evidence()
            features[1].update(change)
            with self.subTest(change=change):
                self.assertFalse(recheck_candidate(criteria(), features)["all_hard_constraints_verified"])

    def test_biome_level_and_mismatch_are_checked(self):
        for change in ({"coordinates": {"x": 50, "z": 0, "y": 64}}, {"verification_status": "biome_mismatch"}):
            features = evidence()
            features[2].update(change)
            with self.subTest(change=change):
                checked = recheck_candidate(criteria(), features)
                self.assertFalse(checked["all_hard_constraints_verified"])
                self.assertEqual(checked["spatial_checks"], [])

    def test_pair_must_pass_its_own_distance(self):
        request = criteria()
        request["hard_constraints"][2]["max_distance"] = 29
        checked = recheck_candidate(request, evidence())
        self.assertEqual(checked["constraint_checks"][2]["status"], "not_verified")
        self.assertEqual(checked["constraint_checks"][2]["measured_distance"], 30)

    def test_explicit_anchors_and_inclusive_boundaries(self):
        request = criteria()
        request["hard_constraints"][0]["anchor"] = {"x": 180, "z": 0}
        self.assertFalse(recheck_candidate(request, evidence())["all_hard_constraints_verified"])
        request["hard_constraints"][0]["radius"] = 180
        self.assertTrue(recheck_candidate(request, evidence())["all_hard_constraints_verified"])

    def test_exact_biome_coordinate_is_not_substituted(self):
        request = criteria()
        request["hard_constraints"][1] = {
            "id": "cherry", "type": "biome_at", "biome": "cherry_grove", "coordinate": {"x": 50, "z": 0}, "y": 96,
        }
        self.assertTrue(recheck_candidate(request, evidence())["all_hard_constraints_verified"])
        request["hard_constraints"][1]["coordinate"]["x"] = 51
        self.assertFalse(recheck_candidate(request, evidence())["all_hard_constraints_verified"])

    def test_plan_includes_spatial_witnesses_and_deduplicates_chunks(self):
        prediction = {
            "features": [
                {"constraint_id": "villages", "coordinates": {"x": 0, "z": 0}},
                {"constraint_id": "villages", "coordinates": {"x": 1, "z": 1}},
                {"constraint_id": "cherry", "coordinates": {"x": 50, "z": 0}},
            ],
            "spatial_checks": [{
                "from_constraint": "villages", "from_coordinates": {"x": 80, "z": 0},
                "to_constraint": "cherry", "to_coordinates": {"x": 90, "z": 0},
            }],
        }
        original = copy.deepcopy(prediction)
        targets = build_candidate_targets(criteria(), prediction)
        self.assertEqual(len(targets), 4)
        self.assertEqual(targets[1]["coordinates"]["y"], 96)
        self.assertEqual(prediction, original)
        with patch("dreamseed_mcp.candidate_verification.MAX_CANDIDATE_STRUCTURE_TARGETS", 1):
            with self.assertRaises(CandidatePlanError):
                build_candidate_targets(criteria(), prediction)


if __name__ == "__main__":
    unittest.main()
