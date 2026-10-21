# Structure seed batching

The `structure48` strategy generates full world seeds in cohorts sharing the lower 48 bits. It requires at least one structure constraint. All ten supported placement rules were inspected in the pinned Cubiomes `getStructurePos`, `getFeaturePos`, and `getLargeStructurePos` implementations. Their Java random placement state uses the lower 48 bits. This does not apply generally to arbitrary Minecraft structures.

Biome generation, structure biome viability, terrain screening, and outpost village exclusion still run against each full 64 bit world seed. Cache entries never contain these decisions. Each worker owns one placement cache scoped to its fixed request. Memory does not grow with the number of searched seeds.

## Reproduction

```sh
build/dreamseed search --config examples/structure48.json
.venv/bin/python scripts/benchmark_structure48.py --candidates 50000 --repeats 3
```

`sample_seed` selects a deterministic sequence. `upper_bits_per_structure_seed` accepts 1 through 65536, default 256. `placement_cache` defaults to true and can be disabled to compare identical candidates without reuse. These settings are rejected for other strategies.

The cohort index is added to the sampling seed modulo 2 to the power 48. Three XOR shifts and two odd multiplications permute that value within 48 bits. A SplitMix64 value selects the first upper 16 bits; successive candidates increment those bits modulo 65536. Distinct cohorts have distinct lower bits throughout the bounded budget. Every returned value is a complete signed 64 bit world seed.

Coverage is `sampled_structure_seed_batches`, never globally exhaustive. Cohorts explore fewer structure layouts than independent sampling, and can repeat biome patterns. This strategy is useful for selective structure placement constraints, not necessarily biome dominated requests. Completed candidate budgets have the same results across worker counts; timeout prefixes can vary with scheduling.

## Measurements

On the local Apple M3 with an optimized Apple Clang 21 build, three runs of 50000 candidates per workload used Java 1.21.3, sampling seed 20261020, one worker, cohorts of 256, and one village constraint. Cached and uncached runs produced identical results and match counts.

| Village radius | Cached median candidates per second | Uncached median candidates per second | Rejected before biomes |
| --- | --- | --- | --- |
| 64 | 2473717 | 1500857 | 49744 |
| 500 | 17740 | 17626 | 256 |

Each cached run made 196 placement computations and reused them 49804 times, versus 50000 computations without caching. At radius 500, biome viability dominates and the measured gain is small. The radius 64 runs took approximately 20 milliseconds cached and 33 milliseconds uncached, so short run timing noise matters. These are local observations, not general throughput guarantees.

The completed job's `placement_filter` reports computation count, reuse count, early rejections, and full seed evaluations started. Interrupted work can start a full evaluation without completing it. Counts of placement computations across multiple workers are not counts of globally unique structure seeds.
