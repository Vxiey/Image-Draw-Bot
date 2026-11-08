# Batch 29 — complete Portrait source borrowing and image ownership

## Status and classification

**Focused before/after, independent source/test review and complete historical
replay and integrated validation verified. This completes existing
contracts and adds zero improvement IDs.**

R1502/global800 established avoiding two full-source identity copies for already
oriented RGBA in the ordinary `PixelData.prepare_image` caller. DP42/global373
established borrowing oriented inputs while preserving alpha/palette behavior.
The same unnecessary normalization remained in the supported Portrait path.
IW08/global582 owns the private-image lifetime work; PL37/global177 and
CG09/global109 already cover cancellation. Portrait image cleanup was explicitly
an uncounted IW08 completion in `v148-batch03-gpu-platform.md`.

This change extends those existing guarantees to another actual caller. It
does not count copying, Stop, PixelAccess or caller cleanup as separate groups.

## Published before behavior

Baseline is published batch28
`bfa43deb090c9ef858b04313fad9559ec4acfab1`. The scratch probe used the frozen
batch28 checkout, private calibration/runtime directories, disabled bytecode
writes and a write/network audit. All **883 root Python files** were unchanged
before/after, canonical map digest
`74a659994b8f25037a6b233eb05efcafd2f60bffd3fa0de073d3623355c7929c`.

The public chain is actual PNG import → calibrated Paint UI options → current
ink `Auto` or explicit `Portrait / shaded` → `make_plan` →
`prepare_portrait_image`. Ordinary `ImageImport.read_image` and clipboard
normalization already provide an owned, oriented RGBA source. Portrait
unconditionally called `ImageOps.exif_transpose(image)` and then
`.convert('RGBA')` again. Pillow's no-op transpose and same-mode conversion each
copied the full input before compositing, grayscale conversion and resizing.

| Actual public before case | Input → gray / fitted | Paths | Full-source RGBA copies before first resize | Nominal copied pixel bytes |
| --- | --- | ---: | ---: | ---: |
| Imported opaque RGBA, Auto / Balanced current ink | 1024 × 768 → 192 × 144 | 2,848 | 2 | 6,291,456 |
| Imported partial-alpha RGBA, Portrait / High likeness | 1024 × 768 → 192 × 144 | 2,798 | 2 | 6,291,456 |
| Direct RGB compatibility control | 320 × 240 → 192 × 144 | 2,613 | 0 RGBA copies; one full RGB copy | Separate conversion path |
| Direct RGBA with EXIF 6 | 320 × 240 → 108 × 144 | 1,532 | 1 after the required orientation | 307,200 |

The two ordinary imported cases each repeat **6 MiB of nominal pixel copying**.
This is a work observation, not a measurement of native peak memory or RSS.

The same probe recorded **47 direct preparation cases**, four complete public
plans, two lazy PNG/TIFF cases and eight retained-error/Stop cases. The direct
matrix includes opaque, partial and fully hidden RGBA, RGB and grayscale color
keys, LA, indexed transparency, premultiplied RGBa, EXIF transforms, detail-aware
preview and every supported quality on CPU. It saves exact grayscale bytes,
fitted sizes, metadata and full public plan fingerprints.

Two existing ownership gaps were reproduced:

- Stop inside the actual CPU subject-lifting loop closed the private gray
  wrapper, but the retained `_prepare_portrait_image_impl` frame still held a
  readable `PixelAccess` and therefore its native imaging core. Both direct and
  public calls reproduced this.
- Stop immediately after real preparation, before real `portrait_strokes`,
  left the returned 127 × 96 gray image open in the caller's retained
  `_make_plan` frame. That image was private to the public planning operation.

Initial Stop allocated nothing. Native Pillow conversion/resize failures and
the old successful ownership controls already closed their recorded private
wrappers and preserved the caller's source; those controls remain required.

