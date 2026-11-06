# v1.0.148 colour and planning — batch 04

This batch proposes **nine distinct product improvements**, compared with
`1d48eabaf349a5fd8049a2c96ef5426745c3078c`. The later `2aca72a` checkpoint only
corrected pip test fixtures; it did not change this product baseline. The Detail Zoom cross-area review and frozen whole-program integration are complete; see the checkpoint results below.

Related implementations of the same behavior are counted together. Tests,
benchmark fixtures, caller changes, metadata and documentation do not add IDs.

## Changes and independent evidence

| ID | Previous behavior | Corrected behavior | Evidence |
| --- | --- | --- | --- |
| PB01 | Adaptive Detail flattened a translucent source onto white, filtered those visible RGB values, then attached the original alpha again. A later composite therefore added white twice and washed out the image. | Transfer the filtered visible-color delta back into unassociated source channels while retaining alpha. Unchanged/protected pixels remain byte-exact; invisible source RGB cannot affect visible smoothing. | `test_v148_planning_batch04_color`: uniform partial-alpha cases, protected translucent edges, independent white-composite comparison and hidden-RGB variants. |
| PB02 | Layered colour mixing put a secondary stipple on top of a full primary run in separate colour groups. Executing the primary colour later could erase the stipple completely. | Assign each ordered-Bayer source pixel to exactly one primary or secondary group. Both palette orders now reproduce the same intended mixture, for serial and worker planners. | `LayeredRasterTests` uses an independently specified Bayer matrix, checks single coverage per pixel and compares complete rasters in both colour orders. |
| PB03 | When no progressive sequence existed, Detail Zoom appended fine paths to their original colour groups. A later base/background colour could overpaint the recovered detail. | Materialize the complete established base colour order, then append the detail pass. Preserve path phase hints, explicit detail brush size and all base geometry. Target and guarded preview must follow this same sequence; existing configured visual verification is retained by the coordinated runtime integration. | `test_v148_planning_batch04_geometry.DetailPassDeliveryTests` renders both base colour orders and checks every recovered black detail survives; root application tests cover ordered target/guarded preview. Cross-area safety-metadata, pixel-footprint and runtime-verification review corrections are part of this item. Independent review is closed; `test_v148_detail_zoom_verification.py` also verifies actual per-batch snapshots, selected brush size, failure/Stop before later input and checkpoint publication only after batch verification. |
| PB04 | Local greedy nearest-path choices sometimes increased total pen-up travel, even though the optimizer existed to reduce it. | Compare the complete candidate route with the supplied route and retain the shorter one. Apply the same nonregression contract to segment and polyline optimizers without changing geometry, structural windows or reversal policy. | Two reproduced greedy regressions plus 90 deterministic randomized groups, each checked with and without reversal against independent endpoint-distance and segment-multiset oracles. |
| PB05 | Supported legacy speed labels fell through to Balanced behavior in time-derived stroke caps, nearest-path search windows and two-opt budgets. | Normalize the existing aliases before those planner decisions, so old profiles receive the same planning semantics as their canonical speed. | Exhaustive supported-alias comparisons for three drawing modes, path search and two-opt budget. These call sites share one count. |
| PB06 | Both sketch component filters retained coordinates for every pixel in a connected component after it had already met the size floor and was guaranteed to survive. | Keep removal/protected-peak evidence only while the component can still be rejected as small; clear that evidence at the acceptance threshold. The connectivity frontier and seen/output masks remain. Both legacy and Sketch 2.0 implementations share one count. | Independent union/find component oracle across five densities and five size floors; protected high-contrast component counts and caller-mask nonmutation; Stop inside a large retained component. Paired complete-contour and Sketch 2.0 measurements below. |
| PB07 | Axis conversion allocated a second full-area transition raster and made two NumPy search calls per column. | Compute transitions in blocks of 64 columns, transposed into the same x-major/y-major result order, while keeping the existing area bound. | Independent pixel-set/vertical-run oracle with overlaps, reversed endpoints, negative offsets and widths straddling 64-column boundaries; exact 1024 × 768 paired output. |
| PB08 | A target-path cap first retained a scored tuple for every input path, although the heap needed only the best capped subset. | Stream ranked entries into the bounded heap. Retain protected-prefix priority, stable ties, source order and aligned phase/semantic metadata. | Independent full-sort selection oracle including caps below/equal to the protected count; exact 60,000-to-500 paired result and complete metadata. |
| PB09 | Quick Sketch texture trimming retained and sorted every micro-stroke before selecting a small cap. | Keep only the best bounded micro-stroke candidates in a heap; prefer two-pixel strokes and then earlier colour/source positions while leaving all longer strokes intact. | Independent stable-sort oracle across zero, small and boundary caps; exact 100,000-to-500 paired output, order and counters. |

