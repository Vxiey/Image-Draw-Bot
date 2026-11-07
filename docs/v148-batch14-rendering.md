# 1.0.148 batch 14 — lossless paths, translucent fallback and cursor costing

Baseline: `f7b561f479d94f307924dbc779e5c8e365422f8d` (781 recorded groups).

This ledger describes **three distinct behavior groups, R1401–R1403**. Their
caller changes, fallback handling, cancellation, tests and measurement evidence
belong to those groups; they are not additional improvements. The global
register and release state are maintained separately.

## R1401 — index overlapping runs during lossless Pixel path attachment

`PixelStrokeEngine._merge_horizontal_runs_lossless` tested every incoming run
against every still-active path from the preceding row. A comb or fence image
contains many separated runs in each row, so most comparisons could never
produce an attachment. This happened inside the actual Pixel component
candidate builder and the regional planner's reused lossless candidate path.

The existing active list already follows the preceding row's sorted run order.
Build an operation-local list of starts and prefix-maximum ends, then bisect the
range which could overlap each incoming interval. Prefix maxima preserve
nested and overlapping input intervals as well as ordinary disjoint raster
runs. Keep each original active-list index, the complete overlap/distance/index
tie key, point/row caps, path order and attachment geometry. Snapshot interval
values before attachments mutate selected active paths. Check Stop during
index preparation, long candidate windows and incoming-run traversal.

On the recorded 4,500-run fixture (25 rows, 180 separated two-pixel runs per
row), the original function performs 412,560 `max` operations in its overlap
and attachment arithmetic. The regression imposes a linear-work ceiling while
an independent integer raster verifies the same painted pixels. Literal
baseline path lists cover nested intervals, attachment ties, reversed runs,
row gaps, vertical passthrough and restrictive caps. Stop during a busy row
leaves the caller's runs unchanged.

The benchmark compares the complete historical function with the current one
on 900 seeded cap/row-limit cases, including their exact ordered paths and
independent source/painted pixel sets. Actual public `make_plan` comb fixtures
also compare every stable returned field and independently paint the complete
sequence with Pillow at the native one-pixel grid.

PL08 changed `ContinuousPaths`' active-path scans; PL17 changed component
union/detection across rows. R1301 changed repeated boundary distances inside
2-opt. R1401 targets the different lossless Pixel attachment search and
preserves all three earlier contracts.

## R1402 — preserve fractional alpha through emergency palette matching

The normal CPU/CUDA/OpenCL palette route scores an unrounded float32
source-over-white RGB composite. Pixel Accurate's last-resort CPU matcher
instead received the rounded byte RGB retained for image and feature analysis.
Losing the fractional channel values could cross both a palette midpoint and
the strict Skip-white threshold of 245 when only the backend changed.

With seed 1481402, a 100×100 RGBA image and the calibrated application palette,
the baseline has **34 active palette-choice differences and 27 drawable-mask
differences** between the ordinary CPU route and forced last-resort fallback.
RGBA `(210,145,222,152)` selects white normally but pink in the old fallback.
RGBA `(202,187,174,33)` remains drawable normally but disappears from the old
fallback after its minimum channel rounds upward to 245.

The fallback now composites original RGBA channels with the same float32
arithmetic, inside the existing bounded pixel/palette tiles. It does not retain
a second full-image float RGB buffer. Its drawable mask compares exact uint16
source-over-white numerators against `245*255`; all products and sums fit
within 65,025. The normal routed backend is unchanged. The byte RGB used for
PixelMap images, edges and feature analysis is unchanged. Failure diagnostics
remain present, and `InterruptedError` cannot become ordinary CPU fallback.

The same 10,000-pixel fixture now has **zero palette-choice differences and zero
drawable-mask differences**. Five regressions cover an independent integer RGB
distance/threshold oracle, seeded translucent images in RGB-nearest and
perceptual Balanced/Faithful modes, indexed-palette transparency, a 30,000×1
panorama, Stop and the real public `make_plan` path. The public fixture retains
all 130 intended drawable pixels, identical groups, executable sequence,
palette, estimate, main preview and every UI preview after backend failure.
The independent-oracle and public-plan tests both fail on the complete
historical baseline module.

The panorama test observes multiple matching tiles, each no larger than the
existing `262144 / palette_count` pixel allowance. This correction is not a
claim of GPU execution or GPU performance: the routed backend failure is
controlled, and CPU/fallback equality is measured directly. No timing speedup
is claimed for the corrected matching arithmetic.

CG04 concerned fully transparent pixels; CP01 concerned hue-family penalties
for nearly neutral colors. Neither addressed fractional alpha rounding at the
emergency matching and white-skipping boundary.

