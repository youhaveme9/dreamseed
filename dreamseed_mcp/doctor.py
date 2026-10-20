from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from . import __version__
from .job_manager import default_binary, default_state_dir
from .minecraft_setup import installation_status


EXPECTED_ENGINE_VERSION = __version__
EXPECTED_CUBIOMES_COMMIT = "e61f90580cbdd883214a8054670dacae655e59c0"
EXPECTED_PACKAGES = {"mcp": "2.2.0", "pydantic": "2.12.5"}


def result(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def run_checks(binary: Path, state_dir: Path) -> dict[str, Any]:
    checks = [result("python", sys.version_info >= (3, 11), sys.version.split()[0])]
    for package, expected in EXPECTED_PACKAGES.items():
        try:
            installed = version(package)
            checks.append(result(package, installed == expected, f"{installed}, expected {expected}"))
        except PackageNotFoundError:
            checks.append(result(package, False, "not installed"))

    executable = binary.is_file() and os.access(binary, os.X_OK)
    checks.append(result("native_engine", executable, str(binary)))
    if executable:
        try:
            completed = subprocess.run(
                [str(binary), "capabilities"], text=True, capture_output=True,
                timeout=5, check=False,
            )
            capabilities = json.loads(completed.stdout)
            valid = (
                completed.returncode == 0
                and capabilities.get("engine") == "DreamSeed"
                and capabilities.get("engine_version") == EXPECTED_ENGINE_VERSION
                and capabilities.get("minecraft_versions") == ["1.21.1"]
                and capabilities.get("cubiomes_commit") == EXPECTED_CUBIOMES_COMMIT
            )
            detail = (
                f"engine {capabilities.get('engine_version')}, "
                f"Cubiomes {capabilities.get('cubiomes_commit')}"
            )
            checks.append(result("engine_capabilities", valid, detail))
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            checks.append(result("engine_capabilities", False, str(error)))

    try:
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        probe = state_dir / f".doctor.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        probe.unlink()
        checks.append(result("job_storage", True, str(state_dir)))
    except OSError as error:
        checks.append(result("job_storage", False, str(error)))

    minecraft = installation_status(verify_hash=True)
    minecraft_ok = minecraft["available"] if minecraft["exists"] else True
    minecraft_detail = minecraft["detail"]
    if not minecraft["exists"]:
        minecraft_detail += "; optional verifier is not installed"
    checks.append(result("minecraft_verifier", minecraft_ok, minecraft_detail))

    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a DreamSeed local installation")
    parser.add_argument(
        "--binary",
        default=str(default_binary()),
    )
    parser.add_argument(
        "--state-dir",
        default=os.environ.get("DREAMSEED_STATE_DIR", str(default_state_dir())),
    )
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    report = run_checks(Path(arguments.binary).expanduser().resolve(), Path(arguments.state_dir).expanduser().resolve())
    if arguments.json:
        print(json.dumps(report, indent=2))
    else:
        for check in report["checks"]:
            mark = "PASS" if check["ok"] else "FAIL"
            print(f"{mark}  {check['name']}: {check['detail']}")
        print("DreamSeed is ready" if report["ok"] else "DreamSeed needs attention")
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
