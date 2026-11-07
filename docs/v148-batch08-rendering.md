# 1.0.148 batch 08 — rendering and executable planning

Baseline: `73788a51c1a3502f03f007e4d2ffe0152f56b7e6` (745 recorded improvements).

This ledger proposes **four distinct behavior groups**, RD01–RD04. CPU/GPU
variants, individual callers, tests, reports, cancellation propagation and
documentation are evidence or completion of those groups. They are not counted
again. The shared execution-cost work below completes RP28/RP02 and adds **zero**
groups.

## RD01 — respect the selected GPU policy in regional reconstruction

`DrawBot.make_plan` routes Extra Fast 2.0 through
`AdaptiveRegionHybrid.build_adaptive_hybrid_plan`. Its reconstructed PixelMaps
formerly called `edge_magnitude(..., gpu_mode='Auto')`, including when the user
had selected CPU or a particular GPU family. A measured OpenCL preference could
therefore open that backend during an explicitly CPU plan. The post-Fill map
had the same issue.

Pass the original policy through both real reconstruction calls and the
`HybridBenchmarkSuite` caller. The shared backend selector remains authoritative;
this patch does not invent a device or alter fallback/health behavior.

Evidence: `test_v148_rendering_batch08_gpu_policy.py` exercises the actual route
selector with controlled saved device evidence and CPU numerical results, then
the public Extra Fast 2.0 planner. CPU never opens the injected OpenCL context;
Auto and forced NVIDIA selection retain their route identities. A separately
injected, exact safe Fill candidate exercises both reconstruction calls. That
fixture isolates propagation and makes no claim about detector acceptance or
physical GPU execution.

This is distinct from SS27 (resource-scheduler classification) and GP03
(explicit-device health/cache identity): the incorrect backend invocation was
inside an active regional planner call.

## RD02 — contrast depends on visible pixels, including transparent sources

The old main planner discarded alpha before calculating contrast. Two RGBA
images with the same visible gray square and fully transparent padding produced
different drawing colors solely because the hidden RGB bytes were black or
white. With contrast 2, the reproduced center changed between RGB 242 and 15.

`VisibleContrast.enhance_contrast` derives the adjustment from the white-composited
visible image. It then uses the existing PB01 alpha-restoration contract to
transfer the visible RGB delta while retaining the original alpha. Identity
contrast preserves every RGBA byte; opaque input remains byte-exact with Pillow's
previous contrast calculation. Owned Pillow images are closed on success and
Stop, and borrowed input stays usable. `make_plan` invokes this operation before
the standard, Pixel Accurate and regional branches.

Evidence: `test_v148_rendering_batch08_contrast.py` includes an independent
integer compositing/delta oracle for alpha 0, 1, 64, 128, 254 and 255, five
contrast factors, exact opaque/identity parity, real public planner outputs and
Pillow ownership checks. The reproduced hidden-RGB inputs now produce identical
source groups, executable groups and preview pixels in all three active routes.
For partially transparent pixels, finite unassociated RGB values still require
clamping: this is not a claim that arbitrary visible contrast is achievable
without changing alpha.

CG04/PB01 originally defined alpha preservation and compositing. RD02 fixes a
different active transform whose *statistics* still depended on invisible color.

## RD03 — bounded exact square-footprint reductions

Regional brush candidate generation repeatedly evaluates erosion and whether a
brush touches remaining pixels. Both helpers formerly created a full ROI shift
buffer for every `(dx, dy)` in the square brush. At width 28, the pair generated
1,568 full ROI shift buffers per invocation.

`AdaptiveRegionHybrid` now performs separable integer rolling reductions. Each
pass uses at most 16 rows × 1,024 columns of explicit int64 work storage
(131,072 bytes), with a carry across column chunks. The boolean output remains a
full map. The exact asymmetric even-width convention is preserved:
`before=(width-1)//2`, `after=width//2`. Outside pixels remain false, inputs remain
borrowed/read-only, returned maps do not alias them, and Stop propagates between
bounded chunks and candidate calls.

Evidence: `test_v148_rendering_batch08_footprint.py` compares against literal
pixel footprints and an independent padded sliding-window reduction, including
thin planes, empty/full/random masks, both chunk boundaries, transposes, reversed
views and brushes 1, 2, 3, 4, 7, 16 and 28. A real verified multibrush `make_plan`
is compared with independent scalar morphology for executable geometry,
preview pixels, quality and candidate decisions.

### Paired measurement

`benchmark_v148_rendering_batch08.py` substitutes only the two baseline
footprint operators into the same current complete planner. Both sides use the
same color, contrast, GPU policy, cost model, scheduler and preview code. It
checks complete output parity before alternating five elapsed-time pairs;
separate runs record traced peaks after garbage collection.

The final measurement was refreshed after the RP28 and Fill integration.
`v148-batch08-rendering-benchmarks.json` records the exact source fingerprints
and raw paired measurements of this frozen checkpoint.

| Workload | Before median | After median | Before traced peak | After traced peak |
|---|---:|---:|---:|---:|
| Both operators, 128×128, width 28 | 6.752 ms | 0.597 ms | 66,657 B | 117,677 B |
| Both operators, 768×512, width 28 | 46.848 ms | 7.228 ms | 1,574,113 B | 1,471,974 B |
| Actual 128×96 multibrush `make_plan` | 111.979 ms | 89.666 ms | 1,847,092 B | 1,849,302 B |

