# v1.0.148 batch20 — adopt the prepared preview estimate

Baseline: `47777158e5b1daf759993190e638fe507e7691da` (818 published
improvements). **U2001 is one behavior group.** Tests, comparison tooling,
source-snapshot cleanup and existing automatic-preview completions add no IDs.

## Observed repeated work in the actual controller

The real `update_plan` worker already calculates draw-time metadata in
`finish_plan`, then refreshes it after setting the final preview/target areas.
The `planned` event consumer unconditionally calculated it a third time on the
Tk thread before displaying the result. For an execution sequence, that means
another full `ExecutionCostModel.sequence_cost` traversal and per-path costing,
plus reading the local timing/throughput information again.

The before test drives the real worker, public `make_plan`, event queue,
`planned`/`done`, `poll` and Tcl-bound visible labels. Its initial High likeness
fixture had no final execution sequence and therefore did not demonstrate the
claimed path work; it was corrected to the actual Pixel Accurate route before
the accepted baseline and before any ETA product edit. The valid baseline ran
two test methods in 1.752 seconds: the legacy geometry-change control passed,
and all three real worker/adoption subcases failed the no-repeat assertion.
They performed **98, 191 and 115 additional `path_cost` calls on the UI thread**
for native, projected and explicit full-detail previews respectively. Each
displayed estimate already exactly matched its worker's prepared estimate.

## One-use transfer from the owning worker

The worker sets all final preview flags and geometry before its final estimate
attachment. On success it transfers a private reference to that exact metadata
object with the owned result. After the existing Stop, generation and
publication-ownership checks, the UI consumes this reference once. It reuses
the metadata only when it is the same dictionary currently attached to the
plan. No image, geometry, settings or persistent/global estimate cache is
introduced.

Legacy/manual producers without that transfer, replaced metadata and a failed
worker preparation retain the original fresh-calculation fallback. A later
adoption of a changed plan recalculates because the transfer was consumed.
Each new planning operation still reads current calibration. An external
calibration update between worker completion and event adoption does not
silently change the completed result; the next real preview uses the new
samples. Stopped/stale results are released before estimate reuse or fallback.

**Two worker estimates remain.** This group removes the third pass on the UI
thread; it does not claim to combine planner/final-projection calculations or
change execution cost arithmetic, learned timing, calibration, geometry,
palette choices, drawing speed, input authorization or diagnostics.

## Correctness and historical comparison

`test_v148_ui_batch20_preview_estimate.py` has seven methods covering the three
real preview variants, a changed legacy target, one-use consumption, replaced
metadata, failed final preparation, Stop/stale result disposal and a real
temporary calibration database updated between two previews. The focused
gate passed **7 methods in 2.897 seconds**. The shared fixture keeps its Tcl
owners on their creator thread until actual workers finish and uses the
normal planner/estimator functions. Screen-window allocation, the recurring
Tk scheduler and rendering widgets are the UI boundaries.

An independent source review of the handoff and fallback contracts found no
blocker. The independent combined BA01/ETA run passed **23 methods in 5.066
seconds**. Native Windows execution remains a separate published-commit gate.

`benchmark_v148_ui_batch20_estimate.py` loads the complete historical
`DrawBot.py` and compares real controller operations with current shared
dependencies. It compares the complete returned plan, source pixels, estimate
metadata and displayed labels, excluding only named planning-clock/profile
fields and their corresponding visible clock text. The available-RAM OS
probe is fixed at 8,192 MB on both sides; scheduling decisions remain real.
The first comparison exposed changing OS RAM values, so that fixture boundary
was controlled rather than excluding resource decisions from parity.

Six verified workloads include three prepared-result adoptions, an unprepared
legacy control, and two complete worker-to-adoption pipelines. In the dense
320×240 fixture, adoption costed **6,583 paths before and zero after**. The
preliminary untraced complete pipeline retained both worker estimates and
their **13,166 path-cost calls**. The final complete-pipeline workload uses
the source's native 96×72 size for the instrumentation reason described below.
It retains **2,386 worker path-cost calls** on both sides and removes **1,193
UI path-cost calls**. The legacy control continues to cost **115
paths** on both sides.
All complete plan/label comparisons passed in the verification run. One
unrelated reset-test file changed during that preliminary read-only run;
final timing evidence requires all captured source hashes to stay unchanged.

## Measurement boundary

The final measurement uses six balanced AB/BA pairs per workload, no work
observers inside timed samples, separate tracemalloc probes and an unchanged
source manifest. Source creation, fixture setup and output hashing are outside
the timers. Whole-pipeline numbers include the accompanying zero-count private
snapshot cleanup. Tcl/controller adoption is measured; native widget painting,
mouse drawing, Windows/CUDA performance and most native Pillow allocation are
outside this measurement. Final values and raw artifact hash are recorded
after the common frozen-source gate.

