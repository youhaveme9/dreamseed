from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]


def run(arguments: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    subprocess.run(arguments, cwd=cwd, env=env, check=True)


def json_command(arguments: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None) -> dict:
    completed = subprocess.run(arguments, cwd=cwd, env=env, check=True, text=True, capture_output=True)
    return json.loads(completed.stdout)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_metadata(build_dir: Path) -> tuple[str, dict]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    version = project["version"]
    cmake = re.search(r"project\(DreamSeed VERSION ([0-9.]+)", (ROOT / "CMakeLists.txt").read_text())
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    module = ast.parse((ROOT / "dreamseed_mcp" / "__init__.py").read_text())
    python_version = next(
        ast.literal_eval(node.value) for node in module.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
    )
    capabilities = json_command([str(build_dir / "dreamseed"), "capabilities"])
    versions = {version, cmake.group(1) if cmake else None, plugin["version"], python_version, capabilities["engine_version"]}
    if len(versions) != 1:
        raise RuntimeError(f"release version mismatch: {versions}")
    catalog = json.loads((ROOT / "dreamseed_mcp/minecraft_versions.json").read_text())
    if capabilities["minecraft_versions"] != [item["name"] for item in catalog["versions"] if item["enabled"]]:
        raise RuntimeError("unexpected Minecraft version")
    if not (ROOT / "docs" / "releases" / f"{version}.md").is_file():
        raise RuntimeError("release notes are missing")
    if f"## {version}" not in (ROOT / "CHANGELOG.md").read_text():
        raise RuntimeError("changelog does not contain the release version")
    if os.environ.get("GITHUB_REF_TYPE") == "tag" and os.environ.get("GITHUB_REF_NAME") != f"v{version}":
        raise RuntimeError("Git tag does not match the package version")
    return version, capabilities


def inspect_tar(archive: Path, required: set[str]) -> str:
    with tarfile.open(archive) as source:
        members = source.getmembers()
        roots = {PurePosixPath(item.name).parts[0] for item in members}
        if len(roots) != 1:
            raise RuntimeError("release archive must contain a single root directory")
        prefix = next(iter(roots))
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise RuntimeError(f"unsafe release archive member: {member.name}")
            if any(part in {".git", ".venv", "__pycache__", "build", "build-sanitize", "dist", "jobs"} for part in path.parts):
                raise RuntimeError(f"private or generated directory in release: {member.name}")
            if path.suffix in {".jar", ".pyc", ".pyo", ".pem", ".key", ".p12"} or path.name.startswith(".env") or path.name in {"eula.txt", "mojang_eula_acceptance.json", ".DS_Store"}:
                raise RuntimeError(f"private or proprietary file in release: {member.name}")
            names.add(path.relative_to(prefix).as_posix())
        missing = required - names
        if missing:
            raise RuntimeError(f"source archive is incomplete: {sorted(missing)}")
    return prefix


def extract_archive(archive: Path, destination: Path, required: set[str]) -> Path:
    prefix = inspect_tar(archive, required)
    with tarfile.open(archive) as source:
        source.extractall(destination)
    return destination / prefix


def native_archive(output: Path, binary: Path, build_dir: Path, version: str, target: str, epoch: int) -> Path:
    archive = output / f"dreamseed-{version}-{target}.tar.gz"
    files = {
        "bin/dreamseed": binary,
        "INSTALL.md": ROOT / "docs" / "native_install.md",
        "LICENSE": ROOT / "LICENSE",
        "THIRD_PARTY_NOTICES.md": ROOT / "THIRD_PARTY_NOTICES.md",
        "licenses/Cubiomes-LICENSE": ROOT / "third_party" / "cubiomes" / "LICENSE",
        "licenses/nlohmann-json-LICENSE.MIT": build_dir / "_deps" / "nlohmann_json-src" / "LICENSE.MIT",
    }
    files.update({f"examples/{path.name}": path for path in (ROOT / "examples").glob("*.json")})
    with archive.open("wb") as raw, gzip.GzipFile(fileobj=raw, filename="", mode="wb", mtime=epoch) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as stream:
            for name, path in sorted(files.items()):
                content = path.read_bytes()
                member = tarfile.TarInfo(f"dreamseed-{version}/{name}")
                member.size = len(content)
                member.mode = 0o755 if name == "bin/dreamseed" else 0o644
                member.mtime = epoch
                stream.addfile(member, io.BytesIO(content))
    return archive


def check_wheel(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for name in names:
            path = PurePosixPath(name)
            if path.suffix in {".jar", ".pyc", ".pem", ".key", ".p12"} or path.name.startswith(".env") or "eula_acceptance" in name:
                raise RuntimeError(f"private or generated file in wheel: {name}")
        for suffix in ("licenses/LICENSE", "licenses/THIRD_PARTY_NOTICES.md", "entry_points.txt"):
            if not any(name.endswith(suffix) for name in names):
                raise RuntimeError(f"wheel is missing {suffix}")
        for name in ("minecraft_versions.json", "terrain_data.py", "terrain_analysis.py", "structure_blocks.py",
                     "http_server.py", "http_auth.py", "web_server.py", "web/index.html", "web/app.js", "web/style.css"):
            if f"dreamseed_mcp/{name}" not in names:
                raise RuntimeError(f"wheel is missing dreamseed_mcp/{name}")


def check_installations(source: Path, wheel: Path, native: Path, temporary: Path, capabilities: dict) -> dict:
    rebuilt = source / "build"
    run(["cmake", "-S", str(source), "-B", str(rebuilt), "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_TESTING=ON", "-DDREAMSEED_WARNINGS_AS_ERRORS=ON"])
    run(["cmake", "--build", str(rebuilt), "--parallel", "4"])
    run(["ctest", "--test-dir", str(rebuilt), "--output-on-failure"])
    rebuilt_capabilities = json_command([str(rebuilt / "dreamseed"), "capabilities"], cwd=temporary)
    if rebuilt_capabilities != capabilities:
        raise RuntimeError("rebuilt source capabilities differ from the release binary")
    for binary in (rebuilt / "dreamseed", native / "bin" / "dreamseed"):
        result = json_command([str(binary), "search", "--config", str(source / "examples" / "multi_constraint_search.json")], cwd=temporary)
        if result["state"] != "completed" or result["results"][0]["seed"] != "2579":
            raise RuntimeError("packaged native search did not reproduce the deterministic example")
    environment = temporary / "installed"
    run([sys.executable, "-m", "venv", str(environment)], cwd=temporary)
    python = environment / "bin" / "python"
    run([str(python), "-m", "pip", "install", "--disable-pip-version-check", str(wheel)], cwd=temporary)
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "DREAMSEED_BINARY"):
        env.pop(key, None)
    env.update({
        "PATH": os.pathsep.join([str(native / "bin"), env.get("PATH", "")]),
        "DREAMSEED_STATE_DIR": str(temporary / "jobs"),
        "DREAMSEED_MINECRAFT_SERVER_JAR": str(temporary / "missing-server.jar"),
        "DREAMSEED_ACCEPT_MOJANG_EULA": "false",
    })
    run([str(python), "-m", "pip", "check"], cwd=temporary, env=env)
    doctor = json_command([str(environment / "bin" / "dreamseed-doctor"), "--json"], cwd=temporary, env=env)
    if not doctor["ok"]:
        raise RuntimeError(f"installed wheel doctor failed: {doctor}")
    smoke = json_command([str(python), str(source / "scripts" / "release_smoke.py")], cwd=temporary, env=env)
    return {"source_rebuilt": True, "native_archive_search": True, "isolated_wheel_install": True, "mcp": smoke}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and package a DreamSeed release locally")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    build_dir = args.build_dir.resolve()
    version, capabilities = check_metadata(build_dir)
    if args.check:
        print(f"Release metadata is consistent at version {version}")
        return
    system = {"Darwin": "macos", "Linux": "linux"}.get(platform.system())
    if system is None:
        parser.error("release packaging currently supports macOS and Linux")
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if status.strip() and not args.allow_dirty:
        parser.error("release packaging requires a clean worktree; use --allow-dirty only for a local rehearsal")
    output = (args.output or ROOT / "dist" / version).resolve()
    if output.exists() and any(output.iterdir()):
        parser.error(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH") or subprocess.check_output(["git", "show", "-s", "--format=%ct", "HEAD"], cwd=ROOT, text=True).strip())
    architecture = {"aarch64": "arm64", "AMD64": "x86_64"}.get(platform.machine(), platform.machine())
    target = f"{system}-{architecture}"
    with tempfile.TemporaryDirectory(prefix="dreamseed-release-") as name:
        temporary = Path(name)
        packages = temporary / "packages"
        packages.mkdir()
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(epoch))
        run([sys.executable, "-m", "build", "--outdir", str(packages), str(ROOT)], env=env)
        source_archive, = packages.glob("*.tar.gz")
        wheel, = packages.glob("*.whl")
        required = {
            "CMakeLists.txt", "Makefile", "MANIFEST.in", "pyproject.toml", "LICENSE",
            "engine/src/engine.cpp", "cli/main.cpp", "mcp/server.py", "dreamseed_mcp/server.py",
            "third_party/cubiomes/generator.c", "third_party/cubiomes/LICENSE",
            ".claude-plugin/plugin.json", ".mcp.json", "skills/find-minecraft-seed/SKILL.md",
            "scripts/release.py", "scripts/release_smoke.py", "scripts/merge_release.py", f"docs/releases/{version}.md",
            "dreamseed_mcp/minecraft_chunks.py", "dreamseed_mcp/minecraft_registry.py",
            "tests/fixtures/java_1_21_1_seed_0_structures.json",
            "dreamseed_mcp/candidate_verification.py", "examples/verify_seed_candidate.json",
            "dreamseed_mcp/minecraft_versions.json", "dreamseed_mcp/versions.py", "engine/src/version_catalog.hpp.in",
            "tests/fixtures/java_1_21_3_seed_0_structures.json", "tests/fixtures/java_1_21_3_candidate_verification.json",
            "tests/test_versions.py", "tests/test_structure48.py", "docs/structure48.md", "scripts/benchmark_structure48.py",
            "dreamseed_mcp/structure_blocks.py", "tests/fixtures/igloo_template_blocks.json", "examples/verify_igloo_blocks.json",
            "docs/structure_blocks.md", "tests/test_structure_blocks.py", "tests/test_http_auth.py", "tests/test_web.py",
            "tests/web_client.test.cjs",
            "dreamseed_mcp/terrain_data.py", "dreamseed_mcp/terrain_analysis.py", "dreamseed_mcp/terrain_rendering.py", "dreamseed_mcp/terrain_cli.py",
            "tests/fixtures/java_1_21_3_terrain.json", "tests/test_terrain.py", "docs/terrain.md",
            "dreamseed_mcp/http_server.py", "dreamseed_mcp/http_auth.py", "dreamseed_mcp/web_server.py",
            "dreamseed_mcp/web/index.html", "dreamseed_mcp/web/app.js", "dreamseed_mcp/web/style.css", "docs/http_and_web.md",
            "engine/src/placement.metal", "engine/src/placement_metal.mm", "engine/src/placement_stub.cpp", "engine/src/metal_source.hpp.in",
            "engine/include/dreamseed/placement.hpp", "tests/test_placement_prefilter.py", "scripts/benchmark_placement.py", "docs/gpu_filtering.md",
            "tests/fixtures/java_1_21_1_candidate_verification.json", "docs/candidate_verification.md", "docs/roadmap.md",
        }
        source = extract_archive(source_archive, temporary / "source", required)
        check_wheel(wheel)
        native_tar = native_archive(packages, build_dir / "dreamseed", build_dir, version, target, epoch)
        native = extract_archive(native_tar, temporary / "native", {"bin/dreamseed", "licenses/Cubiomes-LICENSE", "licenses/nlohmann-json-LICENSE.MIT"})
        validation = check_installations(source, wheel, native, temporary, capabilities)
        artifacts = []
        for path in sorted(packages.iterdir()):
            artifacts.append({"name": path.name, "sha256": digest(path), "size_bytes": path.stat().st_size})
        manifest = {
            "schema_version": 1, "project": "DreamSeed", "version": version,
            "minecraft_versions": capabilities["minecraft_versions"], "target": target,
            "git_revision": revision, "working_tree_dirty": bool(status.strip()),
            "python_version": platform.python_version(), "os_version": platform.release(),
            "libc": list(platform.libc_ver()), "validation": validation, "artifacts": artifacts,
        }
        manifest_path = packages / f"release-manifest-{target}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        checksums = "".join(f"{digest(path)}  {path.name}\n" for path in sorted(packages.iterdir()))
        (packages / "SHA256SUMS").write_text(checksums, encoding="ascii")
        for path in packages.iterdir():
            shutil.copyfile(path, output / path.name)
    print(json.dumps({"ok": True, "version": version, "target": target, "output": str(output), "validation": validation}, indent=2))


if __name__ == "__main__":
    main()
