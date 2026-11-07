# Batch 21: one calibration database observation per public plan

## Scope and baseline

Verified group **R2101** covers one change: nested public planning reads and validates its primary timing-calibration database once, while continuing to resolve every complete calibration context separately. Source review, complete-output parity, final measurement review and the integrated test gate are closed; registration remains the root finalizer's responsibility. The baseline is published commit `ec22fd8739573adc2df1b3e33dbe1a98a09b9c99`.

Product changes are confined to `DrawTimeCalibration.py` and a thin public `DrawBot.make_plan` wrapper. The previous planning body is unchanged under `_make_plan`. Recursive public callbacks borrow the outer observation. The owner is never placed in an options dictionary, returned plan, saved calibration, or application field.

The legacy `test_extra_fast_region_quality_rc24.py` source-routing assertion now first verifies the public `with planning_calibration_scope(): return _make_plan(...)` delegation, then follows that explicit delegation to its original adaptive-region routing requirement. The new regression also exercises the actual public hybrid route. This test adaptation is not another improvement group.

## Reproduced work before the change

The exact-baseline work-count probe used actual `make_plan` calls, a generated RGBA 128 × 96 source, the real calibrated-palette loader, and private timing files populated by the production `record_sample` writer. Eight genuinely requested full contexts were learned, with three samples per context. Paint had three stored contexts and Gartic had five. The five inspected source modules and all seeded timing bytes were unchanged after the probe. There were no wall-time measurements in that probe.

Pixel planning loaded the same database through `PixelStrokeEngine` → `ExecutionCostModel`, final ETA attachment → `DrawTimeEstimate`, and preview diagnostics → `CalibrationState.timing_state`. Paint Fill substituted `RegionFillEngine` for the initial cost-model caller. The hybrid route additionally planned a baseline, evaluated region/brush candidates, and finalized the selected hybrid plan. Its six calls used three different full keys; replacing those calls with a single normalized correction would be incorrect.

The permanent actual-public regression failed before implementation in all three subcases: Pixel read three times, Paint Fill read three times, and hybrid-with-Fill read six times. This was an observed production call-chain failure, not a missing-helper-only test.

## Ownership and compatibility

`planning_calibration_scope()` owns at most the first validated database for one operation. Storage remains bounded by the existing reader's 4 MiB, 100,000-item and depth-32 limits. `MAX_CONTEXTS = 256` remains a writer eviction policy; the reader regression verifies a valid 257-context file without truncation or mutation. Different profile/path identities take the existing fresh-read path instead of expanding the observation indefinitely.

The identity includes the absolute selected path, profile key and explicit-versus-default path mode. The last distinction preserves the rule that an explicitly missing file does not trigger default-profile migration. The profile distinction preserves migration prefixes even if an unusual caller maps multiple profiles to one destination.

Every access still checks the full v4 key, then its v2 and legacy fallbacks. Tool, brush width, Fill policy, color workflow, drawing mode, preset, quality and style remain independent. Returned shared rows recursively copy reader-bounded JSON values so mutating nested runtime/count/extension data cannot affect a later lookup. Ordinary unscoped calls retain their existing fresh-read/shallow-return path and do not pay for this nested isolation.

The owner records the actual creating `Thread` object. A copied `ContextVar` context in another thread cannot borrow or close that owner's database. Nested calls in the same planning operation borrow without closing the outer scope. Scope teardown clears the database and resets the context; lookup/copy frames clear shared aliases so a retained exception cannot keep the database alive.

Writers and both reset paths remain outside the observation and continue reading current state under their existing locks. Replacing a file, learning a sample or resetting during an active read scope does not alter that scope's already selected snapshot. The next independent operation reads the new state. Missing, malformed or temporarily inaccessible data likewise produces the existing fallback for that operation and is retried on the next operation. `MemoryError` and cancellation errors are not converted into an empty database.

## Work counts and complete-output evidence

The historical harness loads both complete baseline modules, `DrawBot.py` and `DrawTimeCalibration.py`, together. It also binds the imported `ExecutionCostModel.correction_for` alias to the selected complete calibration module. Consequently, the old controller cannot accidentally use the new shared-row isolation path. Unrelated planner dependencies are identical on both sides.

Only the eight contexts actually requested by the public fixtures are seeded, using the baseline production writer and its normal indented JSON representation. Each has three samples; ratios and operation timings intentionally differ between contexts. No unrelated history is added to enlarge the files.

