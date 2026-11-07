# v1.0.148 batch25 — preserve admitted paint order and score actual Fill topology

Original reproduction:
`bb6dfa6a5e8a43bfcfc77c9e00f52dc2dfd7db9c` (828 registered groups).
Integrated paired baseline:
`586e12db5ea5142951c844f60dc2364f07a01c37` (830 registered groups).
This rendering ledger records **two** behavior groups: **R2501** and **R2502**.
Tests, the benchmark, resource cleanup and fallback completions add no IDs.
The coordinator owns registry totals, integration and release gates.

## R2501 — timed admission preserves the component plan's paint order

`PixelAccuracyEngine.progressive_time_budget` selected its quotas in the order
`fill → mid_detail → cleanup → fine_detail` and also emitted them in that
order. The component planner actually uses
`fill → mid_detail → fine_detail → cleanup`: final cleanup protects important
details from the physical footprint of earlier strokes. Giving cleanup an
admission preference must not move it underneath overlapping fine detail.

The numeric reproduction uses the real
`PixelMap → build_pixel_stroke_plan → assign_adaptive_brushes` path. A 32×32 map
contains 25 protected dark pixels, each next to an ordinary colored pixel.
The available brush is 3 px. A ten-second admission budget retains the same
25 cleanup paths and five fine-detail paths on both versions. Previously the
five fine-detail brush stamps erased five already correct protected centers:
protected accuracy was **80%**. Retaining the admitted paths' original paint
order gives **100%**, with the same 30 path occurrences, coordinates and brush.
A separate literal square-stamp oracle checks the resulting ink.

The fix stores each admitted occurrence's original position, preserves the
existing phase quotas and selection priority, and emits the selected positions
in their original order. Identical-looking path occurrences remain distinct.
Returned entries are still copies; the caller's sequence is unchanged. The
metadata now separates admission priority from execution order. Unlimited and
ample-budget controls retain their full original sequence.

The public-caller regression reads the existing eye crop
`(155,102,174,121)` from `golden-regression/small-detail-preservation.png` and
builds a 100×100 Pixel Accurate plan with a 3 px brush and a 30-second budget.
The selected 92 paths retain the original component order: 24 fill, 17 mid
detail, 11 fine detail and 40 cleanup. The public benchmark confirms that
this crop's final accuracy remains **85.82%**, protected accuracy remains
**55.8045%**, and its estimate remains **7.0436 s**. Its execution order changes;
the numeric overlapping-brush case establishes the actual quality gain.

### Deduplication

- **PB03** established ordered layered phases; this defect occurs later, when
  timed Pixel admission reorders an already formed component sequence.
- **P1402/PL31** preserve inherited brush semantics. This change retains the
  existing explicit available brushes and fixes paint occurrence order.
- **R2201** rejects harmful optional correction proposals. R2501 fixes the
  initial sequence before correction scoring, where the detail could already
  be wrong and therefore outside the already-correct-pixel protection.
- **R2401** bounds the component scheduler's active queue while preserving its
  exact emitted order. R2501 preserves that order through later timed
  admission; it does not claim queue-work or candidate-pricing improvements.

## R2502 — preview and scoring replay categorical contour-and-bucket Fill

The scaled hybrid simulator and preview previously projected an accepted
region's ideal source `row_spans` into physical pixels. Execution instead
draws its mapped contour and seal paths with the real brush, then clicks the
bucket seed. These footprints differ even for a valid rectangular Fill.

A real accepted 131×80 source rectangle on a 180×120 source, fitted to a
360×240 canvas with a 1 px brush, has **41,920** intended native target pixels.
Its actual mapped pixel-center contour runs from `(41,41)` to `(301,199)`.
Contour plus bucket paints **41,499** pixels: **421 are missing**, for
**98.9957%** coverage. The previous shared footprint reported 100% and zero
missing pixels. The contour, accepted Fill and executable plan are retained.

