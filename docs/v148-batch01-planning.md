# v1.0.148 planner and geometry improvements — batch 01

This ledger counts distinct runtime corrections or measured planning improvements. Tests, documentation, formatting, and version changes are not counted. Benchmarks are local CPU measurements in the existing security virtual environment, not claims about a released executable or every computer.

## Implemented changes

| ID | File | Previous behavior and evidence | New behavior and regression evidence |
| --- | --- | --- | --- |
| PL01 | FastDryRun.py | A path cap of zero or two could retain four paths, one for each selected color. | Color allocation also respects the total path budget; zero remains empty. `DryRunCapsTests.test_path_limit_smaller_than_color_limit_and_zero_are_respected`. |
| PL02 | FastDryRun.py | Progressive execution sampling ignored the requested color cap; eight colors survived a cap of two. | Select eligible colors first, then preserve sequence order while sampling within both limits. `DryRunCapsTests.test_progressive_sequence_obeys_color_cap_and_keeps_original_order`. |
| PL03 | AdaptiveDetail.py | Endpoint/midpoint sampling missed a protected third pixel in a four-pixel micro-stroke. | Visit every raster pixel of the bounded short segment before pruning. Horizontal, reverse, vertical, and diagonal fixtures in `ProtectedGeometryTests`. |
| PL04 | TimeBudget.py | Removing empty paths before aligning metadata shifted outline phase hints and protected prefixes to later tone paths. | Filter paths and their original semantic indices together. A cap of one preserves the outline fixture in `ProtectedGeometryTests`. |
| PL05 | DeadlineScheduler.py | A block-local reorder passed its transition check while global color/brush changes rose from one to three. | Evaluate both adjacent stroke boundaries, including across non-stroke operations. `DeadlineTransitionTests`. |
| PL06 | RealSpeedBudget.py | A NaN elapsed sample recorded an 80 paths/sec estimate and invalid accumulated seconds. Corrupt profiles contaminated later estimates. | Reject nonfinite samples without writing; validate old profiles and repair only from a valid new sample. `TimingIntegrityTests`. |
| PL07 | Precision.py | Counting ordinary moves constructed and retained the complete coordinate path. | Calculate ordinary counts directly; dense rounding cases retain the exact path fallback. Independent expected counts and 800 randomized execution comparisons in `PrecisionCountTests`. |
| PL08 | ContinuousPaths.py | Each run rescanned active paths whose sorted intervals had already ended. | Advance a bounded interval sweep while preserving candidate priority and exact coverage. Separated-column expected paths and 80 independent raster comparisons in `ContinuousSweepTests`. |
| PL09 | SafeFillMask.py | A malformed explicitly supplied contour collapsed to the same value as an absent legacy contour and skipped checks. | Reject malformed contours in source and runtime gates, retaining absent-contour compatibility. `FillGeometryGateTests.test_malformed_present_contour_cannot_be_treated_as_absent`. |
| PL10 | SafeFillMask.py | Malformed or reversed exact row spans could be discarded into a permissive bounding-box fallback. | Reject invalid/inverted/fractional spans and spans outside their declared box in both gates. `FillGeometryGateTests.test_malformed_reversed_or_inconsistent_spans_are_rejected`. |
| PL11 | SafeFillMask.py | A seed outside its intended region was accepted if it lay inside the overall canvas. | Require membership in the exact region span mask, or the compatible legacy box. `FillGeometryGateTests.test_seed_must_belong_to_its_exact_region_not_just_safe_canvas`. |
| PL12 | StrokeOptimizer.py | Exact graph/neighbor merges reversed directed paths even with `allow_reverse=False`. | Propagate the direction contract through every merge stage; default reversible behavior remains. `StrokeDirectionTests` compares directed segment multisets. |
| PL13 | ShapePaths.py | Collinear compression erased direction reversals and their painted excursion. | Remove a middle point only when both segments continue in the same direction. Explicit backtracks and an interior-connector hatch raster test in `ShapeGeometryTests`. |
| PL14 | ShapePaths.py | A 1,200-point alternating contour exceeded Python's recursion limit during RDP simplification. | Use an index-range stack, normalize once, and check cancellation within long contours. A 1,600-point expected zigzag and cancellation fixture in `ShapeGeometryTests`. |
| PL15 | AxisRegionPlanner.py | Adjacent-pair testing split a later short run nested inside an earlier long run into a new component. | Carry the farthest connected same-row endpoint through the sweep. `AxisComponentTests.test_nested_same_row_runs_are_one_connected_component`. |
| PL16 | AxisRegionPlanner.py | Component mass counted duplicate/overlapping source runs repeatedly. | Count the sorted row union while preserving every original source index. `AxisComponentTests.test_component_pixel_mass_counts_union_not_duplicate_runs`. |
| PL17 | ShapePaths.py | Component detection compared every previous-row run with every current-row run. | Sweep sorted nonoverlapping intervals and stop after the current run; independent pixel flood oracle verifies connectivity and area. `ShapeGeometryTests.test_component_sweep_matches_independent_pixel_flood`. |
| PL18 | StrokeOptimizer.py | Bounded nearest-neighbor search still shifted the entire future job on each list removal. | Remove only from a bounded active window and replenish it from an iterator. Independent route-choice oracle across speeds/direction settings and a 14,000-path chain in `StrokeDirectionTests`. |
| PL19 | PixelAccuratePlanner.py | The last-resort palette fallback allocated a row-count × full-width × palette tensor, so very wide rows defeated the row bound. | Tile both axes with at most 262,144 pixel/color pairs per tile. Saved pre-change outputs for four distance policies, a direct RGB distance oracle, and wide strided exact-color fixtures in `PaletteTileTests`. |
| PL20 | StatefulFillSimulation.py | A NaN missing-pixel tolerance approved a fixture missing 75% of its intended coverage. | Require a finite tolerance in [0,100] before simulation. `FillSimulationIntegrityTests.test_nonfinite_missing_tolerance_cannot_approve_incomplete_fill`. |
| PL21 | StatefulFillSimulation.py | Pre-cancelled work still allocated canvas masks; a very long contour outside the canvas had no bounded cancellation point. | Check cancellation before allocations, during span/contour/flood work, and before publishing a successful result. Mask-allocation traps and a 100,000,000-pixel contour fixture in `FillSimulationIntegrityTests`. |
| PL22 | DrawingStyleProfiles.py | A 160-pixel style thumbnail required full-resolution RGBA conversion and another full copy first. | Select the nearest-neighbor thumbnail in the original mode, then convert only that sample. Exact metrics for RGB/RGBA/palette/monochrome inputs and a conversion-size guard in `BoundedSamplingTests`. |
| PL23 | ProgressiveRenderer.py | Phase, importance, and spatial seeding repeatedly scanned the same path for length, bounds, and center. | Calculate reusable geometry once per path without temporary coordinate lists. Compare complete sequence output against the independent original geometry helpers in `BoundedSamplingTests`. |
| PL24 | PixelStrokeEngine.py | Missing optional shadow maps allocated and summed two zero arrays for every raster run. | Leave absent shadow sums at zero; only accumulate real optional maps. Exact component/statistics fixtures and a zero-allocation trap in `PixelMapIntegrityTests`. |
| PL25 | PixelAccuratePlanner.py | A negative drawable index selected the last palette color in dot mode, while line mode silently discarded it; malformed shapes were unchecked. Unsigned indices also failed when constructing a negative sentinel. | Validate matching dimensions and every drawable palette index, and copy valid values to a signed background row. Preserve the legacy height-only PicturePalettePlanning adapter. Dots/lines, malformed shapes, and all four unsigned integer widths have regressions. |
| PL26 | AdaptiveDetail.py | Pre-cancelled Off/small-image paths still converted the image, and cancellation during the final composite published a result. | Check before conversion, on early returns, and before returning the processed image. `AdaptiveCancellationTests`. |
| PL27 | FastDryRun.py | Taking eight representative items first copied every entry in an already-indexable sequence. | Index existing sequences directly; retain one-shot iterator compatibility and independent output lists. A million-element sequence forbidding iteration verifies bounded reads in `BoundedSamplingTests`. |
| PL28 | DetailZoomPass.py | `max(2, ...)` prevented the below-2 exit from ever enforcing the advertised analysis-size ceiling. | Skip unavailable zoom rather than exceeding the 1500/1800-pixel bound. Tests stop conversion for oversized inputs and verify the exact 1800-pixel boundary. |
| PL29 | DetailZoomPass.py | Nonmaximum suppression sorted all eligible cells into Python tuples before selecting at most twice the small path cap. | Partition to a mathematically sufficient 18×cap shortlist, preserving ties by source index, then apply the same suppression. Random, tied, and boundary-cap fixtures match an independent full-sort oracle. |
| PL30 | AdaptiveDeadlineRenderer.py; ExecutionCostModel.py | Empty geometry became billable dots or caused palette/brush state changes despite executing no stroke. | Exclude empty paths from deadline entries, overhead counts, and implicit execution-state transitions; explicit UI operations remain billable. `CostStateTests` covers both planners. |
| PL31 | ExecutionCostModel.py | An explicit brush change followed by a stroke omitting brush metadata implicitly switched back to the default, charging a second switch. | Inherit the current brush until an entry explicitly changes it. Initial and explicit state fixtures in `CostStateTests.test_implicit_brush_uses_explicit_or_initial_current_state`. |
| PL32 | PixelStrokeEngine.py | Each orientation computed both candidate order costs, then recomputed the chosen cost. | Reuse the selected evaluated cost; exactly four cost calls cover two orientations and two orders. `CostStateTests.test_component_candidate_cost_is_evaluated_once_per_order`. |
| PL33 | DetailZoomPass.py | Detail strokes chose the smallest nominal brush, even when only larger sizes had verified controls. | Reuse the existing verified brush ladder and retain the fixed-brush fallback and Paint Pencil rule. Explicit verified/unverified fixtures in `DetailZoomBoundaryTests`. |
| PL34 | FastDryRun.py | Repeated color-order entries overwrote a group's sample but incremented path totals repeatedly. | Deduplicate valid active indices in first-seen order; reject unusable entries without corrupting accounting. `PlannerReuseTests.test_repeated_color_order_cannot_duplicate_dry_run_accounting`. |
| PL35 | StrokeOptimizer.py | Every shared-endpoint join rescanned all already-used indices, producing quadratic behavior for repeated endpoints. | Advance an endpoint-local cursor; consumed candidates never become eligible again. Random graph chains match an independent first-available reference, plus a 10,000-point fixture. |
| PL36 | GarticSketchPaths.py | Dense-component density analysis built exact vertical runs, then vertical candidate generation built them again. | Pass the existing vertical raster into the candidate builder. A spy verifies one construction and an independent full pixel set verifies coverage. |
| PL37 | PortraitPlanner.py | Portrait preparation ignored cancellation through most non-preview processing, including CPU contrast, subject lifting, and saliency loops. | Check cancellation before conversion, between analysis stages, and inside bounded CPU loops/path generation. `PortraitLifecycleTests` tests pre-cancel and mid-contrast interruption. |
| PL38 | PortraitPlanner.py | GPU analysis sessions were released only after normal line-mode completion; dot returns and exceptions skipped cleanup. Preparation also had no explicit owner when metadata was omitted. | Finalize sessions on all terminal stroke paths, release failed/unowned preparation sessions, and retain a successful explicitly owned session for the next stage. Fake session lifecycle tests cover normal, dot, failure, cancellation, and ownership transfer. |
| PL39 | HybridRenderer3.py | Weighted int16 luminance overflow made white evaluate as −1 instead of 255, suppressing a black/white edge. | Accumulate weighted channels in int32. Independent black/white and primary-color expected statistics in `StructureAnalysisTests`. |
| PL40 | Sketch2Planner.py | A single connected component could flood for its full size before checking cancellation; source-size rejection happened after conversion. | Check cancellation within the component queue and before/after analysis; reject oversized input before conversion. `StructureAnalysisTests` exercises one large component and allocation guards. |