## R1403 — prepare immutable path costs for repeated cursor comparisons

Pixel component scheduling already cached each component's intrinsic path
cost. However, each candidate comparison still called `path_seconds` twice on
its first path: once with the current cursor and once without. Those calls
recomputed integer coordinates, scaled length, rounded screen positions,
precision-limited move counts and learned operation classification. Only the
cursor-to-start distance had changed. The same first path could be examined
within the bounded 72-candidate window at many consecutive scheduling steps.

`ExecutionCostModel.prepare_path_cost` produces an immutable operation-local
snapshot of one path's cost and the model's scalar pricing terms. The snapshot
retains neither the mutable source path nor the model/options object. Ordinary
`path_cost` behavior stays intact. Repricing computes the same bounded cursor
travel and preserves the exact original `(travel_base + distance + body) *
multiplier` addition order; it does not add a delta to an already rounded total.
All detailed cost fields, learned/default branches, native precision, movement
counts and travel ceiling remain equal.

The Pixel scheduler prepares one first-path snapshot per component and reuses
it only inside that scheduling operation. External compatible cost models
without the new API continue through their original `path_seconds` interface.
Preparation and final ordered sequence costing receive Stop; a final costing
interruption is propagated rather than replaced by an apparently successful
diagnostic fallback. The source path geometry, phase order, color transitions,
candidate priorities and final sequence pricing are unchanged.

On a 180-component, four-phase fixture, complete path-cost evaluations fall
from **8,840 to 540**, with identical complete scheduler outputs. Five new
regressions compare all cost fields exactly across 945 path/cursor/scale/
precision/calibration combinations, verify snapshot ownership and fresh-call
behavior, count actual full path-cost calls, inject Stop and compare a real
public Pixel plan's sequences, costs and preview pixels. The benchmark adds
42 complete baseline scheduler comparisons across component counts, scales
and learned/default calibration, for 942 helper/scheduler parity cases overall.

RP29 prepared deadline renderer policy; R1301 reused 2-opt boundary distances.
R1403 removes repeated first-path geometry preparation from Pixel component
candidate pricing. It does not change the execution cost model version or
claim another group for each cost field or caller.

## Uncounted completion — R901/R1004 Subject-only physical footprints

A fixed four-pixel brush on a 64×64 source with a centered 32×32 selected
subject and an 81×64 canvas exposed a remaining coordinate mismatch. The
8.5-pixel horizontal letterbox moved native brush centers relative to the
source-only erosion mask. Actual `make_plan` → `execute_plan` replay painted
32 pixels outside the subject and missed 32 intended pixels, while the old
accuracy metadata reported zero spill, zero missing pixels and 100% coverage.
The error reproduced at positive and negative desktop origins. The analogous
integer letterbox worked, which explains why the earlier R901 regression did
not expose the unfinished R1004 physical-coordinate contract.

Subject clipping now uses the existing `NativeBrushProjection` when source
and canvas grids differ. It erodes the bounded physical subject ROI by the
actual verified brush width and keeps only reachable safe centers and safe
connectors. The execution sequence remains in its original source coordinates;
execution applies `CanvasTransform` once. A long diagonal is retained only
after its actual native connector also passes the proof: independently rounded
source samples can otherwise form a safe stepped path whose long chord spills.
Empty entries do not change the brush. Retained paths materialize the inherited
physical width so omitting a previous path cannot erase an intended tool change.

A private native ROI PixelMap and transformed sequence supply the existing
Pixel Accuracy evaluator and progressive checkpoints, with corrections still
disabled for Subject-only. They are not retained in the finished plan. Scores
describe physical pixels before CanvasGuard/runtime delivery. Coverage and
error views retain their full physical-canvas extent, capped to the existing
1600-pixel diagnostic size. The target mask remains unchanged; a subject too
narrow for the available brush remains visibly missing instead of receiving an
invented thinner brush. The new main preview samples exact square footprints
from the already guarded native sequence, preserving its skipped paths, order,
widths and fractional fitted crop.

The reproduced half-pixel case now has zero actual spill, zero actual missing
pixels, accurate reported counts and pixel-identical Coverage and main preview
images. Native mouse-action replay covers three signed origins, horizontal and
vertical letterboxing, an unreachable narrow selection and the coincident
source/canvas grid. Independent mask and raster checks cover readonly holes,
scaled diagonals, empty entries, inherited widths and guard skips. Interrupted
diagnostic publication closes every privately owned image; the application
handoff also closes returned diagnostics if later finalization fails.

This completes the existing R901/R1004 behavior and adds **zero** new IDs.
CanvasGuard, correction limits, quality settings, available tool widths and
native input authorization are unchanged.

## Final validation and measurements

