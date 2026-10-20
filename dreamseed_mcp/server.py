from __future__ import annotations

import atexit
import logging
import sys
from typing import Any

from mcp.server import MCPServer
from pydantic import ValidationError

from .job_manager import JobError, JobManager
from .schemas import (
    CancelResponse,
    CapabilitiesResponse,
    CompareRequest,
    ComparisonResponse,
    ErrorResponse,
    InspectRequest,
    InspectionResponse,
    ResultsResponse,
    SearchRequest,
    StartResponse,
    StatusResponse,
)


logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
server = MCPServer(
    "DreamSeed",
    instructions="Search real Minecraft Java 1.21.1 seeds with a local Cubiomes engine. Seeds are decimal strings. Coordinates are origin relative unless explicitly supplied.",
)
manager = JobManager()
atexit.register(manager.shutdown)


def error_response(error: Exception) -> dict[str, Any]:
    if isinstance(error, JobError):
        return error.response()
    if isinstance(error, ValidationError):
        return {"ok": False, "error": {"code": "validation_error", "message": "request validation failed", "details": error.errors(include_url=False)}}
    logging.exception("tool failed")
    return {"ok": False, "error": {"code": "internal_error", "message": str(error)}}


@server.tool()
def get_search_capabilities() -> CapabilitiesResponse:
    """Return supported versions, filters, operations, limits, and caveats."""
    try:
        return CapabilitiesResponse(ok=True, capabilities=manager.capabilities())
    except Exception as error:
        return CapabilitiesResponse.model_validate(error_response(error))


@server.tool()
def start_seed_search(request: SearchRequest) -> StartResponse:
    """Validate a bounded request and start a local seed search job."""
    try:
        return StartResponse.model_validate(manager.start(request.model_dump(by_alias=True, exclude_none=True)))
    except Exception as error:
        return StartResponse.model_validate(error_response(error))


@server.tool()
def get_search_status(job_id: str) -> StatusResponse:
    """Return state, exact counters, elapsed time, strategy, and coverage."""
    try:
        return StatusResponse.model_validate(manager.status(job_id))
    except Exception as error:
        return StatusResponse.model_validate(error_response(error))


@server.tool()
def get_search_results(job_id: str) -> ResultsResponse:
    """Return verified results currently available for a search job."""
    try:
        return ResultsResponse.model_validate(manager.results(job_id))
    except Exception as error:
        return ResultsResponse.model_validate(error_response(error))


@server.tool()
def cancel_seed_search(job_id: str) -> CancelResponse:
    """Cancel a running search process and report its final state."""
    try:
        return CancelResponse.model_validate(manager.cancel(job_id))
    except Exception as error:
        return CancelResponse.model_validate(error_response(error))


@server.tool()
def inspect_seed(request: InspectRequest) -> InspectionResponse:
    """Inspect Cubiomes biome samples and supported structures in an area."""
    try:
        return InspectionResponse(ok=True, inspection=manager.inspect(request.model_dump(exclude_none=True)))
    except Exception as error:
        return InspectionResponse.model_validate(error_response(error))


@server.tool()
def compare_seeds(request: CompareRequest) -> ComparisonResponse:
    """Evaluate known seeds with one criteria set and rank matching seeds."""
    try:
        return ComparisonResponse(ok=True, comparison=manager.compare(request.model_dump(by_alias=True, exclude_none=True)))
    except Exception as error:
        return ComparisonResponse.model_validate(error_response(error))


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
