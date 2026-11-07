# Batch 19 — prepare unchanged color-region statistics once

Baseline: published commit `7f41c7ee8c4b69f750008bd2d83349d186396fd1`.
This ledger records **one** independently reviewed optimization group,
**C1901 / global 816**, accepted after the final combined gate. It does not
count individual statistics, callers, tests, cleanup paths or metadata fields
separately. [Combined validation](v148-batch19-validation.json) records the
complete batch and its separate published-commit CI gate.

## Actual repeated work

The dynamic exact-color reducer compares temporary quantizer buckets and
merged clusters. Each region comparison previously rebuilt both sides'
weighted statistics, even when their membership had not changed since the
preceding comparison. That work includes member rows, tile distributions,
weighted lightness/importance/protection/edges, additive coverage, tone roles
and hue-family sets.

The initial regression exercises the complete dynamic-stroke builder, the
palette-only builder and actual `DrawBot.make_plan`. A seeded 96×72 RGBA source
contains distinct colored tiles, transparent and partially transparent pixels
and a white corner. The ordinary eight-color reduction performs **3,956**
weighted-stat calculations for just **39 distinct ordered membership states**;
the most repeated state is rebuilt **228 times**. This is observed inside the
real region/statistics implementation, rather than substituting decisions or
providing precomputed clusters.

Before the implementation, three failure records occurred across the two
actual-flow methods; the single-color public control passed. There were no
fixture errors. The run took 0.434 seconds, which is test duration rather than
a performance measurement.

## Operation-local preparation

The merge operation now keeps one lazily prepared state per current cluster
and, when needed, the current incoming item. Nothing is cached globally, on
the input context or on returned clusters. A state is invalidated immediately
after an early in-place append and after a forced merge replaces a cluster.
The parallel state list is shifted with the cluster list.

Every changed cluster is recomputed from its original ordered source members.
Previously averaged summaries are never combined, so floating-point order,
additive union coverage and protection thresholds retain their exact values.
All perceptual distances, hue guards, relation arithmetic, merge thresholds,
tie keys and forced-merge ordering are unchanged. The direct public region
relation still computes its own statistics when no private prepared pair is
provided. Missing, empty and partially populated contexts keep their defaults.
A single-color public input still computes no unused pair statistics.

The production intermediate quantizer has at most 64 buckets. The operation
retains only current cluster states, not every historical combination or
pairwise result. This trades a bounded set of snapshots for fewer repeated
calculations. On success, Stop or error, `finally` clears the owned statistics
and state list. Region comparison drops its temporary array aliases before
later adjacency work can fail. Tests deliberately retain both a wrapper
exception and an exception inside the real adjacency comparison: neither
keeps the private tile arrays alive. Borrowed entries and contexts are intact.

## Correctness and independent review

`test_v148_colour_batch19_regions.py` has eight methods covering:

- The complete public stroke and palette builders, actual `make_plan`, and
  `PictureCustomPaletteLegacy.build_picture_palette`. The first three original
  reproduction paths now perform **39** calculations, one per state.
- In-place cluster growth and forced replacement, comparing the complete
  cached relation against its uncached calculation at every decision. Complete
  merged outputs and diagnostics are also equal.
- A changed context, adjacency map and member weight observed freshly by the
  next operation; partial/empty/absent contexts; and the single-color control.
- Borrowed source bytes/metadata and entry/context ownership, cancellation,
  and deterministic release while an exception traceback remains retained.

The adjacent gate passed **61 tests in 0.990 seconds**, with no skips:

```sh
.venv/bin/python -m unittest test_v148_colour_batch19_regions \
  test_step4_region_aware_quantization_v10128 \
  test_step3_dominant_hue_preservation_v10127 test_v148_colour_batch03 \
  test_color_engine_v1041 test_v148_colour_batch03_picture \
  test_v148_colour_batch03_analysis
```

Independent review of both product diffs and all eight new actual-flow methods
closed without blockers. The reviewer reran the new module: eight passed in
0.433 seconds. The review checked both invalidation paths, member/tie order,
absence of caller/global mutation, direct uncached compatibility and ownership
under Stop and retained errors.

## Complete historical comparison

`benchmark_v148_colour_batch19.py` loads both complete historical modules,
`DynamicColors` and `RegionAwareQuantization`, from the baseline and links the
old reducer to its old region functions. No historical function receives a
new private keyword. Public callers and unrelated dependencies are current on
both sides.

