from __future__ import annotations

import html
from typing import Any


def render_terrain(grid: dict[str, Any], seed: str, minecraft_version: str, include_mesh: bool) -> dict[str, Any]:
    width, height = grid["width"], grid["height"]
    rows = grid["rows"]
    values = [cell["surface_y"] - 1 for row in rows for cell in row if cell is not None]
    low, high = min(values, default=0), max(values, default=1)
    scale = max(1, high - low)
    cell_size = min(32, 960 / max(width, height))
    canvas_width, canvas_height = max(320, width * cell_size), height * cell_size + 64
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width:g}" height="{canvas_height:g}" viewBox="0 0 {canvas_width:g} {canvas_height:g}">',
             '<rect width="100%" height="100%" fill="#17212b"/>',
             f'<text x="8" y="20" fill="white" font-family="sans-serif" font-size="13">Java {html.escape(minecraft_version)} seed {html.escape(seed)}</text>']
    vertices, faces, indices = [], [], {}
    origin, step = grid["origin"], grid["sample_step"]
    for row in range(height):
        for column in range(width):
            cell = rows[row][column]
            color = "#777777"
            if cell is not None:
                fraction = (cell["surface_y"] - 1 - low) / scale
                color = "#237abb" if cell["is_water"] else "#ef6030" if cell["is_lava"] else f"#{int(65 + fraction * 170):02x}{int(100 + fraction * 130):02x}{int(65 + fraction * 170):02x}"
                if include_mesh:
                    indices[row, column] = len(vertices) + 1
                    vertices.append(f"v {column * step} {cell['surface_y'] - 1} {row * step}")
            parts.append(f'<rect x="{column * cell_size:g}" y="{32 + row * cell_size:g}" width="{cell_size:g}" height="{cell_size:g}" fill="{color}"/>')
    if include_mesh:
        for row in range(height - 1):
            for column in range(width - 1):
                points = ((row, column), (row + 1, column), (row, column + 1), (row + 1, column + 1))
                if all(point in indices for point in points):
                    a, b, c, d = (indices[point] for point in points)
                    faces.extend((f"f {a} {b} {c}", f"f {c} {b} {d}"))
    parts.append(f'<text x="8" y="{canvas_height - 10:g}" fill="white" font-family="sans-serif" font-size="12">Surface block Y {low} to {high}; step {step}; gray means unobserved</text></svg>')
    return {
        "format": "svg", "svg": "".join(parts), "width": canvas_width, "height": canvas_height,
        "mesh": ({"format": "obj", "obj": "\n".join(vertices + faces) + "\n", "origin": origin,
                  "vertex_count": len(vertices), "triangle_count": len(faces), "vertical_exaggeration": 1} if include_mesh else None),
        "semantics": "Generated surface height samples, not a voxel scene. Triangles interpolate between observed columns only.",
    }
