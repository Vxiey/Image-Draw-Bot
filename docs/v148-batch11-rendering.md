# 1.0.148 batch 11 — compare complete exact brush packs

Baseline: published batch10 commit
`a8fabbc811029a8bfcbe8a5af2a848b034e5cd89`, tree
`d8941d4c99747e38bb39dea13667e4f6f6b19fd2` (773 recorded groups).

This ledger proposes **one distinct behavior group, R1101**. The local policy,
complete-pack comparison, bounded winner retention, diagnostics and regression
evidence form one selection change. They are not separate improvements.

## R1101 — choose by the cost of the completed exact packing

The regional brush planner's original local policy admits layouts covering at
least 90% of the best available gain, then compares their cost per newly covered
pixel. That is a useful greedy rule, but the cheapest first layout can leave
residual strips requiring many narrower cleanup paths. A completed pack can
then cost more than another available layout which covered the whole region
with its first width.

The actual public planner demonstrates this with a 200×150 white source,
a blue rectangle at `(48,40)..(143,103)`, a 400×300 canvas, and verified physical
brush controls for 2, 4, 8 and 16 pixels. The original policy emits 47 paths at
a modeled component cost of 10.576774 seconds. A maximum-gain alternative
needs 12 paths, all with the already verified 16-pixel control, at 8.546753
seconds. Replaying the real `execute_plan` loop's recorded native actions
covers the same 24,576 physical target pixels with no missing or spilled pixels.

Replacing the local rule globally would be incorrect. A separate 128×96
source/canvas with a 111×79 region at `(8,8)..(118,86)` costs 4.851547 seconds
and 32 paths under the original policy. Forcing maximum gain costs 7.333243
seconds and 54 paths, despite identical native coverage. The new selector
therefore compares completed results and retains the original 32-path geometry.

For each existing verified brush ladder, evaluate the original gain-per-cost
policy and one maximum-gain alternative. Every alternative still passes the
same safe native footprint, zero-spill and complete-coverage gates. Price the
complete entry sequence with the existing execution cost model, including
narrow cleanup paths and actual brush/phase transitions. Select the lower
cost; exact cost ties prefer the original policy before considering path
count. The original policy's own ladder tie order remains deterministic.

There are at most two policies across the existing maximum of six ladders.
Only the best finished candidate is retained while the next candidate is
built. The local helper still retains scalar alternative scores and rebuilds
its chosen raster once, preserving R1002's allocation contract. Candidate
statistics identify the chosen policy and each policy's best completed cost.
Stop is checked through the existing geometry loops, between ladders/policies
and before publication; a stop while computing the second policy does not
publish the already completed first-policy candidate.

This remains a bounded search over available layouts and verified controls,
not a claim of global optimality over every possible drawing. Cost figures
above are modeled component execution costs under the fixture's calibration,
not measured target-application wall time. Planning does more candidate work;
the measured planning-time and allocation tradeoff is recorded below.

## Regression and ownership evidence

`test_v148_rendering_batch11_pack_choice.py` contains six tests. Both public
fixtures run the actual planner and executor against original-only,
maximum-only and automatically selected policies. An independent physical
rectangle raster matches every recorded native stroke, public main preview
and Coverage output. Width changes occur through the existing verified
controls; CanvasGuard skips zero paths. The winning cost is independently
recomputed for the retained sequence using the existing cost model.

An exact-cost tie fixture makes completed alternatives equal while preserving
their different real local geometries. It checks that the original survives
even when the maximum-gain alternative has fewer paths. Other tests inject
Stop in the second policy, compare both local policies with the literal
footprint/Pillow oracle on holes and partial residuals, and check the
historical benchmark's early compatibility error.

The earlier R1002 oracle accepts the new explicit policy keyword while keeping
its unchanged default 90%-gain test, complete tie key, geometry/mask/cost
comparison, bounded live-plane test, Stop test and actual-planner oracle.
This is an uncounted compatibility completion of its evidence.

Focused validation: the six new tests passed in 2.477 seconds. A combined run
of the new tests, R1002–R1004, existing rc6 brush packing, rc23 ROI and rc25
budget/Extra Fast cases passed **43 tests in 6.323 seconds**. Root independently
reviewed the complete product/test delta and ran the six new tests plus the
seven R1002/R1003 tests: **13 passed in 3.030 seconds**. The product/test review
is closed without a blocker. Root also approved the benchmark's historical
function isolation, per-call parity reference and explicit fixed pair order.
The shared frozen whole-program gate remains pending. Final measurements were
completed after the global source freeze, with their exact fingerprints below.

## Measurement isolation and historical reproduction

`benchmark_v148_rendering_batch11.py` loads only the original
`_brush_pack_candidate` function from the published baseline into a copy of
the current module globals. Its calls use the current helper's unchanged
default local policy. Both variants therefore share the current coordinate
transform, physical projection, cost model and complete public planning flow.
The comparison isolates complete-pack policy selection and retention.

