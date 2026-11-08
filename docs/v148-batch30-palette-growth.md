# Batch 30: reuse nearest-color assignments while the picture palette grows

## Scope and count decision

The published baseline is `4b90b715a9128a022774f411e14e8a1b45676339`, with
840 registered improvements. **R3002 is registered as global 842 after reviewed integrated gates.** The only product file changed for
this group is `PicturePaletteRefinement.py`. Tests, fallback controls, private
fixtures and benchmark maintenance do not add further IDs.

This is distinct from CG34's repeated CIEDE2000 palette-pair comparisons,
CG40's expansion of weighted percentile inputs, CQ13's unused stroke/edge
preparation, AW01's bounded sample reads, C1901's region statistics and C2001's
shared visible RGB/alpha analysis. CG32's medoid representative choice also
remains unchanged. Two independent source/count reviews support one group
for the previously repeated nearest-center work during append-only growth.

## Demonstrated repeated work

The original public `build_picture_palette` was observed on the unchanged
published worktree. It used deterministic 128×96 images, real private cache
I/O and actual dynamic palette preparation and refinement. Every observed
`_assign` delegated to the original implementation. There was no timing or
allocation instrumentation in this before probe.

In the red-shade case with a 24-color limit, the initial reducer supplied eight
centers. Refinement then appended centers 9 through 24, each time recalculating
distances to **all** existing centers. With 10,885 distinct sampled colors,
the complete original refinement evaluated 4,528,160 point-center pairs.
The gray case started with four centers and similarly refilled twenty slots.
Already-full gradient and regional palettes provided unaffected controls.

All 887 baseline Python files retained the exact source-map digest
`48245acbd0a159956f998b1009f022a5d7b0245f977f741eef84016c9ffbb4bc`.
The private process audit reported no repository writes or network operations.
The complete outputs, per-assignment shapes and transform hashes are retained
in the common completion evidence under
`pending-batch30-palette-audit/before/summary.json`, SHA256
`89a1421057bd1ae7f08d2169467816dc3079e81ff3df2653a6a20031acd90483`.
Its actual observer source is retained alongside the report.

The new actual cold-builder regression was also loaded against this unchanged
published product. Its two workload cases preserved the expected colors but
failed the new reduced-work requirement: **two expected assertion failures,
zero errors**. No missing-new-helper exception was used as failure evidence.
The original test log, report, fixture hash and unchanged baseline map remain
in `pending-batch30-palette-audit/tests-before/`.

## Implementation and numeric conditions

The first complete nearest-center assignment is unchanged. When one source
color is appended, the implementation transforms the complete new center
array and checks that its old prefix is exactly equal to the preceding
transform. If that prefix differs, it performs the original complete
assignment. This preserves behavior even if a numeric backend rounds
different vector lengths differently.

For an unchanged prefix, only distances to the newly appended center are
computed. A sample changes its label only when the new distance is strictly
smaller than its existing minimum. Equal distances keep the first center,
matching the original `argmin` tie rule. The original chunked assignment
kernel and its cancellation checks are used for the new column. No partial
labels or errors are applied if that calculation is interrupted.

The complete medoid refinement loop, weighted-error/tail acceptance, sample
selection, source colors, final order and cache format remain unchanged.
This is local reuse within one refinement call, with no persistent numeric
cache or new field in public palettes, options or plans.

## Correctness and complete historical comparison

The six new methods cover actual cold build → saved palette → warm read;
exact chosen colors; work reduction; 2,047/2,048/2,049-point chunk boundaries;
center counts around common vector widths; exact ties; transformed-prefix
invalidation; cancellation during a new-column calculation; and interruption
of actual public growth before a partial palette can be saved. Source pixels,
metadata and EXIF remain unchanged. The focused new plus existing refinement
suite passed **10/10**, with no skips.

The benchmark loads the complete published `PicturePaletteRefinement.py` from
Git, with SHA256
`3f28cd7c69d5e09dc53c74ff72ef5f470a40538dede08827990e025365454aa5`.
The new module's SHA256 is
`9fa64a4d111ea4d7c81f57a5d84e456f0f863195d6b09dc6bccbfaaee745c4d3`.
All other current dependencies are explicitly shared and source-bound. The
legacy public picture builder's real inline import binds to the selected
complete module, so the historical comparison does not mix old and new
refinement functions.

All **32 historical comparisons** pass:

- Sixteen complete public builder outputs: four actual images, two color
  limits, and both cold computation and actual warm cache reads.
- Twelve direct controls: RGB, RGBA and indexed transparency; one-pixel axes;
  ordinary dimensions; and a source larger than the 16,384-sample limit.
- Four complete `DrawBot.make_plan` comparisons: gray and red-shade sources
  under Balanced and Pixel Accurate. Pixel Accurate really enters picture
  refinement; Balanced is an unchanged nonconsumer control. All plan fields,
  image pixels, image metadata/EXIF and storage paths are compared, excluding
  only the seven pre-existing profiler-clock paths listed in the raw report.

The earlier untimed parity diagnostic is preserved separately. It already
matches the same final 892-file source map; it is not used as an extra timing
sample. Public `make_plan` is checked for output parity only and is not included
in the elapsed claims below.

## Balanced elapsed observations and controls

[Reproduction script](../benchmark_v148_colour_batch30_palette_growth.py) and
[complete raw results](v148-batch30-palette-benchmarks.json) retain six balanced
AB/BA pairs per workload. Warm-up and validation are untimed; every returned
timed result is checked against its complete expected output after the timer.
Cache deletion or warm priming happens before each timer. Actual cold cache
reads, creation and publication are included in the public-builder operation.
The same local module-binding context overhead is included on both sides.
Work counters and traced allocations run separately from elapsed samples.
No individual sample is discarded.

