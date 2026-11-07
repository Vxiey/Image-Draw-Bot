# Batch 27: complete source-white handling in the legacy CPU planner

Published parent: `8e0a0e4c61ca0742dfb7857649103477cd307516`, with 838
registered improvement groups. This change adds **zero IDs**. It completes
the source-mask-before-color-mapping contract already recorded as **CQ05 /
global 503** in the older `PixelData` route. The existing **CG04 / global 104**
alpha-zero exclusion contract remains covered and unchanged.

## Reachable behavior and before evidence

The real controller's `options()` selects the older `PixelData.build_strokes`
route when RGB nearest, Fast fidelity, calibrated palette, layers Off and CPU
are selected. Auto can instead use `AdvancedColor` while its actual route
selector still chooses CPU. These two CPU paths disagreed about Skip white.

With a real saved and loaded calibration containing black and `(240,240,240)`
but no white swatch, a 64 × 48 white image with a 96-pixel black shape produced:

| Actual public plan | Drawn source pixels | White-background behavior |
|---|---:|---|
| Before, explicit CPU | 3,072 | Selected the gray swatch and painted it |
| Before, Auto selecting CPU | 96 | Left the background undrawn |
| After, explicit CPU | 96 | Left the background undrawn |

The reverse case also failed: a source channel value of 244 was drawable, but
mapping it to a calibrated white swatch caused the older route to omit its
stroke. Both failures followed from testing the selected swatch instead of
the composited source color.

Eight new test methods produced **13 expected failing assertions, zero
errors**, in the before run (1.335 seconds). These were six failing methods
with subcases, not thirteen independent improvements. The skip-disabled and
Stop methods passed, as did the Auto/CPU controls inside the failing methods.
The product under test was byte-identical to the published parent's
`PixelData.py`:

`b56ac3cf09c8e603d0d373a685cf79535b89e370ae371b3aed6e97ca0e51fe31`

This focused before run used the batch27 working tree. Other coordinated
controller work was present; the fixtures explicitly disable the resource
scheduler and do not invoke Mobile Preview. It is not represented as a
full-suite result for the unmodified parent commit.

## Correction

Both the serial loop and the row worker now decide whether a pixel is drawable
from its composited source RGB before looking up the nearest palette entry.
The existing threshold is retained: Skip white excludes a pixel only when all
three source channels are at least 245. Alpha-zero pixels still break runs
even when Skip white is disabled.

The change preserves the nearest-color calculation, stable palette indices,
horizontal run and dot order, thread chunking, serial fallback, cancellation
results and borrowed-image ownership. No controller or accelerated backend
change is required.

## Verification

`test_v148_colour_batch27_cpu_white.py` exercises actual calibration writes and
loads, `DrawBotApp.options`, `make_plan`, and real thread workers. An independent
integer-alpha/source-mask oracle checks every pixel label and reconstructed
RGB raster. The Auto comparison runs the actual selector with a controlled
empty persisted hardware profile; no fabricated accelerated route is used.

Coverage includes both sides of the 245 threshold, mixed RGB channels,
partially transparent pixels composited on white, alpha-zero gaps, lines and
dots, skip-disabled controls, a failure after actual thread row computation
followed by the real serial fallback, and Stop during both serial and thread
work. Source bytes and saved calibration bytes remain intact.

* New focused methods: **8/8 passed**, 1.192 seconds.
* Related gate: **59/59 passed**, 2.872 seconds, including the new methods,
  `test_drawbot`, profile palette checks, actual resource-allocation planning,
  batch03 source masks and batch17 layered mapping diagnostics.
* `git diff --check` passed.

Evidence logs are retained in the task scratch directory as
`batch27-cpu-white-before.log`, `batch27-cpu-white-after.log` and
`batch27-cpu-white-related.log`. No performance benchmark or GPU execution
claim is made. The published parent's separate Windows CI result does not
verify these unpublished changes; the coordinated batch27 gate will do so.

Focused product SHA-256 at the CPU review checkpoint, before the separately
owned batch27 monochrome-image-lifetime completion in the same file:
`24c979b91edeb0d4382fd778c59725d5f8124c9d01359525a6ed14d32ef019ac`.
Test SHA-256:
`ba69774877ae4cab04a0bc1e58b0a075d4b09573300022ac58b0a798ae1a29e5`.

Root independently reviewed both product branches and the actual-flow oracle,
then ran all eight methods: **8/8 passed**, 1.211 seconds, with no blocker.
A second independent source review covered all eight methods, fallback,
cancellation and scalar/worker cache behavior and also closed without a blocker.

## Final integrated evidence

The preserved before observations, initial observer diagnostics and final
source-bound completion checks are published in
[completion evidence](v148-batch27-completion-evidence.json).
The common-source full regression suite, native UI cases, source/raster/package
gates and scope limits are recorded in
[batch27 validation](v148-batch27-validation.json).
The new published commit requires its own Windows/package checks in
[PR46](https://github.com/Vxiey/Image-Draw-Bot/pull/46); the preceding commit’s
CI results are not substituted for those checks.
