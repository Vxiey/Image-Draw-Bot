# 1.0.148 batch 12 — reuse source preparation across accuracy scores

Baseline: published batch11 commit
`b0eedca7d8d63fde5c9da6a1cffb394613ff95bf`, tree
`fa09dfb415b7d851ff33625f38bff68981bfcbf8` (777 recorded groups).

This ledger records **one distinct group, R1201**, with final frozen paired
measurements and the completed shared local gate below. Its caller handoff, source context,
CPU fallback, cancellation and evidence belong to one repeated-work reduction.

## R1201 — prepare an unchanged PixelMap's score inputs once per operation

The public Pixel Accurate path calls `refine_with_corrections`, then
`progressive_accuracy_checkpoints`, against the same source PixelMap. Each
score previously rebuilt the desired categorical target, selected source edge
values and computed their 70th percentile, rebuilt edge/protected masks, and
counted their source pixels. Correction-run extraction also rebuilt the same
desired target. These values depend on the unchanged source and background,
not on the changing simulated stroke raster.

A real Manual/CPU plan with a fixed 4-pixel brush, two colored rectangles,
thin line and isolated dots demonstrates the work. At both 160×112 and
640×448, there are six actual scoring calls: the initial score, two correction
attempts and three retained-phase checkpoints. The first correction is
accepted and the second is rejected. The original flow performs eight target
builds and six source-edge percentile calculations on the same PixelMap.

`PixelScoreContext` lazily prepares the categorical target, drawable view,
edge/protected masks and source-only counts. The unchanged scoring arithmetic
uses those inputs for every simulated result. Correction extraction reuses
the desired target while keeping its existing independent importance and
protected-feature semantics. There is no new lightweight checkpoint formula:
all six complete scores still run and return the same metrics.

Root's narrow `DrawBot.make_plan` handoff creates one local context after the
base sequence is chosen, passes it through refinement and checkpoints, and
deletes it immediately after checkpoints. It is never put on the PixelMap,
options, SimulationResult or returned plan. The final preview's floating-point
accuracy evaluation therefore does not retain this source workspace.

Public helper calls without an explicit context get a fresh one, so editing a
PixelMap between separate calls is observed. An explicit context belongs to
one unchanged PixelMap operation; another map is rejected. Changing its
background index replaces the desired target instead of reusing the old
background. Only one target variant is retained. Source arrays are borrowed
read-only where their existing dtype permits; caller arrays and writeability
flags are not changed.

Preparation is lazy. A successful CUDA score does not prepare CPU score
features. The existing CUDA/Auto/OpenCL request forwarding, GPU scoring and
fallback rules are unchanged. A failed GPU score can use the same local
source context for CPU fallback. Stop is checked on reuse and before/after
preparation stages; an interrupted feature build does not publish partial
cached features or convert cancellation into CPU fallback.

## Correctness and public-caller evidence

`test_v148_accuracy_batch12_context.py` contains six regressions. An independent
per-pixel oracle classifies missing, wrong, spilled and correct pixels and
computes every metric. It covers holes, numeric Boolean masks, immutable
source arrays and explicit/absent white backgrounds. Actual public planning
with fixed 2- and 4-pixel brushes compares complete sequences, groups, all UI
preview images, costs, maps, correction decisions and checkpoint rows against
that oracle. The 2-pixel fixture accepts its correction; the 4-pixel fixture
accepts the first and rejects the second.

Instrumentation in the real public call observes exactly one context, one
desired-target preparation and one feature preparation across at least five
scores. Weak references verify that the context is already gone when the
actual `AccuracyEvaluator.evaluate_preview` call begins. Additional cases
exercise a background-index change, a mutated PixelMap on later independent
calls, foreign contexts, Stop during feature construction, successful GPU
scoring without CPU preparation, GPU-score-to-CPU fallback, explicit CPU mode
and interruption propagation. GPU branch checks use controlled host-backed
fixtures and do not claim hardware performance validation.

The six new tests passed, as did an initial focused run of 35 existing pixel
accuracy, correction, simulation and CP02 regressions. Root independently
reviewed source and tests without a blocker and ran a 40-test selection with
five unrelated environment skips. Root's benchmark-method review is also
closed. C independently reviewed the complete reuse paths, local ownership,
caller release, GPU behavior and Stop, and ran all six new tests in 1.127
seconds with unchanged source hashes. That independent review is closed
without a blocker. The shared frozen whole-program gate passed as recorded below.

## Paired measurement contract

`benchmark_v148_rendering_batch12.py` compares the whole public `make_plan`
call, identical full-result fingerprinting and owned-image cleanup. The before
variant loads the entire published baseline `PixelAccuracyEngine` module for
the current caller's local import. Two adapters discard only the new
`score_context` keyword, and its context factory returns `None`. Thus the old
flow performs all its old work and is not charged for new context preparation
or retention. All other dependencies, including current caller and brush
policy, remain common to both sides.