The three new regression modules contain 14 tests. Focused checks currently
include 32 lossless-path/geometry tests, 40 palette/fallback/resource tests
(one hardware/environment skip), and 45 prepared-cost/Pixel/cost-model tests.
The initial complete parity and independent public raster checks passed, and
independent source review of R1401–R1403 and the Subject native completion found
no remaining blockers. All 39 focused Subject/physical/canvas/Pixel-context and
handoff-ownership checks passed, including the final coincident-grid preview
regression. The shared final whole-program gate ran **3,768 tests in 98.292 s,
with 46 environment/hardware skips and no failures**. Its 806 Python, batch,
workflow and requirements files remained unchanged; the source manifest SHA256
was `c93ef1bebfdfa6b4830eea69be348be789f0a627b77372c7b97ab88bba4ab14c`.

`benchmark_v148_rendering_batch14.py` substitutes exactly one historical
function at a time, while keeping the current caller and all other
dependencies shared. It compares R1401 and R1403 separately, uses six balanced
AB/BA pairs after one warm pair, checks complete outputs on every warm,
instrumented, timed and traced call, and measures traced allocation separately
after garbage collection. All root product Python modules and measurement
helpers are fingerprinted before and after the run.

Public measurements include the complete `make_plan` call, identical result
fingerprinting and owned-image cleanup. Only explicit profiler durations and
`options.pixel_stroke_meta.planning_stage_seconds` are excluded from result
parity. Tracemalloc measures Python/NumPy allocation, not process RSS or most
native Pillow pixel storage. These CPU planning fixtures cannot establish
native drawing, interactive UI or hardware GPU speedups.

The final run followed that successful whole-program gate, while all other
agents held product/test files stable and no other test or benchmark job ran.
It used Python 3.12.14, NumPy 2.3.5 and Pillow 13.0.0 on Linux x86_64. All
**942 complete helper/scheduler parity cases** and all four independently
rasterized public-plan fixtures passed. Every warm, instrumented, timed and
traced output remained equal. All **251 measured product/helper source hashes**
were identical before and after the run.

Final elapsed medians, with six observations per side in alternating AB/BA
order:

| Isolated change and workload | Before (ms) | After (ms) | Elapsed reduction |
| --- | ---: | ---: | ---: |
| R1401, 4,500 horizontal runs | 105.879 | 23.237 | 78.1% |
| R1403, 180-component scheduler | 357.892 | 38.945 | 89.1% |
| R1401, complete `make_plan`, 320×112 comb | 399.995 | 303.368 | 24.2% |
| R1401, complete `make_plan`, 480×160 comb | 1,053.320 | 680.411 | 35.4% |
| R1403, complete `make_plan`, 96×72 tiles | 95.901 | 72.734 | 24.2% |
| R1403, complete `make_plan`, 192×144 tiles | 728.273 | 245.377 | 66.3% |

The isolated work counters also agree with the regression evidence:
R1401 overlap/attachment `max` calls fall from **412,560 to 30,216**;
R1403 full `path_cost` calls fall from **8,840 to 540**. The public R1403
fixtures reduce those same full evaluations from **1,080 to 240** and
**16,337 to 1,144**, respectively. These are distinct workloads, not additive
percentages or a promise for other images.

Separate traced allocation peaks, in bytes:

| Workload | Before | After |
| --- | ---: | ---: |
| R1401, 4,500 horizontal runs | 1,608,136 | 1,608,136 |
| R1403, 180-component scheduler | 1,261,191 | 1,026,623 |
| R1401, complete `make_plan`, 320×112 comb | 6,179,088 | 6,179,250 |
| R1401, complete `make_plan`, 480×160 comb | 12,859,778 | 12,859,476 |
| R1403, complete `make_plan`, 96×72 tiles | 3,932,209 | 3,932,209 |
| R1403, complete `make_plan`, 192×144 tiles | 5,373,208 | 5,286,580 |

R1401 is a search-work reduction with effectively unchanged allocation peaks.
R1403 reduces the isolated scheduler's traced peak, but the full plan also owns
image/feature/preview buffers, so the same proportional saving does not apply
to whole-plan memory. Timing and traced allocation are measured separately;
no speedup is inferred from the allocation table.

The complete final samples, output digests, parameters, exclusions, historical
function hashes and current source hashes are in
[`v148-batch14-rendering-benchmarks.json`](v148-batch14-rendering-benchmarks.json).
That final artifact has SHA256
`bc196c430321afd7b60943574a3e182b54494b301e9447ee100485dff6b03c5c`.
It supersedes the earlier intermediate measurement snapshot and its initially
incomplete shared-helper arithmetic counter. R1402 remains a correctness fix
with direct palette/white-mask parity evidence, without a timing claim.
