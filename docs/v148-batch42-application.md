# v1.0.148 batch 42 — application images, drops and initial settings

## Scope and count boundary

The baseline is public commit
`e33fa67d17e3c33ccda8e736e7e16c2582d9fc06`, tree
`72e55f2a6d3dad971a13e9ab9141aa521cf15177`, equivalent to the local
`b75ef8e` batch-41 checkpoint. All changes below are in the FINAL worktree;
NEXT remained frozen throughout the batch-41 discovery and its isolated
follow-up. The release version remains **1.0.148**.

This ledger proposes **four independent new groups**. Parent integration owns
the global registry and final count. Three RealSpeed callers complete the
already counted N4101 delivery-context contract and receive **zero new IDs**.
Test cases, pages, modes, error paths and allocation measurements are not
separate improvements. This document does not claim that the 900 target or a
passing complete gate has been reached.

| Local group | Reproduced problem | Product boundary | Distinction from earlier work |
| --- | --- | --- | --- |
| A4201 | The mobile queue already owns an RGBA snapshot, but its PNG encoder converts that snapshot to RGBA again. The synchronous API makes the same redundant identity conversion. | `MobilePreview._image_png_bytes` borrows an already suitable source or directly resizes it, then uses the unchanged white composition, RGB conversion and PNG writer. | Earlier mobile queue work deduplicates jobs, snapshots and encoding. This removes a separate buffer inside one necessary encode. |
| A4202 | The captured-screen dialog first copies the entire screen, then reduces that copy to a small preview. | `DrawBotApp.display_screen` reads the full source directly into the bounded display result, using the same Pillow thumbnail dimensions, BICUBIC resampling and reducing gap. | The dialog source still belongs to the existing full-resolution Use/Save workflow. This is its distinct preview preparation path, not general preview rendering or image-import ownership. |
| A4203 | Four existing preview pages were omitted from drop-target registration: quantized target, Delta E, coverage and accuracy error. | Constructor registration now traverses canonical `PreviewViews.VIEW_SPECS`, with one binding per distinct existing widget and the existing import/verified-start callbacks. | One omission across four of twelve pages; no new gesture or extra authorization policy is introduced. |
| A4204 | The first constructor captured generic variable literals and read settings without applying the selected profile's declared defaults. Missing/partial settings therefore gave different initial behavior from returning to the same profile. | Apply the existing `apply_profile_defaults` immediately after the shared fallback snapshot and before `read_settings` and widget construction. | AW09/global623 preserves already established values when fields are absent. Its regression preloads those values. It did not establish profile defaults during the initial constructor. |

## A4201: the mobile encoder reads an existing RGBA owner

The asynchronous queue continues to detach its own source snapshot before
starting a worker. The encoder now reads that owner directly when no reduction
is needed. For an oversized RGBA synchronous input, it resizes the borrowed
pixels directly. Other modes retain their previous conversion order, including
palette/color-key transparency. The encoder closes only a result it created;
neither ordinary completion nor compositor/PNG failure closes the borrowed
source. Stop and stale-publication behavior remain the queue's established
contract and add no ID.

`test_v148_application_batch42_mobile_encoder.py` contains four methods. They
exercise the actual public queue, detached snapshot, worker encoder and image
publication, compare exact PNG bytes against the complete previous pipeline,
retain compositor/encoder failure tracebacks, and cancel an actual blocked
encode. RGB, RGBA, L, LA and P plus color-key inputs cover both size branches.
The only replaced service in the queue test is its unneeded HTTP listener.
All pixels originate in the committed icon asset.

The benchmark measures the complete encoder rather than an isolated convert.
It includes small/bound/reduced RGBA inputs and unchanged RGB/L controls. The
queue's necessary owned snapshot is outside that encoder timing boundary and
still exists. Any reported avoided source-copy payload must not be described
as a universal process-memory or speed reduction.

## A4202: captured-screen display without a pre-reduction copy

The dialog still owns the full capture until destruction. Use creates the same
full-resolution RGBA drawing source; Save snapshots and writes the full PNG.
Only the display result changes how it is prepared. Identity-sized small
inputs still need one independently owned display image; no enlargement occurs.
The existing source and display-result cleanup paths cover PhotoImage failure.