Raw evidence is scratch `pending-batch29-portrait-preparation/before/`, with
full per-case output JSON and grayscale/plan PNGs. Its `summary.json` SHA-256 is
`f59d67ab207fadaae17a42dd7d44271df5630b61f15caaa0c073ef521625fac9`.
The report's `passed` value means the before probe completed and preserved its
source/audit constraints; it does not mean the recorded ownership defects were
passing product behavior.

## Narrow correction

`PortraitPlanner` loads the source before consulting EXIF, applies a real
orientation only when necessary, and borrows an already oriented RGBA input.
Other modes still pass through the existing Pillow conversion. An owned
orientation is closed after conversion when superseded, or after compositing
when it is itself the RGBA source. The caller's borrowed image is never closed
or registered as private.

The existing **white composite → L conversion → resize → contrast and
enhancement** order, all numeric expressions, fitted/sample geometry, GPU
selection and quality settings remain unchanged. Compositing or grayscale is
not moved after resize. Stop is checked between normalization stages so a
cancelled orientation cannot allocate the next conversion.

The CPU subject-lifting loop drops `PixelAccess` in `finally`, including when
a real interruption traceback is retained. In `DrawBot`, the returned gray is
owned from preparation through stroke generation, both finalization call sites,
finite-time fitting and tuner finalization. A `finally` closes it on every exit.
Published plans use their own `gray.convert('RGBA')` result, so the local gray
does not need to remain open after that operation returns.

## Permanent regressions and before provenance

The new `test_v148_rendering_batch29_portrait_preparation.py` contains eight
methods. Explicitly importing that fixture against the frozen baseline gave
**six expected failures across four methods, zero errors**, with all 883 old
source hashes unchanged. Failures cover both actual imported public callers,
post-orientation Stop, both subject-lift Stop paths and public gray ownership.
The four already-correct mode/lazy/native-error/success methods passed.

The first diagnostic test run scoped its copy observer too broadly around all
of `make_plan`, observing two unrelated full-source copies in addition to the
two Portrait copies. Its log and report remain unchanged in `tests-before/`.
The permanent observer was narrowed to the actual preparation call and the
frozen before test was repeated in `tests-before-scoped/`: it records exactly
the two relevant copies. No product code changed to hide other work.

The scoped before summary SHA-256 is
`48adc09219580d512ffa2c05455af39cfbc90eb8f04a9fcf6a79d464dfae76d6`.
After the correction and the caller cleanup, **8/8 methods pass**, no skips,
in **1.533 seconds**. This is test duration, not a performance comparison.
The public regressions now observe zero full-source RGBA copies inside
preparation and compare complete stable public plans against original Pillow
normalization using one shared real calibration context. Image metadata and
EXIF are included; only the seven existing profiler-clock paths are excluded.

| Regression | Preserved behavior |
| --- | --- |
| Imported Auto / Portrait current ink | Actual importer/options/planner, zero redundant preparation copies, full plan/gray/metadata/geometry equality and unchanged source. |
| Modes, alpha, EXIF and detailed previews | Original Pillow normalization controls across RGBA/RGB/L/LA/P/RGBa, keyed and indexed transparency, all EXIF transforms and exact returned pixels/fitted metadata. |
| Lazy PNG and TIFF | Required decode/orientation remains correct; caller image and borrowed stream remain usable. |
| Successful preparation | All recorded private intermediates close; returned gray stays independent and mutable; source remains unchanged. |
| Initial and post-orientation Stop | No initial allocation and no conversion after an actual orientation raises the cancellation signal. |
| Native conversion/resize errors and late Stop | Actual Pillow failure frames remain retained while private images close and the original stays usable. |
| Direct/public subject-lift Stop | Real CPU loop interruption cannot retain a PixelAccess alias. |
| Public Stop after preparation | Actual `portrait_strokes` observes Stop; the private returned gray closes despite a retained `_make_plan` traceback. |

Current focused hashes:

