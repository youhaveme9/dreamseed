from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


log = logging.getLogger("dreamseed.jobs")


class JobError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def response(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": str(self), "details": self.details}}


@dataclass
class SearchJob:
    job_id: str
    request: dict[str, Any]
    state: str = "queued"
    candidates_evaluated: int = 0
    matches_found: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    finished_at: float | None = None
    process: subprocess.Popen[str] | None = None
    error: dict[str, Any] | None = None
    stderr: str = ""
    summary: dict[str, Any] | None = None
    cancel_requested: bool = False
    thread: threading.Thread | None = None


class JobManager:
    def __init__(self, binary: str | None = None, max_concurrent: int = 2, max_jobs: int = 100):
        project = Path(__file__).resolve().parents[1]
        selected = binary or os.environ.get("DREAMSEED_BINARY") or str(project / "build" / "dreamseed")
        self.binary = Path(selected).resolve()
        self.max_concurrent = max_concurrent
        self.max_jobs = max_jobs
        self.jobs: dict[str, SearchJob] = {}
        self.lock = threading.RLock()

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
        return json.loads(completed.stdout)

    def inspect(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._run_once("inspect", request, 30)

    def compare(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._run_once("compare", request, 300)

    def start(self, request: dict[str, Any]) -> dict[str, Any]:
        validated = self._run_once("validate", request, 10)["normalized_request"]
        with self.lock:
            active = sum(job.state in {"queued", "running", "cancelling"} for job in self.jobs.values())
            if active >= self.max_concurrent:
                raise JobError("job_limit", f"at most {self.max_concurrent} searches may run concurrently")
            self._prune()
            if len(self.jobs) >= self.max_jobs:
                raise JobError("job_storage_limit", "too many retained jobs")
            job_id = uuid.uuid4().hex
            job = SearchJob(job_id=job_id, request=validated)
            self.jobs[job_id] = job
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
                job.started_at = time.monotonic()
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
                job.finished_at = time.monotonic()
                job.process = None
        except JobError as exc:
            if process is not None:
                self._stop_process(process)
            if stderr_thread is not None:
                stderr_thread.join(timeout=1)
            with self.lock:
                job.state = "failed"
                job.error = exc.response()["error"]
                job.finished_at = time.monotonic()
                job.process = None
        except Exception as exc:
            if process is not None:
                self._stop_process(process)
            if stderr_thread is not None:
                stderr_thread.join(timeout=1)
            log.exception("search job failed")
            with self.lock:
                job.state = "failed"
                job.error = {"code": "internal_error", "message": str(exc)}
                job.finished_at = time.monotonic()
                job.process = None

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
            now = job.finished_at or time.monotonic()
            elapsed = 0 if job.started_at is None else now - job.started_at
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
            }
            if job.error is not None:
                response["error"] = job.error
            if job.summary is not None:
                response["coverage"] = job.summary["coverage"]
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
                "search_complete": job.state in {"completed", "timed_out", "cancelled", "failed"},
            }
            if job.summary is not None:
                response["coverage"] = job.summary["coverage"]
                response["limitations"] = job.summary["limitations"]
            elif job.state in {"queued", "running", "cancelling"}:
                response["limitations"] = ["The search is still running, so rankings and available results can change."]
            if job.error is not None:
                response["error"] = job.error
            return response

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self._job(job_id)
        with self.lock:
            if job.state not in {"queued", "running", "cancelling"}:
                return {"ok": True, "job_id": job.job_id, "state": job.state, "already_finished": True}
            job.cancel_requested = True
            job.state = "cancelling"
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
                job.finished_at = time.monotonic()
            return {"ok": True, "job_id": job.job_id, "state": job.state, "already_finished": False}

    def shutdown(self) -> None:
        with self.lock:
            job_ids = [
                job.job_id for job in self.jobs.values()
                if job.state in {"queued", "running", "cancelling"}
            ]
        for job_id in job_ids:
            self.cancel(job_id)
