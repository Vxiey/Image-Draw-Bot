# v1.0.148 batch 25 — widget, worker and calibration lifetime completion

Initial development baseline: `bb6dfa6a5e8a43bfcfc77c9e00f52dc2dfd7db9c`
(828 recorded improvements). The completed work was then integrated onto
`586e12db5ea5142951c844f60dc2364f07a01c37` (830 recorded improvements),
preserving the concurrent batch 24 changes as described below. This work
completes existing button/window lifetime,
A1501/BA01 cancellation, image ownership and profile-isolation contracts. It
adds **zero improvement IDs**. No image was generated or exported for these
regressions, and no rendering-speed or physical Windows drawing result is
claimed.

## Retire a button's delayed pointer animation before deleting its commands

The preceding Windows job
[`128495385074`](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42403249179/job/128495385074)
reported five `invalid command name ..._click_animation` background callbacks
between `2026-11-07T18:54:45.778Z` and `18:54:45.864Z`. The exact command names
were `2458597756096_click_animation`, `2458637355008_click_animation`,
`2456750303488_click_animation`, `2456750294656_click_animation` and
`2456750302400_click_animation`.

They appeared while the following native switch-row test was pumping the
interpreter. The preceding
`test_button_canvas_and_late_text_image_labels_keep_pointer_to_key_activation`
had released the pointer on **one button five times**: its canvas, original
and recreated text label, and original and recreated image label. Each
CustomTkinter 6 pointer release schedules a separate 100 ms animation on that
button. The test then explicitly destroys the child before destroying its
parent root.

`KeyboardButton.destroy` previously cancelled only the keyboard-idle job.
Its inherited destruction deleted the five Python/Tcl animation commands,
leaving their delayed Tcl scripts pending. A later scoped-root destruction
cannot discover an already removed child in the root's live subtree.
The product now calls the existing `cancel_widget_after_jobs(self)` before
inherited destruction. Only exact single-command jobs owned by that widget
subtree are retired; another button's animations and unrelated root timers
remain. Neither CustomTkinter globals nor Tcl error reporting is suppressed.

The log adjacency and five-release source path identify the responsible
lifetime defect; the original run did not record a retrospective Python
object-to-command mapping. The portable reproduction registers five actual
Tcl `after` jobs on the actual `KeyboardButton` method and checks their removal,
command deletion, survivor execution and absence of background errors. It
substitutes native window allocation/destruction, using real `tk.Tcl` and
`tk.Misc.destroy`. Before the fix its one runnable method failed with all five
owned timers still pending; its two native methods were skipped locally.
Record: `batch24-button-lifetime-before.log` in the parent scratch directory.

Two isolated native methods use the actual `create_root` and `StudioUI.button`
factories. They exercise repeated pointer releases with an unrelated live
button and a command that destroys its own button, then drain the native event
loop and check callback errors. The implicated older native pointer-focus test
also now asserts that its owned scripts are gone immediately after child
destruction. These native checks require Windows or an available Tk display;
this local environment has neither a supplied display nor a usable local X
server. The Windows errors are therefore reproduced at the Tcl-ownership
boundary locally, **not yet claimed absent from a new Windows CI run**.

## Keep a fresh Stop through generic worker preparation

Explicit Draw and Build preview already cleared a previous operation's Stop
before their own cancellable preparation. Generic `begin_worker`, used by
image import and other workers, still cleared it after constructing and hiding
the screen-window owner. A new Esc during those operations was consequently
erased before the thread checked cancellation.

`begin_worker` now clears an old Stop only after its existing request-validity
gates and before native preparation. A new Stop during construction or hiding
remains set and prevents the task from running. The established
`reset_stop=False` path is unchanged. Busy, closing and pending profile/clear
requests neither clear Stop nor enter native preparation. Accepted workers
still own their normal terminal event and cleanup.

