from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from pydantic import ValidationError

from .job_manager import JobError, JobManager
from .minecraft_verifier import VerifierError
from .schemas import TerrainAnalysisRequest


def write_export(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect official Minecraft terrain without an MCP client")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    manager = None
    state = None
    try:
        request = TerrainAnalysisRequest.model_validate_json(args.config.read_text(encoding="utf-8"))
        if args.output_dir is not None:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            if any(args.output_dir.iterdir()):
                raise ValueError("output directory must be empty; existing files will not be overwritten")
        state = tempfile.TemporaryDirectory(prefix="dreamseed-terrain-state-")
        manager = JobManager(state_dir=state.name)
        terrain = manager.analyze_terrain(request.model_dump(exclude_none=True))
        if args.output_dir is not None:
            write_export(args.output_dir / "terrain.json", json.dumps(terrain, indent=2) + "\n")
            if terrain["preview"] is not None:
                write_export(args.output_dir / "heightmap.svg", terrain["preview"]["svg"])
                mesh = terrain["preview"]["mesh"]
                if mesh is not None:
                    write_export(args.output_dir / "surface.obj", mesh["obj"])
        print(json.dumps({"ok": True, "terrain": terrain}, separators=(",", ":")))
        return 0
    except (OSError, ValueError, ValidationError, VerifierError, JobError) as error:
        code = error.code if isinstance(error, (VerifierError, JobError)) else "terrain_error"
        print(json.dumps({"ok": False, "error": {"code": code, "message": str(error)}}))
        return 2
    finally:
        if manager is not None:
            manager.shutdown()
        if state is not None:
            state.cleanup()


if __name__ == "__main__":
    sys.exit(main())
