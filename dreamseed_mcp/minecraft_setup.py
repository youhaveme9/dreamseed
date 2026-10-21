from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .versions import DEFAULT_VERSION, VERSIONS, get_version

MINECRAFT_VERSION = DEFAULT_VERSION
SERVER_SHA1 = get_version().server_sha1
SERVER_SIZE = get_version().server_size
SERVER_URL = get_version().server_url
EULA_URL = "https://www.minecraft.net/en-us/eula"
ACCEPTANCE_FILE = "mojang_eula_acceptance.json"


def default_server_dir(minecraft_version: str = DEFAULT_VERSION) -> Path:
    configured = os.environ.get("DREAMSEED_MINECRAFT_DIR")
    if configured:
        return (Path(configured).expanduser() / minecraft_version).resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "DreamSeed" / "minecraft" / minecraft_version).resolve()
    data_home = os.environ.get("XDG_DATA_HOME")
    root = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return (root / "dreamseed" / "minecraft" / minecraft_version).resolve()


def configured_server_jar(minecraft_version: str = DEFAULT_VERSION) -> Path:
    configured = os.environ.get("DREAMSEED_MINECRAFT_SERVER_JAR")
    if configured:
        return Path(configured).expanduser().resolve()
    return default_server_dir(minecraft_version) / "server.jar"


def configured_java() -> str:
    return os.environ.get("DREAMSEED_JAVA", "java")


def acceptance_path(jar: Path) -> Path:
    return jar.parent / ACCEPTANCE_FILE


def eula_accepted(jar: Path, minecraft_version: str = DEFAULT_VERSION) -> bool:
    if os.environ.get("DREAMSEED_ACCEPT_MOJANG_EULA", "").lower() in {"1", "true", "yes"}:
        return True
    try:
        record = json.loads(acceptance_path(jar).read_text(encoding="utf-8"))
        return record.get("accepted") is True and record.get("minecraft_version") == minecraft_version
    except (OSError, json.JSONDecodeError):
        return False


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def java_major(java: str) -> int | None:
    try:
        completed = subprocess.run(
            [java, "-version"], text=True, capture_output=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = completed.stderr + completed.stdout
    for token in output.replace('"', " ").split():
        if token[0:1].isdigit() and "." in token:
            try:
                return int(token.split(".", 1)[0])
            except ValueError:
                continue
    return None


def installation_status(verify_hash: bool = False, minecraft_version: str = DEFAULT_VERSION) -> dict[str, Any]:
    spec = get_version(minecraft_version, require_enabled=False)
    jar = configured_server_jar(minecraft_version)
    accepted = eula_accepted(jar, minecraft_version)
    major = java_major(configured_java())
    exists = jar.is_file()
    size_ok = exists and jar.stat().st_size == spec.server_size
    hash_ok = sha1_file(jar) == spec.server_sha1 if verify_hash and size_ok else None
    available = exists and size_ok and accepted and major is not None and major >= spec.java_major
    if verify_hash:
        available = available and hash_ok is True
    if not exists:
        detail = "Minecraft server jar is not installed"
    elif not size_ok:
        detail = "Minecraft server jar size does not match the pinned release"
    elif verify_hash and not hash_ok:
        detail = "Minecraft server jar checksum does not match the pinned release"
    elif not accepted:
        detail = "Mojang EULA acceptance has not been recorded"
    elif major is None or major < spec.java_major:
        detail = f"Java {spec.java_major} or newer is required"
    else:
        detail = f"Official Minecraft Java {minecraft_version} server verification is ready"
    return {
        "available": available,
        "detail": detail,
        "jar": str(jar),
        "accepted": accepted,
        "exists": exists,
        "java_major": major,
        "size_ok": size_ok,
        "sha1_ok": hash_ok,
        "minecraft_version": minecraft_version,
    }


def record_acceptance(jar: Path, minecraft_version: str = DEFAULT_VERSION) -> None:
    jar.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    record = {
        "accepted": True,
        "minecraft_version": minecraft_version,
        "eula_url": EULA_URL,
        "accepted_at": datetime.now(timezone.utc).isoformat(),
    }
    target = acceptance_path(jar)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".eula.", suffix=".tmp", dir=jar.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2)
            stream.write("\n")
        os.replace(temporary_name, target)
    finally:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        except OSError:
            pass


def download_server(jar: Path, minecraft_version: str = DEFAULT_VERSION) -> None:
    spec = get_version(minecraft_version, require_enabled=False)
    jar.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".server.", suffix=".jar", dir=jar.parent)
    try:
        digest = hashlib.sha1()
        total = 0
        request = urllib.request.Request(spec.server_url, headers={"User-Agent": f"DreamSeed/{__version__}"})
        with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(request, timeout=30) as response:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > spec.server_size:
                    raise RuntimeError("download exceeded the pinned server size")
                digest.update(chunk)
                output.write(chunk)
        if total != spec.server_size or digest.hexdigest() != spec.server_sha1:
            raise RuntimeError("downloaded server jar failed size or checksum verification")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, jar)
    finally:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        except OSError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the pinned official Minecraft server verifier")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--accept-mojang-eula", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--minecraft-version", choices=tuple(VERSIONS), default=DEFAULT_VERSION)
    arguments = parser.parse_args()
    spec = get_version(arguments.minecraft_version, require_enabled=False)
    jar = configured_server_jar(arguments.minecraft_version)
    if arguments.download:
        if not arguments.accept_mojang_eula:
            parser.error(f"--download requires --accept-mojang-eula after reviewing {EULA_URL}")
        if not jar.is_file() or jar.stat().st_size != spec.server_size or sha1_file(jar) != spec.server_sha1:
            download_server(jar, arguments.minecraft_version)
        record_acceptance(jar, arguments.minecraft_version)
    status = installation_status(verify_hash=True, minecraft_version=arguments.minecraft_version)
    if arguments.json:
        print(json.dumps(status, indent=2))
    else:
        print(status["detail"])
        print(f"Server jar: {status['jar']}")
        if not status["available"]:
            print(f"Review {EULA_URL}")
            print("Then run: dreamseed-minecraft-setup --download --accept-mojang-eula")
    raise SystemExit(0 if status["available"] else 1)


if __name__ == "__main__":
    main()
