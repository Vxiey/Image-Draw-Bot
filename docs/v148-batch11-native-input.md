# v1.0.148 native input — batch 11

Baseline: published batch10 commit
`a8fabbc811029a8bfcbe8a5af2a848b034e5cd89`, tree
`d8941d4c99747e38bb39dea13667e4f6f6b19fd2`.
This area contains **one distinct behavior improvement**, N1101. Independent
source review is closed; the combined checkpoint gates remain pending. No
release is implied.

| ID | Reproduced previous behavior | Correction and evidence |
| --- | --- | --- |
| N1101 | `CanvasTransform.point` rounded mapped half-pixel centers away from zero. A 130×130 source in a 130×131 canvas therefore delivered a different raster when moved between positive and negative desktop coordinates. Ten horizontal one-pixel strokes crossing screen Y0 left local row65 blank; the transposed case also left a column blank. The actual executor sent the paths without CanvasGuard skips, so this was a coordinate conversion defect rather than omitted work. | Round mapped canvas centers to their nearest integer with one tie direction, toward the higher integer, on both sides of zero. Compare the fraction to½ instead of adding0.5 or using an epsilon. `test_v148_native_batch11_coordinates.py` reproduces the failures before the fix and checks both axes through real `make_plan` and `execute_plan`, replaying the emitted mouse actions with Pillow. Positive, negative and zero-crossing origins now produce the same contiguous raster. |

## Contract and scope

Only `Precision.CanvasTransform.point` changes in production. Its continuous
`float_point` calculation is retained. The standalone `round_screen` function
and the interpolation/counting contract of `precision_path` remain unchanged.
The same transform is already consumed by the native executor, PreviewSafety
and NativeBrushProjection, so their mapped centers follow one policy.

Normal integer mappings and ordinary positive-coordinate mappings retain their
pixels. Exact mapped half ties use the higher neighboring integer consistently;
for example, −0.5 maps to 0 and +0.5 maps to 1. Tests also check adjacent fitted
floating-point values against an independent exact-fraction rounding oracle.
No guessed tolerance shifts a value across a nearby boundary.

All native authorization, target validation, CanvasGuard and button-release
paths remain in the existing executor. The actual delivery tests use a mock
mouse and no-wait clock; they send no real desktop input. They verify that the
requested one-pixel brush remains one pixel, every planned path is sent and no
guard skip is hidden. The tests do not claim observation of ink in a real target
application.

R1004's two fixtures that deliberately documented the old signed half-tie gap
are updated to require the corrected continuous raster. Their independent
physical target, missing/spill counts, full-canvas Coverage and fitted-preview
comparisons are preserved. An odd half-pixel placement can still differ from
the ideal nearest-source target at its outer edge; those diagnostics remain
truthful rather than claiming universal zero error.

## Deduplication

- RB06 established the full-canvas placement and guard coordinate frame.
- R1004 made the physical simulation match delivered coordinates and explicitly
  left native input unchanged. This change corrects those delivered coordinates.
- PL07 optimized movement counts while retaining the existing interpolation.
- UI16 and RT01 validate signed native coordinate bounds.

None of those earlier groups corrected the signed half-tie discontinuity in
the actual input transform. Both axes, shared consumers and adjusted historical
fixtures belong to this one N1101 group; tests and documentation add no counts.

## Verification

The six new tests cover exact ties, adjacent fitted values, integer-translation
properties, ordinary mappings and actual public planning/execution. The two
end-to-end tests each cover three margin widths and three desktop origins:
18 real planner/executor scenarios in total. Independent action replay checks
the full delivered rectangle, and R1004's oracle checks reported coverage and
the public diagnostics for letterboxed plans.

Before the correction, the focused tie test and both actual axis tests failed
with nine failing subcases. After the correction, the new module, all R1004
physical tests and the legacy precision module passed **25 tests in 2.533 s**:

```text
python -m unittest test_v148_native_batch11_coordinates test_v148_rendering_batch10_physical test_precision_v102
```

Related shared-transform, guard, safe-fill and planning consumers passed
**48 tests in 0.308 s**:

```text
python -m unittest test_v148_rendering_batch06_canvas test_safe_fill_mask_v1052 test_v148_planning_integrity test_v148_planning_batch03_runtime test_canvas_guard_v1047 test_canvas_guard_safety test_rc4_brush_canvasguard
```

Independent review by the rendering owner is **closed with no concrete
blockers**. The reviewer followed the transform through `execute_plan`,
PreviewSafety and NativeBrushProjection, checked the unchanged generic rounding,
interpolation and guard/brush contracts, and independently reran the same
25-test focused selection: **PASS in 3.267 s**. The reviewer also accepted the
single-group count and its distinction from RB06, R1004 and PL07.

`git diff --check` passed. This area's production and test files are now frozen
for the combined checkpoint verification.
There is no performance claim. The area worker has not staged, committed or
published any files.

## Frozen checkpoint validation

Batch 11: final frozen-source discovery passed 3,602 tests in 128.751 seconds (43 platform/hardware skips), with unchanged Python and batch-script hashes. Independent source reviews are closed for all four behavior groups. The 5,000-cycle source gate, source-package hygiene and eight exact-raster fixtures passed. Paired pack-selection measurements bind the final source and disclose planning overhead separately from modeled drawing cost. This checkpoint still requires its own Windows/Linux, dependency, CodeQL and packaged Windows checks. No 1.0.148 release is published.
