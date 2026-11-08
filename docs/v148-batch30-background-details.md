# Background cleanup preserves flood-protected detail

**R3001 is registered as global 841 after reviewed integrated gates.** Baseline: published
`4b90b715a9128a022774f411e14e8a1b45676339` (840 implemented improvements).

## Observed user-visible failure

The real **Remove BG** command lost an attached dark feature on a white source.
The actual worker completed normally, the UI adopted its output, and **Save PNG**
exported the same missing detail. This was not a cancelled task, rejected result,
palette approximation or an image-preview discrepancy.

The 100 × 80 source contains a 30 × 30 dark subject with a 20-pixel-long attached
line. The original border flood protects all known foreground pixels. The
following MaxFilter/MinFilter cleanup expands the *background* classification
into the thin line, even though no color, edge or connectivity test accepted that
line as background. Final alpha and metadata then describe the damaged mask.

| Attached feature | Original foreground | Flood removed foreground | Cleanup removed feature | Final alpha-zero feature pixels |
| --- | ---: | ---: | ---: | ---: |
| 1 px wide | 920 | 0 | 20 of 20 | 20 |
| 2 px wide | 940 | 0 | 40 of 40 | 40 |
| 3 px wide control | 960 | 0 | 0 of 60 | 0 |

The observed path is `DrawBotApp.remove_image_background` → real
`begin_worker`/`Thread` → `BackgroundRemoval.remove_background` → queued result →
`DrawBotApp._handle_event` adoption → real `save_png_copy` worker and PNG encoder.
The result was not adopted on the worker thread. The source and Undo pixels were
unchanged, and the exported RGBA bytes exactly matched the adopted image.

The before probe, log, complete metadata, source/result fingerprints and source,
flood-mask, cleaned-mask and exported PNG files are preserved under
`pending-batch30-background-audit/before/` in the task evidence. Its summary SHA256
is `7fb72caab814f24adb29f58f1a7fbe94a101a2615b11a76d1f66dd713088efd1`.
The read-only audit recorded no writes to the frozen checkout and no network
access. All 887 root Python hashes remained unchanged, with compact canonical
map digest
`48245acbd0a159956f998b1009f022a5d7b0245f977f741eef84016c9ffbb4bc`.

## Change and limits

`BackgroundRemoval._cleanup` intersects its newly allocated, byte-sized cleaned
mask with the original border-flood mask before returning it. Cleanup can still
retract a background decision, but cannot add one without the flood's color,
edge and border-connectivity evidence. The input mask remains unchanged. The
same existing Pillow cleanup contexts own the temporary images.

The flood, background clustering, thresholds, morphological filters, proxy
dimensions, feather calculation, original-alpha multiplication and preservation
guards are unchanged. Existing metadata calculations consume the corrected mask;
their reported retained area and foreground box now include the protected
feature. No controller, export or Undo implementation is part of this change.

This protects detail **already retained by the analysis proxy's flood**. It does
not guarantee preservation of every one-pixel feature in an arbitrarily large
source: proxy resizing happens earlier, and the configured feathering still
softens boundaries. A thin enclosed white strip remains foreground because it
is not border-connected; a thin white slot connected to the border remains
eligible for removal. No inference about foreground identity is added.

There is no elapsed-time, total-memory or physical drawing performance claim.

## Counting and earlier contracts

The original RC28/classical remover already describes chromatic contour and
border-connectivity protection. That establishes the expected behavior. An
initial peer recommendation treated the repair as an uncounted completion on
that basis. A subsequent review of all 840 registered entries distinguished the
old product promise from already counted v1.0.148 repairs: no registered group
corrects this morphological mask-classification error.

The final reviewed decision registers **one distinct algorithmic quality
group, R3001/global841**, after the completed integrated gates. All widths, strengths, alpha
cases, holes, metadata and lifecycle controls belong to that one behavior.

Nearby existing groups address different causes:

- **071:** Corner-color sampling/model behavior; not cleanup classification.
- **072:** cancellation boundaries in background removal.
- **IW03:** avoiding unnecessary scalar neighbor-distance work in the flood.
- **IW05:** analyzing the visible white composite instead of invisible RGB.
- **IW07:** bounded alpha-combination scratch and exact alpha rounding.
- **IW08:** disposal of owned images on success, cancellation and failure.
- **AZ01:** transfer of the already-private RGBA result without another copy.

No extra group is proposed for Stop, image disposal, PNG export, Undo or tests.

## Regression evidence

[Six permanent regression methods](../test_v148_rendering_batch30_background_details.py)
cover the actual UI/worker/adoption/PNG/Undo flow; unchanged borrowed source;
all three strengths; RGB and partial-alpha RGBA; dark, light and near-luminance
chromatic contrasts; enclosed thin white holes and border-connected slots;
ordinary subjects and preservation guards; and retained Stop/error exits after
the real cleanup boundary.

The new fixture was imported against the frozen baseline before changing
product code. It produced **31 expected assertion failures in four methods**, two
passing control methods and **zero errors**. The fixture SHA256 was
`bd1770c5577603b8b6025661a0caa5fbaa603e8a20dc6d3f26dbaeef19f7db61`;
the 887-file baseline map and write/network audit remained unchanged.

After the change, the same six methods passed in 0.477 seconds. The focused
combined gate passed **37 tests in 0.680 seconds**, including the original
classical/RC28 remover cases, IW01–10 work/visibility/safety checks and AZ01
ownership regressions. These are test-run observations, not performance
benchmarks. Independent source/test review is closed without blockers.

