# v1.0.148 batch19 — bounded native-footprint preparation

Baseline: published commit `7f41c7ee8c4b69f750008bd2d83349d186396fd1`.
The complete historical `AdaptiveRegionHybrid.py` has SHA-256
`cf21781c5cb67f1c0a6827ad8b8ddd7e2fe037f3503a4850fe134ecc0f30f7dd`.

This ledger records **one** distinct optimization group, **R1901 / global 817**. It is not
an additional geometry, brush, cancellation, or diagnostic-scoring contract.
Product, tests and benchmark source are stable. Independent review and the
final paired measurements are complete. The combined batch gate completed
**4,083 cases in 117.859 seconds: 4,025 passed and 58 skipped**, with all
**857** source/configuration hashes unchanged. [Combined validation](v148-batch19-validation.json) records registration and
the separate published-commit CI gate.

## R1901 — prepare bounded native footprints once across simulation tiles

### Actual caller and baseline reproduction

The public regional path is
`DrawBot.make_plan → build_adaptive_hybrid_plan → build_adaptive_execution → simulate_native_plan`.
The simulator already divides the physical canvas into bounded tiles. Before
this change, each tile invoked `_native_rectangles` over the complete input:
the same source coordinates were transformed, diagonal samples interpolated,
brush rectangles clipped, and fill spans projected again before intersection
with that tile.

The first two regression methods were run before the implementation. The
actual public-plan method failed its two work-count subcases; independent
native delivery, quality counts, Coverage pixels and main preview comparisons
passed before those assertions. The second literal native-raster method also
passed. There were no fixture errors.

* A 200×150 source with one blue rectangle, planned onto 400×300, produced
  12 paths across three tiles: **36** native-path transformations.
* The same source planned onto 1200×900 produced one connected fallback path
  across 26 tiles: **26** transformations of that path. Its native ROI exceeds
  the existing 75,000-pixel allowance, so the planner retains its existing
  non-exact candidate and honestly reported missing pixels. This optimization
  preserves that result and does not expand the planning allowance.

### Implementation and bounded fallback

The simulator prepares a private, ordered table only when it has at least two
tiles and ordinary replayable planner containers. The existing canonical
rectangle generator supplies every entry. Each record stores one color and
four inclusive native bounds as five int64 values. Per-tile intersection
selects record positions in ascending order, so fill-before-stroke ordering,
overpainting, inherited brush width, clipping and diagonal sampling remain
unchanged. Tile arrays, score arithmetic, metadata and Pillow-compatible
bounded preview sampling are unchanged.

The table has at most `min(8192, projection.pixel_limit)` records: at most
**327,680 bytes** of raw record capacity. Successful construction shrinks the
owned array to its used records. A tile query additionally needs bounded
Boolean selection arrays and at most one intp index per record. No full-canvas
ink raster or unbounded rectangle list is introduced, and no cache survives
the operation.

The original stream is retained for a single tile, non-replayable sequence,
path or span containers, an oversized point/span input, or record overflow.
Overflow discards the partial table and may add one bounded attempt of at most
8,193 yielded records before the original per-tile work. The benchmark includes
this unfavorable control explicitly. Optional table allocation or shrink
`MemoryError` also falls back to streaming. Only these optional allocation
steps catch that error; malformed geometry still fails, and a concurrent Stop
raises `InterruptedError` rather than being absorbed by the fallback.

Stop is checked during admission, construction and tile selection. Closing the
query generator and clearing the owned table in `finally` prevent a retained
Stop/error traceback from keeping its private allocation alive. Existing
owned-preview cleanup remains in place.

### Work and ownership evidence, outside timing

All counts below come from the actual current and complete historical modules
with identical inputs. A path transformation means a call to
`NativeBrushProjection.native_path` inside the real simulation.

| Workload | Tiles | Path transformations before → after | Rectangle preparations before → after | Retained table bytes |
| --- | ---: | ---: | ---: | ---: |
| Direct single-tile control | 1 | 5 → 5 | 109 → 109 | 0 |
| Direct 2200×1300, mixed brushes/diagonals/fill | 54 | 270 → 5 | 189,000 → 3,500 | 140,000 |
| Direct oversized-diagonal streaming control | 3 | 66 → 83 | 31,812 → 40,005 | 0 |
| Public packed 400×300 plan | 3 | 36 → 12 | 36 → 12 | 480 |
| Public fallback 1200×900 plan | 26 | 26 → 1 | 3,302 → 127 | 5,080 |
| Public fractional 431×321 plan | 3 | 18 → 6 | 828 → 276 | 11,040 |

The table's construction capacity is 327,680 bytes in these multi-tile
workloads. The smaller pixel-allowance regression also verifies a 192-record
capacity (7,680 bytes), shrinking to two records (80 bytes). The overflow
regression proves byte-for-byte parity with the streaming route and leaves
caller-owned read-only map arrays and sequence dictionaries unchanged.

### Correctness and independent review

`test_v148_rendering_batch19_native_tiles.py` contains ten methods covering:

* Actual public `make_plan → execute_plan` output painted from recorded native
  mouse actions, including actual brush-control selections.
* A separate literal source-cell/native-stamp oracle for overlapping colors,
  fills, diagonal phases, clipping, negative origins, fractional fits, empty
  entries that must not change brush width, seeded paths, empty schedules and
  a 2200×1300 canvas whose diagnostics are downsampled.
