from __future__ import annotations

import math
from typing import Any

from .minecraft_registry import MAX_CANDIDATE_BIOME_TARGETS, MAX_CANDIDATE_STRUCTURE_TARGETS


class CandidatePlanError(ValueError):
    pass


def build_candidate_targets(criteria: dict[str, Any], prediction: dict[str, Any]) -> list[dict[str, Any]]:
    constraints = {item["id"]: item for item in criteria["hard_constraints"]}
    targets: dict[tuple, dict[str, Any]] = {}

    def add(constraint_id: str, coordinate: dict[str, int]) -> None:
        constraint = constraints[constraint_id]
        kind = "structure" if constraint["type"] == "structure_within" else "biome"
        name = constraint["structure"] if kind == "structure" else constraint["biome"]
        position = {"x": coordinate["x"], "z": coordinate["z"]}
        if kind == "biome":
            position["y"] = constraint["y"]
            key = kind, name, position["x"], position["y"], position["z"]
        else:
            key = kind, name, position["x"] // 16, position["z"] // 16
        if key not in targets:
            targets[key] = {
                "target_id": f"target_{len(targets)}", "constraint_ids": [],
                "kind": kind, "name": name, "coordinates": position,
            }
        if constraint_id not in targets[key]["constraint_ids"]:
            targets[key]["constraint_ids"].append(constraint_id)

    for feature in prediction["features"]:
        add(feature["constraint_id"], feature["coordinates"])
    for pair in prediction["spatial_checks"]:
        add(pair["from_constraint"], pair["from_coordinates"])
        add(pair["to_constraint"], pair["to_coordinates"])
    for kind, limit in (("structure", MAX_CANDIDATE_STRUCTURE_TARGETS), ("biome", MAX_CANDIDATE_BIOME_TARGETS)):
        count = sum(target["kind"] == kind for target in targets.values())
        if count > limit:
            raise CandidatePlanError(
                f"candidate requires {count} distinct {kind} targets; the limit is {limit}; reduce counts or split the criteria"
            )
    return list(targets.values())


def recheck_candidate(criteria: dict[str, Any], features: list[dict[str, Any]]) -> dict[str, Any]:
    verified: dict[str, list[dict[str, Any]]] = {}
    checks: list[dict[str, Any]] = []
    constraints = {item["id"]: item for item in criteria["hard_constraints"]}
    for constraint in criteria["hard_constraints"]:
        kind = constraint["type"]
        if kind == "max_distance":
            continue
        constraint_id = constraint["id"]
        anchor = constraint.get("anchor", criteria["reference_point"])
        accepted: dict[tuple, dict[str, Any]] = {}
        for feature in features:
            if constraint_id not in feature["constraint_ids"]:
                continue
            if feature["verification_status"] not in {"generated_chunks_confirmed", "minecraft_biome_checked"}:
                continue
            position = feature["coordinates"]
            if kind == "structure_within":
                if feature["kind"] != "structure" or feature["name"] != constraint["structure"]:
                    continue
                identity = feature["name"], position["x"] // 16, position["z"] // 16
            else:
                if feature["kind"] != "biome" or feature["name"] != constraint["biome"] or position.get("y") != constraint["y"]:
                    continue
                identity = feature["name"], position["x"], position["y"], position["z"]
            if kind == "biome_at":
                expected = constraint["coordinate"]
                if position["x"] != expected["x"] or position["z"] != expected["z"]:
                    continue
            elif math.hypot(position["x"] - anchor["x"], position["z"] - anchor["z"]) > constraint["radius"]:
                continue
            accepted[identity] = feature
        verified[constraint_id] = list(accepted.values())
        required = constraint.get("count", 1)
        passed = len(accepted) >= required
        checks.append({
            "constraint_id": constraint_id, "type": kind, "status": "verified" if passed else "not_verified",
            "feature_ids": [item["target_id"] for item in accepted.values()],
            "required_count": required, "verified_count": len(accepted),
            **({"maximum_distance": constraint["radius"]} if "radius" in constraint else {}),
            "detail": "Selected official witnesses satisfy the requirement." if passed else "Selected official witnesses do not prove the requirement.",
        })

    spatial_checks = []
    for constraint in criteria["hard_constraints"]:
        if constraint["type"] != "max_distance":
            continue
        pairs = [
            (math.hypot(a["coordinates"]["x"] - b["coordinates"]["x"], a["coordinates"]["z"] - b["coordinates"]["z"]), a, b)
            for a in verified[constraint["from"]] for b in verified[constraint["to"]]
        ]
        closest = min(pairs, key=lambda item: (item[0], item[1]["target_id"], item[2]["target_id"])) if pairs else None
        distance = closest[0] if closest else None
        passed = distance is not None and distance <= constraint["max_distance"]
        checks.append({
            "constraint_id": constraint["id"], "type": "max_distance", "status": "verified" if passed else "not_verified",
            "feature_ids": [closest[1]["target_id"], closest[2]["target_id"]] if closest else [],
            "measured_distance": distance, "maximum_distance": constraint["max_distance"],
            "detail": "An official witness pair satisfies the distance." if passed else "Selected official witnesses do not prove a valid pair.",
        })
        if closest:
            spatial_checks.append({
                "constraint_id": constraint["id"], "operation": "max_distance",
                "from_constraint": constraint["from"], "to_constraint": constraint["to"],
                "maximum_distance": constraint["max_distance"], "measured_distance": distance,
                "from_coordinates": closest[1]["coordinates"], "to_coordinates": closest[2]["coordinates"],
                "distance_metric": "horizontal_euclidean_blocks",
            })
    check_order = {item["id"]: index for index, item in enumerate(criteria["hard_constraints"])}
    checks.sort(key=lambda item: check_order[item["constraint_id"]])
    passed = all(check["status"] == "verified" for check in checks)
    breakdown = []
    total_weight = 0.0
    weighted_score = 0.0
    if passed:
        for preference in criteria["soft_preferences"]:
            constraint_id = preference["constraint_id"]
            constraint = constraints[constraint_id]
            anchor = constraint.get("anchor", criteria["reference_point"])
            distance = 0.0 if constraint["type"] == "biome_at" else min(
                math.hypot(item["coordinates"]["x"] - anchor["x"], item["coordinates"]["z"] - anchor["z"])
                for item in verified[constraint_id]
            )
            normalized = max(0.0, min(1.0, 1 - distance / max(1, constraint.get("radius", 1))))
            weight = preference["weight"]
            weighted_score += normalized * weight
            total_weight += weight
            breakdown.append({
                "type": "minimize_distance", "constraint_id": constraint_id,
                "measured_distance": distance, "weight": weight, "normalized_value": normalized,
            })
    return {
        "status": "verified" if passed else "not_verified", "all_hard_constraints_verified": passed,
        "constraint_checks": checks, "spatial_checks": spatial_checks, "score_breakdown": breakdown,
        "soft_preference_score": (100 * weighted_score / total_weight if total_weight else 0.0) if passed else None,
    }
