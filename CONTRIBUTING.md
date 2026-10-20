# Contributing

DreamSeed welcomes focused changes that preserve deterministic behavior and honest validation claims.

## Setup

```sh
make build
make venv
make test
```

Run `make release-check` before submitting a change. Use `make sanitize` for native memory safety checks.
Run `make doctor` to verify the local runtime, native engine, pinned dependencies, and job storage.
Run `make release-candidate` before proposing a public release.
The maintainer release procedure is in `docs/releasing.md`. Development dependencies are installed by `make venv` and are separate from the runtime wheel requirements.

The proprietary Minecraft server jar is never required for the default suite. To run the real verifier integration after accepting the Mojang EULA and completing local setup, use:

```sh
DREAMSEED_RUN_MINECRAFT_INTEGRATION=1 .venv/bin/python -m unittest tests.test_minecraft_verifier -v
```

## Requirements

1. Add deterministic tests for changed behavior.
2. Keep stdout reserved for JSON or MCP protocol output.
3. Send diagnostics to stderr.
4. Document false positive and false negative conditions.
5. Never add fabricated seeds, coordinates, fixtures, or benchmark numbers.
6. Preserve the pinned Minecraft version and dependency revisions unless the change includes validation evidence.