`test_v148_ui_batch25_worker_handoff.py` uses actual controller methods,
`ScreenTaskWindow`, worker threads, cancellation events and result queues. Its
window-state adapter replaces native visibility operations; UI poll scheduling
and logging are controlled. The tests verify cancellation during both owner
construction and hiding, preserved visibility cleanup, one terminal event,
successful work after an old Stop, and rejection of incomplete profile state.

## Release a decoded image that never reaches result adoption

After the real decoder returned an owned image, a late Stop raised before
queue publication. A publication failure could take the same path. Neither
path explicitly closed the decoded result. The worker now transfers ownership
only after successful enqueue, closing the result and propagating the original
exception on cancellation or failed publication. Successful results remain
open for the existing UI adoption path. The current source remains untouched.

Image import also now applies the existing `_profile_action_ready` predicate
before changing status to Loading. Previously a pending profile apply/clear
was refused later by `begin_worker`, but its unrelated status had already been
overwritten. Existing deferred Drop-In imports keep their established queueing
behavior.

The same worker module decodes the shipped
`assets/image-draw-bot-icon.png` through the real image reader. It verifies a
closed unpublished image after late cancellation and after a queue-publication
error, unchanged original pixels, and successful open-result transfer and
adoption. A queue subclass fails only the result publication for that boundary
case. Five methods against the baseline produced eight failed subcases; old
Stop and successful-transfer controls remained valid. Record:
`batch24-worker-handoff-before.log` (1.256 seconds).

## Calibration startup and close retain cleanup ownership

Both Paint and application-tool dialogs marked the main app busy before
allocating a top-level and its visibility owner, but those allocations were
outside their cleanup handler. Allocation failure could strand busy state.
Once content construction entered the handler, a failing native destroy could
mask the original error and skip restoring the main window. A failed
calibration refresh on successful Close likewise skipped clearing busy state.

Both entry methods now include busy-state entry, top-level allocation,
visibility ownership and content construction in one cleanup scope. They
record the allocated top-level immediately so failed teardown remains
reachable for retry or shutdown. Cleanup failures are logged with their
traceback while the original construction error propagates. Activity is reset
in `finally`, and the main-window visibility owner is restored when acquired.
Successful-close callbacks also restore idle state and visibility when a
calibration refresh raises; that refresh failure remains visible.

The helper dialogs formerly marked themselves permanently closed before
native destruction, making a failed native destroy impossible to retry.
`PaintToolCalibrationApp.close` and `AppToolCalibrationApp.close` now have a
separate reentrancy guard. They cancel their capture job and provisionally mark
the dialog closed during teardown so reentrant capture cannot run. A native
destroy failure rolls that flag back and propagates, preserving the Close
action for retry. After successful destruction, the completion callback runs
once. A completion-refresh error does not reopen an already destroyed dialog.
If Close interrupts a capture countdown, teardown also releases that
countdown's visibility owner. On failed destruction the cancelled countdown
can no longer restore its iconified dialog, so Close now restores it for a
visible retry. Successful destruction simply releases that already-finished
visibility ownership.

Five portable calibration methods cover both Paint and Gartic routes: failed
top-level allocation; failed visibility-owner allocation; failed content
construction plus failed native cleanup; refresh failure after destruction;
and failed-first/successful-second destruction with converging Close/capture
callbacks. They execute the actual controller methods, helper close/capture
methods, scoped lifetime wrapper, `ScreenTaskWindow`, and real Tcl job
registration/deletion. Native window allocation/content construction and
unrelated UI refresh are explicit boundaries. The corrected baseline fixture
produced eight failed assertions and two errors where cleanup masked the
expected original construction failure. Record:
`batch24-calibration-lifetime-before-final.log` (0.426 seconds).

A sixth portable method starts the actual capture countdown and real Tcl timer
before injecting a native destroy failure. It failed for both Paint and
Gartic against the first retry-only correction: the still-live dialog remained
iconified after its countdown had been cancelled. The completed correction
restores the dialog, removes its timer, retains main-app busy state until a
successful Close retry, and delivers refresh once. Record:
`batch24-capture-close-before.log` (two failed subcases, 0.079 seconds).