* The single-tile bypass, bounded capacity, overflow, replayability, unchanged
  borrowed map data and operation-local ownership.
* Stop during preparation and during tile queries with the real exception
  traceback deliberately retained; the private table is released and the
  owned image is closed.
* Allocation/shrink failure fallback and preserved Stop/malformed-input
  behavior. The review-requested allocation probes failed in three subcases
  before the narrow fallback was added, then passed.

The focused command passed **27 tests** in **3.107 seconds**, without skips:

```sh
.venv/bin/python -m unittest test_v148_rendering_batch19_native_tiles test_v148_rendering_batch10_physical test_v148_subject_native_completion -q
```

The benchmark's untimed verification loads the **complete historical module**
from the baseline commit. It compares all metrics and both diagnostic images
for **72** cases across seeds, source shapes, tile allowances, empty/axis/mixed
paths, fills, letterboxing and inherited brush width. It also compares all six
workload outputs, including three complete public plans, and independently
replays all three public plans through the real executor. Public-plan
comparison excludes only explicitly listed elapsed/profiling fields, exactly
as recorded in the raw report. Shared current dependencies are identical on
both sides; no old helper receives a new private API.

The 72-case output digest is
`e4c22496b134f8477d150bd3602650cec96b3330d60c34672b8dc8d336ba4834`.
The latest verify-only run also recorded unchanged source hashes. It is an
untimed correctness artifact, not a performance claim.

Root's independent source review is closed. It confirmed ordering, clipping,
brush inheritance, input admission and the single-tile bypass. Its
optional-allocation failure finding was reproduced and addressed as described
above. Root reran all ten new methods: **10 passed in 1.706 seconds**. No
DrawBot, execution guard, native-input, palette, stroke, schedule, version or
register change is part of R1901.

### Paired measurements

The frozen final command was:

```sh
.venv/bin/python benchmark_v148_rendering_batch19.py --repeats 6
```

After the test-only Tcl-fixture repair, all six workloads were rerun. These
final measurements supersede the first measurement artifact. The raw report
is `docs/v148-batch19-rendering-benchmarks.json`, SHA-256
`d5a1d7c16702bfab4595641dc3fdff895b244f86daa8de3e5a8683de5f438799`.
All six workloads have six balanced AB/BA pairs, exact complete output on every
invocation and separate tracemalloc passes after garbage collection. Work
counters and independent native replay run outside the timers. All **807**
root Python source hashes were unchanged; the shared batch19 source manifest
is `a0d152b40c9a48c43492f51a6ac54aa655a7df99aabeae90b03d1db2e6e0b551`.

| Workload | Before median ms | After median ms | Elapsed change | Before traced peak bytes | After traced peak bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Direct single-tile control | 0.618 | 0.617 | −0.2% | 124,332 | 125,316 |
| Direct 2200×1300 mixed native raster | 363.838 | 102.163 | −71.9% | 9,096,439 | 9,241,071 |
| Direct oversized-diagonal streaming control | 67.453 | 80.062 | **+18.7%** | 2,236,267 | 2,237,535 |
| Public packed 400×300 plan | 180.282 | 180.896 | +0.3% | 10,666,085 | 10,665,137 |
| Public fallback 1200×900 plan | 650.259 | 625.961 | −3.7% | 87,433,110 | 87,445,386 |
| Public fractional 431×321 plan | 280.042 | 283.920 | +1.4% | 12,072,603 | 12,072,829 |

The large direct native simulation is **71.9% faster in this workload**, with
a **144,632-byte higher traced peak** (+1.59%), consistent with its retained
140,000-byte footprint table. The deliberately overflowing input is **18.7%
slower** because the bounded unsuccessful preparation precedes streaming. The
single-tile control has identical work counts and no table; its sub-millisecond
timing difference is not treated as an optimization benefit.

The three actual public plans show mixed, small whole-plan timing changes:
two measured medians are 0.3% and 1.4% slower; the larger fallback plan is 3.7%
faster. Their reduced geometry work is real, but this evidence does **not**
establish a general end-to-end planning speedup. The largest observed public
traced-peak increase is 12,276 bytes (+0.014%); the other two peaks fall by
948 bytes and rise by 226 bytes. These full-plan peaks are effectively unchanged
in this measurement scope.

Timing includes planning/simulation, output fingerprinting and owned-image
cleanup. Traced peaks cover Python/NumPy allocations and exclude process RSS
and most native Pillow storage. The raw table-capacity/lifetime counts above
are separate evidence. No general drawing or whole-application speed claim is
made.

### Deduplication

* **R1004** established the physical-brush coordinate contract, bounded native
  ROI, tiled statistics and native preview parity. R1901 preserves all of them
  and removes repeated preparation across tiles already introduced there.
* **RP17** removed a full-canvas Boolean mask per simulated path. It did not
  prepare physical geometry once across tiles.
* **RP19** established cancellation in the simulator; its checks remain a
  requirement, not a second counted improvement.
* **RP38** established exact bounded preview sampling and brush rectangles.
  The same renderer remains the canonical source of R1901's records.
* **R1802** reuses repeated initial brush-candidate scoring across ladders and
  policies. R1901 operates later, on an already chosen execution sequence,
  and neither changes nor re-counts that candidate-selection work.

Tests, benchmark workloads, allocation fallback, review fixes and these
documentation artifacts do not add more groups.
