# v1.0.148 Sketch Fill composition — batch 11

Baseline: published batch10 commit
`a8fabbc811029a8bfcbe8a5af2a848b034e5cd89`, tree
`d8941d4c99747e38bb39dea13667e4f6f6b19fd2`.
This area contains **one distinct behavior improvement**, S1101. The combined
checkpoint gates remain pending. This is development work, not a release.

## S1101 — the composed Sketch Fill plan owns its final results

The actual UI accepts Microsoft Paint, Manual settings, Sketch + Auto Fill and
Pixel Accurate together. Sketch Fill intentionally creates a color sub-plan,
then adds its initial contours and final re-outline. Copying that sub-plan's
options retained `_pixel_execution_groups` and its old Pixel diagnostics.
`finish_plan` chose Pixel groups for counts, movement estimates and PreviewSafety,
but chose the new Sketch sequence for execution. The two representations no
longer described the same work.

A real options → public planner reproduction used a 40×32 white image with a
red rectangle at `(7, 6, 32, 25)`, a black two-pixel border, and a one-pixel
brush. The final sequence had six paths: two sketch, three color-fill and one
re-outline. The plan reported three paths and its real executor reported
`3/3` progress while sending all six. The inherited Pixel map reported no spill;
an independent one-pixel Pillow replay of the final sequence found 92 painted
pixels outside its color target. The old Coverage view differed at those same
92 pixels.

`SketchFillRenderer` now removes the color sub-plan's competing compiled
groups/sequence and derived result metadata before finalization. It preserves
the selected color geometry, palette, selectors, calibration, safety settings
and the complete Sketch phase order. `finish_plan` consequently derives its
groups, count, PreviewSafety and timing inputs from the composed Sketch plan.
The general finalizer's dispatch priority is unchanged.

The boolean `pixel_accurate` is deliberately retained. Besides identifying the
inner renderer, it is an existing native delivery hint that limits small-brush
mouse interpolation. Removing it changed the one-pixel case's mouse trace.
The final implementation preserves that delivery policy while removing only
the old compiled owner and its measurements. Keeping the hint does not publish
a Pixel accuracy claim.

## Honest final diagnostics

The final Sketch sequence has not been measured by Pixel Accuracy's target-mask
simulator. Its metadata explicitly declares `pixel_metrics_status=not_calculated`
and explains why the color sub-plan's scores do not transfer to added contours.
Old Pixel coverage/error images, Pixel accuracy percentages and the old
source-relative result are not retained as final results. An exception in the
new source comparison therefore cannot resurrect the inner plan's success.

The ordinary finalizer still generates the actual Sketch phase previews and
recalculates source-relative Visual, Color, Luminance, Hue, Edge, Accuracy error
and ΔE from the final simulated drawing. The real workspace summary and preview
diagnostic formatter omit unavailable Pixel percentages instead of inventing
0% or reusing 100%. The coordinator's narrow `show_previews` change labels the
empty Coverage view **Coverage not calculated** and explains the available
source-relative comparisons. No old Coverage bitmap remains visible.

The temporary options copy is distinct from the color sub-plan's dictionary;
the cleanup only drops its own references. It does not mutate the retained
inner measurement records or close shared image objects. This change makes no
image-allocation or buffer-lifetime performance claim.

## Verification

`test_v148_sketch_batch11_ownership.py` has four tests. They use actual UI options,
the public recursive planner, finalizer, workspace formatter, preview callback
and executor. Native widgets, mouse/ink inspection and telemetry persistence are
replaced at their boundaries; the planner and controller behavior remain real.

- Balanced and Pixel Accurate color plans produce matching final counts,
  groups and safety path counts. An independently calculated movement estimate
  prices the full public sequence under the existing configured timing model.
  The inner Pixel metadata is unchanged.
- Actual plan → workspace/preview callbacks show the six composed paths and
  their three phases, omit stale percentages, display the explicit Coverage
  limitation, and retain the final drawing, ΔE and source-error views.
- An injected failure of the final accuracy evaluation leaves the new result
  unknown, without presenting the successful inner evaluation as current.
- The actual executor retains its phase order, brush width, CanvasGuard checks,
  completed-path count and button release. Its one-pixel Pixel delivery still
  calls the real interpolation helper with the existing 1.5-pixel step.

Before the producer correction, the four-test module reported three failures
and one missing-status error. After the final delivery-policy correction, the
new module plus legacy Sketch Fill, advertised renderer, progressive-summary
and phase-preview regressions passed **42 tests in 0.647 s**:

```text
python -m unittest test_v148_sketch_batch11_ownership test_sketch_fill_v10131 test_v148_ui_batch07_renderer test_v148_ui_batch09_progressive test_v148_planning_batch03_hybrid
```

A separate functional comparison loaded only the baseline Sketch Fill builder
and substituted it into the same current `options` → `make_plan` → `execute_plan`
chain used by the new builder. It required exact equality of the full native
mouse-action lists, execution sequences, source groups, colors/selectors,
fitted geometry, planned raster and main simulated preview. All four cases
passed after preserving the delivery hint:

| Requested quality | Brush | Previous reported paths | Corrected paths / sequence length | Identical recorded mouse actions |
| --- | ---: | ---: | ---: | ---: |
| Balanced | 1 px | 6 | 6 / 6 | 570 |
| Balanced | 2 px | 6 | 6 / 6 | 570 |
| Pixel Accurate | 1 px | 3 | 6 / 6 | 667 |
| Pixel Accurate | 2 px | 43 | 46 / 46 | 685 |

The comparison uses the published baseline only for this local evidence; the
regression suite requires no Git history, network access or real mouse input.
It is not a runtime benchmark or a measurement of target-application ink.

## Deduplication and review

- R1001 avoids an unnecessary regional wrapper after Pixel/Subject policy has
  selected its renderer. Here the color sub-plan is intentionally required;
  Sketch Fill subsequently composes a different final sequence from its paths.
- A1101 clears derived state when rebuilding from the original source during
  a tuner rescue. S1101 is the direct composition boundary, with no rescue
  needed to reproduce the defect.
- UK04 enabled the advertised renderer choice and its settings round trip.
  U903 corrected presentation of each renderer's existing phase counters.
  Neither made the composed execution groups and measurements current.

The producer cleanup, every affected result field, the UI limitation and their
tests are one S1101 group. No separate count is assigned to each field or test.

The platform reviewer independently closed the initial source/test review and
ran 13 new/related tests successfully. The final delivery-policy preservation
delta is also independently closed: the reviewer read the executor policy and
the baseline comparison's complete mouse-action assertions, then ran all four
new tests successfully in 0.310 s with unchanged source/test hashes. No concrete
blocker remains from that review. Product/test source is frozen for the combined
checkpoint gates. This area worker has not staged, committed or published files.

## Frozen checkpoint validation

Batch 11: final frozen-source discovery passed 3,602 tests in 128.751 seconds (43 platform/hardware skips), with unchanged Python and batch-script hashes. Independent source reviews are closed for all four behavior groups. The 5,000-cycle source gate, source-package hygiene and eight exact-raster fixtures passed. Paired pack-selection measurements bind the final source and disclose planning overhead separately from modeled drawing cost. This checkpoint still requires its own Windows/Linux, dependency, CodeQL and packaged Windows checks. No 1.0.148 release is published.
