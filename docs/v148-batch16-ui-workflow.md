# Batch 16 — UI and setup workflow

Baseline: `d1a5e3a709745ee64263b5801cf1b9089cd6b707` (803 recorded groups).
The separately tracked U1502 Windows focus completion adds no group and is
documented in the batch 15 UI ledger.

## U1601 — keep plan feedback attached to the accepted source and setup

The visible estimated draw time and preview accuracy diagnostics survived
ordinary invalidation of their plan. Changing a setting, adopting another
file or clipboard bitmap, undoing background removal, switching profiles or
clearing the cached drawing could therefore show the preceding plan's time
and accuracy beside a different source or an empty preview. Manual preview
made this persistent: no replacement plan was supposed to run until the user
explicitly requested one.

These are the existing `draw_time_text` readouts in the StudioUI “Safety &
draw” card and “Preview workspace”, and `preview_diagnostics_text` in that
workspace. `DrawBotApp._handle_event('planned')` populates them from the
accepted plan. The actual labels were already correctly bound to their Tk
variables; the stale contents were in those variables themselves.

`DrawBotApp._clear_plan_feedback` now resets just these two derived fields to
their existing “after Build preview” messages. The shared `_mark_plan_stale`
path calls it after detaching the old plan. The separate cached-drawing clear
path calls the same helper. Existing callers thereby clear obsolete values
without scheduling work in Manual mode. A later accepted real plan populates
the same bound readouts again. An edit result that reports no change retains
the still-valid plan and feedback.

### Runtime-time policy remains at its existing callers

The adjacent live readout is “Drawing timer”; the completed result is “Total
draw time”. Neither label explicitly defines a separate history view.
`_handle_event('draw_timer')` owns the active elapsed/remaining display, and
`_handle_event('draw_time_actual')` supplies the completed duration. The file
adoption branch already resets both runtime fields when a new file is loaded.

This change preserves that existing policy. The new helper clears only the
plan estimate and diagnostics. It does not clear elapsed or completed time
when settings, area, profile or the cached plan are invalidated, and it does
not change the existing file-adoption reset. It does not reinterpret the
completed field as new cross-source history or add timer resets to other
source/edit paths. Active paused/running timer events continue to own their
runtime display.

### Counting and validation

This is one plan-feedback lifecycle behavior. U901 fixed labels that displayed
literal Tk variable names; it did not define invalidation of their contents.
AX05 fixed the context and displayed estimate of the explicit learned-timing
reset action. That action's narrower correction remains intact. Neither is
counted again, and the import/edit/profile/clear variants, helper, messages
and tests are not separate improvements.

`test_v148_ui_batch16_plan_status.py` has eight feedback methods and four
saved-area methods. Before the production patch, **11 of the 12 methods
failed, comprising 15 assertion/subtest failures**; the no-op-edit control
already passed. The feedback cases run the public `make_plan` function and
the actual `planned` consumer, with matching preview generation, before
driving the real import/edit/profile/clear/options paths. The active StudioUI
label factories use real Tcl variables; only native widget allocation and
OS/persistence presentation boundaries are replaced. The assertions read
the displayed value through each label's real variable binding, not merely a
mock setter call.

Coverage includes file and native-bitmap adoption, exact restored Undo
pixels, real profile application, cached-plan clearing, Manual-mode
non-scheduling, no-op preservation, completed-duration preservation, the
existing loaded-source timer reset, active paused timer ownership and
repopulation by a subsequent accepted real plan. Worker image ownership is
unchanged and remains covered by the adjacent batch 15 adoption regressions.

## RT53 completion — restore a saved area transactionally

`reuse_area` assigned the proposed saved corners before target capture. On a
capture error it then replaced the corners with an empty list and discarded
the target, even when a complete usable area and plan existed beforehand.
A target-capture helper that had partially updated metadata could also leave
the remaining geometry fields inconsistent. Direct invocation lacked the
shared busy/profile/closing guard.

The action now uses `_profile_action_ready` and snapshots the previous
corners, normalized anchor data, target window, client rectangle and DPI.
It validates the saved dimensions and completes target capture before
committing the visible area and invalidating the plan. On the existing
handled error paths it restores the complete prior geometry and retains
the old plan, area feedback, estimate and diagnostics; the status explains
the failed attempt. Failed or blocked attempts do not schedule preview work
or alter the busy state. Success refreshes the visible area and invalidates
the old plan through the shared path.

