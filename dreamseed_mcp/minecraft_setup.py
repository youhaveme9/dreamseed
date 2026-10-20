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

MINECRAFT_VERSION = "1.21.1"
SERVER_SHA1 = "59353fb40c36d304f2035d51e7d6e6baa98dc05c"
SERVER_SIZE = 51_627_615
SERVER_URL = "https://piston-data.mojang.com/v1/objects/59353fb40c36d304f2035d51e7d6e6baa98dc05c/server.jar"
EULA_URL = "https://www.minecraft.net/en-us/eula"
ACCEPTANCE_FILE = "mojang_eula_acceptance.json"


def default_server_dir() -> Path:
    configured = os.environ.get("DREAMSEED_MINECRAFT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "DreamSeed" / "minecraft" / MINECRAFT_VERSION).resolve()
    data_home = os.environ.get("XDG_DATA_HOME")
    root = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return (root / "dreamseed" / "minecraft" / MINECRAFT_VERSION).resolve()


def configured_server_jar() -> Path:
    configured = os.environ.get("DREAMSEED_MINECRAFT_SERVER_JAR")
    if configured:
        return Path(configured).expanduser().resolve()
    return default_server_dir() / "server.jar"


def configured_java() -> str:
    return os.environ.get("DREAMSEED_JAVA", "java")


def acceptance_path(jar: Path) -> Path:
    return jar.parent / ACCEPTANCE_FILE


def eula_accepted(jar: Path) -> bool:
    if os.environ.get("DREAMSEED_ACCEPT_MOJANG_EULA", "").lower() in {"1", "true", "yes"}:
        return True
    try:
        record = json.loads(acceptance_path(jar).read_text(encoding="utf-8"))
        return record.get("accepted") is True and record.get("minecraft_version") == MINECRAFT_VERSION
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


def installation_status(verify_hash: bool = False) -> dict[str, Any]:
    jar = configured_server_jar()
    accepted = eula_accepted(jar)
    major = java_major(configured_java())
    exists = jar.is_file()
    size_ok = exists and jar.stat().st_size == SERVER_SIZE
    hash_ok = sha1_file(jar) == SERVER_SHA1 if verify_hash and size_ok else None
    available = exists and size_ok and accepted and major is not None and major >= 21
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
    elif major is None or major < 21:
        detail = "Java 21 or newer is required"
    else:
        detail = "Official Minecraft Java 1.21.1 server verification is ready"
    return {
        "available": available,
        "detail": detail,
        "jar": str(jar),
        "accepted": accepted,
        "exists": exists,
        "java_major": major,
        "size_ok": size_ok,
        "sha1_ok": hash_ok,
    }


def record_acceptance(jar: Path) -> None:
    jar.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    record = {
        "accepted": True,
        "minecraft_version": MINECRAFT_VERSION,
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


def download_server(jar: Path) -> None:
    jar.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".server.", suffix=".jar", dir=jar.parent)
    try:
        digest = hashlib.sha1()
        total = 0
        request = urllib.request.Request(SERVER_URL, headers={"User-Agent": f"DreamSeed/{__version__}"})
        with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(request, timeout=30) as response:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > SERVER_SIZE:
                    raise RuntimeError("download exceeded the pinned server size")
                digest.update(chunk)
                output.write(chunk)
        if total != SERVER_SIZE or digest.hexdigest() != SERVER_SHA1:
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
    arguments = parser.parse_args()
    jar = configured_server_jar()
    if arguments.download:
        if not arguments.accept_mojang_eula:
            parser.error(f"--download requires --accept-mojang-eula after reviewing {EULA_URL}")
        if not jar.is_file() or jar.stat().st_size != SERVER_SIZE or sha1_file(jar) != SERVER_SHA1:
            download_server(jar)
        record_acceptance(jar)
    status = installation_status(verify_hash=True)
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