## Counting boundaries

- Both sketch component filters belong to PB06. Legacy sketch's row-at-a-time
  seed enumeration also completes the existing IW04 seed-allocation pattern;
  it does not add another count.
- Both travel optimizers belong to PB04, and all supported-speed-alias call
  sites belong to PB05.
- Detail Zoom's target refresh, ordered guarded preview, matching safety
  metadata and preservation of runtime verification belong to PB03. Fixing
  the existing one-pixel preview footprint on that new route completes RP38;
  it is not a new count.
- Additional cancellation/ownership coverage completes the existing planner
  cancellation and owned-image contracts. No extra IDs are assigned for
  callback propagation, tests or cleanup-only changes.

## Reproducible measurements

Run the generated local fixtures with:

```bash
python benchmark_v148_planner_memory.py --repeats 5
```

The [script](../benchmark_v148_planner_memory.py) loads the named baseline
modules from local Git history. Baseline modules use current shared dependencies.
The [raw result](v148-batch04-planner-benchmarks.json) includes input parameters,
source hashes, Python/NumPy/Pillow versions, every elapsed sample and compared
output fingerprints. Each comparison first requires exact output parity, then
takes five alternating before/after timings and separate Python-traced peaks.

| Fixture | Baseline median | Current median | Baseline Python peak | Current Python peak |
| --- | ---: | ---: | ---: | ---: |
| Complete legacy contour, connected grid, 512 × 384 | 133.51 ms | 102.43 ms | 8,705,672 B | 8,438,575 B |
| Sketch 2.0 retained component, 300 × 220 | 125.21 ms | 117.32 ms | 4,698,552 B | 169,088 B |
| Exact vertical runs, solid 1024 × 768 | 11.12 ms | 6.20 ms | 1,812,252 B | 1,124,556 B |
| Target cap, 60,000 paths to 500 | 80.70 ms | 76.38 ms | 12,148,500 B | 1,798,608 B |
| Quick Sketch micro-texture, 100,000 strokes to 500 | 96.42 ms | 74.44 ms | 19,944,320 B | 931,188 B |

These are synthetic CPU workloads. Python tracing excludes most native Pillow
storage, and the component frontier can still grow with source geometry. The
table does not claim constant total memory, physical GPU speed, Windows input
throughput or complete drawing speedups. All five fixtures produced exactly
equal compared output in this run.

## Focused validation

The directly related run passed **113 tests** in **4.863 seconds**, without
skips. The new resource-oracle module then passed **five tests** in **0.095
seconds**. Together this is 16 new tests and 102 existing related tests; it is
separate from root's whole-program release gates.

New test modules:

- [Colour and aliases](../test_v148_planning_batch04_color.py).
- [Travel and detail order](../test_v148_planning_batch04_geometry.py).
- [Bounded working sets](../test_v148_planning_batch04_resources.py).

The related modules are:

```text
test_black_sketch_v1095 test_sketch_detail_v1099 test_game_sketch_v1097
test_gartic_sketch_v1098 test_sketch2_v10131 test_sketch_fill_v10131
test_step25_quick_sketch_fill_contour_v10148 test_time_budget_v1020
test_axis_region_hybrid_v10145 test_step24_adaptive_detail_zoom_v10147
test_advanced_color_v108 test_advanced_color_matching_v109
test_adaptive_detail_v1038 test_stroke_optimizer_v1037
test_stroke_optimizer_two_opt_v10138
```

The existing Detail Zoom test now checks the complete base-plus-detail sequence
instead of treating its absence as expected. This fixture correction does not
add a product count. No published release, code-signing result or antivirus
verdict is asserted by this checkpoint.

## Frozen integration checkpoint

Independent area and cross-area reviews are closed. Whole-program discovery ran
**2,934 tests in 75.509 seconds**, passing with 23 platform/hardware skips; source
hashes were unchanged during the run. The 5,000-cycle release source gate,
source-package hygiene and eight exact-raster engine fixtures also passed.
This batch is included in the 668-improvement development checkpoint. Its own
Windows/Linux CI is pending; 1.0.148 is not yet released.
