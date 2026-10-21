from __future__ import annotations

import math
from collections import deque
from typing import Any


def components(mask: list[list[bool]]) -> list[list[tuple[int, int]]]:
    height, width = len(mask), len(mask[0])
    seen: set[tuple[int, int]] = set()
    result = []
    for row in range(height):
        for column in range(width):
            if not mask[row][column] or (row, column) in seen:
                continue
            seen.add((row, column))
            queue = deque([(row, column)])
            group = []
            while queue:
                point = queue.popleft()
                group.append(point)
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = point[0] + dr, point[1] + dc
                    if 0 <= nr < height and 0 <= nc < width and mask[nr][nc] and (nr, nc) not in seen:
                        seen.add((nr, nc))
                        queue.append((nr, nc))
            result.append(group)
    return result


def describe_component(grid: dict[str, Any], kind: str, points: list[tuple[int, int]]) -> dict[str, Any]:
    step, origin = grid["sample_step"], grid["origin"]
    xs = [origin["x"] + column * step for _, column in points]
    zs = [origin["z"] + row * step for row, _ in points]
    heights = [grid["rows"][row][column]["surface_y"] - 1 for row, column in points]
    mean_x, mean_z = sum(xs) / len(xs), sum(zs) / len(zs)
    xx = sum((x - mean_x) ** 2 for x in xs) / len(xs)
    zz = sum((z - mean_z) ** 2 for z in zs) / len(zs)
    xz = sum((x - mean_x) * (z - mean_z) for x, z in zip(xs, zs)) / len(xs)
    delta = math.sqrt((xx - zz) ** 2 + 4 * xz * xz)
    major = max(0, (xx + zz + delta) / 2)
    minor = max(0, (xx + zz - delta) / 2)
    length = math.sqrt(12 * major) + step
    width = math.sqrt(12 * minor) + step
    boundary = any(row in {0, grid["height"] - 1} or column in {0, grid["width"] - 1} for row, column in points)
    return {
        "kind": kind, "classification": "sampled_terrain_heuristic",
        "centroid": {"x": mean_x, "z": mean_z},
        "bounds": {"min_x": min(xs), "min_z": min(zs), "max_x": max(xs), "max_z": max(zs)},
        "sample_count": len(points), "touches_boundary": boundary,
        "metrics": {"min_surface_block_y": min(heights), "max_surface_block_y": max(heights),
                    "relief_blocks": max(heights) - min(heights), "axis_length_blocks": length,
                    "axis_width_blocks": width, "axis_aspect_ratio": length / width},
    }


def analyze_grid(grid: dict[str, Any], preferences: list[dict[str, Any]]) -> dict[str, Any]:
    rows, step = grid["rows"], grid["sample_step"]
    height, width = grid["height"], grid["width"]
    observed = [cell for row in rows for cell in row if cell is not None]
    if not observed:
        return {"metrics": {}, "features": [], "feature_count": 0, "score": None, "score_breakdown": []}
    heights = [cell["surface_y"] - 1 for cell in observed]
    slopes = []
    valley_mask = [[False] * width for _ in range(height)]
    for row in range(height):
        for column in range(width):
            cell = rows[row][column]
            if cell is None:
                continue
            for nr, nc in ((row + 1, column), (row, column + 1)):
                if nr < height and nc < width and rows[nr][nc] is not None:
                    slopes.append(abs(cell["surface_y"] - rows[nr][nc]["surface_y"]) / step)
            if 0 < row < height - 1 and 0 < column < width - 1 and not cell["is_water"]:
                for neighbors in (((row - 1, column), (row + 1, column)), ((row, column - 1), (row, column + 1))):
                    sides = [rows[r][c] for r, c in neighbors]
                    if all(side is not None and side["surface_y"] - cell["surface_y"] >= 12 for side in sides):
                        valley_mask[row][column] = True
    high_mask = [[cell is not None and cell["surface_y"] - 1 >= 128 for cell in row] for row in rows]
    water_mask = [[cell is not None and cell["is_water"] for cell in row] for row in rows]
    features = []
    for kind, mask in (("valley_cross_section_candidate", valley_mask), ("high_ground_component", high_mask),
                       ("water_component", water_mask)):
        for points in components(mask):
            component = describe_component(grid, kind, points)
            metric = component["metrics"]
            if kind == "water_component":
                cells = [rows[r][c] for r, c in points]
                ocean = any("ocean" in cell["biome"] for cell in cells)
                if len(points) >= 4 and not component["touches_boundary"] and not ocean and metric["relief_blocks"] <= 2:
                    component["kind"] = "enclosed_water_candidate"
                    features.append(component)
                if len(points) >= 4 and not ocean and metric["axis_aspect_ratio"] >= 3 and metric["axis_length_blocks"] >= 64:
                    elongated = dict(component, kind="elongated_water_candidate")
                    features.append(elongated)
            else:
                features.append(component)
                if kind == "high_ground_component" and metric["relief_blocks"] >= 32 and metric["axis_length_blocks"] >= 64:
                    features.append(dict(component, kind="mountain_range_candidate"))
    features.sort(key=lambda item: (item["kind"], -item["sample_count"], item["centroid"]["x"], item["centroid"]["z"]))
    metrics = {
        "relief_blocks": max(heights) - min(heights), "min_surface_block_y": min(heights),
        "max_surface_block_y": max(heights), "mean_surface_block_y": sum(heights) / len(heights),
        "mean_slope": sum(slopes) / len(slopes) if slopes else 0,
        "max_sample_slope": max(slopes, default=0),
        "water_fraction": sum(cell["is_water"] for cell in observed) / len(observed),
        "lava_fraction": sum(cell["is_lava"] for cell in observed) / len(observed),
        "valley_fraction": sum(sum(row) for row in valley_mask) / len(observed),
        "high_ground_fraction": sum(sum(row) for row in high_mask) / len(observed),
        "coverage_fraction": len(observed) / (width * height),
    }
    breakdown = []
    for preference in preferences if len(observed) == width * height else []:
        measured = metrics[preference["metric"]]
        value = max(0, 1 - abs(measured - preference["target"]) / preference["tolerance"])
        breakdown.append({**preference, "measured_value": measured, "normalized_value": value})
    weight = sum(item["weight"] for item in breakdown)
    return {
        "metrics": metrics, "features": features[:64], "feature_count": len(features),
        "score": 100 * sum(item["normalized_value"] * item["weight"] for item in breakdown) / weight if weight else None,
        "score_breakdown": breakdown,
    }