| Actual caller | Correction lookups, before → after | Full keys | JSON reads, before → after | Row validations, before → after |
|---|---:|---:|---:|---:|
| Paint Pixel Accurate | 3 → 3 | 1 | 3 → 1 | 9 → 3 |
| Paint Standard, accepted safe rectangle Fill | 3 → 3 | 1 | 3 → 1 | 9 → 3 |
| Gartic regional hybrid | 5 → 5 | 2 | 5 → 1 | 25 → 5 |
| Gartic regional hybrid with Fill candidates | 6 → 6 | 3 | 6 → 1 | 30 → 5 |
| Paint Dynamic, configured deadline | 2 → 2 | 1 | 2 → 1 | 6 → 3 |
| Gartic Auto Sketch, **Unlimited** recursive Detailed route | 2 → 2 | 1 | 2 → 1 | 10 → 5 |
| Paint Pixel, missing database control | 3 → 3 | 1 | 0 → 0 | 0 → 0 |
| Public unscoped correction reader control | 1 → 1 | 1 | 1 → 1 | 3 → 3 |

The Fill fixture really accepts three Fill regions. The hybrid-with-Fill fixture evaluates Fill candidates but retains zero Fill regions; it must not be described as a delivered-Fill benchmark. Cold missing files perform no JSON parsing on either side.

The verification harness compares **84 complete public-plan pairs**: six actual callers across RGB/RGBA with partial and zero alpha, missing/malformed data, distinct learned v4 rows, v2, v1, and one-time shared-file migration, plus twelve separate Manual Auto Sketch controls. Image bytes, groups, execution paths, selectors, estimates, correction metadata and resulting migration-file bytes match. Only explicitly named existing profiler/planning-clock fields are excluded.

The first exploratory comparison correctly rejected the hybrid wall-clock fields. The final comparator names each of its four elapsed-time fields in both metadata locations, following the earlier batch18 clock boundary. The next exploratory comparison rejected Manual Auto Sketch's naturally varying remaining drawing budget. No budget or estimate field was then excluded: the timed Sketch fixture instead uses the real **Unlimited → Auto → Detailed** route. Manual Auto remains an additional untimed complete-output and work-count oracle with the same controlled `AutoSketchBudget.time.monotonic` observation on both sides. That local module reference is replaced only for this oracle; all measured workloads keep real product clocks and watchdogs. No elapsed-time claim for Manual Auto is inferred from Unlimited results.

## Correctness gates and independent review

The fourteen new methods cover actual public Pixel/Fill/hybrid plans; distinct v4/v2/legacy keys; nested mutable result isolation; fresh ordinary reads; bounded alternate profile/path behavior; nesting and file replacement; fresh writers/reset; explicit/default migration; malformed/missing/unreadable recovery; the 257-row reader boundary; other threads including copied contexts; retained cancellation tracebacks; initial allocation/cancellation errors; and lazy cancellation before any calibration I/O.

The independent platform review read the complete product diff and public wrapper, and ran the fourteen new methods plus all five existing rc24 routing regressions: **19/19 passed in 0.964 s**. The initial broader timing/isolation/ETA/reset gate passed **35 tests in 0.911 s** before the last three focused edge methods were added. No safety guard, input authorization, drawing quality threshold or calibration writer/reset algorithm changed.

The final integrated unittest gate ran **4,198 cases in 199.785 s: 4,140 passed and 58 were skipped**. All 876 checked source/configuration files remained unchanged during that gate. Root independently reviewed the historical benchmark linkage and the explicit clock-field exclusions without blockers.

## Final paired measurements

The final raw evidence is [v148-batch21-calibration-benchmarks.json](v148-batch21-calibration-benchmarks.json), SHA-256 `6e591e870a65d41f67da2847ddc9b0f27e2d9f8bf1691539387a3cde43f17835`. All **826 root Python source hashes** stayed unchanged throughout the run and match the clipping report's source map. The calibration source-map manifest, using `sha256(json.dumps(source_sha256, sort_keys=True).encode())`, is `9f35728c8361cdc1b949dafb03a1d278e0adc4b44728db818835142a0f2801c3`.

The recorded historical source hashes are `c8068c39af54a3fa552eb94d18c92615f127f21c5fb9e3fe3e98f8d7a404d94c` for `DrawBot.py` and `d7005ae297c0ff7bb6a2b8b580d661ab7e4d5e21ad9bb7cbfee77c4aa2fade66` for `DrawTimeCalibration.py`. The production-shaped fixture files are 4,388 bytes with three Paint contexts and 7,125 bytes with five Gartic contexts.

Root ran the following command in the coordinated quiet source/CPU window:

```text
.venv/bin/python benchmark_v148_rendering_batch21_calibration.py --repeats 6
```

