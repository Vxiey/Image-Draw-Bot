# Batch 27 — single-ink image ownership completion (zero new IDs)

This completes **IW08 / global 582** for the older
`PixelData.monochrome_strokes` consumer. It adds no improvement ID.
That consumer is reached by the actual public planner's current-ink mode,
ordinary black sketch and Sketch Fill contour phases.

## Observed before behavior

The consumer created an RGBA conversion, an RGBA white composite and an L-mode
grayscale image before checking Stop. None had explicit cleanup. A retained
`InterruptedError` from the row loop therefore kept all three private images
open. A failed grayscale conversion kept the preceding two images open. A
preexisting Stop still performed all three allocations and the compositing
work before raising.

The source-bound before probe used complete published commit
`8e0a0e4c61ca0742dfb7857649103477cd307516`. All 873 root Python hashes remained
unchanged; their canonical manifest SHA-256 was
`e4057cf13bd9e97e52b07dbdba90f6962a9bbb012c0c78430d782418d8d0442d`.
It retained actual exceptions and observed real Pillow buffers for RGB and
RGBA inputs, including the public `DrawBotApp.options` → `make_plan` →
`monochrome_strokes` call. Each interrupted 24 × 16 fixture retained the three
open buffers. Grayscale-allocation boundary failures retained the two completed
buffers. The caller's source pixels stayed unchanged.

Six regression methods produced **18 failing subcases and zero errors**
before correction. These are variants of the existing ownership contract,
not separate product improvements. The normal-return ownership tests retain
the created wrappers deliberately to observe explicit close; they do not
claim that ordinary garbage collection permanently leaked those images.

## Resulting behavior

An initial Stop check now runs before image access or allocation. The consumer
uses the existing `read_only_rgba` context: it borrows an existing RGBA source
and closes only a conversion it created. The white composite and grayscale
image have scoped cleanup on success, cancellation and partial failure. Its
native PixelAccess reference is cleared in `finally` before the grayscale
wrapper closes, including when an exception traceback remains alive.

The visible-white alpha composite, Pillow grayscale conversion, threshold of
180, horizontal runs, dots and source-coordinate order are unchanged. The
function still returns a single group and preserves its existing CPU/settings
arguments. Cancellation is rechecked between large operations and before
publishing the completed group. Borrowed input images and the public planner's
returned image and preview remain open for their owners.

## Verification

`test_v148_rendering_batch27_monochrome_ownership.py` covers real RGB, RGBA,
grayscale and palette sources; lines and dots; preexisting Stop; Stop after
real grayscale conversion; failures after compositing and before grayscale
allocation; and actual current-ink/sketch public plans. An independent pixel
membership/maximal-run oracle compares the complete output. Retained errors
and explicitly retained private image wrappers verify cleanup without relying
on garbage collection.

The six new methods and the existing current-ink, public planner/native-input
and CPU white-mask tests passed **32 tests in 1.489 s**, without skips.
Sketch Fill's independent retained-traceback tests also exercise this same
consumer after contour production. The final batch report records whole-source
verification and historical full-plan comparisons. This completion makes no
throughput, RSS or physical-GPU performance claim.

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
