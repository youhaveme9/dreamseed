from __future__ import annotations

import atexit
import base64
import json
import logging
import sys
from typing import Any

from mcp.server import MCPServer
from mcp_types import CallToolResult, ImageContent, TextContent
from pydantic import ValidationError

from .job_manager import JobError, JobManager
from .minecraft_verifier import VerifierError
from .schemas import (
    CancelResponse,
    CapabilitiesResponse,
    CompareRequest,
    ComparisonResponse,
    ErrorResponse,
    InspectRequest,
    InspectionResponse,
    MinecraftVerificationRequest,
    MinecraftVerificationResponse,
    RenderSeedMapRequest,
    RenderSeedMapResponse,
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
    if isinstance(error, (JobError, VerifierError)):
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
    """Return ranked Cubiomes predictions currently available for a search job."""
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


@server.tool()
def verify_seed_with_minecraft(request: MinecraftVerificationRequest) -> MinecraftVerificationResponse:
    """Use the official local Minecraft Java server to locate targets and probe surfaces."""
    try:
        verification = manager.verify_with_minecraft(request.model_dump(exclude_none=True))
        response = MinecraftVerificationResponse(ok=True, verification=verification)
        rendering = verification.get("rendering")
        if rendering is None:
            return response
        summary = {
            "ok": True,
            "seed": verification["seed"],
            "status": verification["status"],
            "locations": len(verification["locations"]),
            "failures": len(verification["failures"]),
            "caveats": verification["caveats"],
        }
        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(summary, separators=(",", ":"))),
                ImageContent(
                    type="image",
                    data=base64.b64encode(rendering["svg"].encode("utf-8")).decode("ascii"),
                    mimeType="image/svg+xml",
                ),
            ],
            structuredContent=response.model_dump(mode="json"),
        )
    except Exception as error:
        return MinecraftVerificationResponse.model_validate(error_response(error))


@server.tool()
def render_seed_map(request: RenderSeedMapRequest) -> RenderSeedMapResponse:
    """Render a bounded sampled biome map as static SVG with status coded markers."""
    try:
        rendering = manager.render(request.model_dump(exclude_none=True))
        response = RenderSeedMapResponse(ok=True, rendering=rendering)
        summary = {
            "ok": True,
            "seed": rendering["seed"],
            "format": rendering["format"],
            "width": rendering["width"],
            "height": rendering["height"],
            "marker_count": rendering["marker_count"],
            "caveats": rendering["caveats"],
        }
        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(summary, separators=(",", ":"))),
                ImageContent(
                    type="image",
                    data=base64.b64encode(rendering["svg"].encode("utf-8")).decode("ascii"),
                    mimeType="image/svg+xml",
                ),
            ],
            structuredContent=response.model_dump(mode="json"),
        )
    except Exception as error:
        return RenderSeedMapResponse.model_validate(error_response(error))


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
