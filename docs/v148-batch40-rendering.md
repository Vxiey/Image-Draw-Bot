# v1.0.148 batch 40 — rendering detail and preparation

## Scope and count

Four independent implementation groups are proposed. The reviewed baseline is
`888116094b91758dded968a7e3b5559683db9ad7`, whose improvement registry contains
846 implemented groups. This ledger does not assign final global IDs or change
the registry. It does not claim that 900 improvements have been completed.

The work changes existing image analysis and planning code. Tests use existing
repository source assets, resized versions, or a palette-only derivative of an
existing detail motif. No new source motif or rendered image artifact is created.

| Local group | Defect or repeated work | Implemented change | Evidence and count boundary |
| --- | --- | --- | --- |
| R4001 | Adaptive Detail detected local contrast only after conversion to luminance. Differently colored details with identical luminance disappeared under simplification. | Compute the local five-pixel range in RGB, then use the maximum channel range as the protection signal. Preserve the existing thresholds, dilation, smoothing choices and alpha restoration. | The existing small-detail fixture, remapped to two colors whose Pillow luminance is 76, loses 10,949 source pixels with the historical implementation and zero with the new one. Preserve, Balanced, Strong and Auto retain that motif. A grayscale source produces the identical historical signal. This is a chromatic-detail fidelity change, distinct from historical transparency restoration and boundary/protection-map fixes. |
| R4002 | Pixel micro-detail analysis allocated full-image neighbor, same-color, boundary and thin-feature intermediates although the computation uses only the four nearest neighbors. | Calculate the unchanged float32 arithmetic in 256×256 output tiles with one-pixel halos. Retain the required full output, and check Stop at each tile and before publication. Small inputs keep the original single-call arithmetic. | Independent scalar analysis and historical function comparison produce exact arrays, including one-row/column, reversed views and tile boundaries. At 1536×1024, measured traced peak is 39,323,264 to 7,996,454 bytes. This is the micro-detail stage's working set, separate from historical luminance/visual-importance scratch work and palette mapping. Stop forwarding completes the existing cancellation contract and does not add another ID. |
| R4003 | Exact vertical component runs dispatched one NumPy transition search per column. | Batch adjacent columns in x-major transition tiles, preserving background gaps, component identities and run order. Use at most 64 columns and target at most 131,072 transition cells, falling back to one column for an exceptionally tall image. | Historical and independent scalar outputs match exactly; the complete serial/parallel component results agree. A 96-column fixture uses four transition searches instead of 96. This changes the distinct vertical extraction pass; historical 845 removed a duplicate horizontal source-group scan. Bounded transition-index arrays add some temporary allocation, which is disclosed below. |
| R4004 | Hybrid scheduling repeatedly rescanned every component of a phase to reconstruct each candidate color's unchanged membership. | Partition each ordering attempt's selected phase into color lists once. Keep cursor-dependent transition costs, cost-model calls, gain tie-breaks, phase resets and retained order unchanged. | The historical and new complete schedules, including metadata, are equal for unlimited and active 30-second controls. Actual 273-component choices require 18,738 versus 11,312 integer color reads, a 39.6% reduction. Timing observations do not establish an across-the-board speed increase. This membership preparation is separate from existing execution-time admission/order policy and prepared path-cost work. |

## Uncounted completion work

`AdaptiveDetail.apply_adaptive_detail` now explicitly owns and closes its
conversion, range, focus, resize and composite images, transferring only the
returned image and protection mask. Stop and retained exception tracebacks
release those owned pixel buffers; the borrowed source stays usable. This is
resource-lifetime completion, not a fifth improvement group.

Independent review found that a retained exception could keep the newly
allocated micro-detail output alive after cancellation. A `finally` boundary
now drops unpublished output, converted input aliases and private tile scratch.
Normal return still transfers the completed array. A retained-error weakref
regression covers Stop after a tile, a later tile's `MemoryError` and Stop after
the small-input result. This review fix has zero additional IDs.

Hybrid orientation selection previously checked containment separately, then
called an exact-coverage verifier which checks containment again. It now calls
the exact verifier directly and forwards Stop into that verifier, including the
unmerged fallback. Exact candidate acceptance is unchanged. This is redundant
verification/cancellation completion and receives no separate ID.

The audit did not alter empty-target accuracy semantics, adaptive brush policy,
palette ownership, GPU score semantics or Fill behavior without a demonstrated
new failing contract.

## Regressions

`test_v148_rendering_batch40_detail.py` contains nine tests covering chromatic
detail, grayscale parity, borrowed/owned Pillow lifetime, retained Stop and
allocation-error tracebacks, independent micro-detail arithmetic, tile limits,
noncontiguous/tiny geometry and cancellation after completed tiles.

