from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def content_fingerprint(path: Path) -> str:
    entries: dict[str, str] = {}
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                if name in entries:
                    raise RuntimeError(f"duplicate wheel entry: {name}")
                entries[name] = hashlib.sha256(archive.read(name)).hexdigest()
    else:
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                name = PurePosixPath(member.name)
                if name.is_absolute() or ".." in name.parts or member.issym() or member.islnk():
                    raise RuntimeError(f"unsafe source entry: {name}")
                if not member.isfile():
                    continue
                relative = PurePosixPath(*name.parts[1:]).as_posix()
                if relative in entries:
                    raise RuntimeError(f"duplicate source entry: {relative}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise RuntimeError(f"could not read source entry: {name}")
                with stream:
                    entries[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_bundle(manifest_path: Path, revision: str, expected_versions: list[str] | None = None) -> dict:
    if expected_versions is None:
        catalog_path = Path(__file__).resolve().parents[1] / "dreamseed_mcp/minecraft_versions.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        expected_versions = [item["name"] for item in catalog["versions"] if item["enabled"]]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("git_revision") != revision or manifest.get("working_tree_dirty") is not False:
        raise RuntimeError(f"bundle is not from the intended clean commit: {manifest_path.name}")
    if manifest.get("project") != "DreamSeed" or manifest.get("minecraft_versions") != expected_versions:
        raise RuntimeError("unexpected bundle project or Minecraft version")
    if not re.fullmatch(r"[a-z0-9_]+-[a-z0-9_]+", manifest.get("target", "")):
        raise RuntimeError("invalid bundle platform")
    version = manifest.get("version", "")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise RuntimeError("invalid bundle version")
    validation = manifest.get("validation", {})
    if not all(validation.get(key) is True for key in ("source_rebuilt", "native_archive_search", "isolated_wheel_install")):
        raise RuntimeError("bundle is missing required installation validation")
    mcp = validation.get("mcp", {})
    if mcp.get("ok") is not True or mcp.get("tools_tested") != 11 or mcp.get("job_recovery") is not True:
        raise RuntimeError("bundle is missing complete MCP validation")
    names = set()
    for artifact in manifest["artifacts"]:
        name = artifact["name"]
        path = manifest_path.parent / name
        if Path(name).name != name or name in names or path.is_symlink():
            raise RuntimeError(f"unsafe or duplicate artifact name: {name}")
        if path.stat().st_size != artifact["size_bytes"] or digest(path) != artifact["sha256"]:
            raise RuntimeError(f"artifact checksum mismatch: {name}")
        names.add(name)
    expected = {
        f"dreamseed-{version}-{manifest['target']}.tar.gz",
        f"dreamseed_mcp-{version}.tar.gz",
        f"dreamseed_mcp-{version}-py3-none-any.whl",
    }
    if names != expected:
        raise RuntimeError(f"unexpected artifact set: {sorted(names)}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Combine validated platform bundles for a GitHub release")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--commit")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / "dreamseed_mcp/minecraft_versions.json").read_text(encoding="utf-8"))
    minecraft_versions = [item["name"] for item in catalog["versions"] if item["enabled"]]
    expected_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    revision = arguments.commit or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    paths = sorted(arguments.input.resolve().rglob("release-manifest-*.json"))
    if not paths:
        parser.error("no platform manifests found")
    bundles = [(path, verify_bundle(path, revision, minecraft_versions)) for path in paths]
    versions = {manifest["version"] for _, manifest in bundles}
    targets = [manifest["target"] for _, manifest in bundles]
    if versions != {expected_version} or len(targets) != len(set(targets)):
        parser.error("platform bundles have different versions or duplicate targets")
    if not any(target.startswith("linux-") for target in targets) or not any(target.startswith("macos-") for target in targets):
        parser.error("both Linux and macOS validated bundles are required")
    bundles.sort(key=lambda item: item[1]["target"])
    version = next(iter(versions))
    source_name = f"dreamseed_mcp-{version}.tar.gz"
    wheel_name = f"dreamseed_mcp-{version}-py3-none-any.whl"
    fingerprints = {}
    for name in (source_name, wheel_name):
        values = {content_fingerprint(path.parent / name) for path, _ in bundles}
        if len(values) != 1:
            parser.error(f"unpacked package contents differ between platforms: {name}")
        fingerprints[name] = next(iter(values))
    output = arguments.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("output directory is not empty")
    output.mkdir(parents=True, exist_ok=True)
    canonical = bundles[0][0].parent
    for name in (source_name, wheel_name):
        shutil.copyfile(canonical / name, output / name)
    platforms = {}
    for path, manifest in bundles:
        name = f"dreamseed-{version}-{manifest['target']}.tar.gz"
        shutil.copyfile(path.parent / name, output / name)
        platforms[manifest["target"]] = {
            "python_version": manifest["python_version"], "os_version": manifest["os_version"],
            "libc": manifest["libc"], "validation": manifest["validation"],
        }
    artifacts = [{"name": path.name, "sha256": digest(path), "size_bytes": path.stat().st_size} for path in sorted(output.iterdir())]
    manifest = {
        "schema_version": 1, "project": "DreamSeed", "version": version,
        "git_revision": revision, "working_tree_dirty": False, "minecraft_versions": minecraft_versions,
        "package_content_fingerprints": fingerprints, "platforms": platforms, "artifacts": artifacts,
    }
    (output / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    checksums = "".join(f"{digest(path)}  {path.name}\n" for path in sorted(output.iterdir()))
    (output / "SHA256SUMS").write_text(checksums, encoding="ascii")
    print(json.dumps({"ok": True, "version": version, "commit": revision, "platforms": sorted(platforms), "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
