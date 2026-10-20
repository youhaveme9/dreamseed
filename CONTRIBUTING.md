# Contributing

DreamSeed welcomes focused changes that preserve deterministic behavior and honest validation claims.

## Setup

```sh
make build
make venv
make test
```

Run `make release-check` before submitting a change. Use `make sanitize` for native memory safety checks.

## Requirements

1. Add deterministic tests for changed behavior.
2. Keep stdout reserved for JSON or MCP protocol output.
3. Send diagnostics to stderr.
4. Document false positive and false negative conditions.
5. Never add fabricated seeds, coordinates, fixtures, or benchmark numbers.
6. Preserve the pinned Minecraft version and dependency revisions unless the change includes validation evidence.