## Complete historical controls and actual after artifacts

The final untimed follow-through repeats the same three actual UI/worker/PNG
fixtures. It retains every source, Undo, output-identity, export and flood
assertion from the before probe, then requires no newly classified foreground
and no fully erased attached feature. All three pass.

| Feature | Before cleanup removed | After cleanup removed | Before final alpha-zero | After final alpha-zero |
| --- | ---: | ---: | ---: | ---: |
| 1 px | 20 | 0 | 20 | 0 |
| 2 px | 40 | 0 | 40 | 0 |
| 3 px control | 0 | 0 | 0 | 0 |

The 3 px result remains byte-identical, including the exported PNG SHA256
`2a012da76bd53ca0c79daa39d8837f79cfe433fb9eaf765f65c33149bd95c15f`.
At the unchanged default feather setting, all twenty 1 px feature pixels are
softened but visible; two pixels of each wider feature are softened. These
observations are not a promise of fully opaque one-pixel edges.

The separate historical verifier loads the **complete published
`BackgroundRemoval.py` module**, sharing the same current Pillow/NumPy
dependencies. It verifies that every other product AST node is unchanged, then
compares whole image representations and complete metadata without excluded
fields. Twenty ordinary/3 px/partial-alpha/no-op control pairs are exact.
Twenty-four thin-feature cases across the three strengths, opaque/partial alpha
and zero/default feathering show the intended correction. All 44 pairs preserve
identical complete flood outputs, including all three returned arrays and
counters; source pixels and metadata are unchanged. Source and both result PNGs,
full per-case metadata and hashes remain in the raw evidence.

| Evidence | SHA256 |
| --- | --- |
| `pending-batch30-background-audit/after-initial/summary.json` (three actual UI/PNG cases) | `e51fad63d832d31069c0feda664dac2850f4a01830843498202be1ed136f9c03` |
| `pending-batch30-background-audit/historical-initial/summary.json` (20 exact controls + 24 corrected cases) | `fb361aa7dc8a916e24b98d17125c05c34f7fd8946a4d9195dedf2d0af7a33500` |
| Complete historical product module | `4b5eb0d5b03dde9572489cb97f852058b31b9f28d6b5fe8f0619f1ea39973f1d` |
| Corrected product module | `213262b4f93846a4325acc22716628012f361c87484d91eef98008ce99f2a60a` |

Despite their preserved `-initial` directory names, both completed runs bind the
same stable 892-file root Python map:
`ce9691bce3bdb6b6e992ab3383b323e803f85e8df95c6a99ff6f409a9d345abd`.
Each before/after source map is identical and each write/network audit is empty.
The image evidence is untimed; it makes no memory or speed claim.

The completed integrated result and explicit count decision are recorded below.


## Integrated frozen-source result

Batch 30 records **842 distinct improvements, 158 remaining**. 2 new behavior groups are registered: R3001, R3002. Background cleanup preserves detail already protected by the border flood; picture-palette growth avoids retesting unchanged centers. Portrait stroke ownership, Stop across image-copy handoff and test-fixture Tcl disposal complete existing contracts with zero IDs. All 840 prior registry entries and 78 earlier benchmark JSON reports are preserved. Completed frozen discovery ran **4,551 tests in 231.751 seconds: 4,478 passed and 73 skipped**; all 943 source/configuration hashes were unchanged. Fourteen Linux/Xorg native cases, the 5,000-cycle source gate, eight exact raster fixtures and initial package hygiene (1,359 files) passed. The package check after final metadata passed with 1,361 files and no warnings. The incomplete process attempts and the Tcl-aborted attempt remain negative evidence. A proved old calibration fixture released borrowed Tcl aliases after real cleanup; no product GC policy, skip, assertion or timeout was weakened. The final background and Portrait historical comparisons and the six-workload/six-pair palette measurement retain their original 892-file map; the final 893-file map differs only in the two explicitly recorded fixture files. Historical checks retain 20 exact background controls and 24 intended corrections, 14 Portrait helper and seven public pairs, and 32 palette comparisons including four public plans. The cold red picture-palette helper and direct refinement improve in all six pairs; unchanged-work controls are not treated as algorithm gains. No universal speed, peak-memory, process-RSS, physical Paint or GPU improvement is claimed. Parent 4b90 has seven green checks after one unchanged Windows-job rerun; the new head requires its own exact-commit CI. Version 1.0.148 remains unreleased.

The final gates bind **893 root Python files**, compact SHA256 `0da8de7641efb47fea77c62ece22629b27f9425c137e9d8ccd8d7e9933ae5845`, and **943 source/configuration files**, compact SHA256 `5f6b89f5b52c9ae6f0335345f744fb887936afdab1e847eb5c22d73f3c155b41`. The original measured/evidence map remains **892 root files**, SHA256 `ce9691bce3bdb6b6e992ab3383b323e803f85e8df95c6a99ff6f409a9d345abd`. The only later differences are the old calibration fixture cleanup and its new subprocess regression; their exact sources, hashes, import boundary and diff are recorded in [raw evidence](v148-batch30-completion-evidence.json) and [final validation](v148-batch30-validation.json). No timing or image checkpoint is silently rebound. The final metadata review and post-metadata package check are recorded separately; publication of the new head does not imply its remote checks have completed.
