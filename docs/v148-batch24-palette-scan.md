# Batch 24 — responsive manual palette analysis

Baseline: `bb6dfa6a5e8a43bfcfc77c9e00f52dc2dfd7db9c`, with 828 registered
improvement groups. The final integration gate is complete; registration is recorded in the batch24 registry.

## Observed problem and behavior change

The actual manual `CalibrationApp.read_snapshot` callback performed palette
component detection, grid sampling and preview construction on the Tk thread.
While that callback was running, the dialog could neither repaint nor handle
Cancel. Automatic browser/Paint discovery already had a separate analysis
lifetime; this manual caller still performed its analysis synchronously.

An actual Tk 9.0.4 dialog on Linux/Xorg reproduced the blocking boundary. A
controlled detector gate waited for a Tk heartbeat, with a 250 ms watchdog to
prevent the old synchronous caller from hanging the probe. Before the change,
the sequence was `scan-enter`, `scan-finish`, `request-return`, `Tk-heartbeat`;
the detector ran on the main thread. The changed caller returned while its
private worker was active, allowing the heartbeat to release the same detector
before `scan-finish`. The selected position, sampled RGB and adopted crop were
unchanged. This is a thread/handoff oracle, not a timing or throughput benchmark.

`PaletteScanWorker` now owns one pure Pillow input, a plain settings snapshot and
an analysis function. The worker performs the existing detector and preview
operations. A locked mailbox owns the result until the GUI consumes it. Only
the GUI poll creates a Tk PhotoImage, updates the preview and adopts the
reviewed colors, crop and target anchor. No Tk interpreter, variable, widget,
GUI callback or exception traceback is sent through the worker mailbox.

During analysis, controls which mutate the draft are disabled and Cancel stays
available. A new crop transfers immediately to the worker; a rescan uses a
private copy because the dialog may close its old displayed crop. Closing the
dialog retires the mailbox without joining a running CPU task on Tk. The worker
checks cancellation and releases late results without scheduling callbacks to
a destroyed interpreter. A completed but stale result is discarded.

## Preserved behavior and failure handling

Preset matching and its geometry-based fallback, generic auto detection,
generic grids and Paint grids retain their existing colors, coordinate order,
duplicate policy, names/indices, notes and preview drawing. Public scanner
functions gain an optional cancellation keyword. Borrowed RGB images remain
borrowed; any required conversion is owned and closed by the scanner.

The existing atomic-adoption contract remains: failed analysis, PhotoImage
allocation or preview presentation keeps the old palette and target. Startup
or poll-installation failure retires its newly owned input. Failure to schedule
a later poll also restores the draft controls and a recoverable error message;
a following scan can succeed. Repeated requests cannot close the current
worker's input. Save, capture, another region selection and Undo cannot mutate
a pending scan.

The retained-error cleanup completes existing ownership rules: PixelAccess,
NumPy/generator aliases and Pillow ImageDraw handles must release their private
native data even when an exception traceback remains reachable. A closed Pillow
wrapper alone is insufficient when a drawing/access handle retains its core.
These cleanups, race cases and failure paths are not separately counted.

## Deduplication and limits

- **CAL05 / 267** concerns cancellation of automatic browser/Paint analysis;
  **CAL52 / 314** concerns the component algorithm. Neither made this manual
  calibration dialog responsive.
- **NR03 / 666** provides helper cancellation, while **CAL10 / 272** and
  **CAL11 / 273** cover countdown/close lifetimes. Their rules are reused.
- **UC01 / 714** already requires atomic palette rescans. Preserving and
  completing that rule adds zero IDs.
- **IW08 / 582** already requires correct image ownership. Private copies,
  cancellation disposal and retained-error cleanup are supporting completions,
  not extra groups.

One new group is proposed for asynchronous manual analysis. Tests, individual
modes, callback branches and cleanup assertions do not increase that count.
A rescan now needs a private full-size image copy. The worker has thread and
polling overhead and does not reduce the detector's underlying CPU work. This
change establishes dialog responsiveness and explicit ownership, not a general
RAM, detector-speed, physical mouse, GPU or Windows-native performance claim.

## Targeted verification

The portable controller/worker suite uses real detector work and mailbox
handoffs. It covers live-draft preservation, background-thread identity,
exclusive input ownership, blocked/closed/stale requests, startup and both poll
failure boundaries, retained errors, all detector modes, cancellation during
conversion/component work and publication/retirement races. Existing atomic
rescan tests retain all their assertions and now wait for the real CPU worker
before delivering its normal GUI poll.

The first combined targeted gate passed **48 tests in 0.114 seconds: 44 passed
and four native/platform cases skipped**. A separate real native run passed
**2/2 tests in 0.733 seconds**, using bounded subprocesses, real CalibrationApp
widgets, actual Tk heartbeats, PhotoImage adoption and the real Cancel button.
No invalid-command, Tcl interpreter-lifetime or ignored-destructor diagnostic
was emitted. These observations are Linux/Xorg evidence; Windows validation
belongs to the future exact-commit CI.

