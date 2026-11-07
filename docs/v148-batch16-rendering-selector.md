# v1.0.148 batch 16 — Sketch Fill native contour color

Baseline: published batch15 commit
`d1a5e3a709745ee64263b5801cf1b9089cd6b707`.

This area implements **one distinct behavior group, R1601**. The selector index,
truthful fallback RGB, native execution checks and compatibility cases all
belong to that single group. This ledger records focused development evidence;
the combined batch16 checkpoint and publication are owned by the coordinator.

## R1601 — select the native contour ink described by the final plan

`SketchFillRenderer` composes an initial contour pass, the ordinary Paint color
plan and a final re-outline. A calibrated palette may contain a measured
near-black swatch, such as `(4, 4, 4)`, without any exact `(0, 0, 0)` entry.
This is a valid calibration accepted by `Colors.load_calibration`.

The previous `_black_selector` appended a new contour color to the plan and
appended one selector to the existing selector list. Ordinary palette-only
plans represent their selections implicitly and supply an empty selector tuple.
The added selector therefore occupied index zero while its color occupied index
N. The actual executor found no selector at N, used its normal implicit
`palette_index=N` fallback and clamped it to the last calibrated swatch. The
fallback row also claimed exact black even though its intended native action
could only paint the measured near-black RGB.

### Reproduced before the fix

The new regression loads a real four-swatch Paint calibration:

| Native index | Measured RGB |
| --- | --- |
| 0 | `(4, 4, 4)` |
| 1 | `(255, 255, 255)` |
| 2 | `(220, 30, 30)` |
| 3 | `(254, 175, 168)` |

The source is a 40×32 white image with a red rectangle at `(7, 6, 32, 25)`
and a two-pixel black border. Actual Paint UI options select Manual,
Sketch + Auto Fill and a fixed one-pixel brush. Both **Balanced** and
**Pixel Accurate** run through the real recursive `make_plan`, finalizer and
`execute_plan`.

The native boundary is a test mouse. It chooses its ink solely from the actual
clicked calibration position and paints the delivered coordinates into an
independent RGB image. It never uses the plan's requested RGB to choose ink.
Paint's normal adaptive and strict color verification remain enabled; the
inspection boundary samples the painted image.

On the unchanged baseline, both cases stopped on the first color batch:

```text
RGB (0, 0, 0) could not be verified after adaptive recovery.
Closest rendered RGB was (254, 175, 168) (0% match).
```

The two-test initial module had **two subcase errors** in the real executor;
the independent positive control for an existing custom-black selector passed.
The error was reproduced before changing `SketchFillRenderer.py`.

### Change

When a contour fallback must be added, `_black_selector` first materializes
each missing implicit palette action at its existing color index. It then
appends the new selector at the same index as the new color. The new color and
selector both record the selected native swatch's measured RGB.

The existing append strategy remains in place. Existing color groups and
sequence indexes are not reordered or merged. Explicit palette and custom
selectors retain all their fields, including `source_rgb`, `require_exact`
and fallback policy. An existing exact-black entry returns through the original
branch without introducing selectors into a previously implicit palette.
The darkest-swatch selection criterion and first-index tie behavior are
unchanged. This does not introduce a custom-color dialog or invent an exact
black capability for a palette-only target.

No brush selection, physical width, contour geometry, phase order, CanvasGuard,
verification policy or executor code changes are part of R1601.

## Verification

`test_v148_rendering_batch16_selector.py` contains **five test methods** with
**ten actual public-plan cases**, six of which continue through the actual
executor:

| Cases | Checked behavior |
| --- | --- |
| Near-black native palette, Balanced and Pixel Accurate | Correct native contour/re-outline selection; all six paths complete; both intermediate phase images and final preview match the independent painted RGB image byte for byte. |
| Darkest swatch moved to index 2, fixed physical 4 px, both qualities | First and final selections use the measured dark swatch; the native brush stays 4 px; phase metadata and counts agree with execution; actual final RGB raster equals the preview. |
| Existing exact native black, both qualities | Original palette and empty implicit-selector tuple are retained; actual execution and preview still agree. |
| Prepared custom picture palettes with and without exact black, both qualities | The real UI-to-planner route preserves every existing custom selector and exact-color requirement. Existing custom black is reused; otherwise the appended native row accurately describes the measured swatch. |
| Existing mixed explicit palette/custom selector control | The black index, every selector field and caller-owned inputs are unchanged. |

All actual executions retain native color verification, report every final
sequence path as sent, report zero guard-skipped paths and release the mouse.
The source image and inner plan's color/selector records remain unchanged.
The physical replay uses the application's existing square-brush model with
an independent Pillow centerline; it is not a claim about a particular physical
Paint installation or brush shape.

The new tests passed in **0.538 s**. The following adjacent regression gate
passed **77 tests in 5.090 s**, without skips or failures:

```text
.venv/bin/python -m unittest -q test_v148_rendering_batch16_selector test_v148_sketch_batch11_ownership test_sketch_fill_v10131 test_v148_ui_batch07_renderer test_v148_ui_batch09_progressive test_v148_planning_batch03_hybrid test_v148_application_batch12_brush_contract test_v148_rendering_batch15_sketch_memory test_paint_color_verification_v10122 test_drawbot
```

`git diff --check` also passed. No performance benchmark or speed claim is
associated with this correction.

## Deduplication

- **S1101** removes the color sub-plan's stale compiled geometry and diagnostics
  so final Sketch groups, counts, safety and timing describe the composed
  sequence. Its sequence and palette selections were deliberately preserved.
  R1601 corrects an actual native selector at that separate color-action
  boundary; it does not recount the composition cleanup.
- **R901** and its later completions preserve physical brush width and constrain
  subject geometry. R1601 preserves those contracts and changes only the color
  chosen by an existing native action.
- **RP03** remaps source colors after a capped fast-browser palette replaces a
  swatch. Here the native palette is not capped or changed, and source color
  mapping is not rebuilt. The defect is an omitted selector prefix for an
  appended Sketch-only color.
- **CQ12** merges identical dynamic color actions. R1601 performs no merging.
  The retained duplicate measured RGB row is intentional so established
  sequence indexes remain stable.
- **RP28** selector pricing and **R1501** Sketch scratch-memory work are not
  changed or counted again.

## Source evidence and review

SHA-256 of baseline `SketchFillRenderer.py` from the published commit:
`91c9ff9313961c5194f2c7d664fbbe18f77ba28bc79b9e0928ac370d607220d3`.

Focused implementation snapshot:

| File | SHA-256 |
| --- | --- |
| `SketchFillRenderer.py` | `dfffc8dc6a72475ff2f279e920eb06a30dbd88582127c48541a3fbe644bff265` |
| `test_v148_rendering_batch16_selector.py` | `f4a66f2971fdc75511ce7db4e654ed78d2df364af6ddcff2ff371c107ed4da37` |

Independent root review is closed. The reviewer read the complete producer
diff and actual UI/native oracle, including swatch-driven RGB, enabled
verification, fixed 4 px width and exact preview parity. The reviewer also ran
12 selector/UI/brush-contract tests successfully in 3.143 s; no blocker was
found. Whole-program batch16 gates passed; see [final local validation](v148-batch16-validation.json). Exact published-commit Windows/CI results are recorded separately in PR46.
This area worker has not staged, committed or published changes.
