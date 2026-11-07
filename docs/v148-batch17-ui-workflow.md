# Batch 17 — current-source timer feedback completion

Baseline: `e87bcf1b783b33ff866c2188e10c8b5d22a22707` (807 recorded groups).
This is **U1601 completion, zero new improvement groups**. It completes the
existing source-feedback lifecycle; the helper, import methods, edit methods,
Undo paths, and tests are not counted separately.

## Observed behavior and label meaning

The actual `StudioUI.build_ui` labels in both “Safety & draw” and “Preview
workspace” say “Drawing timer” and “Total draw time”. Neither presents a named
historical drawing or a separate history view. The `draw_time_actual` event sets
both fields from the completed executor duration. File adoption already resets
them when another image replaces the source.

The equivalent native-bitmap import did not reset either field. The same gap
affected accepted upscaling, background removal, their Undo paths, the screenshot
window's “Use as source image” button, recovery with an image, and image clearing.
For example, a real accepted plan followed by `draw_time_actual(seconds=37.2)`
left “Total draw time: 37s” and “Drawing timer: completed in 37s” beside a new
clipboard bitmap, or even beside an empty workspace after Clear image. Loading
the same new pixels from a PNG instead displayed the existing empty-time texts.

## Conservative source-only reset

The common `_clear_source_time_feedback` helper reuses the existing file-adoption
texts. Accepted source transitions call it after replacement. The screenshot
callback calls it only after its normal ready guard accepts the action. Recovery
calls it only when an image is adopted, and clear calls it only when the source
image is actually removed after worker ownership ends.

The general `_mark_plan_stale` path remains unchanged. A setting, area or profile
change, clearing only the cached plan, and recovery without an image retain the
existing completed duration. No-op background removal retains its source, plan
and readouts. The existing stopped/stale-result checks precede the new reset.
Busy entrypoints cannot import or edit a source, and the helper also leaves an
active draw/dry-run or closing application's runtime display untouched.

The executor clock, pause accounting, completion events, timing learning,
One-Click/Drop-In authorization and worker image ownership are unchanged. This
does not add a cross-source history policy or clear live time during ordinary
plan invalidation.

## Actual-flow evidence

`test_v148_ui_batch17_source_timer.py` contains 12 methods. Before the patch,
seven methods failed with nine assertion/subtest failures; the five control
methods passed. There were no fixture errors. The baseline log is retained in
the working session as `batch17-source-timer-baseline.txt`.

The tests build and adopt an actual public plan, then exercise the real
controllers and read the actual StudioUI factory's bound Tcl variables. File and
native-bitmap imports, resampling and background removal run through the real
`begin_worker`, worker queue and UI adoption. The native clipboard and screenshot
widgets are OS boundaries; no mouse drawing or GPU execution is simulated as
proof of this UI change. Pixel values, alpha, source ownership and Undo results
are checked alongside the visible time strings.

Recovery is consumed through `recovery_loaded` and its matching `done`, with and
without an image. The screenshot test invokes the actual button callback. A
pending image clear retains the active paused display until the tracked worker
has exited. Negative controls cover cancelled queued results, stale resampling,
busy entrypoints, a real no-op background result, cached-plan clearing, ordinary
options and the existing running/paused/completed timer transitions.

After the targeted DrawBot patch, the combined focused run passed **60 tests in
1.700 s**, with no skips or failures. This includes all 12 new methods plus the
existing plan-status, clipboard-text, executor-timer, completed-duration label,
capture, recovery and subject-recovery regressions. `git diff --check` passed.
Independent source/flow review closed with no blockers: the reviewer read every
new callsite and its event, Stop and pending-clear guards, and independently ran
all 12 new actual-flow methods successfully in 0.931 s. Active draw/dry-run
protection, no-op preservation, both Undo paths and deferred thread-exit handling
were included in that review.

## UK01/UW806 completion — bounded native popup verification and return state

The batch 16 native selector test posted a real menu synchronously, then planned
to send Escape after posting returned. Windows Tk enters `TrackPopupMenu` until
dismissal; X11 returns while its mapped Tk menu remains open. This difference
could stall the Windows test. The platform behavior is explicit in Tk's
[generic menu dispatch](https://github.com/tcltk/tk/blob/core-8-6-15/generic/tkMenu.c)
and [Windows menu implementation](https://github.com/tcltk/tk/blob/core-8-6-15/win/tkWinMenu.c).

The actual native test now schedules its interaction before posting. Windows
checks [GUITHREADINFO](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-guithreadinfo)
popup/menu flags and the exact menu owner's thread and process, then delivers
queued native key messages to that owner. X11 retains its real Tk menu and focus
checks. Callback assertions propagate as failures, with a three-second popup
deadline and failure-only `EndMenu`/unpost cleanup. An isolated selector test
process adds a 20-second hard timeout and a 12-second traceback. No menu is mocked
or skipped in that native case, and its value, callback, Entry, disabled, focus,
global-binding and teardown checks remain.

The same review found a closed Windows menu could retain
`_close_on_next_click=True`: CTk's pointer path writes it after modal return, and
the keyboard path relied on a Tk Unmap that native Windows menus do not emit.
Both posting paths now clear that flag in `finally` only when the actual
`tk windowingsystem` is `win32`. X11's early-return/open state is preserved.
The native test also checks immediate repeated F4/Escape without a pointer Enter.

Two portable methods in `test_v148_ui_batch17_menu_lifecycle.py` exercise the
actual CTk/KeyboardOptionMenu code while modeling only the OS posting boundary.
Before the fix, both Windows entry variants failed and the nonmodal control
passed. After the fix, **49 related tests completed: 40 passed and nine native cases skipped**.
All three actual Xorg/Tk cases passed, including the isolated selector process.
Separate real-popup probes proved callback failure propagates out of a modal
wait and closes the menu, and a never-posted menu fails after three seconds.
These are local X11 and portable results; the native Windows branch still needs
the next Windows CI run. This completion adds **zero improvement groups**.

### Exact Windows follow-up and observed native selection

The [Windows job for `d7721a36975a36137b583beda9ff3c47c05208fd`](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42382098235/job/128431685230)
completed 3,985 test cases in 188.397 seconds, with three skips and one failure.
The selector's isolated child returned in 0.848 seconds, so the previous modal
hang was resolved. Its sole failure was substantive: the assumed
Home/Down/Return sequence selected Safe instead of the asserted Balanced.
The native owner and earlier pointer/focus assertions had passed; this was not
a successful Windows gate.

The follow-up changes only the test harness. It navigates with real Down
messages and waits for the read-only active menu index before progressing from
Safe to Balanced, then sends real Return. The selected variable must still be
Safe and its callback count unchanged before Return; afterward Balanced and
exactly one callback remain mandatory. No `menu.activate`, `menu.invoke`,
mocked popup or weakened result assertion is used.

This observation is supported by the [Tk menu command contract](https://www.tcl-lang.org/man/tcl8.6/TkCmd/menu.htm)
and the Windows source linked above: `WM_INITMENU` clears the old active index,
while `WM_MENUSELECT` records the native selection before servicing Tcl events.
Thus the driver does not infer a highlighted item from keyboard focus or the
entry argument passed to `tk_popup`. Per-entry navigation bounds and the
three-second/20-second timeouts remain in place.

The three real Xorg/Tk cases passed after this follow-up (0.146, 0.154 and
1.098 seconds). Independent harness review and the root's initialization-order
review closed without blockers. A subsequent native Windows run remains the
required platform proof. No product code or improvement count changes in this
follow-up.