One additional Windows-only isolated method constructs both actual tool-dialog
widget trees with the public root factory. Calibration readers are redirected
to a temporary directory, the actual capture countdown starts, and one native
destroy attempt is made to fail. It checks visible retry, cancelled capture,
refresh-error propagation, idle/visibility restoration and callback errors.
It performs no native mouse input. This method is a pending native gate, not
part of the local runnable pass count.

## Accepted verification and integration boundary

The related selection on the initial, pre-integration candidate completed
**120 tests in 4.817 seconds: 105 passed and 15 native/display-dependent cases
skipped**. It includes all three new
modules (15 methods, 12 locally runnable), the implicated pointer-focus test,
keyboard and scoped-window tests, explicit/automatic preview cancellation,
profile Drop-In, existing UI lifecycle, Paint-tool and calibration tests.
Record: `batch24-ui-related-final.log`. The historical scratch log filenames
retain their original batch number; the new test modules and this ledger were
renamed to batch 25 during integration. Test durations are regression evidence,
not performance measurements.

Earlier exploratory logs are not accepted gates: the first wide invocation
named nonexistent `test_app_tools`; an early window adapter accidentally kept
an inherited mocked `deiconify`; and an imported test class initially caused
duplicate discovery. The corrected adapters and test selection are used by the
baseline records named above and the final selection. No production assertion
or native platform requirement was removed to obtain a pass.

Changes are limited to four `DrawBotApp` methods, `KeyboardButton.destroy`, the
two tool-dialog `close` methods and their regressions/documentation. Frozen
whole-project verification, independent source review and the exact-commit
Windows job remain separate integration gates. These completions do not
represent additional feature IDs or proof of physical Paint drawing.

## Concurrent batch 24 integration

The incoming `586e12db5ea5142951c844f60dc2364f07a01c37` already included the
same zero-ID `KeyboardButton.destroy` timer correction and an immediate
owned-timer assertion in the preceding pointer-focus regression. The merged
implementation retains one `cancel_widget_after_jobs(self)` call, with no
duplicate timer cancellation or assertion. Its executable module AST is
identical to the incoming `UiKeyboardNavigation.py`; only explanatory comments
differ. The pointer-focus assertion retains normalization through
`tk.splitlist`, without removing its existing focus, activation, global-binding
or deleted-command checks.

The incoming [widget-lifetime completion](v148-batch24-widget-lifetime-completion.md)
and native test remain intact. The additional batch 25 regressions retain the
portable real-Tcl five-animation reproduction and the isolated native repeated
release and self-destruction cases. Neither implementation nor additional
regression coverage increases the improvement count.

Static AST comparison found that the merged `DrawBotApp` differs from the
incoming version in exactly `begin_worker`, `load_source`,
`calibrate_paint_tools` and `calibrate_app_tools`. Each method matches the
verified pre-integration snapshot retained in local stash `223237a`. The
incoming `_apply_profile_change`, `options` and `upscale_dialog` methods match
their incoming ASTs exactly, preserving profile palette reset, resolved Paint
palette workflow and keyboard-accessible Upscale controls. No merge markers
remain in the three reviewed files, and their scoped whitespace check passed.

The focused integrated selection completed **69 tests in 3.885 seconds: 56
passed and 13 native/display-dependent cases skipped**. It combines the five
incoming batch 24 UI modules, the three batch 25 lifetime/handoff modules, the
implicated batch 16 pointer-focus module, and the batch 20/22 preview Stop
modules. Record: `batch25-ui-integration-focused.log` in the parent scratch
directory. This is the merged-source focused result; the 120-test result above
belongs to the earlier candidate. Full merged-suite validation and exact-commit
Windows/native checks are separate integration gates and remain pending at
this review. No local native pass or physical drawing result is inferred from
the skipped cases.