| Operation | Before median | After median | Median change | Faster pairs |
| --- | ---: | ---: | ---: | ---: |
| Cold 24-color gray picture palette | 38.545 ms | 38.045 ms | −1.30% | 5/6 |
| Cold 24-color red-shade picture palette | 246.641 ms | 178.919 ms | −27.46% | 6/6 |
| Already-full gradient control | 542.194 ms | 524.792 ms | −3.21% | 4/6 |
| Already-full region control | 771.390 ms | 760.932 ms | −1.36% | 4/6 |
| Warm cache control | 0.546 ms | 0.516 ms | −5.43% | 4/6 |
| Direct red-shade refinement | 154.559 ms | 68.455 ms | −55.71% | 6/6 |

The unchanged full-palette, region and warm-cache controls perform identical
algorithm work; their timing movement is treated as control noise, not a
benefit attributable to this change. The gray workload removes substantial
assignment work but changes the whole-builder median only slightly. The
direct refinement measurement excludes fingerprinting, dynamic preparation,
cache I/O and downstream drawing, so its percentage is not an application or
public-planner speed claim.

| Operation | Point-center pairs before | After |
| --- | ---: | ---: |
| Cold gray | 14,310 | 2,160 |
| Cold red shades | 4,528,160 | 1,828,680 |
| Full gradient control | 2,654,208 | 2,654,208 |
| Region control | 3,120 | 3,120 |
| Warm cache control | 0 | 0 |
| Direct red refinement | 4,245,150 | 1,306,200 |

## Allocation limits and source binding

There is **no measured peak-memory improvement**. Separate traced Python
peak observations are 5,038,433 → 5,038,641 bytes for gray,
5,106,450 → 5,106,498 for red, 5,120,986 → 5,121,150 for the full-palette
control, 5,126,530 → 5,126,898 for the region control, unchanged 1,070,273
for warm cache and 2,180,528 → 2,180,820 for direct refinement. Retained
values are also preserved in the raw report. These are Python allocator
observations, not complete native Pillow/NumPy or process RSS measurements.

All final parity, elapsed, work and allocation observations use the same
**892 root Python files**, unchanged before and after, with compact source-map
SHA256 `ce9691bce3bdb6b6e992ab3383b323e803f85e8df95c6a99ff6f409a9d345abd`.
The raw artifact's SHA256 is
`349e15e385ceb3e3e3c128486eeb9763ad491412d7aa563a1fdfc9f05d2ec644`.
Independent review verified all 36 pair orders, exact medians and percentages,
work sums, allocation values, complete comparisons and both module hashes.

The completed frozen-program gate is recorded below. This ledger does not claim
Windows timing, physical Paint delivery, GPU acceleration, a general app
speedup, a release, or additional IDs for controls and verification.


## Integrated frozen-source result

Batch 30 records **842 distinct improvements, 158 remaining**. 2 new behavior groups are registered: R3001, R3002. Background cleanup preserves detail already protected by the border flood; picture-palette growth avoids retesting unchanged centers. Portrait stroke ownership, Stop across image-copy handoff and test-fixture Tcl disposal complete existing contracts with zero IDs. All 840 prior registry entries and 78 earlier benchmark JSON reports are preserved. Completed frozen discovery ran **4,551 tests in 231.751 seconds: 4,478 passed and 73 skipped**; all 943 source/configuration hashes were unchanged. Fourteen Linux/Xorg native cases, the 5,000-cycle source gate, eight exact raster fixtures and initial package hygiene (1,359 files) passed. The package check after final metadata passed with 1,361 files and no warnings. The incomplete process attempts and the Tcl-aborted attempt remain negative evidence. A proved old calibration fixture released borrowed Tcl aliases after real cleanup; no product GC policy, skip, assertion or timeout was weakened. The final background and Portrait historical comparisons and the six-workload/six-pair palette measurement retain their original 892-file map; the final 893-file map differs only in the two explicitly recorded fixture files. Historical checks retain 20 exact background controls and 24 intended corrections, 14 Portrait helper and seven public pairs, and 32 palette comparisons including four public plans. The cold red picture-palette helper and direct refinement improve in all six pairs; unchanged-work controls are not treated as algorithm gains. No universal speed, peak-memory, process-RSS, physical Paint or GPU improvement is claimed. Parent 4b90 has seven green checks after one unchanged Windows-job rerun; the new head requires its own exact-commit CI. Version 1.0.148 remains unreleased.

The final gates bind **893 root Python files**, compact SHA256 `0da8de7641efb47fea77c62ece22629b27f9425c137e9d8ccd8d7e9933ae5845`, and **943 source/configuration files**, compact SHA256 `5f6b89f5b52c9ae6f0335345f744fb887936afdab1e847eb5c22d73f3c155b41`. The original measured/evidence map remains **892 root files**, SHA256 `ce9691bce3bdb6b6e992ab3383b323e803f85e8df95c6a99ff6f409a9d345abd`. The only later differences are the old calibration fixture cleanup and its new subprocess regression; their exact sources, hashes, import boundary and diff are recorded in [raw evidence](v148-batch30-completion-evidence.json) and [final validation](v148-batch30-validation.json). No timing or image checkpoint is silently rebound. The final metadata review and post-metadata package check are recorded separately; publication of the new head does not imply its remote checks have completed.