The small-map peak increases because bounded integer work costs more than a
small boolean plane. The larger helper fixture reduces its traced peak, while
the complete planner peak is essentially unchanged. These are Python/NumPy
traced allocations, not process RSS or all native Pillow pixel storage. The
whole-call timing includes identical result fingerprinting and image cleanup.
No claim extends to every image, physical mouse input or hardware GPU execution.

This is a separate operation from prior component retention, background
simplification storage and the PL/CP component traversal optimizations.

## RD04 — produce executable pixel-center Fill contours

Both Fill detector paths emitted cell-edge polygons. Every consuming transform,
native contour gesture and stateful simulator interprets those coordinates as
source pixel centers. A rectangle ending at `(150,99)` consequently emitted a
corner at `(151,100)`. In the actual Extra Fast 2.0 planner, even an otherwise
safe rectangle failed the unchanged one-pixel boundary-halo proof.

Safe rectangles now end at their actual boundary pixel centers. For a general
closed region, each directed unit cell edge maps to its owning in-component
pixel. Convex corners collapse duplicate owners; concave corners connect through
an inside orthogonal pixel. Exact collinear simplification retains reversals,
including a one-pixel spur. The detector chooses a seed in the still-unpainted
interior and requires that one bucket click can reach all of that interior;
disconnected chambers retain their scanlines. Conversion and interior proof are
cancellable through both public detectors.

No halo, brush-footprint or flood escape rule is widened. The final Hybrid Fill
metadata is reconciled with the actually retained regions: rejected proposals
no longer advertise outlines, covered pixels, color batches or saved time.
Their decision entry records fallback and the rejection reason. This reporting
consistency belongs to the same Fill decision group.

Evidence: `test_v148_rendering_batch08_fill.py` tests both real detectors using
independent Pillow line/flood operations for rectangles, L/U/trap shapes and a
one-pixel spur. The resulting one-pixel raster equals the complete intended
source mask, with no spill or missing pixels. Real `make_plan` now accepts the
safe rectangle for both engines, while brushes 2 and 5 continue to fail the
unchanged halo rule with truthful final metadata. Source-alpha holes still
prevent bucket Fill. A fake native mouse rasterizes the actual `execute_plan`
contour, bucket and remaining palette strokes; no desktop input is sent.

The tests prove the discrete one-pixel/1:1 contract, not an unknown target
application's physical brush kernel. Existing runtime CanvasGuard and leak
verification remain authoritative. No timing improvement is claimed for this
correctness change.

Prior PL09 concerns malformed explicit contour validation, PL21 cancellation,
RP11 group clipping and RB07 discarded border-component storage. None repaired
the producer's cell-edge/pixel-center mismatch. Those existing contracts remain
intact; tests and individual shape variants are not separate improvements.

## Uncounted RP28/RP02 completion — actual custom, phase and brush controls

The shared `ExecutionCostModel` now prices the actual retained selections in
Hybrid and Pixel sequences. A phase change reselects its color; a change between
verified effective browser brush controls does too. Unused custom selectors
consume no budget. Adaptive verification is charged once per retained color in
the global sequence, not once for every source color or repeated phase. Fill
selectors outside the sequence receive their own cost.

The runtime records the entire non-palette `select()` call as `color_change`,
before verification and drawing. A learned value therefore replaces the whole
custom selection; it must not receive a second 0.78-second dialog surcharge.
The model's backward-compatible palette/custom portions stay nonnegative. The final-summary and canonical ETA integration uses cold geometry and controls
before measured correction. Warm cached Fill candidate costs are explicitly
repriced for that cold summary. Control-only summaries skip repeated path
geometry work and retain per-row cancellation checks. The model
version and Pixel policy label advance together; the label fix adds no count.

`test_v148_rendering_batch08_costs.py` compares the model with an actual fake
native execution: six paths cause exactly five selections (initial selection,
phase reset, verified brush reset, other color, return). The real 32-color
Extra Fast 2.0 case now retains six paths in the 10-second budget and 22 in the
30-second budget; their tested total model costs, including countdown, are
9.546397 and 29.012416 seconds. Custom selection totals are 3.90 and 16.38
seconds. The independent retained-selection oracle, learned whole-call samples,
current-color mode, unique verification and real Pixel builder are covered.
Timing defaults remain estimates; this does not claim exact physical duration.

## Focused validation and review

RD01–RD03 source/test review is independently closed by root. The platform
reviewer independently closed RD04 and additionally checked 1,500 connected
random-growth shapes against Pillow line/flood: 824 accepted interiors matched
exactly, 676 retained conservative fallback, zero mismatches. Rendering review
confirmed the operation split and found one warm Fill-cache leak into cold ETA;
that leak is corrected and covered by actual-plan tests. Five application cost
summary tests plus six new cost-model and seven legacy ETA tests passed (18 in
0.948 seconds). The shared frozen gate follows. The focused command includes
all five new rendering modules:

```text
python -m unittest test_v148_rendering_batch08_gpu_policy test_v148_rendering_batch08_contrast test_v148_rendering_batch08_footprint test_v148_rendering_batch08_costs test_v148_rendering_batch08_fill
```

Existing neighboring Fill, Pixel, regional budget, source transparency and
runtime cost regressions also run. All broader test totals and the final
benchmark fingerprint refresh are recorded by the shared checkpoint gate.
