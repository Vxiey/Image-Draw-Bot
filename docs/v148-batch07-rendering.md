# Batch07 — rendering decisions and planning memory

Baseline: `8a9c848b9dd0f2c4738aee729dace75be2a5778d` (published checkpoint,
729 improvements). This batch contains **six distinct new behavior groups**.
The related callers, tests, reports, documentation, cancellation and completion
of existing contracts add no separate improvement counts. Independent source
review of all six groups and the transparent-source caller completion is closed.
The shared product/test source is frozen; the parent whole-project gate remains
pending.

## New improvements

| ID | Reproduced problem | Implemented behavior | Production and independent evidence |
| --- | --- | --- | --- |
| RC01 | Deadline importance sampled stored vertices, so reversing or subdividing an unchanged path could alter its priority, phase and protection. A two-endpoint line also omitted every interior pixel. In an actual source fixture, reversing the same segment changed importance from about 0.391 to 0.841 and changed an optional accuracy stroke into a protected structure stroke. | Stream canonical forward/reverse geometry, remove redundant forward-collinear vertices while preserving turns and backtracking, and sample up to 24 locations at uniform arc-length intervals. Pixel coordinates are deduplicated; the existing mean/high-percentile weighting remains. | `test_v148_rendering_batch07_importance`: independent straight-line score, interior feature, reversal/collinear subdivision, closed and backtracking paths, duplicate/dot/clamped cases and actual `adapt_execution_plan` phase/value/protection equality. Long traversals and the actual caller propagate Stop. |
| RC02 | Shadow analysis copied already-owned float32 luminance/blur/gradient planes and a second full set of five published guidance maps. | Transfer the existing owned float32 planes without redundant `astype` copies. Output planes remain independent of borrowed inputs; formulas and dtype remain unchanged. | `test_v148_rendering_batch07_shadow`: separate finite-difference and neighbor-boundary oracle for all eight maps, thin/empty masks, read-only source inputs and actual `build_pixel_map` map ownership. Paired 512² analysis reduces traced peak by about 24%; all maps and metadata match the baseline exactly. |
| RC03 | Initial deadline admission debited every custom selector before any path was admitted, including empty/unselected colors. A real 32-color, 30-second plan admitted zero paths even though a useful subset fit. The later ordered-cost gate could remove overbudget paths but could not recover candidates rejected at this earlier stage. | Keep unconditional preparation overhead separate from conditional color costs. Debit palette/custom/adaptive-verification setup only when the first path using a color is admitted, then retain the final ordered delivery gate. Empty groups and current-color-only plans do not buy unused color controls. | `test_v148_rendering_batch07_admission`: independent bounded-budget arithmetic, unused-selector invariance, minimum/empty/current-color cases and actual manual 32-color `make_plan`. The recorded source now retains 15 paths with an effective estimate about 29.28 seconds within the 30-second budget. Root's `finish_plan` summary counts the retained execution selections. |
| RC04 | Both fast browser rasterizers unconditionally excluded supplied white groups, even after the source planner had deliberately retained white ink or correction strokes with Skip white disabled. White variants could also be mapped into a colored swatch or lose short fragments. | Preserve explicit supplied white geometry, retain a white anchor within the color ceiling, map white variants only to retained white, and prevent white gap joining or minimum-run pruning. Source white-skipping stays with the upstream source mask. | `test_v148_rendering_batch07_white`: exact independent coverage sets for dots, thin runs and colored gaps; the two-color black/white anchors; white-variant mapping; and both actual `resolve_profile_policy` → `apply_profile_polish` → `make_plan` routes with Skip white both enabled and disabled. |
| RC05 | Background simplification retained a Python `(x,y)` tuple for every reached pixel alongside its existing visited mask, then copied its private RGB image before applying exactly those pixels. | Retain only the component count during traversal. After the unchanged coverage gate, scan membership spans from the existing byte mask and update the owned RGB conversion. Eliminate the full coordinate list and second RGB image copy. | `test_v148_rendering_batch07_background`: independent set/frontier flood oracle, enclosed islands, all mode thresholds at and below the exact boundary, source ownership and actual RGBA `make_plan`. A paired 384² connected-background fixture reduces traced peak about 90% with exact full raster and metadata parity. |
| RC06 | Gartic's dual-axis choice ranked only surviving stroke cost. With minimum run 2, a 36-pixel horizontal blue line was pruned into zero vertical candidates; the empty candidate won as cheaper and deleted the line. Rotating the source caused the corresponding horizontal loss. | Compare retained original-pixel coverage first, then the existing stroke-count and pen-distance cost. Count source interval unions and exclude pixels invented by gap bridging. Preserve the original vertical storage ceiling and minimum-fragment policy. | `test_v148_rendering_batch07_orientation`: 60 independent raster-oracle cases, both orientations and minimum lengths, gap inflation, overlap/storage behavior and actual Gartic Auto-policy plan/preview. Both 36-pixel thin-line fixtures now retain their source and execution pixels. |