Separate untimed instrumentation counts full scores, desired-target builds
and percentile calls scoped only inside accuracy scoring. It does not count
unrelated palette, shadow or preview percentiles. Both public fixtures have
already passed this complete baseline-module substitution with identical
output fingerprints:

| Actual public fixture | Paths | Full scores before → after | Target builds before → after | Source-edge percentiles before → after |
|---|---:|---:|---:|---:|
| 160×112, fixed 4 px | 368 | 6 → 6 | 8 → 1 | 6 → 1 |
| 640×448, fixed 4 px | 1,284 | 6 → 6 | 8 → 1 | 6 → 1 |

The final measurement ran after the global source freeze: one warm
pair, five interleaved timing pairs in fixed before-then-after order, and
separate Python/NumPy traced peaks after garbage collection. Every
instrumented, warm, timed and traced result is checked against the initial
reference, including complete source/fitted geometry, colors, all groups and
sequence entries, UI previews, counts, path statistics, estimate, every Pixel
Accuracy metric/correction/checkpoint field and operation cost metadata.
Only volatile profiler durations are excluded.

The script fingerprints 27 relevant source files before and after the run.
All 27 were unchanged during the final run and were checked against the files
again afterwards. Medians were independently recomputed from the five raw
samples. Tracemalloc describes traced allocation, not process RSS or most
native Pillow pixel storage. GPU and actual target drawing speed are outside
this CPU planning measurement.

### Final frozen results

Raw samples, full preparation counts and source hashes:
`docs/v148-batch12-rendering-benchmarks.json`.

| Whole public planning fixture | Before median | After median | Observed median change | Before traced peak | After traced peak |
|---|---:|---:|---:|---:|---:|
| 160×112, fixed 4 px | 156.041 ms | 153.227 ms | −1.80% | 4,762,599 B | 4,762,478 B |
| 640×448, fixed 4 px | 876.438 ms | 867.347 ms | −1.04% | 40,132,011 B | 40,130,565 B |

The unchanged complete outputs include 368/1,284 paths, accepted first and
rejected second corrections, every score/map/checkpoint and all public preview
pixels. Each workload still computes six full scores. The directly observed
work reduction is eight→one target preparations and six→one source-edge
percentile calculations on one unchanged PixelMap.

The whole-call medians differ only modestly, and the sample ranges overlap:
146.703–159.744 ms before versus 147.714–171.365 ms after for the smaller
fixture, and 858.221–958.123 ms versus 859.391–894.118 ms for the larger one.
These five pairs do not establish a general or statistically reliable
end-to-end speedup. Traced peak differences of 121 and 1,446 bytes are
effectively unchanged at this scale; there is no claimed full-planner peak
memory reduction. The evidence supports removing repeated source preparation
while preserving the complete existing behavior.

Selected final SHA-256 fingerprints:

| Source | SHA-256 |
|---|---|
| `PixelAccuracyEngine.py` | `750bfbb2b278fa8dbebb072818b9aa1990f5015770be0ff2fd500a8f56c4f83d` |
| `DrawBot.py` | `d5ec2b423148f728e062e79509eb8743c10e300ac9fe16761bd5fb0186f4ece4` |
| `benchmark_v148_rendering_batch12.py` | `e1d5cdba750828459dc87e60e2ec909b5239aceb822f4c56943216f60d92afda` |

These are the final post-freeze samples. The earlier adapter check did not
record timing numbers or produce a competing raw artifact.

## Deduplication

RP14 reduced per-component full-canvas work inside regional accuracy scoring.
CP06 bounded floating-point/OKLab scratch and image lifetime inside the
different `AccuracyEvaluator`. CP02/RP18 corrected background and absent
feature-category semantics. Those contracts are preserved and not recounted.
R1201 removes repeated source preparation across pre-existing categorical
scoring calls in the active Pixel Accurate flow. It does not reduce R1101's
new alternative-pack search and does not claim another group for each helper,
fallback, field, test or documentation change.

## Frozen checkpoint validation

Batch 12: final frozen-source discovery passed 3,626 tests in 150.380 seconds (45 platform/hardware skips), with unchanged Python and batch-script hashes. Independent source reviews are closed for both new behavior groups and the uncounted physical-brush completion. The 5,000-cycle source gate, source-package hygiene and eight exact-raster fixtures passed. Paired full public-planner measurements bind the final source and retain identical results while reducing repeated score preparation. Timing and traced allocations are reported separately; these are not native drawing or GPU benchmarks. This checkpoint still requires its own Windows/Linux, dependency, CodeQL and packaged Windows checks. No 1.0.148 release is published.