`test_v148_application_batch42_capture_preview.py` contains three methods.
Actual `display_screen` callbacks compare pixels, mode, size and metadata with
`source.copy().thumbnail((800, 480))`. Existing screenshot/icon assets cover
RGB, transparent RGBA, RGB color keys, reduction and small controls. The real
Save callback reaches `_save_captured_png` and its worker task, and the written
PNG is decoded to verify every pixel. The actual Use callback retains full
dimensions and closes the dialog source. A retained bitmap-upload error proves
that both owned images are closed.

Native widgets and Tk bitmap upload are replaced only at the unavailable GUI
boundary. Timing of the actual display method therefore describes Pillow and
Python preparation, not native GUI latency or Windows responsiveness.

## A4203: the same drop flow on all named preview pages

The main window remains import-only. Every named preview page receives the
already implemented explicit canvas gesture, which may request the browser
verification/start workflow. Paint remains import-only on these pages, and an
unready generic target does not gain automatic-start authorization. Missing
legacy widgets are skipped. Aliased widgets, including a root alias, are
registered once. Native registration failure preserves the existing window
fallback and visible status path.

`test_v148_application_batch42_preview_drop.py` contains five methods. It
records actual native registration arguments, then invokes each installed
callback through the real payload parser, `load_source`, `begin_worker`,
decoder and result queue using the committed icon. It checks the accepted
one-shot flag without mutating persistent One-Click state, plus import-only,
busy/closing, missing-widget, alias and registration-error cases. No native
mouse input is sent by these tests.

## A4204: initial profile defaults before persisted values

The first profile is still Other drawing app. Its declared defaults now supply
Conservative background fill and Adaptive exact color workflow before settings
are read. A saved choice still overrides those defaults; absent or invalid
fields retain them. Future-schema protection and unreadable-file behavior are
unchanged. The shared generic fallback snapshot is captured before profile
application, preserving the same reset/switch ordering as before. Traces and
widgets are installed later.

`test_v148_application_batch42_startup_defaults.py` contains three methods.
They execute the actual constructor, settings reader and public `options`
builder while replacing native Tk variable/widget allocation and deferred UI
services. They observe values before widget construction, compare a subsequent
reset/default application, preserve explicit saved values, and keep partial,
invalid and future-schema files byte-identical. No Tcl interpreter is created
or retained by these fixtures.

## Zero-ID N4101 completion: browser throughput follows delivery context

N4101 originally bound operation timing in `DrawTimeCalibration` to effective
native delivery. The separate browser throughput database was still keyed by
profile alone. A completed run could therefore supply path-cap and visible-ETA
evidence after its speed, delay, interpolation spacing or precision changed.
Paint is not a supported RealSpeed producer; this completion corrects the
supported browser paths.

`RealSpeedBudget` uses the existing canonical
`DrawTimeCalibration._delivery_signature`; it does not duplicate the formula.
The completed executor supplies its final options. `apply_budget_policy` and
the visible ETA throughput floor supply their current resolved options. A
matching context can reuse its own measurements; effective aliases share that
context. Unbound historical rows remain readable through the older direct API
but cannot silently bind themselves to a new explicit application request.
An explicitly annotated compatible legacy row remains readable.

New delivery contexts are bounded to 256 entries and the existing one-MiB file
limit. Eviction removes oldest new bound contexts, preserving old unbound and
unrecognized records. If preserved history leaves no room for a valid new
document, publication fails without modifying the existing file. Profile reset
removes the selected profile's unbound row and all bound contexts within its
existing atomic transaction; other profiles remain intact.

`test_v148_application_batch42_delivery_speed.py` contains seven methods,
covering legacy compatibility, changed/equivalent schedules, actual budget and
visible ETA consumers, actual completed execution and persisted context,
profile reset scope, context eviction and byte-limit failure. Its real planner
and executor use a small derivative of the existing icon; the native input and
unrelated diagnostic writers are test boundaries.

Existing reset, calibration-scope and preview fixtures forward the new optional
context argument. The existing post-planning-history test records its actual
plan options. The legacy policy fixture now records explicit options and also
asserts learned use. The batch02 no-reimport test retains its version-1 key but
adds explicit delivery proof; all reset, repeated-read and file-preservation
assertions remain unchanged. These fixture adaptations add no IDs.

## Evidence and current validation status

