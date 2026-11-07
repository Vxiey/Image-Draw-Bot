# Batch 28 — Sketch previews use the delivered physical brush width

## Status and classification

**Verified in the focused before/after, independent review and integrated batch gates. This is a zero-count completion, not a new improvement ID.**
The relevant existing contracts are RP38/global552 (Sketch footprint and phase
previews), R1004/global770 (fixed native brush width under scaling),
S1101/global777 (the composed Sketch plan owns its final diagnostics), and
IW08/global582 (owned images and drawing cores on Stop or error).

The user-visible failure was a Sketch + Auto Fill preview that looked more
filled than the actual fixed-width strokes. Balanced commonly plans on a
smaller image, such as 67 × 50 for a 96 × 72 drawing area. Its final and phase
previews enlarged source-grid brush coverage, even though `execute_plan`
transformed the stroke centers and retained the physical brush width.

The correction changes the final `preview`, `sketch2`, `sketch_fill` and
`sketch_fill_final` images. Source-relative Accuracy and delta-E consequently
describe the corrected final image. It does not change the path/color builders,
the executor, physical brush selection, CanvasGuard policy, or native delivery
rules. An existing active tuner consumes accuracy and may consequently make a
different rescue decision; no universal auto-tuner geometry-parity claim is
made outside the fixed controls.

## Concrete published before behavior

The first independent diagnosis used published commit
`8e0a0e4c61ca0742dfb7857649103477cd307516`, with all 873 root Python files
unchanged at canonical digest
`e4057cf13bd9e97e52b07dbdba90f6962a9bbb012c0c78430d782418d8d0442d`.
Its smallest case was the source path `(10,10) → (20,10)` at 67 × 50 fitted to
96 × 72 with a one-pixel physical brush:

- Independent rational center mapping gives native `x=15..29, y=15`: **15
  pixels**. Actual `finish_plan → execute_plan` delivers exactly that bitmap.
- The old preview paints `x=14..29, y=14..15`: **32 pixels**, including **17
  extra pixels**. One path is sent, none is skipped, and the calibrated color
  verification matches.
- This axis case involves no diagonal raster tie, palette alias, alpha, fill
  seed or skipped native action that could explain the mismatch.

The same diagnostic ran actual public options and planners:

| Before case | Planning → fitted size | Sent / skipped | Different pixels | Different RGB values |
| --- | --- | --- | ---: | ---: |
| Single horizontal physical stroke | 67 × 50 → 96 × 72 | 1 / 0 | 17 | 51 |
| Public Balanced RGB | 67 × 50 → 96 × 72 | 30 / 0 | 1,259 | 3,758 |
| Public Balanced RGBA | 67 × 50 → 96 × 72 | 37 / 0 | 866 | 2,587 |
| Public Balanced RGB identity control | 40 × 32 → 40 × 32 | 6 / 0 | 0 | 0 |
| Public Pixel Accurate RGBA identity control | 96 × 72 → 96 × 72 | 16 / 0 | 0 | 0 |

The complete source/plan/action/image evidence remains in scratch
`pending-batch28-sketch-preview/before/`. Its `summary.json` SHA-256 is
`a4fb134bc0cc772104a49d81a3308a41fb87b4be1ee5d0a7969d37b2f3dcc5de`.
The diagnosis preceded this batch and did not modify that published checkout.

### Final direct comparison of the same five cases

The independent after probe copies that scratch script and preserves its
source, calibration, native actions, rational axis oracle and sent/skipped
assertions. Only the checkout/parent/output destination, corrected preview
expectations and audit-hook resolution of relative `dir_fd` cleanup paths
change. Its output directory is exclusive. This is one untimed run against
the final batch28 source on parent
`f800da5785731bbe0b0f8e3908bc330a65ac79c6`, not a performance experiment.

All five cases pass: the axis preview is now **15 pixels**, byte-identical to
the native delivery and independent oracle. All five final preview/delivery
comparisons have **zero different pixels and zero different RGB values**.
The Balanced RGB and RGBA mismatches above therefore change from 3,758 and
2,587 RGB values to zero; the two identity controls remain exact. Comparing
the saved before/after artifacts also confirms identical source and delivered
bytes, native actions and color verifications, groups, selectors, path counts
and fitted sizes for these fixed controls.

The after probe leaves all **883 root Python sources** unchanged, canonical
digest `74a659994b8f25037a6b233eb05efcafd2f60bffd3fa0de073d3623355c7929c`,
with no audit violations. Full per-case PNGs and plan/action metadata are in
scratch `pending-batch28-sketch-preview/after/`; its `summary.json` SHA-256 is
`c04d1c7a377565fe5a84434de238a16e4531868d7977126ece83b5ea0f227d08`.
The script SHA-256 is
`8c335923cd00b5d94e55b0f633333e4bd153b5ccd1fe38ba299a4104601f0a9e`
and `after/run.log` SHA-256 is
`a3bafccb8dc1997ba7c6d6fb5d7b104231c9b33e79e5780d4ad8dda4082f98dd`.