The public proof uses the shipped
`golden-regression/dominant-hue-four-color.png`, the real `make_plan` and the
real `execute_plan` over a numeric mouse surface. Its mouse adapter records
palette/tool actions and literally applies line stamps and a four-neighbor
pixel flood. At a 720×480 target, the ordinary planner accepts two black Fill
regions. White is skipped so unrelated outer CanvasGuard clipping does not
confound this specific comparison.

| Public accepted-Fill result | Before | After / recorded executor |
| --- | ---: | ---: |
| Accepted Fill regions | 2 | 2 |
| Ordinary execution paths | 478 | 478 |
| Missing native target pixels | 141,097 | **141,763** |
| Wrong-color native pixels | 0 | 0 |
| Native coverage | 29.7410% | **29.4093%** |
| Pixel Accuracy Score | 32.3648% | **31.7608%** |
| Estimated draw seconds | 108.6132 | 108.6132 |

The corrected diagnostics expose **666 missing pixels** that the ideal-span
model hid. They do not claim a visual improvement or faster drawing for this
unchanged Fill geometry. The public preview now matches the recorded executor
at every displayed sample, and the complete before/after execution geometry
fingerprints are identical. The source image and accepted region records are
not modified.

### Shared implementation and bounds

`NativeFillSimulation.native_fill_rectangles` replays the operations consumed
by `AdaptiveRegionHybrid._native_rectangles`:

1. Preserve the executor's first-occurrence color-batch order.
2. Draw all seals and closed contours of one color before that color's seeds.
3. Use the same native pixel-center projection, integer seal/seed conversion,
   legacy bbox contour, odd/even square brush convention and clipped path
   rectangles. An isolated seal point is not an executor operation.
4. Flood the seed's current categorical color through four-neighbor connected
   row runs. A seed already at the selected color changes nothing.
5. Feed the resulting ordered rectangles to the existing tiled score and the
   existing fitted-preview sampling path, followed by ordinary strokes.

The new private canvas stores horizontal colored intervals; blank pixels are
implicit. It does not allocate a full native-resolution Fill image. Retained
intervals are limited to `min(65,536, planner_pixel_allowance)`; frontier size
is checked against twice that allowance. Region and cache-preflight work are
also bounded. Existing row-span-only diagnostic inputs retain their analytic
compatibility path; actual executable regions have contours or legacy bboxes.

The R1901 footprint cache still has at most
`min(8,192, planner_pixel_allowance)` records. Cache admission now checks the
replayability and bounded size of the newly consumed contour and seal fields
without consuming one-shot iterators. Overflow explicitly closes the private
Fill stream before retrying the ordinary exact stream. Preview and simulation
also close their streams deterministically.

Stop checks cover mapping, row-interval edits, matching scans, flood work and
publication. Private rows, pending work, temporary match lists, mapped paths,
color batches and cancellation callbacks are dropped when processing ends.
Retaining a Stop traceback does not retain the partial row-match workspace.

The existing outer hybrid fallback handles `MemoryError` from this optional
native simulation: it returns the **same complete original base-plan object**
with its original geometry and preview and an explicit MemoryError reason.
Both an actual interval-allowance failure and an injected row allocation
failure exercise that public path. No partial Fill plan or empty replacement
is published. `InterruptedError` propagates and does not become a fallback.

### Model boundary and deduplication

The shared model remains a categorical palette-index canvas, with blank `-1`,
a physical square brush and four-neighbor bucket connectivity, before
CanvasGuard. This patch does not establish equivalence for duplicate RGB
aliases, white ink versus an already white physical canvas, antialiasing,
application-specific brush shapes or actual Windows delivery. The public
numeric executor proof deliberately avoids those unrelated effects. No
reproduced accepted public duplicate-RGB case justified changing the existing
scoring contract.

- **R1004** corrected source/native brush dimensions and target sampling. It
  supplied the existing projection used here; it still treated Fill as ideal
  source spans. R2502 corrects contour/seed connectivity and coverage.
