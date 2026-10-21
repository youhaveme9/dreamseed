# Security policy

## Supported versions

Security fixes are applied to the latest 0.2.x release and the main branch. Users of 0.1.x should upgrade.

## Reporting

Use the repository's [security reporting page](https://github.com/youhaveme9/dreamseed/security/advisories/new) when private reporting is available. Do not include vulnerability details, secrets, or private world data in public issues. For general bugs, use the [issue tracker](https://github.com/youhaveme9/dreamseed/issues).

DreamSeed accepts local MCP input as untrusted data. Reports involving validation bypasses, resource exhaustion, unsafe process handling, or arbitrary filesystem access are especially useful.

Search requests and retained results are stored locally as owner readable job files. Keep `DREAMSEED_STATE_DIR` in a private local directory and do not share one state directory between concurrent server processes.

The optional official Minecraft verifier binds its temporary server to loopback only. It disables remote console, query, and status access. It accepts only fixed locate and surface probe operations from validated schemas. The official server jar is not distributed with DreamSeed and must match the pinned size and SHA1 before execution.