The two workloads are the real winning case and the case which preserves the
original geometry above. Each measured call compares complete source/main/
Coverage pixels, colors and fitted geometry. Paths, counts, choice diagnostics
and costs intentionally differ when the alternative wins. Separate untimed
actual-executor replays verify identical native pixels on both sides. The
final measurement uses one warm/parity pair, five interleaved timing pairs
in fixed before-then-after order, and separately traced Python/NumPy allocation
peaks after garbage collection. A local reference compares every timed and
traced call's visible output with the first warm result; parity is not inferred
only from the initial pair.
It reports complete planning-call overhead, not native drawing speed, process
RSS or most Pillow pixel-core allocation.

The final frozen run confirmed visible-output parity for every measured call
and separate native-action raster parity: 47→12 paths for the win, 32→32 for
the counterexample. All 30 recorded source hashes were unchanged during the
run and were checked again against the files afterwards. The medians below
were also recomputed from the five samples in the raw artifact.

### Final frozen measurements

Raw evidence: `docs/v148-batch11-rendering-benchmarks.json`.

| Public planning workload | Before median | After median | Planning-time change | Before traced peak | After traced peak |
|---|---:|---:|---:|---:|---:|
| 200×150 source, 400×300 canvas, cheaper completed alternative | 268.356 ms | 319.191 ms | +18.94% | 10,739,882 B | 10,654,211 B |
| 128×96 source/canvas, original pack remains cheaper | 158.485 ms | 257.280 ms | +62.34% | 1,847,186 B | 1,909,589 B |

| Retained execution | Before paths | After paths | Before modeled component cost | After modeled component cost | Equal native painted pixels |
|---|---:|---:|---:|---:|---:|
| Cheaper completed alternative | 47 | 12 | 10.576774 s | 8.546753 s | 24,576 |
| Original pack remains cheaper | 32 | 32 | 4.851547 s | 4.851547 s | 8,769 |

The extra alternative search increases planning time in both fixtures. The
winning fixture takes 50.836 ms more planning time and chooses a component
whose modeled execution cost is 2.030021 s lower. The counterexample takes
98.795 ms more planning time and correctly preserves the original executable
geometry and cost. These are different measurements: the modeled cost
reduction is not an observed end-to-end drawing speedup. The traced peak is
85,671 bytes lower in the first workload and 62,403 bytes higher in the second;
there is no general full-planner memory reduction or process-RSS claim.

Selected final SHA-256 fingerprints (all 30 are in the raw JSON):

| Source | SHA-256 |
|---|---|
| `AdaptiveRegionHybrid.py` | `45f998d8c58750e65c801a582a7f4faea19fc3c8a6407b43d0d558309d06976e` |
| `DrawBot.py` | `9ea748520ad5bdcfa77d676f58f0c043a802b568b5ed391dfc96b3858910a340` |
| `benchmark_v148_rendering_batch11.py` | `5b9e4452f1b7fcf32a294bdb7a6ac7c87620cf6f0f02ac4b2e91177347f733f8` |

These are final post-freeze samples, not a relabeling of an earlier run.

The historical `benchmark_v148_rendering_batch10.py` substitutes a helper
which predates `maximize_gain`. Its original complete-planner workload cannot
represent the new caller contract. It now fails explicitly before loading
historical functions, timing anything or writing results, and directs users
to the frozen `a8fabbc8` checkpoint for batch10 reproduction. The old JSON
samples, source hashes and reported measurements remain unchanged. This
compatibility safeguard and the new benchmark add no improvement count.

## Uncounted R1004 diagnostic completion

The original R1003 high brush-switch-cost fixture deliberately chooses a
connected 2-pixel fallback at unit scale. Its existing simulated quality
correctly reports 81 spilled pixels, but the region choice still claimed an
exact footprint because the conservative flag previously applied only when a
scaled/letterboxed projection existed. Treat a thick unproven fallback the
same way at unit scale. Its chosen method, paths, cost and quality remain
unchanged; the `exact` flag and explanatory reason now distinguish that
centerline proof from a complete physical-footprint proof. A validated exact
brush pack retains `exact=True`. The existing actual-planner fixture now also
checks the 81-pixel independent footprint and consistent diagnostic status.
Root independently reread this narrow delta and ran all three existing R1003
tests, which passed in 0.385 seconds. This completes R1004's reporting contract
and adds no group.

## Deduplication

R1002 reduced the lifetime of completed local alternative rasters; R1003
admitted a previously rejected exact candidate using one verified size;
R1004 corrected the physical coordinate system and complete-footprint proof.
R1101 changes the selection among already valid complete exact plans when a
local greedy score hides expensive cleanup. RP28's correct sequence pricing
is reused, not recounted. N1101's coordinate rounding and A1101's automatic
rescue ownership are independently owned batch11 changes; neither is part of
this group or of its historical-function substitution.

## Frozen checkpoint validation

Batch 11: final frozen-source discovery passed 3,602 tests in 128.751 seconds (43 platform/hardware skips), with unchanged Python and batch-script hashes. Independent source reviews are closed for all four behavior groups. The 5,000-cycle source gate, source-package hygiene and eight exact-raster fixtures passed. Paired pack-selection measurements bind the final source and disclose planning overhead separately from modeled drawing cost. This checkpoint still requires its own Windows/Linux, dependency, CodeQL and packaged Windows checks. No 1.0.148 release is published.