The five new application modules contain **22 test methods**, all passing in
the serialized application window. The selected adjacent integration also
passed **85/85**, with no skips. Both selections recorded identical before/after
Python source and test hashes. The initial focused attempt is preserved as
20/22: two new fixture expectations were corrected, with no product changes.
The saved-value fixture now explicitly selects Manual settings so Auto policy
does not intentionally override it; the timing fixture checks the corrected
visible `projected_seconds` and separately verifies the unchanged raw sequence
`preview_seconds`. No assertion was removed and no timeout or skip was changed.

Seven independent exact historical function substitutions reproduced all four
new groups and all three N4101 caller omissions as assertion failures, without
errors or skips. The substitutions retained the current surrounding application
and dependencies; they are controlled negative comparisons rather than a full
historical release run. Multiple subtest failures do not add fix IDs.

The two copy optimizations were measured over seven alternating complete-call
pairs after equal warmups. Exact PNG bytes or display pixels matched in all
eight cases, and borrowed source pixels and measured source files remained
unchanged. The medians below retain the slower and unchanged controls.

| Complete operation and existing-asset size | Baseline ms | Candidate ms | Candidate / baseline | Observed source-copy payload, before → after |
| --- | ---: | ---: | ---: | ---: |
| Mobile RGBA 256 × 256 | 29.978 | 25.220 | 0.841 | 262,144 → 0 bytes |
| Mobile RGBA 1600 × 1600 | 579.305 | 593.478 | 1.024 | 10,240,000 → 0 bytes |
| Mobile RGBA 2400 × 2400 | 1692.708 | 1080.841 | 0.639 | 23,040,000 → 0 bytes |
| Mobile RGB 1600 × 1600, unchanged path | 754.376 | 676.609 | 0.897 | 0 → 0 bytes |
| Mobile L 256 × 256, unchanged path | 52.976 | 52.225 | 0.986 | 0 → 0 bytes |
| Capture display RGB 1920 × 1048 | 41.828 | 41.712 | 0.997 | 8,048,640 → 0 bytes |
| Capture display RGBA 1920 × 1048 | 56.530 | 52.479 | 0.928 | 8,048,640 → 0 bytes |
| Capture display RGBA 63 × 37, identity-size control | 0.00921 | 0.01290 | 1.401 | 9,324 → 9,324 bytes |

The four-byte-per-pixel payload is the actual identity-source Pillow copy
observed inside each call, not a total process-memory reduction. Whole-call
tracemalloc peaks are in the JSON; they exclude native Pillow pixel storage.
The fresh subprocess RSS high-water probes all reported zero further growth,
so they establish no peak-RSS reduction. Native widget allocation and bitmap
upload are excluded from the capture display measurement. The unchanged RGB
encoder control varies substantially too, so the timings do not establish a
universal speed improvement. A4201 and A4202 remain narrowly bounded proposed
avoided-copy changes with exact output parity, subject to parent review.

The reproducible evidence tools are:

- `docs/v148-batch42-application-historical.py`: substitutes exact baseline Git
  function bodies independently into the narrow current public-call tests;
  it never edits a checkout. Its complete output is
  `docs/v148-batch42-application-historical.json`.
- `docs/v148-batch42-application-benchmark.py`: complete encoder and headless
  public-dialog comparisons, equal warmups, alternating order, slower controls,
  exact output checks, separate traced-allocation/fresh-process RSS probes and
  source/asset hashes. Its complete output is
  `docs/v148-batch42-application-performance.json`.
- `docs/v148-batch42-application-focused-initial.json`: preserved initial
  20/22 fixture result and raw failure details.
- `docs/v148-batch42-application-focused.json`: final 22/22 in 5.49 seconds
  including loading, exact selection, raw log and unchanged hashes.
- `docs/v148-batch42-application-adjacent.json`: 85/85 in 7.71 seconds including
  loading, covering existing settings, profile/reset, calibration timing,
  actual ETA publication, capture ownership and mobile queue/snapshot paths.
- `docs/v148-batch42-timeout-followup.json`: the six exact worker/helper methods
  that reached their bounds in the initial full41 run, retried in frozen NEXT.
  **6/6 passed**, with no skips or changed assertions/timeouts; all before/after
  Python source hashes matched. The selection took 41.85 seconds including
  loading. These are verification timings, not performance comparisons.

The initial full41 record is preserved separately by parent integration:
4,884 methods, nine failures, one error and 86 environment skips. The six
unchanged isolated passes above do not erase that record or replace the final
complete gate. Native Windows/Tk and physical GPU validation remain outside
this Linux execution environment.
