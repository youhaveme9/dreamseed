#!/usr/bin/env python3
"""Render the landing page's evidence images from saved generation data."""

from __future__ import annotations

import argparse
import json
import math
from html import escape
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dreamseed_mcp.rendering import biome_color  # noqa: E402

ASSETS = ROOT / "site" / "assets"
INSPECTION = {
    "minecraft_version": "1.21.3",
    "seed": "-3989987067671208281",
    "area": {"center": {"x": 0, "z": 0}, "radius": 512, "sample_step": 16, "y": 64},
    "structures": ["village"],
    "include_biome_map": True,
}


def biome_map_svg(inspection: dict) -> str:
    grid = inspection["biome_map"]
    cell = 600 / grid["width"]
    left, top = 100, 40
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 830" width="800" height="830" role="img" aria-labelledby="title desc">',
        '<title id="title">Real biome samples around the world origin</title>',
        '<desc id="desc">Java 1.21.3 seed -3989987067671208281. Cubiomes samples at Y 64, step 16. Village start at X 32 Z 0 independently confirmed with the official server.</desc>',
        '<style>text{font-family:ui-sans-serif,system-ui,sans-serif;fill:#365039}.axis{font-size:12px;fill:#6e7e61}.legend{font-size:12px}</style>',
        '<rect width="800" height="830" fill="#f2f3e9"/>',
        '<g shape-rendering="crispEdges">',
    ]
    for z, row in enumerate(grid["rows"]):
        start = 0
        while start < len(row):
            end = start + 1
            while end < len(row) and row[start] == row[end]:
                end += 1
            color = biome_color(grid["palette"][row[start]])
            parts.append(f'<rect x="{left + start * cell:.3f}" y="{top + z * cell:.3f}" width="{(end - start) * cell:.3f}" height="{cell:.3f}" fill="{color}"/>')
            start = end
    parts.append('</g><rect x="100" y="40" width="600" height="600" fill="none" stroke="#678658" stroke-width="1"/>')

    def point(x: int, z: int) -> tuple[float, float]:
        return (
            left + ((x - grid["origin"]["x"]) / grid["sample_step"] + 0.5) * cell,
            top + ((z - grid["origin"]["z"]) / grid["sample_step"] + 0.5) * cell,
        )

    for coordinate in (-512, -256, 0, 256, 512):
        x, z = point(coordinate, coordinate)
        parts.append(f'<path d="M{x:.2f} 40v600M100 {z:.2f}h600" stroke="#ffffff" stroke-opacity=".22" stroke-width="1"/>')
        parts.append(f'<text x="{x:.2f}" y="665" class="axis" text-anchor="middle">{coordinate}</text>')
        parts.append(f'<text x="85" y="{z + 4:.2f}" class="axis" text-anchor="end">{coordinate}</text>')
    ox, oz = point(0, 0)
    vx, vz = point(32, 0)
    parts.extend([
        '<path d="M741 75V43m-7 9 7-9 7 9" stroke="#49653c" stroke-width="2" fill="none"/>',
        '<text x="741" y="94" text-anchor="middle" class="axis">N</text>',
        f'<path d="M{ox-7:.2f} {oz:.2f}h14M{ox:.2f} {oz-7:.2f}v14" stroke="white" stroke-width="4"/>',
        f'<path d="M{ox-7:.2f} {oz:.2f}h14M{ox:.2f} {oz-7:.2f}v14" stroke="#183e30" stroke-width="2"/>',
        f'<circle cx="{vx:.2f}" cy="{vz:.2f}" r="8" fill="#173e30" stroke="white" stroke-width="3"/>',
        f'<path d="M{vx:.2f} {vz - 10:.2f}v-34h24" fill="none" stroke="white" stroke-width="2"/>',
        f'<rect x="{vx + 24:.2f}" y="{vz - 67:.2f}" width="180" height="47" rx="6" fill="#fdfdf3" stroke="#d9e1cf"/>',
        f'<text x="{vx + 36:.2f}" y="{vz - 48:.2f}" font-size="13" font-weight="650">Village start · 32 blocks</text>',
        f'<text x="{vx + 36:.2f}" y="{vz - 32:.2f}" font-size="11" fill="#738268">X 32 · Z 0 · Officially checked</text>',
        f'<text x="{ox - 14:.2f}" y="{oz + 24:.2f}" font-size="12" text-anchor="end" stroke="#f9f9ed" stroke-width="4" paint-order="stroke">Origin 0, 0</text>',
        '<text x="738" y="665" class="axis">X →</text>',
        '<text x="65" y="30" class="axis">Z ↓</text>',
    ])
    for index, name in enumerate(grid["palette"]):
        x, y = 100 + (index % 3) * 210, 700 + (index // 3) * 24
        if y > 810:
            raise ValueError("Map legend exceeds layout")
        parts.append(f'<rect x="{x}" y="{y - 10}" width="11" height="11" rx="2" fill="{biome_color(name)}"/>')
        parts.append(f'<text x="{x + 18}" y="{y}" class="legend">{escape(name.replace("_", " ").capitalize())}</text>')
    return "\n".join(parts + ["</svg>\n"])


def terrain_svg(terrain: dict) -> str:
    grid = terrain["grid"]
    if (grid["width"], grid["height"], grid["sample_step"]) != (5, 5, 16):
        raise ValueError("The landing preview expects the recorded 5 by 5 fixture")
    heights = [[sample["surface_y"] - 1 for sample in row] for row in grid["rows"]]
    low = min(map(min, heights))
    high = max(map(max, heights))

    def project(x: float, y: float, z: float) -> tuple[float, float]:
        return 320 + (x - z) * math.sqrt(0.5) * 4.3, 188 + ((x + z) / math.sqrt(6) - (y - low) * math.sqrt(2 / 3)) * 4.3

    def vertex(column: int, row: int) -> tuple[float, float]:
        return project(column * 16, heights[row][column], row * 16)

    def points(vertices: list[tuple[float, float]]) -> str:
        return " ".join(f"{x:.2f},{y:.2f}" for x, y in vertices)

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 440" width="640" height="440" role="img" aria-labelledby="title desc">',
        '<title id="title">Observed Minecraft surface mesh</title>',
        '<desc id="desc">25 official server samples, 32 interpolated triangles, no vertical exaggeration. Surface block heights range from 63 to 101.</desc>',
        '<style>text{font-family:ui-sans-serif,system-ui,sans-serif;fill:#5f7550}</style>',
    ]
    for n in range(5):
        a, b = project(0, low, n * 16), project(64, low, n * 16)
        c, d = project(n * 16, low, 0), project(n * 16, low, 64)
        parts.append(f'<path d="M{a[0]:.2f} {a[1]:.2f}L{b[0]:.2f} {b[1]:.2f}M{c[0]:.2f} {c[1]:.2f}L{d[0]:.2f} {d[1]:.2f}" stroke="#bdcda7" stroke-width="1" fill="none"/>')
    for diagonal in range(7):
        for row in range(4):
            column = diagonal - row
            if not 0 <= column < 4:
                continue
            triangles = [((column, row), (column, row + 1), (column + 1, row)), ((column + 1, row), (column, row + 1), (column + 1, row + 1))]
            for triangle in triangles:
                height = sum(heights[r][c] for c, r in triangle) / 3
                lightness = 39 + (height - low) / (high - low) * 26
                parts.append(f'<polygon points="{points([vertex(c, r) for c, r in triangle])}" fill="hsl(88 29% {lightness:.2f}%)" stroke="#d7e7bb" stroke-width="1.2" stroke-linejoin="round"/>')
    for row in range(5):
        for column in range(5):
            x, y = vertex(column, row)
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.5" fill="#f6faec" stroke="#6f8a54" stroke-width=".7"><title>X {grid["origin"]["x"] + column * 16}, Z {grid["origin"]["z"] + row * 16}, surface block Y {heights[row][column]}</title></circle>')
    parts.extend([
        '<text x="35" y="47" font-size="10" letter-spacing="1.5">OFFICIAL TERRAIN SAMPLES</text>',
        f'<text x="35" y="69" font-size="12">Surface block Y {low} to {high}</text>',
        '<text x="35" y="410" font-size="11">25 observed columns · 16 block spacing</text>',
        '<text x="605" y="410" font-size="10" text-anchor="end">No vertical exaggeration</text>',
    ])
    return "\n".join(parts + ["</svg>\n"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, help="Refresh the biome inspection with this native executable")
    args = parser.parse_args()
    source = ASSETS / "verified-inspection.json"
    if args.engine:
        result = subprocess.run([str(args.engine.resolve()), "inspect", "--config", "-"], input=json.dumps(INSPECTION), text=True, capture_output=True, check=True, timeout=30)
        inspection = json.loads(result.stdout)
        if inspection.get("seed") != INSPECTION["seed"] or "biome_map" not in inspection:
            raise ValueError("Native inspection did not return the expected seed and map")
        source.write_text(json.dumps(inspection, indent=2) + "\n")
    inspection = json.loads(source.read_text())
    terrain = json.loads((ASSETS / "terrain-samples.json").read_text())
    (ASSETS / "verified-biome-map.svg").write_text(biome_map_svg(inspection))
    (ASSETS / "terrain-preview.svg").write_text(terrain_svg(terrain))
    print(f"Rendered actual {inspection['biome_map']['width']} by {inspection['biome_map']['height']} biome samples and 25 saved official terrain samples.")


if __name__ == "__main__":
    main()
