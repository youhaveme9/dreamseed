# Installing DreamSeed release files

DreamSeed 0.1.0 targets Minecraft Java Edition 1.21.1. No model API key is needed.

## Choose a package

The complete source archive is `dreamseed_mcp-0.1.0.tar.gz`. It includes the native engine, Cubiomes, MCP server, Claude plugin, skill, tests, and documentation. Building it requires CMake 3.20 or newer, C11 and C plus plus 20 compilers, Python 3.11 or newer, Make, Git, and initial network access for pinned dependencies.

```sh
tar -xzf dreamseed_mcp-0.1.0.tar.gz
cd dreamseed_mcp-0.1.0
make build
make venv
make doctor
./build/dreamseed search --config examples/multi_constraint_search.json
```

Native archives have names such as `dreamseed-0.1.0-macos-arm64.tar.gz` or `dreamseed-0.1.0-linux-x86_64.tar.gz`. Choose the operating system and CPU architecture that match your machine. Only platforms whose release checks pass should be published. The accompanying manifest records the build environment. Native archives include third party license texts and example configurations.

```sh
tar -xzf dreamseed-0.1.0-macos-arm64.tar.gz
cd dreamseed-0.1.0
./bin/dreamseed capabilities
./bin/dreamseed search --config examples/multi_constraint_search.json
```

Replace the native archive name for your platform. The deterministic example returns Cubiomes candidate seed `2579`.

## Add the MCP server

The Python wheel is `dreamseed_mcp-0.1.0-py3-none-any.whl`. Install it in a private virtual environment. The native executable is installed separately.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install /path/to/dreamseed_mcp-0.1.0-py3-none-any.whl
DREAMSEED_BINARY=/absolute/path/to/dreamseed-0.1.0/bin/dreamseed \
  .venv/bin/dreamseed-doctor
DREAMSEED_BINARY=/absolute/path/to/dreamseed-0.1.0/bin/dreamseed \
  .venv/bin/dreamseed-mcp
```

The final command starts a stdio protocol server. An MCP client should launch it. If the native `dreamseed` command is already on PATH, `DREAMSEED_BINARY` is optional.

Use the source archive for the Claude plugin. After `make build` and `make venv`, follow the Codex and Claude setup instructions in `README.md`.

## Verify downloads

Keep `SHA256SUMS` beside the downloaded files. Verify the entries for the files you downloaded with `shasum -a 256 FILE` on macOS or `sha256sum FILE` on Linux. With every listed file present, run `shasum -a 256 -c SHA256SUMS` or `sha256sum -c SHA256SUMS`.

## Enable official Minecraft verification

The default search engine works without Minecraft installed. For official locate and surface checks, install Java 21 or newer, read the [Minecraft EULA](https://www.minecraft.net/en-us/eula), then run the following only if you accept its terms:

```sh
.venv/bin/dreamseed-minecraft-setup --download --accept-mojang-eula
.venv/bin/dreamseed-minecraft-setup --json
```

Minecraft software and acceptance records are never included in DreamSeed release files. See `docs/authoritative_validation.md` in the source archive for verification semantics.