A dense 320×240 allocation-tracing preflight exceeded the reused test fixture's
ten-second worker wait. The benchmark now explicitly allows a bounded
60-second wait on both sides; ordinary preview regressions retain ten seconds.
With that longer diagnostic wait, the unchanged fourteen-second product
preview watchdog selected a fallback plan, completed after 19.9 seconds, and
correctly failed the existing sequence-model assertion. No result from either
rejected preflight is a final timing or allocation datapoint. The product guard,
clock and result assertions are preserved. The dense complete-pipeline workload
is explicitly the source's native 96×72 size for both timing and tracing, while
the separate 320×240 adoption workload remains. This keeps allocation and
elapsed comparisons on the same real execution path. An intermediate 192×144
probe also reached the actual fallback and was rejected. The final source-sized
preflight produced the same complete output with and without tracing and across
both revisions. The actual fallback evidence is retained in
`batch20-eta-dense-trace-fallback.json`; the source-sized parity/work proof and
rejected 192×144 observation are in `batch20-eta-dense-trace-preflight.json` in
the scratch diagnostics.

## Deduplication

U1601 clears feedback when the accepted plan is invalidated; it does not remove
repeated costing while accepting a valid plan. U903's progress bookkeeping,
R1403's candidate delivery-cost reuse and P1501's checkpoint catalog concern
different operations. BA01 source-event handoff and source-image cleanup are
existing-contract completions documented separately, with zero new IDs.

## Final frozen-source measurements

The final report compares `47777158e5b1daf759993190e638fe507e7691da` with the final batch20 source using six balanced AB/BA pairs per workload. All complete timed and separately traced outputs match. All **819 root Python files** remained unchanged. Values below are observed medians, with the allocation probe measured separately from elapsed time. A negative time change means less elapsed time in this fixture.

| Workload | Before median, ms | After median, ms | Time change | Traced peak before → after, KiB |
| --- | ---: | ---: | ---: | ---: |
| `adopt-dense-320x240` | 114.033 | 0.652 | -99.4% | 489.9 → 61.5 |
| `adopt-legacy-84x64-control` | 2.593 | 2.767 | +6.7% | 63.8 → 86.5 |
| `adopt-native-84x64` | 2.913 | 0.567 | -80.5% | 63.0 → 61.6 |
| `adopt-projected-1100x600` | 24.925 | 0.637 | -97.4% | 86.6 → 61.5 |
| `pipeline-dense-source-96x72` | 649.523 | 635.476 | -2.2% | 5651.6 → 5664.6 |
| `pipeline-native-84x64` | 112.706 | 106.434 | -5.6% | 3829.0 → 3842.0 |

These observations retain the measurement boundaries described above. They do not establish native drawing speed, physical GPU performance, process RSS, or a universal application speedup. Python/NumPy tracing excludes most native Pillow image storage.

Raw result: [v148-batch20-ui-estimate-benchmarks.json](v148-batch20-ui-estimate-benchmarks.json); SHA-256 `610b6bdd9c96752dd2da59790d0b8da2ed2b843a1348536a48130185fc38dbe5`. Canonical compact source-manifest SHA-256: `32d88cc73bf427735e361550fcaaa2942063a62de5ae8fefee3baf79dfb122f5`.

### Interpretation

The dense 320×240 **UI-adoption operation** fell from an observed median of
114.033 ms to 0.652 ms while removing all 6,583 repeated UI path-cost calls.
The small and projected prepared-result controls also avoid their repeated
UI scans. These values concern queued controller/Tcl-label adoption after a
worker has finished; they are not total preview or native window-painting times.

The complete 96×72 dense pipeline retained both worker estimates and their
2,386 path-cost calls. Its observed median changed from 649.523 to 635.476 ms,
while the complete small native pipeline changed from 112.706 to 106.434 ms.
Those end-to-end fixture measurements remain separate from the much larger
adoption-only reduction. All three prepared adoption cases and the small native
pipeline were faster in all six pairs. The dense complete pipeline had three
faster and three slower pairs, so its lower median is not a consistent pipeline
speedup claim. Independent review of all raw samples closed without a blocker.
The legacy control still scans 115 paths on both sides;
its observed median increased from 2.593 to 2.767 ms, and its traced peak also
increased. It has no claimed work-removal benefit. Raw samples and all allocation
values remain visible in the report rather than only favorable observations.
