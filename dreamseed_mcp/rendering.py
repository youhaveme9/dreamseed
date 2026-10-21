from __future__ import annotations

import hashlib
from html import escape
from typing import Any


BIOME_COLORS = {
    "badlands": "#d97745",
    "cherry_grove": "#f2a7c4",
    "desert": "#e8cf72",
    "forest": "#4f8a4c",
    "frozen_peaks": "#dcecf3",
    "grove": "#91ad91",
    "jagged_peaks": "#a7adb1",
    "jungle": "#2f7d32",
    "mangrove_swamp": "#506b3a",
    "meadow": "#78bd69",
    "mushroom_fields": "#9f618f",
    "ocean": "#3f77b5",
    "plains": "#8fbd57",
    "river": "#5f9ed1",
    "savanna": "#b8ad5c",
    "snowy_plains": "#e6eeee",
    "snowy_slopes": "#cad9db",
    "stony_peaks": "#a49c83",
    "swamp": "#607548",
    "taiga": "#507b64",
    "windswept_hills": "#6f9566",
}


def biome_color(name: str) -> str:
    if name in BIOME_COLORS:
        return BIOME_COLORS[name]
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return f"#{80 + digest[0] % 120:02x}{80 + digest[1] % 120:02x}{80 + digest[2] % 120:02x}"


def marker_color(status: str) -> str:
    if status in {"generated_chunks_confirmed", "template_blocks_confirmed"}:
        return "#087f8c"
    if status == "minecraft_located":
        return "#18a558"
    return "#64748b" if status == "client_supplied" else "#f59e0b"


def render_seed_map(
    inspection: dict[str, Any], markers: list[dict[str, Any]], title: str | None = None
) -> dict[str, Any]:
    biome_map = inspection.get("biome_map")
    if biome_map is None:
        raise ValueError("inspection does not contain a biome map")
    grid_width = int(biome_map["width"])
    grid_height = int(biome_map["height"])
    cell = max(7, min(18, 640 // max(grid_width, grid_height)))
    left = 42
    top = 58
    map_width = grid_width * cell
    map_height = grid_height * cell
    legend_width = 250
    svg_width = left + map_width + legend_width
    svg_height = max(top + map_height + 44, 90 + 22 * (len(biome_map["palette"]) + len(markers)))
    heading = title or f"DreamSeed {inspection['seed']}"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_width}" height="{svg_height}" viewBox="0 0 {svg_width} {svg_height}">',
        '<rect width="100%" height="100%" fill="#f7f4ed"/>',
        '<style>text{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;fill:#182026}.label{font-size:12px}.small{font-size:10px}</style>',
        f'<text x="{left}" y="30" font-size="18" font-weight="700">{escape(heading)}</text>',
        f'<text x="{left}" y="47" class="small">North is up. X increases right. Z increases down.</text>',
    ]
    palette = biome_map["palette"]
    for row_index, row in enumerate(biome_map["rows"]):
        run_start = 0
        while run_start < len(row):
            palette_index = row[run_start]
            run_end = run_start + 1
            while run_end < len(row) and row[run_end] == palette_index:
                run_end += 1
            parts.append(
                f'<rect x="{left + run_start * cell}" y="{top + row_index * cell}" '
                f'width="{(run_end - run_start) * cell}" height="{cell}" '
                f'fill="{biome_color(palette[palette_index])}"/>'
            )
            run_start = run_end
    parts.append(
        f'<rect x="{left}" y="{top}" width="{map_width}" height="{map_height}" fill="none" stroke="#182026"/>'
    )
    origin = biome_map["origin"]
    step = biome_map["sample_step"]
    center = inspection["area"]["center"]
    center_x = left + (center["x"] - origin["x"]) / step * cell + cell / 2
    center_y = top + (center["z"] - origin["z"]) / step * cell + cell / 2
    parts.extend([
        f'<line x1="{center_x - 6}" y1="{center_y}" x2="{center_x + 6}" y2="{center_y}" stroke="#111" stroke-width="2"/>',
        f'<line x1="{center_x}" y1="{center_y - 6}" x2="{center_x}" y2="{center_y + 6}" stroke="#111" stroke-width="2"/>',
    ])
    all_markers = [
        {
            "kind": "structure",
            "name": item["name"],
            "coordinates": item["coordinates"],
            "validation_status": item["placement_status"],
        }
        for item in inspection["structures"]
    ] + markers
    visible_markers: list[dict[str, Any]] = []
    for marker in all_markers:
        coordinate = marker["coordinates"]
        column = (coordinate["x"] - origin["x"]) / step
        row = (coordinate["z"] - origin["z"]) / step
        if column < -0.5 or column > grid_width - 0.5 or row < -0.5 or row > grid_height - 0.5:
            continue
        x = left + column * cell + cell / 2
        y = top + row * cell + cell / 2
        status = marker["validation_status"]
        fill = marker_color(status)
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="{fill}" stroke="#fff" stroke-width="2">'
            f'<title>{escape(marker["name"])} at {coordinate["x"]}, {coordinate["z"]}: {escape(marker["validation_status"])}</title></circle>'
        )
        visible_markers.append(marker)
    legend_x = left + map_width + 22
    parts.append(f'<text x="{legend_x}" y="{top}" font-size="14" font-weight="700">Biomes</text>')
    legend_y = top + 20
    for name in palette:
        parts.append(f'<rect x="{legend_x}" y="{legend_y - 11}" width="12" height="12" fill="{biome_color(name)}"/>')
        parts.append(f'<text x="{legend_x + 18}" y="{legend_y}" class="label">{escape(name)}</text>')
        legend_y += 20
    if visible_markers:
        legend_y += 6
        parts.append(f'<text x="{legend_x}" y="{legend_y}" font-size="14" font-weight="700">Markers</text>')
        legend_y += 20
        for marker in visible_markers:
            coordinate = marker["coordinates"]
            status = marker["validation_status"]
            fill = marker_color(status)
            label = f"{marker['name']}  {coordinate['x']}, {coordinate['z']}"
            parts.append(f'<circle cx="{legend_x + 6}" cy="{legend_y - 4}" r="5" fill="{fill}"/>')
            parts.append(f'<text x="{legend_x + 18}" y="{legend_y}" class="label">{escape(label)}</text>')
            legend_y += 20
    parts.append(
        f'<text x="{left}" y="{top + map_height + 24}" class="small">Sample step {step} blocks at Y {biome_map["y"]}. Cross marks the requested center.</text>'
    )
    parts.append("</svg>")
    return {
        "seed": inspection["seed"],
        "minecraft_version": inspection["minecraft_version"],
        "format": "svg",
        "width": svg_width,
        "height": svg_height,
        "palette": palette,
        "marker_count": len(visible_markers),
        "svg": "".join(parts),
        "semantics": "Sampled Cubiomes biome map with status coded markers",
        "caveats": [
            "This is a sampled biome map, not a block terrain render.",
            "Orange markers are Cubiomes predictions. Gray markers are client supplied. Green markers are official locate results. Teal markers have confirmed generated structure start data.",
            "The map center is the explicit area center, not actual world spawn.",
        ],
    }