Review found two recoverable boundaries in the initial implementation. Both
were reproduced as failing assertions before correction: a later timer failure
left the status at “Scanning”, and a retained grid-line error kept a native
ImageDraw reference after closing its image. The corrected tests pass with
controls restored and the drawing aliases cleared. The additional scanner
ownership gate, complete historical-module parity, independent review and
frozen-source full-project results will be recorded below once complete.

### IW08 completion: retained scanner and drawing errors

`test_v148_ui_batch24_palette_scan_ownership.py` reproduced **eight failed
assertions across six of eight methods** before the scanner cleanup. A real
unmatched-preset `ValueError` kept a readable native PixelAccess core despite
its closed RGB wrapper. Retained Stop/allocation errors also kept span image
exports, boolean scratch arrays and DFS buffers alive. A real coordinate
`TypeError` in the swatch consumer left its private DFS generator suspended
after yielding a component. The success/borrowed-source control and the
additional genuine Pillow `draw_lines` TypeError control already passed at
that point; the latter used the separately repaired preview finalizer.

After correction, **all eight methods passed in 0.012 seconds**. Tests retain
the actual exception and traceback, inspect whether pixel cores remain
readable, and check weak NumPy/generator references without clearing traceback
frames. Both borrowed RGB and RGBA source pixels stay usable and unchanged.
The genuine Pillow error additionally verifies that `draw`, `im` and `_image`
are cleared on the ImageDraw handle retained inside Pillow's own frame.

The four original algorithm bodies (`_detect_preset_rgb`, `_span_components`,
`_pixel_components`, `_detect_color_swatches_rgb`) are structurally identical
as ASTs inside their added cleanup scopes. No predicate, arithmetic, ordering,
public signature or cancellation point changed in this completion. The
consumer explicitly closes only its own `GeneratorType`; it does not close
borrowed input images. Source SHA-256 immediately before this ownership-only
completion was `4daf75574e59345ee956fbc471416387e5da9e51c9ed1a60409e7ee9c83ba8b5`;
afterward it was `5787aa07b1b4d8649c6e95282a86aab0cd7d093696cc90aa8781063bc7e8bcfc`.
These hashes delimit the cleanup after the asynchronous scanner API had been
introduced, rather than claiming that the intermediate source was the Git
baseline.

The five-module related gate passed **81 tests in 0.399 seconds: 77 passed and
four existing native/platform cases skipped**. It includes the new ownership
and asynchronous scan modules plus the existing calibration image, capture and
UI06 calibration modules. Root independently reviewed the cleanup and all
eight new methods without blockers. This closes existing **IW08 / global 582**
ownership behavior and adds **zero improvement IDs**.

## Frozen final integration

The complete historical verifier passed **54/54 actual controller cases** using
whole `GetColorPositions.py` and `PaletteMaps.py` modules from the published
baseline. It compares the exact full preview bytes, ordered scanner calls,
positions, colors, names/indices, anchors, crop ownership and previous draft.
The only declared delta is the explicit exception-class prefix on worker scan
errors; both original and current status strings remain in the raw report.
Both real game presets, changed-preset fallback, capped/duplicate swatches,
RGB/RGBA, selection/rescan and seven validation/presentation failure routes are
included. Reproduce with `verify_v148_ui_batch24_palette_scan.py`.

The final source snapshot passed **4,308 tests in 205.763 seconds: 4,242 passed
and 66 platform/hardware cases skipped**, with all 900 source/configuration
hashes unchanged. The final combined native gate passed **10/10 in 5.173
seconds**, including both manual scan flows, four Upscale flows, widget timer
disposal and the three older composite pointer/focus cases. No Tcl diagnostic
was emitted. The source gate passed 5,000 lifecycle/profile-isolation cycles;
eight exact existing-raster cases and package hygiene also passed.

The first full gate exposed four subcase failures in one older Sketch Fill
selector fixture: it manually installed prepared colors while leaving its
Calibrated-palette workflow selected. That fixture now reaches preparation
through the real accepted result handler and real plan invalidation. All its
original selector/execution/raster assertions remain unchanged; its ten-case
related gate and the repeated full gate passed. No product rule or new
improvement count was changed to accommodate that fixture.

Independent source, mailbox, ownership and historical-verifier reviews are
closed. Windows and packaged-app validation require the new exact commit CI;
the preceding baseline's green results are recorded separately.

Final parity report: `v148-batch24-palette-scan-parity.json`, SHA-256
`1c7f7b6c6fc98c0a20ff34e0897d2513afb531b73ec9e319ebfb7308f5fbdf25`.

All 850 root Python hashes match the final native, regression, scheduling and
existing-raster checks. Canonical compact manifest SHA-256:
`b8b2992bab94fadacd12d84f874dffc6987183b1dcc6f772e28b532ddc3ed1d8`.