## Local measurements

Elapsed values are medians; peak allocations come from a separate `tracemalloc` run of the same workload. Warm imports are excluded. Input and output objects are retained consistently between measurements.

| Change | Workload | Before | After | Interpretation |
| --- | --- | --- | --- | --- |
| PL07 | 500 High-precision counts, `(0,0)` to `(4000,3000)`, base step 8; median of 5 | 259.390 ms; 103,588 peak bytes | 1.003 ms; 20,648 peak bytes | About 259× faster for this ordinary count workload; dense-rounding cases deliberately use the old exact fallback. |
| PL08 | 400 separated one-pixel columns over eight rows; median of 3 | 158.488 ms; 367,024 peak bytes | 10.349 ms; 367,628 peak bytes | About 15.3× faster; memory remains effectively unchanged. All 400 expected vertical paths are identical. |
| PL17 | Same 400×8 source runs, shape component detection; median of 3 | 181.395 ms; 1,024,208 peak bytes | 8.739 ms; 1,024,272 peak bytes | About 20.8× faster; effectively unchanged memory. |
| PL18 | 50,000 contiguous one-segment paths, nearest-neighbor stage; median of 3 | 197.850 ms; 8,927,304 peak bytes | 89.386 ms; 9,177,712 peak bytes | About 2.2× faster; peak memory increases by about 250 KB because the input iterator retains references. |
| PL19 | Faithful perceptual fallback, 96×256 RGB pixels and 96 colors; median of 3 | 116.860 ms; 151,896,032 peak bytes | 112.727 ms; 16,855,796 peak bytes | About 89% lower peak Python/NumPy allocation; elapsed time is similar. |
| PL22 | Style metrics on 4096×2048 RGB image; median of 3 | 35.195 ms; 899,938 traced bytes | 25.078 ms; 899,661 traced bytes | About 1.4× faster. `tracemalloc` does not include Pillow's C image buffers; the avoided full RGBA conversion is separately verified by the conversion-size test. |
| PL23 | 500 paths with 800 points each, progressive planning; median of 3 | 273.094 ms; 337,932 peak bytes | 217.466 ms; 335,660 peak bytes | About 1.26× faster; full sequence metadata and order match. |
| PL24 | 80×80 two-color checkerboard component analysis without shadow maps; median of 3 | 190.906 ms; 9,813,268 peak bytes | 115.939 ms; 9,505,836 peak bytes | About 1.65× faster; optional zero-array creation is eliminated. |
| PL27 | Sample eight items from an existing one-million-item list; median of 3 | 3.647 ms; 8,000,484 peak bytes | 0.0075 ms; 428 peak bytes | The full reference-list copy is eliminated. The tiny after-time is a microbenchmark observation, not a general latency guarantee. |
| PL29 | Detail-cell selection on a 512×512 random score map, cap 90; median of 3 | 352.699 ms; 37,842,176 peak bytes | 3.227 ms; 4,197,688 peak bytes | About 109× faster and 89% lower peak allocation for this fixture. |
| PL32 | 25 H/V selections on one 500×100 component, 0.15-second path limit; median of 3 | 915.006 ms; 2,234,829 peak bytes | 632.583 ms; 2,344,445 peak bytes | About 1.45× faster; this is a time optimization, with no memory-reduction claim. |
| PL35 | Exact graph merging for 10,000 paths sharing one point; median of 3 | 783.382 ms; 1,930,980 peak bytes | 9.282 ms; 1,931,388 peak bytes | About 84× faster; same merged path and join count. |
| PL36 | Gartic contour planning for a solid 180×120 image; median of 3 | 6.593 ms; 80,136 peak bytes | 4.906 ms; 74,896 peak bytes | About 1.34× faster on this small fixture; exact vertical-raster construction occurs once instead of twice. |

