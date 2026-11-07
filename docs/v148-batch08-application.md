# v1.0.148 batch 08 — application image lifetime and preview work

Baseline: `73788a51c1a3502f03f007e4d2ffe0152f56b7e6` (745 published improvements).
This batch contributes **two distinct improvements**, AZ01–AZ02. The capture,
export and estimate integrations below complete existing contracts at zero
additional count. This document is development evidence, not a released build.

## Counted changes

| ID | Previous behavior and evidence | Change and validation |
|---|---|---|
| AZ01 | A successful background-removal cut copied its already-private, oriented RGBA source a second time immediately before replacing alpha. That full-image allocation served no remaining consumer; a 320×240 cut copied 614,400 bytes of RGBA pixel payload across two copies. | Transfer the existing private buffer into the result after all cut/safety checks and write its final alpha there. Borrowed input remains unchanged. Independent expected pixels, RGB/RGBA and partial alpha, EXIF orientation, no-op, Stop and alpha-write failure regressions verify the ownership transfer and cleanup. Successful cut fixtures now make one full RGBA copy (307,200 bytes), while no-op fixtures retain their existing single copy. |
| AZ02 | Every ordinary desktop preview redraw recomputed the visible bitmap and uploaded it to Tk, even when the same immutable accepted image, viewport and canvas were unchanged. Repeating the actual `show_previews` call performed two rasterizations/uploads per image. | Each canvas retains one bitmap keyed by a weak source identity, source mode and normalized viewport geometry. Repeated accepted-image redraws reuse that bitmap; replacement sources, zoom/pan/size changes, closed sources, hidden/destroyed canvases and construction failures invalidate it. Owned intermediate viewport images close after Tk copies their data. The actual controller test retains Original across a new plan and rerenders only the changed result. Public `viewport_image` retains its fresh-render contract for arbitrary mutable callers. |

## Evidence and measurement scope

`test_v148_application_batch08_background.py` contains four ownership and exact
pixel regressions. The rendering reviewer read the full ownership paths and
independently passed those tests. `benchmark_v148_background.py` compares the
unchanged baseline public operation against the new one on four generated
320×240 fixtures, five alternating pairs each. Every resulting image and
metadata object matches exactly. Raw results and source fingerprints are in
`v148-batch08-background-benchmarks.json`.

| Workload | Before median | After median | Before / after RGBA copies | Before / after copied pixel bytes |
|---|---:|---:|---:|---:|
| Opaque cut | 95.220 ms | 95.234 ms | 2 / 1 | 614,400 / 307,200 |
| Partial-alpha cut | 93.459 ms | 95.613 ms | 2 / 1 | 614,400 / 307,200 |
| Already-transparent no-op | 0.334 ms | 0.323 ms | 1 / 1 | 307,200 / 307,200 |
| Uniform-image safety no-op | 89.016 ms | 87.894 ms | 1 / 1 | 307,200 / 307,200 |

AZ01 reduces copied pixel payload; these measurements do **not** establish a
CPU speedup. They are not process RSS, total peak memory or all Python/native
allocations. The other working buffers remain necessary and are not included
in the copy-payload figure.

`test_v148_application_batch08_preview_cache.py` has seven cases, including an
actual Windows Tk bitmap test. Portable tests verify the real controller,
geometry normalization, weak references, failure cleanup and mutable-public-
caller behavior. The UI reviewer independently checked the immutable accepted-
image publication contract and passed the portable related tests. AZ02 proves
avoided repeated raster/upload operations; no native Tk time or universal
preview speedup is claimed. Windows behavior remains a CI gate.

AZ02 concerns the desktop canvas/Tk bitmap. MP01 concerns the separate mobile
PNG publication worker and its bounded queue; the two pipelines do not share
cached raster output or count each other's changes.

## Existing-contract completions — zero additional improvements

- **AW15/IW20:** Capture and Record reject busy, closing and pending profile/clear
  states. Recording rechecks profile identity and captured area after its Save
  dialog. A refused worker start is reported accurately.
- **IW08/IW16/IW17:** A capture window owns and closes its screenshot; child
  destruction does not close the source early. Thumbnail cores close after Tk
  copies them. Toplevel/PhotoImage failures release their owned images. Saving
  uses an independent snapshot in the tracked PNG worker and the existing
  cancellable atomic writer. Stop or encoder failure preserves any old file.
  Eight regressions exercise actual callbacks and worker bodies; platform
  review independently passed 22 new and related cases and closed this review.
- **RP28/RP02:** The final legacy operation summary and canonical ETA use the
  shared retained sequence model for phase and verified-brush reselections,
  custom selector work and once-per-retained-color adaptive verification.
  A custom selector's entire observed duration belongs to `color_change`;
  palette-only selectors belong to `palette_change`. Fill preludes select
  their colors separately from the later stroke sequence. Cold summaries
  reprice contour/seal geometry rather than reusing learned candidate costs;
  `DrawTimeEstimate` applies its existing measured correction afterward.
  Five integration tests cover bounded control-only costing, actual planning, an independently counted
  five-selection sequence, Fill/current-color behavior, and unchanged cold
  ETA across two learned candidate-cache ratios. These complete the previous
  common execution-cost contract, not a new counted group.

No test sends physical mouse input, installs a scanned executable or changes
an antivirus policy. Local regressions do not establish antivirus clearance or
Windows signing status.