- **RD04** fixed source pixel-center contours and proved source-space Fill.
  This fix keeps those contours and evaluates the mapped native operation.
- **R1901** prepared a bounded shared footprint table for tiled performance.
  That cache remains; replayability and cleanup changes complete its contract
  for the new Fill fields and do not add another performance ID.

## Verification and independent review

`test_v148_rendering_batch25_progressive_order.py` has three methods: actual
component/brush ink, interleaved duplicate occurrences with quota controls, and
the existing-asset public timed plan.

`test_v148_rendering_batch25_native_fill.py` has ten methods covering:

- 120 numeric rectangle-overpaint/flood operations against a dense pixel BFS;
- 12 native geometry/brush cases with widths 1–4, concavity, seals, color
  batching, anisotropic scaling, letterboxing and signed desktop origins;
- a case that distinguishes color-batched contours from per-region interleave;
- the real accepted rectangle's exact counts and preview;
- the existing-asset public executor and complete sampled preview;
- Stop inside flood, retained-Stop workspace ownership and public propagation;
- footprint-cache overflow with identical streamed ink;
- one-shot contour, outer-seal and inner-seal inputs left untouched by cache
  admission;
- actual interval-budget and injected allocation failures preserving the
  meaningful original public base plan.

Before integration, the focused and adjacent rendering gate passed **60
methods in 8.884 s**. Its command, using the current batch25 module names, is:

```text
.venv/bin/python -m unittest \
  test_v148_rendering_batch25_native_fill \
  test_v148_rendering_batch25_progressive_order \
  test_v148_rendering_batch19_native_tiles \
  test_v148_rendering_batch08_fill \
  test_v148_rendering_batch10_physical \
  test_v148_planning_batch03_hybrid -q
```

The final seal-container allowance completion was followed by another passing
targeted replayability regression. The independent runtime reviewer then ran
all **ten final Fill methods in 2.498 s** and found no blocker. That review
checked actual DrawBot color batching, contour/seed mapping, square brushes,
the dense oracle, interval/frontier bounds, retained Stop, cache overflow and
public OOM fallback. Root independently reviewed the progressive-order diff
and its three regressions. Full-suite and platform gates are recorded by the
coordinator; physical Windows/CUDA execution is not claimed here.

After integrating `586e12db`, the combined remote component-queue, batch25
rendering and adjacent physical/Fill gate passed **68 methods in 11.852 s**,
without skips. The existing quality/count/geometry assertions needed no
changes:

```text
.venv/bin/python -m unittest \
  test_v148_rendering_batch24_component_queue \
  test_v148_rendering_batch25_native_fill \
  test_v148_rendering_batch25_progressive_order \
  test_v148_rendering_batch19_native_tiles \
  test_v148_rendering_batch08_fill \
  test_v148_rendering_batch10_physical \
  test_v148_planning_batch03_hybrid -q
```

## Integration and paired planning cost

The concurrent batch24 checkpoint adds the bounded component-selection queue.
At every selection its active list contains the same first 72 pending
components as the original list. Removing the chosen entry and appending the
next unseen entry preserves candidate order, ties, cost-callback order, phase
boundaries and emitted serials. The two fixes in this ledger remain separate
contracts and are renamed R2501/R2502 without changing their implementations.

The historical `PixelAccuracyEngine`, `AdaptiveRegionHybrid`,
`NativeBrushProjection`, `StatefulFillSimulation` and `FillOptimizer` bodies
are byte-identical between the original and integrated baselines. The shared
`PixelStrokeEngine` and root source manifest changed, so final integrated cost
evidence was rerun after the coordinator's source freeze and successful full
regression gate. The final benchmark used an exclusive CPU window with no
overlapping validation jobs.

```text
.venv/bin/python benchmark_v148_rendering_batch25.py --repeats 6
```

