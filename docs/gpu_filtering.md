# Experimental Metal placement filter

The native CLI can filter a provided list of full world seeds using either Cubiomes on CPU or a Metal compute kernel on macOS. Metal is detected at runtime; unsupported platforms return an explicit unavailable backend error. CPU remains the default. No CUDA, OpenCL, or automatic GPU search backend is implied.

```sh
build/dreamseed capabilities
build/dreamseed filter --config examples/filter_placements.json
.venv/bin/python scripts/benchmark_placement.py --candidates 50000 --repeats 3
```

The request accepts an explicit Minecraft version, up to 100000 unique signed world seed strings, structure constraints, `backend`, and `max_seconds`. Other hard constraint kinds are rejected. All ten supported placement types are implemented, including triangular monument and mansion placement and the outpost attempt RNG. Configurations come from the pinned Cubiomes API rather than copied structure salts.

The GPU arithmetic is derived from Cubiomes under its preserved MIT license. It reproduces placement calculations, including the Java random rules and signed region behavior. It does not evaluate biomes, outpost village exclusion, terrain, or generated blocks. Output is labeled `placement_only_not_verified`. Survivors are full input world seeds and must still pass normal comparison or official verification. The tool cannot manufacture a verified search result from a partial structure seed.

Metal work is submitted in batches of at most 1024 input seeds. Timeouts and cancellation are checked between batches. Input size, region count, and buffers are bounded. Build with `-DDREAMSEED_ENABLE_METAL=OFF` to disable this optional backend. Linux builds use the CPU implementation and report Metal unavailable.

## Local measurements

On the local Apple M3, an optimized Apple Clang 21 build filtered the same 50000 full world seeds with a village placement radius of 500. All three CPU and GPU runs returned the same 49934 placement survivors. The median measured rates were 2732794 candidates per second on CPU and 446289 on Metal. Timings include Metal pipeline initialization, but exclude JSON parsing and serialization in both backends.

The GPU was slower for this workload. It remains an experimental explicit option rather than the default. Useful next work is larger resident batches, persistent pipelines across searches, and profiling selective multi structure workloads before claiming any acceleration benefit.

The parity suite compares 1004 seeds per case, including signed 64 bit boundaries, for both supported versions, every supported placement rule, two anchor and radius cases, negative coordinates, and structure counts. A successful parity test does not upgrade placement to biome or block verification.

The host integration uses Apple's [Metal compute API](https://developer.apple.com/documentation/metal/performing-calculations-on-a-gpu). GPU measurements are local observations, not hardware independent promises.