### Permanent regressions against the immediate baseline

The new test fixture was loaded by explicit module path while all product and
existing fixture imports came from the frozen batch27 checkout at
`f800da5785731bbe0b0f8e3908bc330a65ac79c6`. Bytecode writes were disabled. An
audit hook rejected writes into that checkout and any network connection;
calibration and runtime state used private temporary directories.

The first eight methods produced **57 preview byte-equality failures across six
methods, zero errors**. All preceding independent native-footprint, color,
source/sequence preservation and sent/skipped assertions passed. The identity
and phase-publication Stop controls passed before the fix.

After adding the concrete multiple-fragment, precision and in-loop failure
checks, the final baseline run executed **12 methods** with:

- **77 preview byte-equality failures** across eight methods.
- Two additional failed injection expectations because the old source-raster
  renderer does not execute the new physical stamp loop. These are controls
  for the new branch, not evidence that an old nonexistent branch leaked.
- **Zero test errors** and the same two passing identity/phase-Stop methods.

All **881 baseline root Python files** remained byte-identical before and after,
canonical digest
`59de95e5201bf591c7c7118aee9c20e40aa0dbfc020fd5e8714c65ba5903853f`.
There were no write/network audit violations. The complete report is scratch
`pending-batch28-sketch-preview/regressions-before-final.json`, SHA-256
`3b6a582aa5e3dbb0fa8736865db6b012b308aa072f8d4ab002b673d85644974e`.
The initial eight-method fixture and logs are preserved separately.
The final before run used the **12-method** fixture, SHA-256
`4d5c1df86ef94f616951a4b19f00ca36c834293ed1a52e92d0bd4bdbecbfdb93`.
The later thirteenth method checks the new axis branch's existing native
length limit; it is not another historical defect or part of that before run.

## Product handoff and resource ownership

`DrawBot` passes the already prepared `PreviewSafetyPlan`, fitted size and
options to the Sketch renderer. That safety plan contains canvas-local paths
after the existing source transform and edge behavior, with the effective
physical brush width on each admitted entry. The new optional
`retain_phases=False` argument retains an entry's phase only for Sketch's actual
caller. Every admitted fragment receives its originating phase; dropped paths
produce none. Other callers retain their previous sequence keys and metadata.

The Sketch renderer reproduces native precision samples in absolute screen
coordinates, applies the same final point protection, and stamps the physical
square brush along the delivered segments in sequence order. Sampling those
footprints into the fitted preview preserves fractional letterboxes and the
1600-pixel display limit without allocating a full desktop or canvas bitmap.
Both sample axes and the owned output are bounded by the display size.

The same guarded sequence supplies all phase views, including recurring colors,
an entirely rejected phase and one source path split into several admitted
fragments. The renderer does not change the actual execution sequence. Calls to
the old helper signature without the new fitted/safety handoff keep the legacy
source-raster behavior.

On Stop or an exception, newly owned preview images close and the `ImageDraw`
`draw`, `im` and `_image` aliases are cleared. Already created phase images are
retired if a later phase fails. Borrowed source images remain open and unchanged.
A failed optional physical display renderer retains the existing safe-preview
fallback; it does not invalidate the drawing plan or relax input protection.

### Bounded axis work within the same completion

The first physical renderer interpolated long horizontal and vertical segments
into many repeated point guards and overlapping square stamps. The final
renderer uses one equivalent rectangle only when the previous protected point
is the segment's original start, the end also remains unchanged by protection,
the desktop origin is integral and both absolute screen endpoints are at most
`2**31` in magnitude. Those protected endpoints are integer coordinates. Their
monotonic native samples cover the same axis interval inside the existing
convex safe inset; the square-footprint union is the same rectangle, including
negative origins and rounding ties.

The branch still calls `precision_path_count`, preserving the effective
precision step and **100,000-step** rejection boundary. Diagonals, projected
endpoints, fractional origins and larger screen coordinates retain the existing
interpolation path. Stop remains checked around each bounded segment operation
and at renderer completion. No CanvasGuard or executor policy changes.

Two actual public plans compare complete normalized outputs using the saved
pre-axis renderer and the installed final renderer. Both output comparisons
are exact. The following counters cover the four physical preview calls
inside each plan, not every operation in the planner:

| Actual public caller | Paths | Preview calls before / after | Axis interpolation calls / emitted points before | Count-only validations after | Point guards before → after | Rectangle stamps before → after |
| --- | ---: | --- | --- | ---: | --- | --- |
| Balanced RGB, 320 × 256, brush 1 | 10 | 4 / 4 | 1,221 / 15,445 | 1,221 | 15,476 → 1,252 | 15,476 → 1,252 |
| Pixel Accurate RGB, 192 × 160, brush 4 | 421 | 4 / 4 | 4,013 / 24,140 | 4,013 | 25,405 → 5,278 | 25,405 → 5,278 |

The first scratch observation also saved one uninstrumented elapsed observation
per side for each of these two callers. It was not a quiet-window repeated
benchmark, allocation measurement or general speed result. A separate installed
product confirmation records only work counts and complete output parity; it
does not publish further timings. Both keep the same current full public
planning pipeline and dependencies. The confirmation substitutes only the
saved pre-axis rendering function.

| Scratch evidence | SHA-256 | Canonical 883-source map, unchanged within that run |
| --- | --- | --- |
| `axis-work-observation.json` | `55b9a98e6962894f297bc5fce4adc2fef2d38e10cdbcaf221ee6f67fc3722def` | `33a51415bf3d003c909dc29576d29806a44472146243aac1e88bf6842563c6db` |
| `axis-work-after.json` | `0883a31bb927d84b5731b3e1eb58283f506bdda6695670bc69014f14ca41360b` | `73db9cb347c6b63647628d20f51577d91419f1c5b491c2bcfb5fe76e2a49ed5b` |

Both artifacts are in `pending-batch28-sketch-preview/`. The complete saved
pre-axis module `renderer-before-axis.py` has SHA-256
`c69cb03a3cfc85cf7e65e75fdfa540a28366a47552e09a03ac343971452e619f`.
These two observations used the 12-method regression snapshot above. The
subsequent 13-method regression file changes the final source map; the earlier
observations are retained as their own snapshots, not relabeled as the final
integrated source freeze.

## Meaningful focused coverage

The final `test_v148_rendering_batch28_sketch_preview.py` has **13 passing
methods**, no skips. The independent final gate completed in **2.603 seconds**.
The earlier 12-method gate passed in 3.021 seconds; these are test durations,
not a before/after planner performance measurement.

| Control | Actual behavior verified |
| --- | --- |
| Scaled horizontal stroke, brushes 1/3/4 | Independent rational centers and explicit square membership give 15/51/72 physical pixels; actual native delivery and preview match byte for byte. |
| Sketch → fill → re-outline | Actual phase snapshots and final overwrite order match independent physical rasters for all three brush widths. |
| Half-pixel letterbox and signed origin | Positive and negative desktop origins, brush widths 1/3/4, real clipping and one skipped path retain exact delivered and sampled ink. |
| Reduced and full preview | A 3201 × 81 fitted image on a 3202 × 82 canvas is correctly sampled into 1600 × 40, or kept at full size; physical widths are preserved. |
| Public Balanced RGB/RGBA | Actual calibrated UI options → `make_plan` → `execute_plan`, scaled 67 × 50 planning, all four views, source bytes/info, colors and runtime path counts. |
| Identity controls | Balanced RGB 40 × 32 and Pixel Accurate RGBA 96 × 72, brushes 1/3/4, unchanged exact final/phase behavior. |
| Fully rejected re-outline | No phantom final ink appears for a phase outside the brush-safe inset. |
| Multiple admitted fragments | Three source paths become four safe subpaths; the first phase's one polyline leaves and re-enters the inset of an explicit convex canvas. Both fragments retain their phase and the original execution sequence remains intact. |
| Native diagonal precision | Normal/High/Ultra sampling, Pixel brush-step limiting, reversed diagonals and signed origins match actual delivered cursor segments; colors first undergo real axis-based verification. |
| Stop after a phase is produced | The unpublished final/phase images close with the actual interruption traceback retained; the source remains usable. |
| Stop inside physical stamping | Stop follows a real first rectangle stamp; retained images and drawing-core aliases are released. |
| Real Pillow failure inside stamping | After a successful stamp, invalid coordinates enter Pillow's real rectangle implementation. Its retained frame cannot keep the failed image core alive, while the fallback plan and source remain usable. |
| Long-axis native step limit | A real safety plan and renderer admit 100,000 steps and reject 100,001 with the existing native-length error. The accepted physical interval is independently checked in a 9 × 24 output with a negative desktop origin; no full-canvas bitmap is allocated. |

The independent axis oracle calls no product transform, guard, precision or
raster helper, and does not use Pillow's line function. It clips axes against
the documented rectangular inset and writes explicit square membership. Its
separate fitted-crop sampler uses exact rational nearest-cell coordinates and
reads the delivered whole canvas. The public/diagonal oracle runs the real
executor and chooses ink only from clicked calibrated native swatches.