## Existing contracts completed, zero additional count

- **CG04 / PB01:** the ordinary application caller now keeps the zero-alpha
  drawable mask after its existing white composition and adaptive/background
  RGB processing. It reapplies alpha 0 only for absent source pixels and alpha
  255 elsewhere; restoring fractional alpha would composite those visible
  colors twice. Entire-canvas Fill is disabled when it would paint an absent
  source hole. Interior Fill validates its actual painted rectangle or exact
  contour spans against that mask before removing fallback strokes; an opaque
  neighboring fill can remain. Extra Fast's hybrid runs this filter before its
  ordering and stateful Fill simulation. Both browser turbos disable gap
  joining for such a source. Eight actual-caller/oracle regressions in
  `test_v148_rendering_batch07_transparency` include alpha values
  `0, 1, 64, 128, 254, 255`, wholly transparent hidden RGB, Dynamic Exact,
  ordinary and hybrid Fill, and both profile-policy routes. Those actual plans
  also rasterize every final execution path into an independent Pillow one-bit
  mask and assert zero centerline hits on absent source pixels. The new Fill
  filter bounds a region's box before expanding its row spans. This completes the
  previously counted transparent-source contract; it is not a seventh group.
- **RP28:** final ordered pricing recognizes same-color phase resets, bills
  their actual palette/custom reselections, and verifies each retained color
  only once. Refcounts refund verification only when the last retained entry
  of that color disappears; the first retained entry carries its scheduler
  cost. Ordinary deadline sequences do not pay for the batch visual verifier
  that their runtime branch skips. Root's application summary follows the
  retained sequence and separately executed Fill selections. Detail Zoom's
  explicitly created verification batches keep their separate runtime rule.
- **RP30 / IW08:** new full-path geometry scans poll cancellation, and the
  actual deadline caller forwards it. Background simplification checks Stop
  during flood and output publication, with the application forwarding the
  existing callback. Owned temporary Pillow images explicitly close on normal
  and interrupted paths; borrowed source images stay open and unchanged.

The registry comparison distinguishes RC01 from map precision/normalization
and previously cached path geometry; it changes sampling of an existing path.
RC02 concerns ShadowDetailEngine's private guidance planes, separately from
the earlier VisualImportanceMap and accuracy-evaluator working sets. RC03
fixes rejection during **initial admission**; RP28 still owns the later ordered
cost/trim contract. RC04 preserves explicit white intent; RC06 prevents
orientation selection from preferring missing coverage at any color. RC05 is
the background **simplification** operation, independently of RB07's rejected
border components in the two **Fill detectors**.

## Focused validation and limits

The seven new test modules contain **43 regression tests** covering the six
groups and the uncounted transparent-source completion. Together with the
adjacent deadline, shadow, source Fill mask, region Fill, hybrid, browser turbo,
adaptive detail, canvas and prior ordered-pricing suites, **142 tests passed in
3.575 seconds**. After adding the delivered-path mask assertions and the bounded
Fill-box guard, the 30 relevant transparency, source-mask and hybrid tests passed
again in 0.832 seconds. Root's independent reviews of all six groups, admission
summary integration and the transparent-source completion are closed without a
remaining blocker. Whole-project validation remains with the parent gate.

