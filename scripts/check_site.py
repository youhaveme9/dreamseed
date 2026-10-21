#!/usr/bin/env python3
"""Check the static site without browser or build dependencies."""

from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


class SiteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.references: list[str] = []
        self.targets: list[str] = []
        self.images = 0
        self.headings = 0

    def handle_starttag(self, tag: str, attributes: list) -> None:
        attrs = dict(attributes)
        if "id" in attrs:
            assert attrs["id"] not in self.ids, f"Duplicate ID: {attrs['id']}"
            self.ids.add(attrs["id"])
        for key in ("src", "href"):
            if attrs.get(key):
                self.references.append(attrs[key])
        for key in ("aria-controls", "aria-labelledby", "data-copy"):
            self.targets.extend(attrs.get(key, "").split())
        if tag == "img":
            assert "alt" in attrs, "Image is missing alt text"
            assert "width" in attrs and "height" in attrs, "Image dimensions are missing"
            self.images += 1
        if tag == "h1":
            self.headings += 1


def main() -> None:
    parser = SiteParser()
    parser.feed((SITE / "index.html").read_text())
    assert parser.headings == 1, "Expected a single primary heading"
    for target in parser.targets:
        assert target in parser.ids, f"Missing interaction target: {target}"
    local_count = 0
    for reference in parser.references:
        url = urlsplit(reference)
        if url.scheme or url.netloc:
            assert url.scheme == "https", f"Unexpected external URL: {reference}"
            continue
        if url.path:
            assert not url.path.startswith("/"), f"Path breaks project Pages hosting: {reference}"
            path = (SITE / unquote(url.path)).resolve()
            assert path.is_relative_to(SITE), f"Reference escapes static directory: {reference}"
            assert path.is_file(), f"Missing asset: {reference}"
        elif url.fragment:
            assert unquote(url.fragment) in parser.ids, f"Missing anchor: {reference}"
        local_count += 1
    for svg in (SITE / "assets").glob("*.svg"):
        ET.fromstring(svg.read_text())
    css = (SITE / "style.css").read_text()
    assert "prefers-reduced-motion" in css
    assert not re.search(r"https?://|@import", css), "Unexpected external style dependency"
    inspection = json.loads((SITE / "assets/verified-inspection.json").read_text())
    assert inspection["seed"] == "-3989987067671208281"
    assert inspection["minecraft_version"] == "1.21.3"
    grid = inspection["biome_map"]
    assert grid["encoding"] == "palette_indices"
    assert (grid["width"], grid["height"], grid["y"], grid["sample_step"]) == (65, 65, 64, 16)
    assert grid["palette"][grid["rows"][32][32]] == "plains"
    assert any(s["name"] == "village" and s["coordinates"] == {"x": 32, "z": 0} and s["distance_from_center"] == 32 for s in inspection["structures"])
    assert len(grid["rows"]) == grid["height"]
    for row in grid["rows"]:
        assert len(row) == grid["width"]
        assert all(isinstance(index, int) and 0 <= index < len(grid["palette"]) for index in row)
    terrain = json.loads((SITE / "assets/terrain-samples.json").read_text())
    assert terrain["source"] == "official_minecraft_java_server"
    assert terrain["seed"] == "-7333811035076652275"
    assert terrain["control_heights_match"] is True
    assert terrain["preview"]["mesh"]["vertex_count"] == 25
    assert terrain["preview"]["mesh"]["triangle_count"] == 32
    total_size = sum(path.stat().st_size for path in SITE.rglob("*") if path.is_file())
    assert total_size < 2_000_000, "Static site exceeds the 2 MB asset budget"
    print(f"Site checks passed: {local_count} local references, {parser.images} images, valid evidence data, {total_size:,} bytes total.")


if __name__ == "__main__":
    main()