### Reproducing the fixtures

Run from the repository with the existing environment's Python. Use the same interpreter and a separate checkout of the pre-change revision for before/after comparisons. Imports and fixture construction are outside the measured interval. Do not execute drawing input.

```python
import statistics, time, tracemalloc
import numpy as np
from PIL import Image
import Precision, ContinuousPaths, ShapePaths, StrokeOptimizer, FastDryRun
import DrawingStyleProfiles, ProgressiveRenderer, PixelAccuratePlanner as PAP
import PixelStrokeEngine as PSE, DetailZoomPass, GarticSketchPaths
from ExecutionCostModel import build_cost_model

def measure(label, operation, repetitions=3):
    elapsed = []
    for _ in range(repetitions):
        start = time.perf_counter()
        result = operation()
        elapsed.append(time.perf_counter() - start)
    tracemalloc.start()
    result = operation()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(label, statistics.median(elapsed), peak)

measure('PL07', lambda: [Precision.precision_path_count((0,0),(4000,3000),'High',8) for _ in range(500)], 5)
runs = [(x*3,y,x*3,y) for y in range(8) for x in range(400)]
measure('PL08', lambda: ContinuousPaths.build_execution_paths([runs], enabled=True))
measure('PL17', lambda: ShapePaths._components_from_runs(runs))
chain = [((i,0),(i+1,0)) for i in range(50000)]
measure('PL18', lambda: StrokeOptimizer._nearest_order(chain))
rng = np.random.default_rng(148)
rgb = rng.integers(0,256,(96,256,3),dtype=np.uint8)
palette = rng.integers(0,256,(96,3),dtype=np.uint8)
measure('PL19', lambda: PAP._cpu_palette_map(rgb,palette,perceptual=True))
image = Image.fromarray(rng.integers(0,256,(2048,4096,3),dtype=np.uint8))
measure('PL22', lambda: DrawingStyleProfiles._metrics(image))
paths = [tuple((i,y+i%3) for i in range(800)) for y in range(500)]
measure('PL23', lambda: ProgressiveRenderer.build_progressive_sequence([paths]))
idx = np.indices((80,80)).sum(axis=0).astype(np.int16)%2
values = np.ones(idx.shape,dtype=np.float32)*.3
mask = np.ones(idx.shape,dtype=np.bool_)
pixel_map = PAP.PixelMap(80,80,np.zeros((80,80,3),dtype=np.uint8),idx,mask,values,values,mask,{})
measure('PL24', lambda: PSE.connected_components(pixel_map))
items = list(range(1000000))
measure('PL27', lambda: FastDryRun.sample_items(items,8))
score = np.random.default_rng(148).uniform(18,140,(512,512)).astype(np.float32)
measure('PL29', lambda: DetailZoomPass._pick_cells(score,90,threshold=18))
model = build_cost_model({'profile_key':'microsoft-paint','_execution_cost_calibration_override':{'samples':0}},(500,100),(500,100))
component = PSE.Component(0,0,area=50000,bbox=(0,0,499,99),horizontal_runs=[(0,y,499,y) for y in range(100)],vertical_runs=[(x,0,x,99) for x in range(500)])
labels = np.zeros((100,500),np.int32)
measure('PL32', lambda: [PSE.build_component_paths(component,labels,cost_model=model,max_path_seconds=.15) for _ in range(25)])
dots = [((0,0),) for _ in range(10000)]
measure('PL35', lambda: StrokeOptimizer._merge_exact_graph(dots))
solid = Image.new('L',(180,120),0)
measure('PL36', lambda: GarticSketchPaths.trace_contours(solid,options={'_execution_cost_calibration_override':{'samples':0}}))
```

