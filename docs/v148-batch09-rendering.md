# 1.0.148 batch 09 — rendering and executable planning

Baseline: `ab2a59bd1432aac7528d378cef2c4ebcf689a47b` (759 recorded improvements).

This ledger currently proposes **one distinct behavior group**, R901. The
different brush widths, UI integration, numerical and native-input tests,
metadata, cancellation and documentation support that one contract. The Pixel
selector-cost caller correction below completes RP28 and adds **zero** groups.

## R901 — constrain Subject-only drawing by the actual brush footprint

Subject focus formerly forced the requested brush to 1 px. The drawing engine
still selected a real verified brush when the target offered only 2, 4 and 8 px.
Subject-only paths stopped at the selection's edge, but the physical brush
extended outside it. A public 64×64 plan with a 32×32 subject and a verified
2 px brush reproduced **65 outside pixels**. With no verified controls, both
the UI callback and planner silently replaced a declared fixed 4 px width with
1 px in the model even though they could not change the physical brush.

`make_plan` and `subject_focus_changed` now preserve the user's requested width.
After the existing verified-brush assignment, `clip_subject_brush_sequence`
keeps only centers whose complete actual square footprint fits inside the
unchanged Subject-only mask. It reuses RD03's exact morphology and its asymmetric
even-width convention; this is not a second morphology optimization. The helper
splits paths at holes, preserves metadata and source entries, and retains exact
original vertices when the path was already safe. It limits private footprint
masks to two and polls Stop during long paths.

The target mask is never enlarged or reduced to conceal an error. A feature
narrower than every usable brush remains missing in the existing accuracy and
coverage diagnostics. Automatic background-restoring correction stays disabled.
The UI and correction explanation no longer promise a 1 px brush.

Evidence in `test_v148_rendering_batch09_subject.py`:

- Independent Pillow centerline and explicit-square-footprint oracles cover
  readonly masks, holes, off-canvas prefixes, diagonals, backtracking, dots and
  brush widths 1–4. Kept geometry has exactly the expected footprint and zero
  outside pixels; source paths and mask remain unchanged.
- The public verified-2 px plan retains 100% of its 32×32 subject with zero
  spill. A one-pixel-wide, 16-pixel subject has zero executable paths, 16 missing
  pixels and 0% coverage with both the verified controls and a fixed 4 px brush.
- The actual UI callback → `make_plan` → `execute_plan` route preserves a fixed
  4 px brush without controls. A fake native mouse independently paints each
  physical stroke. Both this case and the verified-2 px case exactly reproduce
  the centered subject on a letterboxed 80×64 canvas, at positive and negative
  screen origins. Sent-path counts match, and the mouse is released.
- A long-path Stop raises before publishing a partial sequence. Safe 1 px paths
  preserve their original geometry and metadata exactly.

The earlier subject-selection lifecycle and mask contracts (IW24–IW32),
verified-size selection (PL33), and fitted-canvas placement (RB06) did not
constrain the physical brush against an interior subject boundary. R901 is that
separate executable-geometry correction. It makes no claim about an unknown
target brush shape or speed improvement; the exact square is the application's
existing planning/simulation model.

Independent review: C read the helper and integration and ran the six new tests.
An additional 300 deterministic orthogonal multi-segment cases with holes,
off-canvas prefixes and brushes 1–5 matched its independent footprint oracle
with zero spill. C also reread and closed the final fixed-width/UI delta and
independently ran the new subject tests with the legacy subject suite: 18 tests
passed in 0.373 s.

## Uncounted RP28 completion — resolve selectors before Pixel component pricing

The Pixel Accurate branch had resolved custom selectors locally but attached
them to options only after Block B built its cost model. A real prepared
two-color plan consequently estimated 3.0109 s for components whose retained
geometry and two custom selections cost 4.5709 s. The omitted amount was exactly
two 0.78 s custom-dialog additions.

Pass those already-resolved selectors into the active Pixel cost caller before
building components. `test_v148_rendering_batch09_cost_completion.py` invokes
the public planner with a prepared custom palette and independently totals
retained geometry plus its two actual custom selections. This extends RP28's
existing custom-selection contract to its remaining caller; it is not a new
cost-model group.

## Focused validation

The new Subject-only and selector modules plus the existing subject-focus,
merge, batch08 cost and application-summary modules pass together: **34 tests**,
2.682 s, no failures. `git diff --check` passes. Whole-program frozen validation
is owned by the shared batch checkpoint and remains pending.

## Frozen checkpoint validation

Batch 09: final frozen-source discovery passed 3,514 tests in 190.952 seconds (42 platform/hardware skips), with unchanged Python and batch-script hashes. All four area source reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. The published batch09 checkpoint `3c5fe8fc27ec3b503e2affa6f3ed00cb7856f973` passed complete Windows/Linux regressions, both dependency audits, CodeQL, Windows self-test, bundle build and packaged GUI/native drag-and-drop in [run 42320087469](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42320087469). All four jobs and all seven commit checks succeeded. No 1.0.148 release is published.