| File | SHA-256 |
| --- | --- |
| PortraitPlanner.py | `5fcb6fc29084d173c734c34808fb0deb150907532c58f24673f37f340a224c67` |
| New regression module | `b385d4d5ba3da043429a36121d28810de76c700fa224f86c69708edb9ed29fb6` |
| Scratch `focused-after.log` | `cc7e5de318276ebb052a1d841cbf594421ac9e5adf54b20c74f609aecfae31bb` |

## Complete historical replay

The untimed scratch verifier loads the **complete published PortraitPlanner and
DrawBot modules together** from the baseline commit. It installs their imports
consistently during each historical call. The remaining current dependencies
are explicitly shared between both sides; this is a comparison of the complete
historical caller/preparation pair, not a claim that every old repository
dependency is installed. Both sides share one actual private calibration
directory, including its path values in the output comparison.

All **47 complete helper pairs and five complete public plan pairs** pass.
Helper equality includes exact L bytes, image metadata/EXIF, fitted sizes,
acceleration metadata and detailed-preview metadata. Public equality includes
all returned fields and image bytes, generated groups/sequence, time estimates,
quality diagnostics and policy metadata; only the seven previously declared
profiler-clock paths are excluded. Actual prepared gray results also match
independently at the handoff.

| Public historical pair | Final paths, both sides | Actual finalization calls before / after | Full-source identity copies inside preparation before → after |
| --- | ---: | --- | --- |
| Imported opaque RGBA, Auto / Balanced | 2,848 | 1 / 1 | 2 RGBA → 0 |
| Imported partial-alpha RGBA, Portrait / High likeness | 2,798 | 1 / 1 | 2 RGBA → 0 |
| Direct RGB compatibility control | 2,613 | 1 / 1 | 1 RGB → 0 |
| Direct RGBA with EXIF 6 | 1,532 | 1 / 1 | 1 RGBA → 0; required orientation remains |
| Active finite-time fitting, 1200 × 900 canvas | 611 | 2 / 2 | 2 RGBA → 0 |

The last fixture requires an actual second finalization pass; it does not
simulate fitting by setting metadata. The imported 1024 × 768 cases each avoid
the observed **6,291,456 nominal copied pixel bytes**, while the 320 × 240 finite
control avoids 614,400. These work counters are scoped only to preparation.

Historical module SHA-256 values are
`e65d88efb26e0b0b5941009d93fd86186c514267a424a8da074e10a858c79b7e`
for PortraitPlanner and
`d0bd7e013299eebb74ee502da5d07fb7012b48818561902c01b8be656abf4ec8`
for DrawBot. The latest replay leaves all **887 current root Python sources** unchanged,
canonical digest
`48245acbd0a159956f998b1009f022a5d7b0245f977f741eef84016c9ffbb4bc`,
with no write/network audit violations. Its scratch
`pending-batch29-portrait-preparation/historical-frozen/summary.json` SHA-256 is
`2d82f2a4cc74c85ffd8ca34f1d7635a0a38f7a8a856f27c1cd6285c3ee8d58c3`.
Complete per-side public JSON and preview PNGs are stored beside it. Private
calibration paths are preserved, so fingerprints from separate probe processes
need not equal each other; the complete outputs within every historical pair
are equal.

The earlier 886-source replay remains unchanged in `historical/summary.json`,
SHA-256 `c4f640e91ba146a434d0579543db0d282c0097bf3f8b3d0d1e3c80aa7c91ad7a`,
with its original source digest
`85d9effac91ba6448bdfe5bda592f01899abcc501b8edab3e1e94f8b31e486eb`.
It is retained as a separate checkpoint rather than relabeled as the latest
source. A second preserved replay, `historical-final/summary.json`, has SHA-256
`49fd2952e550c8ece7b967c323889f398c042bcf28cf62d8c978dd6ea1d39bff`
and the 887-source digest
`00eff844ebd213643fe583cdeb32bf37081a6e768b5a2b7e421a9eba26b97469`.
It included the initial typed ETA seal and the new benchmark file.

