from __future__ import annotations

import math
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

from .minecraft_setup import configured_java, configured_server_jar, installation_status


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
STRUCTURE_QUERIES = {
    "village": "#minecraft:village",
    "pillager_outpost": "minecraft:pillager_outpost",
}


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


class ServerConsole:
    def __init__(self, process: subprocess.Popen[str]):
        self.process = process
        self.lines: queue.Queue[str] = queue.Queue()
        self.recent: deque[str] = deque(maxlen=200)
        self.reader = threading.Thread(target=self._read, daemon=True, name="dreamseed_minecraft_log")
        self.reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for raw_line in self.process.stdout:
            line = clean_log_line(raw_line)
            self.recent.append(line)
            self.lines.put(line)

    def wait_ready(self, deadline: float) -> None:
        while time.monotonic() < deadline:
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
        if self.process.poll() is not None or self.process.stdin is None:
            raise VerifierError("minecraft_server_failed", "Minecraft server stopped during verification")
        token = f"DREAMSEED_DONE_{uuid.uuid4().hex}"
        self.process.stdin.write(command + "\n")
        self.process.stdin.write(f"say {token}\n")
        self.process.stdin.flush()
        output: list[str] = []
        while time.monotonic() < deadline:
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
        status = installation_status(verify_hash=True)
        return {
            "available": status["available"],
            "source": "official_minecraft_java_server",
            "minecraft_version": "1.21.1",
            "structure_targets": sorted(STRUCTURE_QUERIES),
            "biome_targets": ["all_search_biomes"],
            "statuses": ["minecraft_located", "partially_located", "not_located"],
            "surface_probe": True,
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
            console.command(f"execute in minecraft:overworld run forceload add {x} {z}", deadline)
            loaded_token = f"DREAMSEED_LOADED_{uuid.uuid4().hex}"
            load_deadline = min(deadline, time.monotonic() + 20)
            while True:
                lines = console.command(
                    f"execute in minecraft:overworld if loaded {x} 0 {z} run say {loaded_token}",
                    load_deadline,
                )
                if any(loaded_token in line for line in lines):
                    break
                if time.monotonic() >= load_deadline:
                    raise VerifierError("surface_chunk_timeout", "Minecraft did not finish loading the target chunk")
                time.sleep(min(0.05, max(0, load_deadline - time.monotonic())))
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
            water_token = f"DREAMSEED_WATER_{uuid.uuid4().hex}"
            lava_token = f"DREAMSEED_LAVA_{uuid.uuid4().hex}"
            safe_token = f"DREAMSEED_SAFE_{uuid.uuid4().hex}"
            water_lines = console.command(
                "execute in minecraft:overworld "
                f"if block {surface_x} {safe_y - 1} {surface_z} minecraft:water run say {water_token}",
                deadline,
            )
            lava_lines = console.command(
                "execute in minecraft:overworld "
                f"if block {surface_x} {safe_y - 1} {surface_z} minecraft:lava run say {lava_token}",
                deadline,
            )
            is_water = any(water_token in line for line in water_lines)
            is_lava = any(lava_token in line for line in lava_lines)
            safe_lines = console.command(
                "execute in minecraft:overworld "
                f"if loaded {surface_x} {safe_y} {surface_z} "
                f"if block {surface_x} {safe_y} {surface_z} minecraft:air "
                f"if block {surface_x} {safe_y + 1} {surface_z} minecraft:air "
                f"unless block {surface_x} {safe_y - 1} {surface_z} minecraft:air "
                f"unless block {surface_x} {safe_y - 1} {surface_z} minecraft:water "
                f"unless block {surface_x} {safe_y - 1} {surface_z} minecraft:lava "
                f"unless block {surface_x} {safe_y - 1} {surface_z} minecraft:powder_snow "
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
                "detail": "Minecraft heightmap surface with explicit loaded chunk, clear feet and head space, and support excluding water, lava, air, and powder snow",
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

    def verify(self, request: dict[str, Any]) -> dict[str, Any]:
        if not self.lock.acquire(blocking=False):
            raise VerifierError("verifier_busy", "another Minecraft verification is already running")
        started = time.monotonic()
        try:
            if self.closed:
                raise VerifierError("verifier_closed", "Minecraft verifier has shut down")
            status = installation_status(verify_hash=True)
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
                            str(configured_server_jar()),
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
                try:
                    console.wait_ready(deadline)
                    reference = request["reference_point"]
                    for name in request["structures"]:
                        feature, failure = self._locate(
                            console, "structure", name, STRUCTURE_QUERIES[name], reference, deadline
                        )
                        if feature is not None:
                            locations.append(feature)
                        if failure is not None:
                            failures.append(failure)
                    for name in request["biomes"]:
                        feature, failure = self._locate(
                            console, "biome", name, f"minecraft:{name}", reference, deadline
                        )
                        if feature is not None:
                            locations.append(feature)
                        if failure is not None:
                            failures.append(failure)
                    if request["probe_surfaces"]:
                        for feature in locations:
                            coordinate = feature["coordinates"]
                            feature["surface"] = self._probe_surface(
                                console, coordinate["x"], coordinate["z"], deadline
                            )
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
            if locations and not failures:
                verification_status = "minecraft_located"
            elif locations:
                verification_status = "partially_located"
            else:
                verification_status = "not_located"
            return {
                "seed": request["seed"],
                "minecraft_version": "1.21.1",
                "edition": "Java",
                "source": "official_minecraft_java_server",
                "status": verification_status,
                "reference_point": request["reference_point"],
                "locations": locations,
                "failures": failures,
                "elapsed_seconds": time.monotonic() - started,
                "caveats": [
                    "Minecraft locate confirms the nearest target reported by the official server, not a building entrance.",
                    "Surface probes generate and load target chunks. A safe teleport rejects water and lava but cannot guarantee protection from every terrain hazard.",
                    "Distances are horizontal distances from the explicit reference point, not from actual world spawn.",
                ],
            }
        finally:
            self.lock.release()