```sh
../security-venv/bin/python -m unittest -q \
  test_v148_rendering_batch07_importance test_v148_rendering_batch07_shadow \
  test_v148_rendering_batch07_admission test_v148_rendering_batch07_background \
  test_v148_rendering_batch07_white test_v148_rendering_batch07_orientation \
  test_v148_rendering_batch07_transparency test_v148_planning_batch03_runtime \
  test_v148_planning_batch03_hybrid test_adaptive_deadline_v10118 \
  test_shadow_contour_v10112 test_safe_fill_mask_v1052 test_better_fill_v1039 \
  test_autofill_smart_tools_v107 test_region_fill_v10117 \
  test_gartic_phone_turbo_v1065 test_skribbl_turbo_v1064 \
  test_skribbl_fast_renderer_v1017 test_adaptive_detail_v1038 \
  test_v148_rendering_batch06_canvas
```

Importance is still a bounded sample of a path, not an exact integral over every
source pixel. Canonicalization requires linear scans of long input paths;
there is no performance claim for RC01. The retained-coverage policy in RC06
chooses the fuller candidate; intentional pruning of genuinely short fragments
still applies. Source-alpha tests use exact one-pixel geometry; this is not a
claim that a wide physical brush can never overlap a neighboring absent pixel.
No physical input, screen capture, downloaded executable or actual GPU run was
used in these checks.

## Paired performance measurements

Run `../security-venv/bin/python benchmark_v148_rendering_batch07.py --repeats 5`.
Raw alternating samples, fixture parameters, before/after source hashes,
shared-dependency hashes and exact-output fingerprints are recorded in
[v148-batch07-rendering-benchmarks.json](v148-batch07-rendering-benchmarks.json).
One pair first warms and checks parity. Five alternating elapsed pairs and
separate traced-memory calls follow. The baseline helper is loaded from the
exact published revision; both sides use the same current application caller
and downstream modules. The old simplifier receives a signature adapter for
the new cancellation keyword, with cancellation false throughout the benchmark.
All 25 recorded current helper/caller/dependency hashes were checked again after
the final measurement and still matched the frozen working tree.

| Workload | Baseline median | Current median | Baseline traced peak | Current traced peak | Compared output |
| --- | ---: | ---: | ---: | ---: | --- |
| Shadow guidance, random 512² source/mask | 23.817 ms | 21.779 ms | 16,521,566 B | 12,586,944 B | Exact, all eight maps and metadata |
| Actual PixelMap build, same 512² RGB | 84.495 ms | 82.062 ms | 20,252,214 B | 20,251,964 B | Exact, every PixelMap field |
| Background simplification, 384² with enclosed island | 185.929 ms | 183.977 ms | 10,838,813 B | 1,070,976 B | Exact, full RGB and metadata |
| Background rejected for low coverage, 128² | 1.678 ms | 1.736 ms | 128,465 B | 128,409 B | Exact, full RGB and metadata |
| Actual `make_plan`, 256×192 with fractional/zero alpha | 126.907 ms | 119.967 ms | 4,911,765 B | 4,911,749 B | Exact, source/preview pixels, groups, paths, sequence, counts, estimate and relevant metadata |

The direct shadow peak fell about **24%** and the accepted-background peak
about **90%** in these fixtures. Other stages dominate the complete PixelMap
and application peak, which is effectively unchanged. The PixelMap build was
about 2 ms faster and the application fixture about 7 ms faster in the final
run. An earlier paired run showed a slightly slower PixelMap build instead;
these samples do not establish a general application speedup. The low-coverage
rejection case is slightly slower and has no meaningful peak-memory improvement.

The tracer includes Python/NumPy allocations that Python tracks, and excludes
most native Pillow pixel-core allocation; it is not process RSS. A separate
retained-object regression proves elimination of the second full RGB copy.
Owned returned image fingerprinting/cleanup is included equally in both timed
image/application calls. CPU helpers and generated sources do not establish
Windows input speed, GPU throughput or total real drawing time. Recorded
source/dependency fingerprints must be checked again at the final batch gate.

## Final local integration gate

The frozen source passed **3,355 tests in 71.096 seconds**, with **35 platform/hardware skips** and no failures. Source hashes were unchanged during the run. All independent area reviews are closed. The 5,000-cycle source gate, source-package hygiene and all eight exact-raster fixtures passed, with zero mismatched pixels. Windows/Linux CI on this new checkpoint remains pending; version 1.0.148 is not published.
