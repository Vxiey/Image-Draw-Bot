# Batch 14 — ownership of deferred browser drawing starts

Baseline: `f7b561f479d94f307924dbc779e5c8e365422f8d`.

## A1405 — keep Browser One-Click bound to its accepted request

Browser One-Click's setup completion scheduled an untracked finish callback.
Stop cancelled the tracked initial setup callback and cleared the global
pending/force flags, but the finish callback checked the persistent One-Click
switch again. With that switch enabled, it could still call the real drawing
entry point after Stop. A subsequent worker clearing the shared Stop event
also made that stale permission indistinguishable from a fresh request.
The initial setup and its result did not retain the accepted source image or
a request identity. The read-only Setup + Verify button shared the same worker
activity, so its successful setup could enter the automatic draw branch before
its independent verification ran.

The historical methods from the complete baseline source reproduce the defect:
`done(browser-one-click-setup)` leaves `browser_one_click_after=None`, Stop is
pressed, a legitimate preview worker clears Stop and completes, and the old
saved callback calls `draw(user_initiated=True)` once. Native input is replaced
only at that final boundary in the reproduction.

Each accepted request now retains its source-image identity, profile name/key,
explicit one-shot permission, purpose and a separate cancellation event.
Setup workers read those captured values and the cancellation event; they do
not read Tk variables. Results must still belong to that same request before
adopting canvas or target state. The matching browser worker completion carries
its captured request identity, so a stale completion cannot release a newer
worker or schedule its start.

Both initial setup and final start use the same tracked callback owner. Each
callback also captures a unique ticket: even an already dispatched callback
that survives `after_cancel` cannot clear a replacement callback's token or
run another request. A successful setup advances only its own request to the
finish stage. The finish checks the current source/profile and ordinary start
requirements, then consumes that permission before entering the unchanged
`DrawBotApp.draw(user_initiated=True)` preflight and planning route. A failed
Tk scheduling attempt never falls back to a synchronous draw.

Stop, accepted source replacements/edits, profile changes, configuration edits,
recovery and unrelated new work revoke the request. Revocation remains set
when a later legitimate worker clears the shared Stop event. Returning to the
same image object or profile does not restore a cancelled request. A newer
import can create a fresh authorized request and complete normally; the old
result, completion and callbacks cannot cancel or start it.

Read-only Setup + Verify uses the same ownership chain with `auto_start=False`.
It can proceed to its independent live verification but cannot borrow the
persistent switch or a previous canvas-drop's force flag to draw. Its queued
verification and worker result also retain the owner and respect cancellation.
The Paint verification route keeps its existing behavior.

This is one behavior group covering ownership of the complete deferred browser
start. Callback stages, cancellation cases, verification purpose and tests are
not separate improvements. AX03's stale status filter and the existing profile
reset do not own or revoke this independently queued automatic drawing action.

## Validation

`test_v148_application_batch14_browser_start.py` contains 14 regressions using
the actual request methods, real worker wrapper, event handlers and deferred
callbacks. The two positive import cases exercise the actual `load_source`
worker and source adoption, setup, completion, finish, real `draw` method,
browser visual-preflight boundary and entry into final planning. They cover
both the persistent switch and explicit canvas-drop force with that switch
off. The test stops at the planning boundary; it does not send native input.

The negative cases retain and invoke old callbacks after Stop and after a new
loader has cleared Stop, replace requests while the old result/completion is
queued, send stale or unowned completion events, restore previous source or
profile values, change readiness, fail setup/scheduling and close the window.
A separate test follows the actual read-only Setup + Verify route through its
independent verifier and confirms that no draw occurs. A real background
thread uses Tk-value sentinels that fail on worker access and verifies that
the captured cancellation event stays set after the global Stop flag clears.

Two existing tests now supply the request ownership required by their actual
production callers. Their original assertions remain: invalid setup cannot
partially adopt target/canvas state, and one-shot permission is consumed before
drawing.

The new module and directly affected legacy modules pass **46 tests**. The
expanded browser/drop/profile/recovery/Paint/event/timer selection passes
**259 tests, no skips or failures**. `git diff --check` passes. Whole-program
and native Windows results are recorded with the final shared checkpoint;
these local portable tests do not establish a live browser or operating-system
input run.

Independent review is closed without blockers. The reviewer passed the 46
ownership/controller tests and 18 existing One-Click/probe/switch tests. A
separate direct-Stop reproduction before and after completion confirmed that
the next worker revokes any remaining old request before clearing Stop, and
that the old callback cannot draw or alter the new worker. The reviewer also
used the actual StudioUI factory, `set_busy` and CTk pointer/keyboard handlers
to confirm that drawing configuration controls are disabled during setup;
the controls that remain active only change preview presentation.