The harness alternates six AB/BA pairs and measures the public `make_plan` call itself. Palette/source/file fixture construction, module linking, output fingerprinting and owned-image cleanup are outside the elapsed interval on both sides. Separate `tracemalloc` probes record peak and retained-with-result allocations for the same public call. Those values describe tracked Python/NumPy allocations, not process RSS or most native Pillow storage.

All 84 historical public pairs, all eight workload comparisons and every warm, timed and separately traced output comparison passed. Each workload has six paired elapsed samples, with three AB and three BA orders. Positive elapsed changes below mean longer elapsed time after the change.

| Workload | Before median, ms | After median, ms | Elapsed change | After faster in paired samples |
|---|---:|---:|---:|---:|
| Paint Pixel, learned v4 | 114.413 | 119.536 | +4.478% | 2/6 |
| Paint Standard, accepted Fill | 54.755 | 53.244 | −2.760% | 4/6 |
| Gartic regional hybrid | 162.517 | 164.187 | +1.028% | 4/6 |
| Gartic hybrid with Fill candidates | 189.428 | 190.438 | +0.534% | 4/6 |
| Paint Dynamic, configured deadline | 53.014 | 51.237 | −3.353% | 5/6 |
| Gartic Auto Sketch, **Unlimited** | 26.727 | 25.758 | −3.627% | 5/6 |
| Paint Pixel, missing database | 117.134 | 118.792 | +1.416% | 3/6 |
| Unscoped correction reader | 0.158570 | 0.173401 | +9.353% | 3/6 |

The elapsed results are mixed. Pixel's learned-file median increases despite fewer reads; neither hybrid median decreases, although four of six individually paired hybrid runs are shorter. Those two summaries measure different things and both are reported. Pixel paired changes range from −32.7% to +19.8%; the missing-file control ranges from −24.1% to +22.3%. The unscoped reader's median difference is about 0.0148 ms, with three shorter and three longer pairs and unchanged work/peak counts. Six pairs with this variation do not establish a general elapsed-time advantage or isolate every small difference's cause. No samples were discarded and no further runs were selected to seek a positive result.

| Workload | Traced peak before, B | Traced peak after, B | Retained with result before, B | Retained with result after, B |
|---|---:|---:|---:|---:|
| Paint Pixel, learned v4 | 5,888,326 | 4,828,350 | 1,238,310 | 1,239,609 |
| Paint Standard, accepted Fill | 5,112,451 | 4,469,030 | 1,099,793 | 1,103,117 |
| Gartic regional hybrid | 5,980,062 | 4,984,602 | 1,412,363 | 1,410,325 |
| Gartic hybrid with Fill candidates | 6,000,117 | 4,984,696 | 1,429,809 | 1,428,049 |
| Paint Dynamic, configured deadline | 5,534,351 | 5,521,603 | 1,515,957 | 1,518,923 |
| Gartic Auto Sketch, **Unlimited** | 4,879,614 | 4,865,836 | 862,857 | 866,419 |
| Paint Pixel, missing database | 2,560,031 | 2,563,966 | 1,237,618 | 1,238,764 |
| Unscoped correction reader | 4,202,482 | 4,202,482 | 10,279 | 10,221 |

The instrumented learned-file Pixel, Fill and hybrid workloads have lower traced peaks. Dynamic and Unlimited Sketch peaks change by less than 0.3%; the cold control rises slightly and the unscoped peak is identical. Retained-with-result values are separate observations: Pixel, Fill, Dynamic, Sketch and the cold control retain roughly 1.1–3.6 KB more, while the hybrid cases retain roughly 1.8–2.0 KB less. These are single allocation probes for each side, not peak/RSS distributions or evidence of a process-wide memory reduction.

Sharing intentionally extends the primary parsed database's lifetime until the outer plan finishes. It removes repeated reads and validations, but introduces selected-row isolation and a bounded snapshot lifetime. The closed observation does not travel with the returned result; the retained-with-result figures measure the whole surviving plan/reader result and allocator-visible objects, not an escaped cache owner. The operation does not cache an already calculated ETA or avoid any context-specific correction. The demonstrated outcome is fewer actual database reads/validations and reduced traced peaks in several loaded-plan fixtures. There is no general planning, drawing, application-speed or RSS claim.

## Deduplication

This is one registered behavior group. P1901 covers hardware-profile/machine-signature observation inside preview scoring, not timing-model databases inside planning. U2001 removed a third UI-adoption geometry/cost pass; this change preserves all correction requests and never enters that UI-adoption path. R1403 prepared immutable path geometry/cursor costing, and R1802 reused identical initial brush-pack scoring within a component. Neither shared persisted timing data across the separate public planning, ETA and diagnostic consumers observed here. No second group is claimed for full-key variants, missing-data handling, ownership cleanup or the moved routing test.