The script loads the complete historical `PixelAccuracyEngine` and
`AdaptiveRegionHybrid` modules from `586e12db` into the same current public
`make_plan` caller. Other dependencies are current on both sides. It uses one
warm call each, six balanced AB/BA pairs and separate traced-allocation probes
after garbage collection. Every invocation checks its variant's selected
output fingerprint, including complete source/execution geometry, palette,
counts, previews, path statistics, estimates and relevant accuracy/Fill/cost
metadata. Volatile regional planning durations are excluded.

Timing includes planning, output fingerprinting and owned-image cleanup. It
does not measure mouse input, GUI delivery, physical GPU work or total draw
time. Traced peak bytes cover Python/NumPy allocations, not process RSS or
most native Pillow storage. Source image bytes remain unchanged.

### Final integrated measurements

These observations replace the earlier pre-integration timing table. They use
the formal historical baseline `586e12db`, with the integrated component queue
shared on both sides and all **863 root Python source hashes** unchanged.
Each workload has six before/after samples in `AB, BA, AB, BA, AB, BA` order.

| Existing-asset public workload | Before median ms | After median ms | Elapsed change | Before traced peak bytes | After traced peak bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Timed Pixel, fixed 3 px | 192.995 | 189.762 | −1.675% | 4,593,589 | 4,593,373 |
| Two accepted native Fills | 624.316 | 626.557 | +0.359% | 32,400,528 | 32,424,260 |
| No-Fill control, identical output | 614.637 | 620.020 | +0.876% | 31,724,331 | 31,745,212 |

There is **no general speedup claim**. The timed Pixel median is 3.232 ms
lower, but only three of six paired samples are faster. Accepted Fill costs
2.241 ms more at the median and is faster in only two pairs. The unchanged
no-Fill control costs 5.383 ms more at the median, with three faster pairs.
Before/after ranges overlap in all three workloads. These six-pair samples
do not establish a universal latency change or attribute every difference to
the patches. Exact bucket topology adds CPU work and bounded private
intervals; uncached multi-tile plans may replay it per tile.

Traced peaks change by **−216 B** for timed Pixel, **+23,732 B** for Fill and
**+20,881 B** for the no-Fill control. There is no general memory-reduction
claim at these multi-megabyte scales. The existing no-Fill control's complete
selected output matches across versions. Accepted Fill geometry also matches;
only its diagnostics and preview intentionally change. The timed Pixel
sequence intentionally changes order while preserving the selected occurrence
set in the independent component proof. The final run reverified the
**80% → 100%** protected-detail result, the public Pixel crop's unchanged
accuracy and the public Fill's **666-pixel** missing-coverage correction.

Raw samples, baseline module hashes, both asset hashes, quality observations,
result fingerprints and the complete root Python manifest are in
`docs/v148-batch25-rendering-quality.json`, SHA-256
`3f1f9e88c97f73bda47271d47c91dd97243992ed2918aed6bc29e56dfb945568`.
Independent read-only review recomputed the medians from the raw samples,
checked the quality/parity fields and confirmed all 863 current Python hashes
still match the recorded manifest. Relevant final SHA-256:

| File | SHA-256 |
| --- | --- |
| PixelAccuracyEngine.py | `b0d57d6ecd1655192672eb3126da6c119e070e82b86e58c187566d2e4937a15c` |
| AdaptiveRegionHybrid.py | `f56d48548d029f08eef44646bec638ec343baa223d99c0547ab07b34dc8c19ca` |
| NativeFillSimulation.py | `0cd4834067f3682eb021dad9025128f6a18bc10a763bce8e898b5a7c6a04352e` |
| benchmark_v148_rendering_batch25.py | `e143b39ca51c507f651139d7d1196219b0f33d653389adeb98f659b9a83d14ca` |

No image generation or new image assets were used. All raster inputs are
tracked pre-existing assets; remaining fixtures are numeric geometry data.
