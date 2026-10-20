.PHONY: configure build test clean venv mcp-test benchmark release-check release-candidate package-check sanitize doctor minecraft-check release release-bundle

BUILD_DIR ?= build
PYTHON ?= python3
CMAKE_FLAGS ?=
RELEASE_DIR ?= dist/0.1.0

configure:
	cmake -S . -B $(BUILD_DIR) -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON $(CMAKE_FLAGS)

build: configure
	cmake --build $(BUILD_DIR) --parallel

test: build venv
	ctest --test-dir $(BUILD_DIR) --output-on-failure
	DREAMSEED_BINARY="$(CURDIR)/$(BUILD_DIR)/dreamseed" .venv/bin/python -m unittest discover -s tests -v

venv:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -e '.[dev]'

mcp-test: build venv
	DREAMSEED_BINARY=$(CURDIR)/$(BUILD_DIR)/dreamseed .venv/bin/python -m unittest discover -s tests -v

benchmark: build
	scripts/benchmark.sh

release-check: CMAKE_FLAGS += -DDREAMSEED_WARNINGS_AS_ERRORS=ON
release-check: test
	.venv/bin/python -m pip check
	$(BUILD_DIR)/dreamseed capabilities >/dev/null
	.venv/bin/dreamseed-doctor --binary $(CURDIR)/$(BUILD_DIR)/dreamseed --state-dir $(CURDIR)/$(BUILD_DIR)/doctor-state
	.venv/bin/python scripts/release.py --check --build-dir $(BUILD_DIR)

package-check: venv
	cmake -E remove_directory $(BUILD_DIR)/artifacts
	cmake -E make_directory $(BUILD_DIR)/artifacts
	.venv/bin/python -m pip wheel --no-deps --wheel-dir $(BUILD_DIR)/artifacts .

release-candidate: release-check sanitize package-check
	.venv/bin/python -m compileall -q dreamseed_mcp mcp tests
	@if command -v claude >/dev/null 2>&1; then claude plugin validate . --strict; else echo "Claude CLI unavailable, plugin runtime validation skipped"; fi

release: release-candidate
	.venv/bin/python scripts/release.py --build-dir $(BUILD_DIR) --output $(RELEASE_DIR)

release-bundle:
	.venv/bin/python scripts/release.py --build-dir $(BUILD_DIR) --output $(RELEASE_DIR)

doctor: build venv
	.venv/bin/dreamseed-doctor --binary $(CURDIR)/$(BUILD_DIR)/dreamseed

minecraft-check: venv
	.venv/bin/dreamseed-minecraft-setup --json

sanitize:
	cmake -S . -B build-sanitize -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON -DDREAMSEED_ENABLE_SANITIZERS=ON
	cmake --build build-sanitize --parallel
	ctest --test-dir build-sanitize --output-on-failure

clean:
	cmake -E remove_directory $(BUILD_DIR)
	cmake -E remove_directory build-sanitize