Successful reuse deliberately retains valid saved anchors. The actual
`read_settings` path restores saved corners and their normalized anchor
data together. The positive regression runs real `detect_canvas_anchors`,
JSON serialization, validated settings loading, `reuse_area`, native target
metadata adoption and `rebase_canvas_area`. The four saved corners remain
available and the 80 × 60 area follows a verified +10/+10 target translation.
Resetting these anchors unconditionally would discard the normal saved
geometry. No additional anchor invalidation was added without a demonstrated
incorrect caller path.

The other saved-area cases inject a capture failure after partial metadata
mutation, reject too-small saved dimensions before native capture, and
exercise the actual direct-entry guards for draw activity, closing, pending
profile change and pending cached-drawing clear. This extends RT53's existing
validate-before-commit setup contract to saved-area reuse and adds **zero
improvement groups**.

## Verification scope

After the targeted DrawBot patch, all **12 new methods passed**. The initial
combined plan-adoption/timer/recovery-clear/profile/readout/timing-learning
selection passed **59 tests: 58 passed and one existing Windows-native case
skipped**. The final saved-anchor settings/rebase assertions also passed in
the same twelve-method module. These tests establish controller state and
bound readout behavior; they do not claim physical target capture or native
mouse execution. The whole-project and Windows gates remain the shared
checkpoint's responsibility.

Independent review of U1601 and the RT53 completion is closed without
remaining blockers. The reviewer traced real target capture, settings/anchor
storage, rebase and timer/invalidation callers, and repeated all twelve new
methods successfully alongside the five delivery-cost regressions.

## Existing keyboard contracts — complete pointer-to-key focus ownership

The small U1502 follow-up was published separately at
`86fa125306b9c2db8e8125fec6a38270b09c8ff9`, retaining the 803-group count.
Its exact Windows job passed 3,851 tests with three skips, then passed the
source self-test, bundle validation and packaged GUI/native drag-and-drop
checks. All seven exact checkpoint checks were green. This closes the earlier
batch 15 native contrast gate; it adds no new behavior group.

The same CTk 6 global click callback affected existing buttons, switches and
option selectors. Real native reproductions after that slider-only fix showed
focus on `CTkCanvas` or `Label` after a click, so the following Space or Down
never reached the logical control's existing key bindings. For the selector,
Escape delivered to that actual focused child also left its popup open. The
three new native regression methods all failed before the shared correction.

The existing focus support now gives each explicitly decorative child a
local focus delegate to its logical control. Buttons register their canvas,
text label and image label, including new labels created during later
configuration. Switches register their visible control canvas, background
canvas and text label. Option selectors register their canvas and text label;
the already corrected slider uses the same helper. Tab traversal still has
one logical stop. Local mouse and native variable/command handlers remain
unchanged, and the later CTk global click callback and other observers still
run normally.

The selector's delegate preserves a visible native popup that already owns
focus. That matters because opening a popup can transfer focus during the
local click handler, before CTk's global callback runs. The popup Menu itself
and native text Entry are never assigned decorative delegates. Native menu
Down/Return/Escape and focus restoration continue to work, without routing
menu entry input through the parent control.

`test_v148_ui_batch16_pointer_focus.py` contains three native integration
methods. They execute actual StudioUI button/menu/switch factories and real
CTk/Tk event delivery. Coverage includes click followed by input on the actual
focused widget; button text/image labels created and replaced by configure;
switch canvas/text/background behavior; disabled controls; the existing
pending-release cancellation; native menu selection/cancellation; retained
Entry focus; observer delivery; unchanged global bindings; and removal of
owned Tcl commands and variable traces on destruction. A native display is
required; Windows runs these cases, while displayless Linux skips them.

All three new methods passed under the local Xorg dummy display with real
Tk/CTk. The nine existing native button/selector/switch/contrast methods also
passed there, each in a fresh interpreter process. The adjacent portable and
display-gated selection passed **93 tests: 78 passed and 15 skipped**. The
Xorg run establishes the real focus and event path on Linux; the new Windows
checkpoint remains the final platform gate.

These close the already recorded UK01 button, U1201 switch and UW806 selector
keyboard contracts, with the existing U1502 slider sharing the implementation.
They add **zero improvement groups**. Children, key combinations, native cases
and the shared helper are not separate improvements.