After that intermediate replay, the standalone
`benchmark_v148_ui_batch29_estimate.py` received partial-report and exclusive-output
handling. Its hash changed from
`cc01aacbd431548c0d2877330a0d9a5bccf3ed510b469eae511946b35263b864` to
`eb9e8c4cbd9442e317280fd7ced18c6bfc20aa3075c3c8feebfb98472199f9d5`.
That intermediate source inventory had the 887-source digest
`fda7b811a726083ed1881fdc810a0ddd6c354bec7b4215c1cf516e81dbe3edeb`.
The initial ETA measurement then led to a compact representation and an actual
two-pass timing observation. Because that changed a dependency used by public
planning, both image verifiers were run again, producing the final
`historical-frozen` reports above. Their complete 887-source maps match each
other, the final ETA report and the final gates exactly. **No source-map
exemption is used for the final evidence.** The full source/configuration map
contains 937 files with canonical digest
`5c1ad8d0ae71e2223216257fac60478ac054283a8eb05482fd884cb8bd9c331c`.
All earlier reports remain intact with their original hashes and provenance.

[Raw completion evidence](v148-batch29-completion-evidence.json) preserves the
before reports, all three historical checkpoints, scripts, logs and PNGs.
Its documented source-map references and optional deterministic gzip encoding
expand to the exact original parsed JSON; text and PNG bytes remain exact.

## Independent review and limits

The independent caller review is closed: the gray lifetime covers all actual
consumers and closes only the local private L image. Independent Portrait
source/test review is also closed without blockers. Its combined gate passed
**18/18 tests** (the eight new Portrait methods, five new Accuracy methods and
five existing CP06 working-set controls), no skips, in **1.781 seconds**.
The reviewer also checked the scoped before failures and unchanged 883-source
map directly. Independent method/raw review also confirms the complete
historical module linkage, both Git source hashes, 47/5 exact pairs, two actual
finite-time finalizations and the original matching 886-source maps. The final
887-source replay repeats all complete comparisons after the compact ETA
correction. Independent expansion of the completion artifact verifies every
original file and its own source binding; the final image maps need no exception.
Integrated batch gates are recorded below.

No elapsed-time, traced-peak, RSS, physical drawing or physical GPU claim is
made. The benefit asserted here is the observed removal of two redundant
source copies in the supported Portrait caller plus completion of existing
ownership and cancellation guarantees.


## Integrated frozen-source result

Frozen batch29 discovery completed **4,522 tests: 4,449 passed and 73 skipped**, in **240.202 seconds**. All source/configuration hashes remained unchanged. Fourteen real Linux/Xorg native cases, the 5,000-cycle source gate, eight existing-raster fixtures and package hygiene passed. The registry contains **840 distinct groups, 160 remaining**. One independently assessed preview-worker cost-handoff group is registered as R2901. The two image completions add zero IDs.

The completed gates bind **887 root Python files**, canonical SHA-256 `48245acbd0a159956f998b1009f022a5d7b0245f977f741eef84016c9ffbb4bc`, and **937 source/configuration files**, canonical SHA-256 `5c1ad8d0ae71e2223216257fac60478ac054283a8eb05482fd884cb8bd9c331c`. The final image replays use the same 887-file root Python map. [Final validation](v148-batch29-validation.json) records actual test/native/source/raster/package counts, the separate timing scopes, controls and review status. [Raw image completion evidence](v148-batch29-completion-evidence.json) preserves all original checkpoints and diagnostic artifacts without adding IDs. [Final ETA raw data](v148-batch29-estimate-benchmarks.json), [rejected tuple data](v148-batch29-estimate-tuple-diagnostic.json) and [intermediate byte data](v148-batch29-estimate-byte-diagnostic.json) remain separate. Validation separately records the final metadata review and package check after metadata generation. No general whole-pipeline speed or memory reduction is claimed; version 1.0.148 remains unreleased.