A concave canvas is not introduced as a permissive positive fixture: existing
CanvasGuard deliberately rejects an unverified nonconvex inset. Multiple safe
fragments are exercised through an actual supported convex canvas and a path
that exits and re-enters its safe interior.

The first expanded after-run exposed one test expectation error: this Pillow
version raises `ValueError`, not `TypeError`, for invalid rectangle coordinates.
The preserved log records it. The regression now accepts those two native
coordinate-error types and additionally requires the actual retained
`PIL/ImageDraw.py` frame; no product change was made to pass that correction.

## Review, source binding and limits

The product author ran the original eight-method gate and an **86-method
adjacent gate**, both green, covering old Sketch ownership, selector/execution,
PreviewSafety, Subject and Detail Zoom contracts. The independent reviewer ran
the twelve-method gate and read the complete Sketch, PreviewSafety and
DrawBot handoff diff. The product author separately reviewed the four added
test bodies. After the axis change, the product author ran **98 methods**
(the earlier 12 plus the 86 adjacent methods), all passing in 7.644 seconds.
The independent reviewer then closed the axis endpoint/rounding/precision-limit
and cancellation review and ran the final **13 methods** above. Both reviews
are closed without blockers.

| Focused source | SHA-256 |
| --- | --- |
| SketchFillRenderer.py | `65ef24fad961f02c21bc3f1dd7bfa7658e21f6ae1e0cd1003947b817ca15756d` |
| PreviewSafety.py | `af8dbffe64237c2f99bc8807d0ca83e88e177463740b48a8dbea5c067d233261` |
| DrawBot.py | `d0bd7e013299eebb74ee502da5d07fb7012b48818561902c01b8be656abf4ec8` |
| New regression module | `8d4ccf8d68a7787f1107d8de1e4d99ddde992aa45de45f07eb23fb410d91c9fa` |

The final focused log is scratch
`pending-batch28-sketch-preview/regressions-after-axis-final.log`, SHA-256
`26fd14deddda782260ba9f4cceb480e689d308eb7128db1bf3a9681a3725baa7`.
The earlier 12-method log remains
`pending-batch28-sketch-preview/regressions-after-final.log`, SHA-256
`4ce1a9c7d281db180400a31c54ed289bfac5d26d4a8f3bda7d540efa3bb2e28b`.
No existing batch27 raw benchmark report was changed; its replay is separately
pinned to the published f800 caller graph so this corrected preview is not
silently compared with the old presentation experiment.

This is evidence for the application's existing fixed square-brush model and
actual issued native coordinates. It is **not a physical Microsoft Paint
capture**, a claim about every external application's brush texture, or a
performance/RSS/GPU result. No timing or allocation benchmark is claimed here.
The integrated suite/native/source/package results are recorded below and in
the batch's final validation report.


## Integrated frozen-source result

Batch 28 completes existing Sketch physical-preview and private PNG-snapshot contracts with zero new IDs: **839 total improvements, 161 remaining**. All 839 registry entries and 75 preceding raw benchmark reports are preserved. Frozen discovery completed **4,498 tests in 224.479 seconds: 4,425 passed and 73 platform/hardware cases skipped**. All 933 source/configuration hashes remained unchanged. Fourteen real Linux/Xorg native cases, the 5,000-cycle source gate, eight exact existing-raster fixtures and package hygiene passed on the same 883 root Python sources. Five actual public/controller-to-executor Sketch comparisons now have exact physical-model previews, including the prior 32-versus-15-pixel axis failure and both scaled Balanced fixtures. Native actions and delivered pixels are unchanged in those fixed controls. Corrected Accuracy/delta-E may legitimately change an active tuner rescue decision. PNG export removes one unnecessary identity copy for unrotated private snapshots while preserving decoded pixels, ICC, borrowed inputs, Stop and atomic publication. Historical batch27 replay is pinned to its published caller graphs and adds no timing samples. This is no physical Paint, general speed, peak-memory or GPU claim. Parent f800 has seven green exact-commit GitHub checks; the new published head requires its own Windows/package checks in PR46. Version 1.0.148 remains unreleased.

The common root-Python manifest is `74a659994b8f25037a6b233eb05efcafd2f60bffd3fa0de073d3623355c7929c`; the full 933-file source/configuration manifest is `680f297ff6c85d9e054e26a6b3108ccfe8eeb8c7729bdb891c7ea85e672b2683`. [Final validation](v148-batch28-validation.json) records the exact gates and platform boundaries. [Raw completion evidence](v148-batch28-completion-evidence.json) retains the original observations, logs, fixtures and complete source maps with documented lossless references.
