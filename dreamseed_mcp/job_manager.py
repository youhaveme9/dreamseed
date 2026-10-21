from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .candidate_verification import CandidatePlanError, build_candidate_targets, recheck_candidate
from .minecraft_verifier import MinecraftVerifier
from .rendering import render_seed_map


log = logging.getLogger("dreamseed.jobs")
JOB_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
ACTIVE_STATES = {"queued", "running", "cancelling"}
FINISHED_STATES = {"completed", "timed_out", "cancelled", "failed", "interrupted"}


def default_binary() -> Path:
    configured = os.environ.get("DREAMSEED_BINARY")
    if configured:
        return Path(configured).expanduser().resolve()
    source_binary = Path(__file__).resolve().parents[1] / "build" / "dreamseed"
    if source_binary.is_file():
        return source_binary
    installed = shutil.which("dreamseed")
    return Path(installed).resolve() if installed else source_binary


def default_state_dir() -> Path:
    configured = os.environ.get("DREAMSEED_STATE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        return (Path(xdg_state).expanduser() / "dreamseed" / "jobs").resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "DreamSeed" / "jobs").resolve()
    return (Path.home() / ".local" / "state" / "dreamseed" / "jobs").resolve()


class JobError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def response(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": str(self), "details": self.details}}


def interface_state_dir(interface: str) -> Path:
    if interface not in {"web", "http"}:
        raise ValueError("interface must be web or http")
    configured = os.environ.get("DREAMSEED_STATE_DIR")
    return Path(configured).expanduser().resolve() if configured else default_state_dir().parent / f"{interface}-jobs"


@dataclass
class SearchJob:
    job_id: str
    request: dict[str, Any]
    state: str = "queued"
    candidates_evaluated: int = 0
    matches_found: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    process: subprocess.Popen[str] | None = None
    error: dict[str, Any] | None = None
    stderr: str = ""
    summary: dict[str, Any] | None = None
    cancel_requested: bool = False
    thread: threading.Thread | None = None
    recovered: bool = False
    last_persisted_at: float = 0


class JobManager:
    def __init__(self, binary: str | None = None, max_concurrent: int = 2, max_jobs: int = 100,
                 state_dir: str | Path | None = None):
        self.binary = Path(binary).expanduser().resolve() if binary else default_binary()
        self.max_concurrent = max_concurrent
        self.max_jobs = max_jobs
        self.jobs: dict[str, SearchJob] = {}
        self.lock = threading.RLock()
        self.closed = False
        self.state_dir = Path(state_dir).resolve() if state_dir is not None else default_state_dir()
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.verifier = MinecraftVerifier()
        self._load_jobs()

    def _job_file(self, job_id: str) -> Path:
        return self.state_dir / f"{job_id}.json"

    @staticmethod
    def _job_record(job: SearchJob) -> dict[str, Any]:
        return {
            "format_version": 1,
            "job_id": job.job_id,
            "request": job.request,
            "state": job.state,
            "candidates_evaluated": job.candidates_evaluated,
            "matches_found": job.matches_found,
            "results": job.results,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "error": job.error,
            "stderr": job.stderr,
            "summary": job.summary,
            "cancel_requested": job.cancel_requested,
        }

    def _persist_locked(self, job: SearchJob, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - job.last_persisted_at < 1:
            return
        target = self._job_file(job.job_id)
        temporary = self.state_dir / f".{job.job_id}.{uuid.uuid4().hex}.tmp"
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(self._job_record(job), stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            job.last_persisted_at = now
        except (OSError, TypeError, ValueError):
            log.exception("could not persist search job %s", job.job_id)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _load_jobs(self) -> None:
        loaded: list[SearchJob] = []
        for path in self.state_dir.glob("*.json"):
            try:
                if path.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError("job file exceeds 16 MiB")
                data = json.loads(path.read_text(encoding="utf-8"))
                job_id = data["job_id"]
                if data.get("format_version") != 1 or path.stem != job_id or not JOB_ID_PATTERN.fullmatch(job_id):
                    raise ValueError("invalid persisted job identity")
                if not isinstance(data["request"], dict) or not isinstance(data["results"], list):
                    raise ValueError("invalid persisted job data")
                budget = data["request"].get("budget")
                if not isinstance(budget, dict) or budget.get("strategy") not in {"sampled", "sequential", "structure48"}:
                    raise ValueError("invalid persisted request")
                if not isinstance(budget.get("max_candidates"), int) or budget["max_candidates"] < 1:
                    raise ValueError("invalid persisted candidate budget")
                if len(data["results"]) > 100:
                    raise ValueError("too many persisted results")
                created_at = float(data["created_at"])
                started_at = None if data.get("started_at") is None else float(data["started_at"])
                finished_at = None if data.get("finished_at") is None else float(data["finished_at"])
                if not all(math.isfinite(value) for value in (created_at, started_at, finished_at) if value is not None):
                    raise ValueError("invalid persisted timestamp")
                candidates = int(data.get("candidates_evaluated", 0))
                matches = int(data.get("matches_found", 0))
                if candidates < 0 or matches < 0:
                    raise ValueError("invalid persisted counters")
                job = SearchJob(
                    job_id=job_id,
                    request=data["request"],
                    state=data["state"],
                    candidates_evaluated=candidates,
                    matches_found=matches,
                    results=data["results"],
                    created_at=created_at,
                    started_at=started_at,
                    finished_at=finished_at,
                    error=data.get("error"),
                    stderr=str(data.get("stderr", ""))[-65_536:],
                    summary=data.get("summary"),
                    cancel_requested=bool(data.get("cancel_requested", False)),
                    recovered=True,
                )
                if job.state in ACTIVE_STATES:
                    job.state = "interrupted"
                    job.finished_at = time.time()
                    job.error = {
                        "code": "server_restarted",
                        "message": "the MCP server stopped before this search finished",
                    }
                elif job.state not in FINISHED_STATES:
                    raise ValueError("invalid persisted job state")
                loaded.append(job)
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                log.warning("ignored invalid persisted job file %s", path)
        loaded.sort(key=lambda item: item.created_at, reverse=True)
        for job in loaded[:self.max_jobs]:
            self.jobs[job.job_id] = job
            if job.state == "interrupted":
                self._persist_locked(job, force=True)
        for job in loaded[self.max_jobs:]:
            try:
                self._job_file(job.job_id).unlink(missing_ok=True)
            except OSError:
                log.warning("could not prune persisted job %s", job.job_id)

    def _ensure_binary(self) -> None:
        if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            raise JobError("engine_unavailable", f"native engine is not executable at {self.binary}")

    def _run_once(self, command: str, request: dict[str, Any], timeout: float = 10) -> dict[str, Any]:
        self._ensure_binary()
        completed = subprocess.run(
            [str(self.binary), command, "--config", "-"],
            input=json.dumps(request), text=True, capture_output=True, timeout=timeout, check=False,
        )
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise JobError("engine_protocol_error", "native engine returned invalid JSON", {"stderr": completed.stderr[-2000:]}) from exc
        if completed.returncode != 0 or "error" in response:
            error = response.get("error", {})
            raise JobError(error.get("code", "engine_error"), error.get("message", "native engine rejected the request"), error)
        return response

    def capabilities(self) -> dict[str, Any]:
        self._ensure_binary()
        completed = subprocess.run([str(self.binary), "capabilities"], text=True, capture_output=True, timeout=5, check=False)
        if completed.returncode != 0:
            raise JobError("engine_error", "could not read native engine capabilities", {"stderr": completed.stderr[-2000:]})
        capabilities = json.loads(completed.stdout)
        capabilities["job_storage"] = {
            "persistent": True,
            "format": "local_json",
            "retained_job_limit": self.max_jobs,
            "completed_job_recovery": True,
            "active_job_restart_behavior": "recovered_as_interrupted",
        }
        verifier_capabilities = self.verifier.capabilities()
        verifier_capabilities["biome_targets"] = capabilities["biome_filters"]["biomes"]
        capabilities["authoritative_verification"] = verifier_capabilities
        capabilities["unsupported"] = [
            "block level confirmation for structures other than supported igloo templates"
            if item == "block level structure confirmation" else item
            for item in capabilities["unsupported"]
        ]
        capabilities["terrain_analysis"] = {
            "supported": True, "available": verifier_capabilities["available"],
            "source": "official_minecraft_java_server", "tool": "analyze_seed_terrain",
            "max_samples": 4225, "max_chunks": 256, "max_radius": 256, "min_sample_step": 4,
            "heightmap": "MOTION_BLOCKING_NO_LEAVES",
            "classifications": ["valley_cross_section_candidate", "high_ground_component", "mountain_range_candidate",
                                "enclosed_water_candidate", "elongated_water_candidate"],
            "classification_semantics": "Explicit sampled terrain heuristics, not semantic proof of valleys, ranges, lakes, or rivers",
            "scoring_metrics": ["relief_blocks", "mean_slope", "water_fraction", "valley_fraction", "high_ground_fraction"],
            "previews": ["svg_heightmap", "obj_surface_mesh"],
        }
        capabilities["experimental"].extend([
            "official Minecraft Java server locate verification, generated structure starts, and surface probing",
            "static SVG rendering of sampled biome maps",
        ])
        return capabilities

    def inspect(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._run_once("inspect", request, 30)

    def compare(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._run_once("compare", request, 300)

    def analyze_terrain(self, request: dict[str, Any]) -> dict[str, Any]:
        from .schemas import TerrainAnalysisRequest
        from .terrain_analysis import analyze_grid
        from .terrain_rendering import render_terrain

        request = TerrainAnalysisRequest.model_validate(request).model_dump(exclude_none=True)
        center = request["area"]["center"]
        checked = self.verifier.verify({
            "minecraft_version": request["minecraft_version"], "seed": request["seed"],
            "reference_point": {**center, "y": 64}, "structures": [], "biomes": [],
            "confirm_structure_starts": False, "probe_surfaces": False, "max_seconds": request["max_seconds"],
        }, terrain_area=request["area"])
        grid = checked["terrain"]
        controls_match = []
        for probe in checked["terrain_controls"]:
            if probe["status"] != "surface_probed":
                continue
            coordinate = probe["coordinates"]
            row = (coordinate["z"] - grid["origin"]["z"]) // grid["sample_step"]
            column = (coordinate["x"] - grid["origin"]["x"]) // grid["sample_step"]
            cell = grid["rows"][row][column]
            if cell is not None:
                controls_match.append(cell["surface_y"] == coordinate["y"])
        if controls_match and not all(controls_match):
            raise JobError("terrain_control_mismatch", "saved heights disagree with independent Minecraft surface commands")
        return {
            "seed": request["seed"], "minecraft_version": request["minecraft_version"], "edition": "Java",
            "source": "official_minecraft_java_server", "grid": grid,
            "analysis": analyze_grid(grid, request["preferences"]),
            "control_probes": checked["terrain_controls"],
            "control_heights_match": True if controls_match and len(controls_match) == len(checked["terrain_controls"]) else None,
            "preview": render_terrain(grid, request["seed"], request["minecraft_version"], request["include_mesh"]) if request["include_preview"] else None,
            "elapsed_seconds": checked["elapsed_seconds"],
            "caveats": [
                "Heights and surface states come from full official server chunks at sampled columns. Gaps between samples are not scanned.",
                "Heightmap Y is the first free height above its surface, not a verified safe teleport coordinate or structure entrance.",
                "Terrain classifications are explicit heuristic candidates. Sampled enclosure cannot prove a lake has no outlet between samples.",
                "Preference scores measure numeric target similarity, not beauty or scenic quality. Partial grids receive no preference score.",
                "The mesh interpolates surface samples only, without caves, overhangs, structures, or complete voxel geometry.",
                "Observed surfaces can include buildings and vegetation; this is not an unmodified terrain height function.",
                "The area is relative to explicit world coordinates, not actual world spawn.",
            ],
        }

    def verify_candidate(self, request: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        deadline = started + request["max_seconds"]
        criteria = {key: request[key] for key in ("minecraft_version", "reference_point", "hard_constraints", "soft_preferences")}
        normalized = self._run_once("validate", {
            **criteria, "budget": {"strategy": "sequential", "start_seed": request["seed"], "max_candidates": 1,
                                   "max_seconds": request["max_seconds"], "workers": 1}, "max_results": 1,
        }, min(10, request["max_seconds"]))["normalized_request"]
        prediction = self._run_once("compare", {**criteria, "seeds": [request["seed"]]}, max(0.01, deadline - time.monotonic()))["results"][0]
        result = {
            "seed": request["seed"], "minecraft_version": request["minecraft_version"], "edition": "Java",
            "source": "cubiomes_prediction_only", "reference_point": normalized["reference_point"],
            "validation_scope": "selected_candidate_witnesses", "prediction_matched": prediction["meets_all_hard_constraints"],
            "features": [], "failures": [], "constraint_checks": [], "spatial_checks": [], "score_breakdown": [],
            "soft_preference_score": None, "all_hard_constraints_verified": False,
            "caveats": [
                "Verification covers selected candidate witnesses, not an exhaustive scan of the world or every matching feature.",
                "A failed witness does not prove that no other matching feature exists for this seed.",
                "Structure distances use confirmed start chunk block origins, not building entrances. Biomes are checked at the reported X, Y, and Z.",
                "All distances are horizontal Euclidean blocks from explicit anchors, not actual world spawn.",
                "Structure start confirmation does not inspect every structure block. Surface safety is separate from hard constraint verification.",
            ],
        }
        if not prediction["meets_all_hard_constraints"]:
            result.update({"status": "prediction_rejected", "elapsed_seconds": time.monotonic() - started})
            result["caveats"].append("The bounded Cubiomes checks rejected this candidate. Minecraft was not started and no authoritative verdict was made.")
            return result
        try:
            targets = build_candidate_targets(normalized, prediction)
        except CandidatePlanError as error:
            raise JobError("candidate_verification_limit", str(error)) from error
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise JobError("verification_timeout", "candidate preparation exhausted the request time limit")
        reference = normalized["reference_point"]
        official = self.verifier.verify({
            "seed": request["seed"], "minecraft_version": request["minecraft_version"],
            "reference_point": {**reference, "y": 64},
            "structures": sorted({target["name"] for target in targets if target["kind"] == "structure"}),
            "biomes": [], "confirm_structure_starts": True,
            "probe_surfaces": request["probe_surfaces"], "max_seconds": remaining,
        }, targets=targets)
        for feature in official["locations"]:
            coordinate = feature["coordinates"]
            feature["distance_from_reference"] = math.hypot(coordinate["x"] - reference["x"], coordinate["z"] - reference["z"])
        result.update(recheck_candidate(normalized, official["locations"]))
        result.update({"source": "official_minecraft_java_server", "features": official["locations"],
                       "failures": official["failures"], "elapsed_seconds": time.monotonic() - started})
        return result

    def verify_with_minecraft(self, request: dict[str, Any]) -> dict[str, Any]:
        verification = self.verifier.verify(request)
        if request.get("include_biome_map"):
            reference = request["reference_point"]
            area = request.get("map_area") or {
                "center": {"x": reference["x"], "z": reference["z"]},
                "radius": 512,
                "sample_step": 32,
                "y": reference["y"],
            }
            inspection = self.inspect({
                "minecraft_version": request["minecraft_version"],
                "seed": request["seed"],
                "area": area,
                "structures": request["structures"],
                "include_biome_map": True,
            })
            markers = [
                {
                    "kind": location["kind"],
                    "name": location["name"],
                    "coordinates": location["coordinates"],
                    "validation_status": location["verification_status"],
                }
                for location in verification["locations"]
            ]
            verification["rendering"] = render_seed_map(
                inspection, markers, f"Minecraft verified seed {request['seed']}"
            )
        return verification

    def render(self, request: dict[str, Any]) -> dict[str, Any]:
        inspection = self.inspect({
            "minecraft_version": request["minecraft_version"],
            "seed": request["seed"],
            "area": request["area"],
            "structures": request["structures"],
            "include_biome_map": True,
        })
        return render_seed_map(inspection, request.get("markers", []), request.get("title"))

    def start(self, request: dict[str, Any]) -> dict[str, Any]:
        validated = self._run_once("validate", request, 10)["normalized_request"]
        with self.lock:
            if self.closed:
                raise JobError("manager_closed", "job manager has shut down")
            active = sum(job.state in ACTIVE_STATES for job in self.jobs.values())
            if active >= self.max_concurrent:
                raise JobError("job_limit", f"at most {self.max_concurrent} searches may run concurrently")
            self._prune()
            if len(self.jobs) >= self.max_jobs:
                raise JobError("job_storage_limit", "too many retained jobs")
            job_id = uuid.uuid4().hex
            job = SearchJob(job_id=job_id, request=validated)
            self.jobs[job_id] = job
            self._persist_locked(job, force=True)
            thread = threading.Thread(target=self._worker, args=(job,), daemon=True, name=f"dreamseed_{job_id[:8]}")
            job.thread = thread
            thread.start()
        return {"ok": True, "job_id": job_id, "state": "queued", "search_strategy": validated["budget"]["strategy"]}

    def _prune(self) -> None:
        finished = [job for job in self.jobs.values() if job.finished_at is not None]
        finished.sort(key=lambda job: job.finished_at or 0)
        while len(self.jobs) >= self.max_jobs and finished:
            old = finished.pop(0)
            self.jobs.pop(old.job_id, None)
            try:
                self._job_file(old.job_id).unlink(missing_ok=True)
            except OSError:
                log.warning("could not prune persisted job %s", old.job_id)

    def _read_stderr(self, job: SearchJob, stream: Any) -> None:
        chunks: list[str] = []
        size = 0
        for line in stream:
            if size < 65_536:
                chunks.append(line)
                size += len(line)
        with self.lock:
            job.stderr = "".join(chunks)[-65_536:]
        if job.stderr:
            log.warning("native search %s wrote diagnostics: %s", job.job_id, job.stderr[-2000:])

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def _worker(self, job: SearchJob) -> None:
        process: subprocess.Popen[str] | None = None
        stderr_thread: threading.Thread | None = None
        try:
            with self.lock:
                job.state = "running"
                job.started_at = time.time()
                self._persist_locked(job, force=True)
            process = subprocess.Popen(
                [str(self.binary), "search", "--config", "-", "--events"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
            with self.lock:
                job.process = process
                cancel_now = job.cancel_requested
            assert process.stdin is not None
            if not cancel_now:
                process.stdin.write(json.dumps(job.request))
            process.stdin.close()
            if cancel_now:
                process.terminate()
            assert process.stderr is not None
            stderr_thread = threading.Thread(target=self._read_stderr, args=(job, process.stderr), daemon=True)
            stderr_thread.start()
            native_error: dict[str, Any] | None = None
            assert process.stdout is not None
            for line in process.stdout:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    raise JobError("engine_protocol_error", "native search emitted invalid event JSON")
                with self.lock:
                    if event.get("event") == "progress":
                        job.candidates_evaluated = event["candidates_evaluated"]
                        job.matches_found = event["matches_found"]
                    elif event.get("event") == "match":
                        job.matches_found = event["matches_found"]
                        job.results.append(event["result"])
                        job.results.sort(key=lambda item: (-item["soft_preference_score"], int(item["seed"])))
                        del job.results[job.request["max_results"]:]
                    elif event.get("event") == "complete":
                        job.summary = event["summary"]
                        job.candidates_evaluated = job.summary["candidates_evaluated"]
                        job.matches_found = job.summary["matching_seeds_found"]
                        job.results = job.summary["results"]
                        job.state = job.summary["state"]
                    elif isinstance(event.get("error"), dict):
                        native_error = event["error"]
                    self._persist_locked(job, force=event.get("event") == "complete")
            return_code = process.wait()
            stderr_thread.join(timeout=1)
            process.stdout.close()
            process.stderr.close()
            with self.lock:
                if job.summary is None:
                    if job.cancel_requested:
                        job.state = "cancelled"
                    else:
                        job.state = "failed"
                        details: dict[str, Any] = {"return_code": return_code}
                        if job.stderr:
                            details["stderr"] = job.stderr[-2000:]
                        if native_error is not None:
                            job.error = {
                                "code": native_error.get("code", "engine_error"),
                                "message": native_error.get("message", "native engine rejected the search"),
                                "path": native_error.get("path"),
                                "details": details,
                            }
                        else:
                            job.error = {
                                "code": "engine_exit",
                                "message": f"native search exited with code {return_code}",
                                "details": details,
                            }
                job.finished_at = time.time()
                job.process = None
                self._persist_locked(job, force=True)
        except JobError as exc:
            if process is not None:
                self._stop_process(process)
            if stderr_thread is not None:
                stderr_thread.join(timeout=1)
            with self.lock:
                job.state = "failed"
                job.error = exc.response()["error"]
                job.finished_at = time.time()
                job.process = None
                self._persist_locked(job, force=True)
        except Exception as exc:
            if process is not None:
                self._stop_process(process)
            if stderr_thread is not None:
                stderr_thread.join(timeout=1)
            log.exception("search job failed")
            with self.lock:
                job.state = "failed"
                job.error = {"code": "internal_error", "message": str(exc)}
                job.finished_at = time.time()
                job.process = None
                self._persist_locked(job, force=True)

    def _job(self, job_id: str) -> SearchJob:
        if not isinstance(job_id, str) or len(job_id) != 32:
            raise JobError("invalid_job_id", "job_id must be a 32 character identifier")
        with self.lock:
            job = self.jobs.get(job_id)
        if job is None:
            raise JobError("job_not_found", "no retained search job has this id")
        return job

    def status(self, job_id: str) -> dict[str, Any]:
        job = self._job(job_id)
        with self.lock:
            now = job.finished_at or time.time()
            elapsed = 0 if job.started_at is None else max(0, now - job.started_at)
            response = {
                "ok": True,
                "job_id": job.job_id,
                "state": job.state,
                "candidates_evaluated": job.candidates_evaluated,
                "matching_seeds_found": job.matches_found,
                "elapsed_seconds": elapsed,
                "search_strategy": job.request["budget"]["strategy"],
                "candidate_budget": job.request["budget"]["max_candidates"],
                "progress_note": "Candidate counts are exact. No global search completion percentage is available.",
                "persisted": True,
                "recovered": job.recovered,
            }
            if job.error is not None:
                response["error"] = job.error
            if job.summary is not None:
                response["coverage"] = job.summary["coverage"]
                if "placement_filter" in job.summary:
                    response["placement_filter"] = job.summary["placement_filter"]
            return response

    def results(self, job_id: str) -> dict[str, Any]:
        job = self._job(job_id)
        with self.lock:
            response = {
                "ok": True,
                "job_id": job.job_id,
                "state": job.state,
                "candidates_evaluated": job.candidates_evaluated,
                "matching_seeds_found": job.matches_found,
                "results": list(job.results),
                "results_available": len(job.results),
                "search_complete": job.state in FINISHED_STATES,
                "persisted": True,
                "recovered": job.recovered,
            }
            if job.summary is not None:
                response["coverage"] = job.summary["coverage"]
                response["limitations"] = job.summary["limitations"]
                if "placement_filter" in job.summary:
                    response["placement_filter"] = job.summary["placement_filter"]
            elif job.state in {"queued", "running", "cancelling"}:
                response["limitations"] = ["The search is still running, so rankings and available results can change."]
            elif job.state == "interrupted":
                response["limitations"] = [
                    "The MCP server stopped before this search finished. Retained results are partial."
                ]
            if job.error is not None:
                response["error"] = job.error
            return response

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self._job(job_id)
        with self.lock:
            if job.state not in ACTIVE_STATES:
                return {"ok": True, "job_id": job.job_id, "state": job.state, "already_finished": True}
            job.cancel_requested = True
            job.state = "cancelling"
            self._persist_locked(job, force=True)
            process = job.process
            thread = job.thread
        if process is not None and process.poll() is None:
            process.terminate()
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                with self.lock:
                    process = job.process
                if process is not None and process.poll() is None:
                    process.kill()
                thread.join(timeout=2)
        with self.lock:
            if job.state == "cancelling":
                job.state = "cancelled"
                job.finished_at = time.time()
            self._persist_locked(job, force=True)
            return {"ok": True, "job_id": job.job_id, "state": job.state, "already_finished": False}

    def shutdown(self) -> None:
        with self.lock:
            self.closed = True
        self.verifier.shutdown()
        with self.lock:
            job_ids = [
                job.job_id for job in self.jobs.values()
                if job.state in ACTIVE_STATES
            ]
        for job_id in job_ids:
            self.cancel(job_id)
        with self.lock:
            threads = [job.thread for job in self.jobs.values() if job.thread is not None]
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=5)