Untimed verification passed **72 complete dynamic-color pairs** across thin
and ordinary dimensions, RGBA/RGB/palette inputs, transparency, all four
fidelity modes, one/eight-color budgets, Paint/browser policies, exact/fallback
selection, source palettes, skip-white choices, lines/dots and protected masks.
It also passed **24 complete merge/diagnostic pairs** with shuffled source
order, changed weights and full/partial/absent contexts. Twenty-four RGBA
outputs were independently rasterized to prove exact drawable coverage and
preservation of ignored pixels. Their combined output digest is
`482d8350624a7684653c78a371dcdaec32b7561874ccf8e023f2d097df52bc15`.

Six additional complete workload pairs cover two stroke-builder sizes,
palette-only preparation, actual Standard and High public plans and actual
picture-palette preparation. Public-plan comparisons include images, geometry,
colors, selectors, costs and metadata. Only the explicitly listed volatile
profiling/timing paths are excluded. The actual effective resolution is
asserted before accepting a plan. Picture-cache load/save and resource probes
are controlled identically, while its real image/color preparation executes.

## Measurement protocol and limits

The coordinated final command is:

```sh
.venv/bin/python benchmark_v148_colour_batch19.py --repeats 6
```

It writes `docs/v148-batch19-colour-benchmarks.json`. Every workload has one
warm/parity pair, six balanced AB/BA timing pairs and separate tracemalloc
probes after garbage collection. Every measured invocation must retain its
complete result fingerprint. Real weighted-stat observations run outside the
timers. Root Python source hashes are recorded and checked for changes.

Timing includes complete CPU color/planning work, result fingerprinting and
owned-plan cleanup. Traced peaks cover Python/NumPy allocation, not process RSS
or most native Pillow cores. The bounded prepared snapshots can increase a
peak even when calculations and elapsed time decrease. The final measurements and
observed tradeoff are recorded below. No physical GPU,
target-application drawing or whole-application speed claim is made.

## Final paired measurements

After the test-only Tcl-fixture repair, all six workloads were rerun with six
balanced AB/BA pairs and exact result fingerprints on warm, timed, traced and
separately observed calls. All **807** root Python source hashes were unchanged.
These final measurements supersede the pre-fixture-repair measurement artifact.
Raw evidence: `v148-batch19-colour-benchmarks.json`, SHA-256
`a34705ec47ee54f219df981b47890288f55fafbce39d9c96c752a8d87bc503f2`.
The shared three-benchmark source manifest is
`a0d152b40c9a48c43492f51a6ac54aa655a7df99aabeae90b03d1db2e6e0b551`.

| Complete workload | Median milliseconds before → after | Time change | Traced peak bytes before → after | Weighted-stat calculations before → after |
| --- | ---: | ---: | ---: | ---: |
| Complete strokes, 96×72 | 99.875 → 71.029 | -28.9% | 393,670 → 393,722 | 3,956 → 39 |
| Complete strokes, 384×288 | 148.050 → 120.253 | -18.8% | 5,571,765 → 5,571,817 | 3,436 → 39 |
| Palette-only, 384×288 | 115.294 → 88.760 | -23.0% | 5,572,141 → 5,572,141 | 3,436 → 39 |
| Public Standard plan, 384×288 | 614.040 → 611.966 | -0.3% | 11,805,499 → 11,805,563 | 3,538 → 39 |
| Public High plan, 384×288 | 1145.608 → 1182.967 | +3.3% | 14,641,396 → 14,641,552 | 3,988 → 39 |
| Picture palette, 192×144 | 107.227 → 76.275 | -28.9% | 1,498,135 → 1,498,827 | 3,434 → 37 |

The complete color/picture builders and both public plans retain exact output.
Weighted-stat calculations fall from thousands to 37–39 actual membership
states. Their elapsed-time effects differ because the reducer is only one
part of a full plan. In this final run, Standard planning was 0.3% shorter
while High planning was 3.3% longer; these full-plan timings do not establish
a consistent end-to-end speedup. Complete color/picture builders were
18.8–28.9% shorter in the measured fixtures. Traced peaks are effectively
unchanged in these fixtures;
the bounded snapshots do not establish a material full-plan memory reduction.
These results support reduced repeated CPU work, without a universal elapsed-
time, native GPU or target-application drawing-speed claim.

Independent source and benchmark-method reviews closed without blockers. The
review checked historical whole-module linkage, complete-output digests,
balanced orders, work-count isolation and both favorable and unfavorable memory
observations. The final repetition uses unchanged product behavior and repaired
test ownership; its full source snapshot matches the final combined gate.

## Deduplication

**CQ04** corrected additive region coverage and small-detail classification;
those formulas and thresholds remain unchanged. **CG30** removed per-color whole-label scans in source region measurement,
before this repeated cluster-relation stage. Earlier
palette-only and cost-only paths also remain controls. C1901 removes repeated
preparation of unchanged cluster membership within the existing reducer and
is counted once across all callers.
