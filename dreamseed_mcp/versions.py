from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Literal


@dataclass(frozen=True)
class MinecraftVersion:
    name: str
    enabled: bool
    cubiomes_enum: str
    data_version: int | None
    java_major: int
    server_sha1: str
    server_size: int
    server_url: str


_catalog = json.loads(files("dreamseed_mcp").joinpath("minecraft_versions.json").read_text(encoding="utf-8"))
VERSIONS = {item["name"]: MinecraftVersion(**item) for item in _catalog["versions"]}
DEFAULT_VERSION = _catalog["default"]
SUPPORTED_VERSIONS = tuple(name for name, spec in VERSIONS.items() if spec.enabled)
MinecraftVersionName = Literal[SUPPORTED_VERSIONS]


def get_version(name: str = DEFAULT_VERSION, *, require_enabled: bool = True) -> MinecraftVersion:
    spec = VERSIONS.get(name)
    if spec is None or (require_enabled and not spec.enabled):
        raise ValueError(f"unsupported Minecraft Java version: {name}")
    return spec