`test_v148_rendering_batch40_region_work.py` contains six tests covering exact
vertical output and component ordering, read-only/noncontiguous inputs, bounded
transition dispatch, serial/parallel identity, Stop during run emission,
unchanged real hybrid schedules and Stop at their exact-coverage gate. The
instrumentation wraps real product operations; it does not replace the planner
with a mock implementation.

The initial combined related run completed **130 tests, with one unavailable OpenCL
hardware test skipped**:

```text
.venv/bin/python -m unittest -q \
  test_adaptive_detail_v1038 \
  test_v148_planning_batch04_color \
  test_v148_planning_resources \
  test_v148_colour_batch05_matching \
  test_v148_rendering_batch26_shadow_ownership \
  test_pixel_accurate_v1086 \
  test_v148_rendering_batch39_pixel_runs \
  test_pixel_stroke_engine_v1087 \
  test_pixel_performance_v1089 \
  test_step17_golden_image_regression_v10141 \
  test_axis_region_hybrid_v10145 \
  test_extra_fast_review \
  test_hybrid_renderer3_v10128 \
  test_rc6_region_brush_packing \
  test_v148_rendering_batch40_detail \
  test_v148_rendering_batch40_region_work
```

An additional focused run of the new region tests with existing hybrid candidate
and pack-score regressions completed 15 tests. `git diff --check` passed before
the combined run. The parent integration owns the complete application/release
checks.

After independent review's unpublished-array cleanup, the detail suite plus
`test_pixel_accurate_v1086` and `test_v148_planning_batch04_color` completed
**22 tests**, including the new retained-traceback regression. The final parent
integration run includes that additional test.

## Historical comparison and observations

Run `.venv/bin/python benchmark_v148_rendering_batch40.py` from the repository.
The script loads the exact historical modules from the baseline Git object,
uses actual repository source data, warms both implementations, alternates six
A/B and B/A pairs, and separately measures traced peak allocation. Full raw
pairs and equality hashes are in `v148-batch40-rendering-validation.json`.
Inputs are prepared before the timed stages; allocation results are not RSS.
These initial paired measurements precede the zero-ID retained-traceback cleanup;
the cleanup changes reference retirement rather than numeric output.

| Stage / source size | Before median | After median | Before traced peak | After traced peak |
| --- | ---: | ---: | ---: | ---: |
| Micro detail, 96×64 | 0.445 ms | 0.4375 ms | 180,336 B | 180,336 B |
| Micro detail, 360×240 | 2.1615 ms | 2.2345 ms | 2,162,384 B | 2,137,880 B |
| Micro detail, 1536×1024 | 46.3435 ms | 38.9595 ms | 39,323,264 B | 7,996,454 B |
| Vertical runs, 96×64 | 3.211 ms | 1.630 ms | 238,209 B | 255,869 B |
| Vertical runs, 360×240 | 10.110 ms | 5.6165 ms | 858,641 B | 931,653 B |
| Complete component builder, 96×64 | 15.1135 ms | 13.8935 ms | 722,404 B | 722,196 B |
| Complete component builder, 360×240 | 49.735 ms | 48.5935 ms | 2,280,596 B | 2,325,228 B |
| Hybrid schedule, 96×64, unlimited | 27.457 ms | 28.7535 ms | 294,520 B | 294,744 B |
| Hybrid schedule, 96×64, active 30-second control | 28.4405 ms | 26.438 ms | 347,672 B | 347,896 B |

Every timing row above has exact historical output equality. The complete
component builder comparisons include component fields, both run orientations,
component labels and stable metadata. Hybrid comparisons include groups,
ordered entries, budget/cost choices and schedule metadata. The benchmark holds
other current modules constant to isolate these stage changes.

The larger micro-detail workspace is approximately 79.7% smaller in this traced
observation. Tiling has overhead: the 360×240 case is slightly slower. The
vertical extractor's stage speedup does not translate into the same improvement
in the full component builder; the 360×240 builder also retains 44,632 more
traced peak bytes. Hybrid partitioning demonstrably removes repeated membership
work, but its unlimited case is slower in this six-pair observation. No universal
CPU, overall planner, native drawing-time or GPU speed claim is made.

Chromatic protection deliberately preserves more image detail. It can increase
the protection count or downstream work compared with the former destructive
luminance-only simplification. Quality takes precedence over reducing the
number of strokes.

## Limits

Validation ran on Linux with CPU execution. The OpenCL-dependent test was
unavailable. These results do not claim a live Microsoft Paint/Gartic session,
Windows DPI coverage, native anti-aliasing equivalence or physical GPU parity.
The historical stage comparisons establish exact planning equality for the
performance changes, while the chromatic-detail change intentionally corrects
the source-preservation behavior.
