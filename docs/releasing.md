# Preparing a release

## Version and validation

The current release version is `0.2.0`. Keep `pyproject.toml`, `CMakeLists.txt`, `dreamseed_mcp/__init__.py`, and `.claude-plugin/plugin.json` consistent. `scripts/release.py --check` compares them with the compiled engine, release notes, changelog, and Git tag when applicable. Bundle merging also checks the shared Minecraft version catalog.

Build and validate the intended release commit from a clean worktree:

```sh
make release
```

The command runs the complete release candidate gate, builds the source archive and Python wheel, assembles a native archive for the current platform, rebuilds the extracted source, and tests a fresh wheel installation outside the checkout. The installed server discovers the packaged binary through PATH. All eleven MCP tools and completed job recovery are exercised. Public release is a separate approved action.

Current release outputs default to `dist/0.2.0`. A nonempty directory is never overwritten. Choose a new directory with `RELEASE_DIR=dist/validation-run-2` if you need another build. Preserve existing published artifacts.

For a local rehearsal before committing, run the release candidate gate, then allow a dirty snapshot explicitly:

```sh
make release-candidate
.venv/bin/python scripts/release.py --allow-dirty --output dist/0.2.0-candidate
```

Rehearsal manifests record `working_tree_dirty: true`. Publish only artifacts rebuilt from the intended clean release commit.

## Official Minecraft integration

The default gate does not download Minecraft or accept its EULA. On a machine with explicit acceptance and the pinned server installed, enable the real integration test:

```sh
DREAMSEED_RUN_MINECRAFT_INTEGRATION=1 make release
```

This validates official locate answers, remote chunk surface probes, player clearance, and a water rejection fixture. CI without an accepted server installation must report that integration as skipped.

## Artifacts

The source archive includes the native source, vendored Cubiomes, tests, documentation, examples, skill, and plugin. The Python wheel includes the MCP package and its license notices. The native archive includes the executable, example requests, installation instructions, and full Cubiomes and nlohmann JSON license texts.

`release-manifest-PLATFORM.json` records the version, source revision, dirty state, actual target, archive hashes, and successful package checks. `SHA256SUMS` covers all packaged files and the manifest. A source rebuild proves the archive can compile; it does not claim that independently rebuilt binaries are byte identical.

The `.github/workflows/release.yml` workflow builds validated bundles on macOS and Linux when manually dispatched or when a version tag is pushed. It uploads workflow artifacts and does not publish a GitHub release. See [GitHub artifact documentation](https://docs.github.com/en/actions/tutorials/store-and-share-data).

## Publication

After explicit publication approval, require CI and release bundle jobs to pass for the intended clean commit. Inspect the source tree and artifacts for private files, verify checksums, and finalize `docs/releases/0.2.0.md` before using it as release notes. Attach only native platforms that passed their actual platform validation. Do not label a locally built macOS binary as Linux compatible.

Create and verify a draft release in [youhaveme9/dreamseed](https://github.com/youhaveme9/dreamseed) before making it public. Download the successful platform artifacts and combine them with `scripts/merge_release.py`. The merge verifies clean source revisions, every input checksum, and identical unpacked source and wheel contents across platforms. Its combined manifest records each platform's validation and its checksums cover the published files.

```sh
gh run download RUN_ID --repo youhaveme9/dreamseed --dir dist/platform-bundles
.venv/bin/python scripts/merge_release.py --input dist/platform-bundles --output dist/0.2.0-release
```

Never include Minecraft jars, EULA acceptance records, local virtual environments, private job storage, or local validation worlds in release assets.