## Validation status

There are exactly **40** counted changes, PL01–PL40. The four new regression modules are `test_v148_planning_integrity` (14 tests), `test_v148_geometry_integrity` (10), `test_v148_planning_resources` (13), and `test_v148_planner_edge_cases` (18): **55 new tests**. Final validation passed **284 tests** across two disjoint focused/related unittest commands: 201 tests in 5.396 seconds and 83 tests in 5.125 seconds, with no failures or skips. This includes the final review-driven unsigned-index and explicitly malformed empty-field regressions. Those corrections belong to PL09/PL10/PL25 and do not add to the change count. `git diff --check` passed for all owned files. No physical drawing input is emitted by these tests.

The new focused suite can be reproduced with:

```bash
python -B -m unittest -q test_v148_planning_integrity test_v148_geometry_integrity test_v148_planning_resources test_v148_planner_edge_cases
```

Related validation covered the existing precision, continuous/raster identity, semantic barriers, target path cap, deadline/replanner, dry run, stroke optimizer/2-opt, shape renderer, progressive renderer, Detail Zoom, Sketch 2.0, Extra Fast, hybrid policy, portrait/GPU adapter, pixel execution cost, picture palette pipeline, and fill simulation tests. The root agent owns whole-program integration; the focused totals above do not claim execution of standalone pytest functions by unittest.

Known limits: these are local CPU, fake-device, and geometry tests. They do not establish live GPU speed, application input timing, or antivirus clearance. Pillow currently emits pre-existing `getdata` deprecation notices in some classification helpers; no behavior change is claimed for those warnings.
