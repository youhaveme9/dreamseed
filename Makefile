.PHONY: configure build test clean venv mcp-test benchmark release-check sanitize

BUILD_DIR ?= build
PYTHON ?= python3
CMAKE_FLAGS ?=

configure:
	cmake -S . -B $(BUILD_DIR) -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON $(CMAKE_FLAGS)

build: configure
	cmake --build $(BUILD_DIR) --parallel

test: build venv
	ctest --test-dir $(BUILD_DIR) --output-on-failure
	.venv/bin/python -m unittest discover -s tests -v

venv:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -e .

mcp-test: build venv
	DREAMSEED_BINARY=$(CURDIR)/$(BUILD_DIR)/dreamseed .venv/bin/python -m unittest discover -s tests -v

benchmark: build
	scripts/benchmark.sh

release-check: CMAKE_FLAGS += -DDREAMSEED_WARNINGS_AS_ERRORS=ON
release-check: test
	.venv/bin/python -m pip check
	./build/dreamseed capabilities >/dev/null

sanitize:
	cmake -S . -B build-sanitize -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON -DDREAMSEED_ENABLE_SANITIZERS=ON
	cmake --build build-sanitize --parallel
	ctest --test-dir build-sanitize --output-on-failure

clean:
	cmake -E remove_directory $(BUILD_DIR)
	cmake -E remove_directory build-sanitize
