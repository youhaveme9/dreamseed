from __future__ import annotations

import math
import json
import os
import queue
import re
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from .minecraft_chunks import MAX_CHUNK_BYTES, inspect_structure_start
from .minecraft_registry import MAX_CANDIDATE_BIOME_TARGETS, MAX_CANDIDATE_STRUCTURE_TARGETS, STRUCTURE_QUERIES
from .minecraft_setup import configured_java, configured_server_jar, installation_status
from .versions import DEFAULT_VERSION, SUPPORTED_VERSIONS, get_version
from .terrain_data import MAX_TERRAIN_CHUNKS, MAX_TERRAIN_POINTS, collect_terrain, terrain_grid
from .structure_blocks import MAX_TEMPLATE_BLOCKS, MAX_TEMPLATE_CHUNKS, igloo_plan, verify_igloo_blocks
from .minecraft_chunks import ChunkDataError


ANSI_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
LOCATE_PATTERN = re.compile(
    r"The nearest (?P<located>.+?) is at \[\s*(?P<x>-?\d+)\s*,\s*(?P<y>~|-?\d+)\s*,\s*(?P<z>-?\d+)\s*\]"
    r"(?:\s*\((?P<distance>[\d.]+) blocks? away\))?",
    re.IGNORECASE,
)
POSITION_PATTERN = re.compile(
    r"\[\s*(?P<x>-?\d+(?:\.\d+)?)[dDfF]?\s*,\s*"
    r"(?P<y>-?\d+(?:\.\d+)?)[dDfF]?\s*,\s*"
    r"(?P<z>-?\d+(?:\.\d+)?)[dDfF]?\s*\]"
)
class VerifierError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def response(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": str(self), "details": self.details}}


def clean_log_line(line: str) -> str:
    return re.sub(r"§.", "", ANSI_PATTERN.sub("", line)).strip()


def parse_locate_output(lines: list[str]) -> dict[str, Any] | None:
    for line in reversed(lines):
        match = LOCATE_PATTERN.search(clean_log_line(line))
        if not match:
            continue
        raw_y = match.group("y")
        distance = match.group("distance")
        return {
            "located_id": match.group("located").strip(),
            "x": int(match.group("x")),
            "y": None if raw_y == "~" else int(raw_y),
            "z": int(match.group("z")),
            "reported_distance": float(distance) if distance is not None else None,
        }
    return None


def parse_entity_position(lines: list[str]) -> tuple[int, int, int] | None:
    for line in reversed(lines):
        if "following entity data" not in line.lower():
            continue
        match = POSITION_PATTERN.search(clean_log_line(line))
        if match:
            return (
                math.floor(float(match.group("x"))),
                math.floor(float(match.group("y"))),
                math.floor(float(match.group("z"))),
            )
    return None


def reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def fluid_predicate(fluid: str) -> str:
    if fluid not in {"water", "lava"}:
        raise ValueError("unsupported fluid predicate")
    return json.dumps({"condition": "minecraft:location_check", "predicate": {"fluid": {"fluids": f"#minecraft:{fluid}"}}}, separators=(",", ":"))


class ServerConsole:
    def __init__(self, process: subprocess.Popen[str]):
        self.process = process
        self.lines: queue.Queue[str] = queue.Queue(maxsize=4096)
        self.overflowed = False
        self.recent: deque[str] = deque(maxlen=200)
        self.reader = threading.Thread(target=self._read, daemon=True, name="dreamseed_minecraft_log")
        self.reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for raw_line in self.process.stdout:
            line = clean_log_line(raw_line)
            self.recent.append(line)
            try:
                self.lines.put_nowait(line)
            except queue.Full:
                self.overflowed = True

    def wait_ready(self, deadline: float) -> None:
        while time.monotonic() < deadline:
            if self.overflowed:
                raise VerifierError("minecraft_log_limit", "Minecraft console exceeded the buffered log limit")
            if self.process.poll() is not None:
                raise VerifierError(
                    "minecraft_server_failed",
                    "Minecraft server exited before becoming ready",
                    {"log_tail": list(self.recent)[-30:]},
                )
            try:
                line = self.lines.get(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if "Done (" in line:
                return
            if "FAILED TO BIND TO PORT" in line or "You need to agree to the EULA" in line:
                raise VerifierError("minecraft_server_failed", line, {"log_tail": list(self.recent)[-30:]})
        raise VerifierError("verification_timeout", "Minecraft server startup exceeded the request time limit")

    def command(self, command: str, deadline: float) -> list[str]:
        if self.overflowed:
            raise VerifierError("minecraft_log_limit", "Minecraft console exceeded the buffered log limit")
        if self.process.poll() is not None or self.process.stdin is None:
            raise VerifierError("minecraft_server_failed", "Minecraft server stopped during verification")
        token = f"DREAMSEED_DONE_{uuid.uuid4().hex}"
        self.process.stdin.write(command + "\n")
        self.process.stdin.write(f"say {token}\n")
        self.process.stdin.flush()
        output: list[str] = []
        while time.monotonic() < deadline:
            if self.overflowed:
                raise VerifierError("minecraft_log_limit", "Minecraft console exceeded the buffered log limit")
            if self.process.poll() is not None:
                raise VerifierError(
                    "minecraft_server_failed",
                    "Minecraft server stopped during verification",
                    {"log_tail": list(self.recent)[-30:]},
                )
            try:
                line = self.lines.get(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if token in line:
                return output
            output.append(line)
        raise VerifierError("verification_timeout", "Minecraft command exceeded the request time limit")


class MinecraftVerifier:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.process_lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self.closed = False

    def shutdown(self) -> None:
        with self.process_lock:
            self.closed = True
            process = self.process
        if process is not None:
            self._stop(process, grace_seconds=0)

    def capabilities(self) -> dict[str, Any]:
        statuses = {version: installation_status(verify_hash=True, minecraft_version=version) for version in SUPPORTED_VERSIONS}
        status = statuses[DEFAULT_VERSION]
        return {
            "available": any(item["available"] for item in statuses.values()),
            "source": "official_minecraft_java_server",
            "minecraft_version": DEFAULT_VERSION,
            "minecraft_versions": list(SUPPORTED_VERSIONS),
            "version_availability": {version: {"available": item["available"], "detail": item["detail"]} for version, item in statuses.items()},
            "structure_targets": sorted(STRUCTURE_QUERIES),
            "biome_targets": ["all_search_biomes"],
            "statuses": ["minecraft_located", "generated_chunks_confirmed", "template_blocks_confirmed", "partially_verified", "partially_located", "not_located"],
            "surface_probe": True,
            "structure_start_inspection": {
                "supported": True,
                "enabled_by_default": True,
                "requires_full_start_chunk": True,
                "requires_serialized_pieces": True,
                "max_decompressed_chunk_bytes": MAX_CHUNK_BYTES,
                "all_structure_blocks_checked": False,
            },
            "candidate_verification": {
                "supported": True, "tool": "verify_seed_candidate",
                "max_structure_targets": MAX_CANDIDATE_STRUCTURE_TARGETS,
                "max_biome_targets": MAX_CANDIDATE_BIOME_TARGETS,
                "structure_counts": True, "spatial_relations": True, "exact_biome_checks": True,
                "scope": "selected_candidate_witnesses",
            },
            "structure_block_validation": {
                "supported_structures": ["igloo"], "scope": "all_non_marker_igloo_template_blocks",
                "max_blocks": MAX_TEMPLATE_BLOCKS, "max_chunks": MAX_TEMPLATE_CHUNKS,
                "block_entities_checked": False, "all_structure_types_supported": False,
            },
            "max_concurrent_per_server": 1,
            "min_seconds": 30,
            "max_seconds": 300,
            "java_memory_mb": 1024,
            "setup_command": "dreamseed-minecraft-setup --download --accept-mojang-eula",
            "detail": status["detail"],
        }

    @staticmethod
    def _properties(seed: str, port: int) -> str:
        values = {
            "allow-nether": "false",
            "difficulty": "peaceful",
            "enable-command-block": "false",
            "enable-query": "false",
            "enable-rcon": "false",
            "enable-status": "false",
            "enforce-whitelist": "true",
            "gamemode": "spectator",
            "generate-structures": "true",
            "level-name": "world",
            "level-seed": seed,
            "level-type": "minecraft:normal",
            "max-players": "1",
            "max-tick-time": "120000",
            "motd": "DreamSeed verifier",
            "online-mode": "false",
            "pause-when-empty-seconds": "-1",
            "server-ip": "127.0.0.1",
            "server-port": str(port),
            "simulation-distance": "3",
            "spawn-protection": "0",
            "sync-chunk-writes": "true",
            "view-distance": "2",
            "white-list": "true",
        }
        return "".join(f"{key}={value}\n" for key, value in values.items())

    @staticmethod
    def _stop(process: subprocess.Popen[str], grace_seconds: float = 10) -> None:
        if process.poll() is not None:
            return
        if grace_seconds > 0:
            try:
                if process.stdin is not None:
                    process.stdin.write("stop\n")
                    process.stdin.flush()
                process.wait(timeout=grace_seconds)
                return
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    @staticmethod
    def _not_found(lines: list[str]) -> bool:
        lowered = "\n".join(lines).lower()
        return "could not find" in lowered or "couldn't find" in lowered or "found no elements" in lowered

    def _locate(
        self,
        console: ServerConsole,
        kind: str,
        name: str,
        query: str,
        reference: dict[str, int],
        deadline: float,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        command = (
            "execute in minecraft:overworld positioned "
            f"{reference['x']} {reference['y']} {reference['z']} run locate {kind} {query}"
        )
        lines = console.command(command, deadline)
        located = parse_locate_output(lines)
        if located is None:
            message = "Minecraft did not find the requested target" if self._not_found(lines) else "Minecraft locate output was not understood"
            code = "not_found" if self._not_found(lines) else "unrecognized_locate_output"
            return None, {"kind": kind, "name": name, "code": code, "message": message}
        feature = {
            "kind": kind,
            "name": name,
            "located_id": located["located_id"],
            "coordinates": {"x": located["x"], "z": located["z"]},
            "horizontal_distance": math.hypot(located["x"] - reference["x"], located["z"] - reference["z"]),
            "reported_distance": located["reported_distance"],
            "verification_status": "minecraft_located",
        }
        if located["y"] is not None:
            feature["coordinates"]["y"] = located["y"]
        return feature, None

    def _probe_surface(
        self, console: ServerConsole, x: int, z: int, deadline: float
    ) -> dict[str, Any]:
        tag = f"dreamseed_probe_{uuid.uuid4().hex}"
        try:
            self._load_chunk(console, x, z, deadline)
            summon = (
                "execute in minecraft:overworld positioned "
                f"{x} 0 {z} positioned over motion_blocking_no_leaves run "
                f"summon minecraft:marker ~ ~ ~ {{Tags:[\"{tag}\"]}}"
            )
            console.command(summon, deadline)
            entity_deadline = min(deadline, time.monotonic() + 5)
            while True:
                position_lines = console.command(
                    "execute in minecraft:overworld run "
                    f"data get entity @e[type=minecraft:marker,tag={tag},limit=1] Pos", entity_deadline
                )
                position = parse_entity_position(position_lines)
                if position is not None:
                    break
                if time.monotonic() >= entity_deadline:
                    raise VerifierError("surface_entity_timeout", "Minecraft did not return a readable surface position")
                time.sleep(min(0.05, max(0, entity_deadline - time.monotonic())))
            surface_x, safe_y, surface_z = position
            safe_token = f"DREAMSEED_SAFE_{uuid.uuid4().hex}"
            is_water = self._fluid_present(console, surface_x, safe_y - 1, surface_z, "water", deadline)
            is_lava = self._fluid_present(console, surface_x, safe_y - 1, surface_z, "lava", deadline)
            if is_water is None or is_lava is None:
                raise VerifierError("fluid_check_unconfirmed", "Minecraft did not confirm both fluid presence and absence controls")
            safe_lines = console.command(
                f"execute in minecraft:overworld positioned {surface_x} {safe_y - 1} {surface_z} "
                f"if loaded {surface_x} {safe_y} {surface_z} "
                f"if block {surface_x} {safe_y} {surface_z} minecraft:air "
                f"if block {surface_x} {safe_y + 1} {surface_z} minecraft:air "
                f"unless block {surface_x} {safe_y - 1} {surface_z} minecraft:air "
                f"unless block {surface_x} {safe_y - 1} {surface_z} minecraft:water "
                f"unless block {surface_x} {safe_y - 1} {surface_z} minecraft:lava "
                f"unless block {surface_x} {safe_y - 1} {surface_z} minecraft:powder_snow "
                f"unless predicate {fluid_predicate('water')} "
                f"unless predicate {fluid_predicate('lava')} "
                f"run say {safe_token}",
                deadline,
            )
            safe_teleport = any(safe_token in line for line in safe_lines) and not is_water and not is_lava
            return {
                "status": "surface_probed",
                "coordinates": {"x": surface_x, "y": safe_y, "z": surface_z},
                "is_water": is_water,
                "is_lava": is_lava,
                "safe_teleport": safe_teleport,
                "detail": "Minecraft heightmap surface with explicit fluid state controls, loaded chunk, clear feet and head space, and support excluding water, lava, air, and powder snow",
            }
        except VerifierError as error:
            return {
                "status": "surface_probe_failed",
                "safe_teleport": False,
                "detail": str(error),
            }
        finally:
            try:
                console.command(f"execute in minecraft:overworld run kill @e[type=minecraft:marker,tag={tag}]", deadline)
                console.command(f"execute in minecraft:overworld run forceload remove {x} {z}", deadline)
            except VerifierError:
                pass

    @staticmethod
    def _fluid_present(console: ServerConsole, x: int, y: int, z: int, fluid: str, deadline: float) -> bool | None:
        predicate = fluid_predicate(fluid)
        observations = []
        for condition in ("if", "unless"):
            token = f"DREAMSEED_FLUID_{uuid.uuid4().hex}"
            lines = console.command(
                f"execute in minecraft:overworld positioned {x} {y} {z} {condition} predicate {predicate} run say {token}", deadline
            )
            observations.append(any(token in line for line in lines))
        return observations[0] if observations[0] != observations[1] else None

    @staticmethod
    def _load_chunk(console: ServerConsole, x: int, z: int, deadline: float) -> None:
        console.command(f"execute in minecraft:overworld run forceload add {x} {z}", deadline)
        token = f"DREAMSEED_LOADED_{uuid.uuid4().hex}"
        load_deadline = min(deadline, time.monotonic() + 20)
        while time.monotonic() < load_deadline:
            lines = console.command(
                f"execute in minecraft:overworld if loaded {x} 0 {z} run say {token}", load_deadline
            )
            if any(token in line for line in lines):
                return
            time.sleep(min(0.05, max(0, load_deadline - time.monotonic())))
        raise VerifierError("chunk_load_timeout", "Minecraft did not finish loading the target chunk")

    @staticmethod
    def _confirm_starts(
        world: Path, locations: list[dict[str, Any]], failures: list[dict[str, Any]],
        clean_save: bool, deadline: float, minecraft_version: str = DEFAULT_VERSION,
    ) -> None:
        for feature in locations:
            if feature["kind"] != "structure":
                continue
            coordinate = feature["coordinates"]
            if clean_save and time.monotonic() < deadline:
                evidence = inspect_structure_start(world, feature["name"], coordinate["x"], coordinate["z"], minecraft_version)
            else:
                evidence = {
                    "status": "unconfirmed", "piece_count": 0,
                    "chunk": {"x": coordinate["x"] // 16, "z": coordinate["z"] // 16},
                    "code": "verification_timeout" if clean_save else "chunk_save_unconfirmed",
                    "detail": "Chunk confirmation requires a flushed world, clean server shutdown, and remaining request time.",
                }
            feature["structure_start"] = evidence
            if evidence["status"] == "confirmed":
                feature["verification_status"] = "generated_chunks_confirmed"
                if "target_id" in feature:
                    feature["coordinates"] = {"x": evidence["chunk"]["x"] * 16, "z": evidence["chunk"]["z"] * 16}
            else:
                failures.append({
                    "kind": "structure", "name": feature["name"], "stage": "structure_start",
                    "code": evidence["code"], "message": evidence["detail"],
                    **({"target_id": feature["target_id"]} if "target_id" in feature else {}),
                })

    def _check_biome(self, console: ServerConsole, feature: dict[str, Any], deadline: float) -> bool | None:
        coordinate = feature["coordinates"]
        x, y, z = coordinate["x"], coordinate["y"], coordinate["z"]
        try:
            self._load_chunk(console, x, z, deadline)
            observations = []
            for condition in ("if", "unless"):
                token = f"DREAMSEED_BIOME_{uuid.uuid4().hex}"
                lines = console.command(
                    f"execute in minecraft:overworld {condition} biome {x} {y} {z} minecraft:{feature['name']} run say {token}",
                    deadline,
                )
                observations.append(any(token in line for line in lines))
            return observations[0] if observations[0] != observations[1] else None
        finally:
            try:
                console.command(f"execute in minecraft:overworld run forceload remove {x} {z}", deadline)
            except VerifierError:
                pass

    def verify(
        self, request: dict[str, Any], *, targets: list[dict[str, Any]] | None = None,
        terrain_area: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.lock.acquire(blocking=False):
            raise VerifierError("verifier_busy", "another Minecraft verification is already running")
        started = time.monotonic()
        try:
            if self.closed:
                raise VerifierError("verifier_closed", "Minecraft verifier has shut down")
            confirm_blocks = request.get("confirm_template_blocks", False)
            if confirm_blocks and (request["structures"] != ["igloo"] or not request.get("confirm_structure_starts", True)):
                raise VerifierError("unsupported_block_validation", "template block validation currently supports only igloo with start confirmation enabled")
            minecraft_version = request["minecraft_version"]
            get_version(minecraft_version)
            status = installation_status(verify_hash=True, minecraft_version=minecraft_version)
            if not status["available"]:
                raise VerifierError(
                    "minecraft_verifier_unavailable",
                    status["detail"],
                    {
                        "setup_command": "dreamseed-minecraft-setup --download --accept-mojang-eula",
                        "jar": status["jar"],
                    },
                )
            deadline = started + request["max_seconds"]
            locations: list[dict[str, Any]] = []
            failures: list[dict[str, Any]] = []
            terrain = None
            terrain_controls = []
            confirm_starts = request.get("confirm_structure_starts", True) and bool(request["structures"])
            needs_save = confirm_starts or terrain_area is not None
            if terrain_area is not None:
                _, width, grouped = terrain_grid(terrain_area)
                if width * width > MAX_TERRAIN_POINTS or len(grouped) > MAX_TERRAIN_CHUNKS:
                    raise VerifierError("terrain_resource_limit", "terrain request exceeds the sample or chunk limit")
            with tempfile.TemporaryDirectory(prefix="dreamseed-minecraft-") as temporary:
                workdir = Path(temporary)
                (workdir / "eula.txt").write_text("eula=true\n", encoding="utf-8")
                (workdir / "server.properties").write_text(
                    self._properties(request["seed"], reserve_local_port()), encoding="utf-8"
                )
                with self.process_lock:
                    if self.closed:
                        raise VerifierError("verifier_closed", "Minecraft verifier has shut down")
                    process = subprocess.Popen(
                        [
                            configured_java(),
                            "-Xms512M",
                            "-Xmx1024M",
                            "-Dlog4j2.formatMsgNoLookups=true",
                            "-jar",
                            str(configured_server_jar(minecraft_version)),
                            "nogui",
                        ],
                        cwd=workdir,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                    )
                    self.process = process
                console = ServerConsole(process)
                flushed = False
                try:
                    console.wait_ready(deadline)
                    if terrain_area is not None:
                        console.command("gamerule randomTickSpeed 0", deadline)
                        origin, width, grouped = terrain_grid(terrain_area)
                        for chunk_x, chunk_z in sorted(grouped):
                            self._load_chunk(console, chunk_x * 16, chunk_z * 16, deadline)
                            console.command(f"execute in minecraft:overworld run forceload remove {chunk_x * 16} {chunk_z * 16}", deadline)
                        for offset in sorted({0, width // 2, width - 1}):
                            x = origin["x"] + offset * terrain_area["sample_step"]
                            z = origin["z"] + offset * terrain_area["sample_step"]
                            terrain_controls.append(self._probe_surface(console, x, z, deadline))
                    reference = request["reference_point"]
                    for name in request["structures"] if targets is None else []:
                        feature, failure = self._locate(
                            console, "structure", name, STRUCTURE_QUERIES[name], reference, deadline
                        )
                        if feature is not None:
                            locations.append(feature)
                        if failure is not None:
                            failures.append(failure)
                    for name in request["biomes"] if targets is None else []:
                        feature, failure = self._locate(
                            console, "biome", name, f"minecraft:{name}", reference, deadline
                        )
                        if feature is not None:
                            locations.append(feature)
                        if failure is not None:
                            failures.append(failure)
                    if targets is not None:
                        for target in targets:
                            feature = {
                                **target, "coordinates": dict(target["coordinates"]),
                                "requested_coordinates": dict(target["coordinates"]), "verification_status": "unconfirmed",
                            }
                            if feature["kind"] == "biome":
                                matches = self._check_biome(console, feature, deadline)
                                feature["biome_matches"] = matches
                                feature["verification_status"] = (
                                    "minecraft_biome_checked" if matches is True else "biome_mismatch" if matches is False else "unconfirmed"
                                )
                                if matches is not True:
                                    failures.append({
                                        "kind": "biome", "name": feature["name"], "target_id": feature["target_id"],
                                        "stage": "biome_check", "code": "biome_mismatch" if matches is False else "biome_check_unconfirmed",
                                        "message": "The official biome at the selected coordinate did not confirm the requested biome.",
                                    })
                            locations.append(feature)
                    if confirm_starts:
                        for feature in locations:
                            if feature["kind"] == "structure":
                                coordinate = feature["coordinates"]
                                self._load_chunk(console, coordinate["x"], coordinate["z"], deadline)
                    if request["probe_surfaces"]:
                        for feature in locations:
                            coordinate = feature["coordinates"]
                            feature["surface"] = self._probe_surface(
                                console, coordinate["x"], coordinate["z"], deadline
                            )
                    if needs_save:
                        lines = console.command("save-all flush", deadline)
                        flushed = any("Saved the game" in line for line in lines)
                    if confirm_blocks and flushed:
                        for feature in locations:
                            if feature["kind"] != "structure":
                                continue
                            try:
                                coordinate = feature["coordinates"]
                                plan = igloo_plan(workdir / "world", coordinate["x"], coordinate["z"], minecraft_version, deadline)
                                for chunk_x, chunk_z in sorted(plan["chunks"]):
                                    self._load_chunk(console, chunk_x * 16, chunk_z * 16, deadline)
                                    console.command(f"execute in minecraft:overworld run forceload remove {chunk_x * 16} {chunk_z * 16}", deadline)
                            except ChunkDataError as error:
                                failures.append({"kind": "structure", "name": feature["name"], "stage": "template_blocks", "code": error.code, "message": str(error)})
                        lines = console.command("save-all flush", deadline)
                        flushed = any("Saved the game" in line for line in lines)
                finally:
                    try:
                        self._stop(process, min(10, max(0, deadline - time.monotonic())))
                    finally:
                        with self.process_lock:
                            self.process = None
                        console.reader.join(timeout=5)
                        if process.stdin is not None:
                            process.stdin.close()
                        if process.stdout is not None:
                            process.stdout.close()
                if confirm_starts:
                    self._confirm_starts(
                        workdir / "world", locations, failures, flushed and process.returncode == 0, deadline, minecraft_version
                    )
                if confirm_blocks and flushed and process.returncode == 0:
                    for feature in locations:
                        if feature["kind"] != "structure":
                            continue
                        coordinate = feature["coordinates"]
                        evidence = verify_igloo_blocks(workdir / "world", coordinate["x"], coordinate["z"], minecraft_version, deadline)
                        feature["block_verification"] = evidence
                        if evidence["status"] == "confirmed":
                            feature["verification_status"] = "template_blocks_confirmed"
                        else:
                            failures.append({"kind": "structure", "name": feature["name"], "stage": "template_blocks",
                                             "code": evidence.get("code", "template_blocks_mismatched"), "message": evidence["detail"]})
                if terrain_area is not None:
                    if not flushed or process.returncode != 0:
                        raise VerifierError("chunk_save_unconfirmed", "terrain reading requires a flushed world and clean server shutdown")
                    terrain = collect_terrain(workdir / "world", minecraft_version, terrain_area, deadline)
            locate_failures = any(failure.get("stage", "locate") == "locate" for failure in failures)
            if locations and locate_failures:
                verification_status = "partially_located"
            elif locations and failures:
                verification_status = "partially_verified"
            elif locations and confirm_blocks:
                verification_status = "template_blocks_confirmed"
            elif locations and confirm_starts:
                verification_status = "generated_chunks_confirmed"
            elif locations:
                verification_status = "minecraft_located"
            else:
                verification_status = "not_located"
            response = {
                "seed": request["seed"],
                "minecraft_version": minecraft_version,
                "edition": "Java",
                "source": "official_minecraft_java_server",
                "status": verification_status,
                "reference_point": request["reference_point"],
                "locations": locations,
                "failures": failures,
                "elapsed_seconds": time.monotonic() - started,
                "caveats": [
                    "Minecraft locate confirms the nearest target reported by the official server, not a building entrance.",
                    "Default structure confirmation checks start metadata only. Explicit igloo template validation checks non marker template block states, not entity contents or all other structures. Biomes retain locate validation only.",
                    "Surface probes generate and load target chunks. A safe teleport rejects water and lava but cannot guarantee protection from every terrain hazard.",
                    "Distances are horizontal distances from the explicit reference point, not from actual world spawn.",
                ],
            }
            if terrain is not None:
                response["terrain"] = terrain
                response["terrain_controls"] = terrain_controls
            return response
        finally:
            self.lock.release()
