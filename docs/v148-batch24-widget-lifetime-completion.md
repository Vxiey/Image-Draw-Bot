# Batch 24: complete individual button timer ownership

## Scope and count

This completes the existing widget/window callback ownership and button
destruction contracts: **GP15 / global 567**, **UW10 / global 691** and the
**UK01 / global 739** application button wrapper. It adds **zero improvement
IDs**. The shared ownership helper introduced in the earlier window-lifetime
completion remains unchanged.

The product change is exactly two lines in
`UiKeyboardNavigation.KeyboardButton.destroy`: after cancelling the existing
pending keyboard release, call `UiWindowLifetime.cancel_widget_after_jobs(self)`
before the normal CTk destruction. No drawing, input authorization, live button
activation, animation algorithm, global binding or shared CTk service changes.

## Exact before attribution

Published checkpoint
[`bb6dfa6a5e8a43bfcfc77c9e00f52dc2dfd7db9c`](https://github.com/Vxiey/Image-Draw-Bot/commit/bb6dfa6a5e8a43bfcfc77c9e00f52dc2dfd7db9c)
passed all seven checks. Its
[Windows job](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42403249179/job/128495385074)
ran 4,270 tests in 326.944 seconds with three unavailable-GPU skips; Windows
self-test, bundle validation and packaged GUI/native drag-and-drop also passed.
The log nevertheless contained **five nonfatal `invalid command name` messages**
ending in `_click_animation`. They appeared while the next switch test ran;
their position alone did not establish their owner.

A separate Linux/Xorg probe ran the original pointer16 button and switch
methods in order, without changing their assertion bodies or cancelling a
timer. It observed real `tk.Misc.after` registrations and the actual
`KeyboardButton.destroy` boundary. All five 100 ms callbacks belonged to the
first method's one `StudioUI.button`. Every native command was a member of that
button's `_tclCommands` before destruction. Immediately after the explicit
child-button destruction, the root still existed, each command had disappeared,
and all five exact `after` jobs remained pending. The second original test's
native event loop then reported those same five command names through the
first interpreter's `bgerror` command.

Both original methods passed in that before probe: two tests in 0.327 seconds.
The ownership oracle correctly failed because it found five orphaned jobs and
five exactly attributable background errors. The observer did not replace the
animation, suppress an error or cancel a callback.

This distinguishes the component disposal gap from the switch itself and from
normal whole-window closing. The scoped root already collects callbacks from
its current widget subtree before destruction. It cannot later collect a
button that has already been removed from that tree. The existing
`KeyboardButton` wrapper is the narrow owner that can cancel its pending native
callbacks before CTk deletes their commands.

## Preserved lifetime behavior

The reused helper selects only actual single-command `after` scripts whose
command token belongs to the current button/widget subtree. It uses raw Tcl
`after cancel`; each widget still deletes its own registered commands through
its normal destruction. It does not cancel every interpreter timer, match
callbacks by a name prefix, or remove other widgets' bindings.

The existing keyboard-release cancellation runs first. A live button retains
CTk's original click animation and command. Other buttons, root callbacks,
another window's callbacks and shared appearance/DPI services keep their
existing owners. `UiWindowLifetime.py` and the CTk library classes are unchanged.

## Regression evidence

`test_v148_ui_batch24_widget_timers.py` uses the actual Studio button factory,
real native pointer events and a bounded isolated child process. It covers
three disposal paths: direct button destruction, destruction of its containing
frame, and a button's own action destroying itself. In each path the real
animation must exist before disposal and be absent afterward. A surviving
button's real animation must execute, and independent root, sibling and other
window callbacks must all run exactly once. A second native interpreter pumps
the event loop after root destruction while the diagnostic command remains
available; any background error fails the test.

The original pointer16 button method additionally checks that none of the
destroyed widget's exact owned timer IDs remains pending. All its existing
activation, focus, late-label/image, disabled-state, keyboard-cancellation,
command-deletion and global-binding assertions remain. No existing test or
native skip condition was removed or weakened.

Before the product change, the new method failed all three disposal subcases
and its final background-error oracle. The strengthened original pointer method
also failed with precisely five pending animation jobs. After the two-line
change:

| Gate | Observed result |
|---|---|
| New native disposal method plus all three original pointer16 methods | 4/4 passed in 2.559 s; no Tcl diagnostics |
| Same original two-flow ownership probe | Five registered animations, all five no longer pending at child destruction; zero orphaned jobs and zero background errors |
| Adjacent button/window lifetime gate | 23 cases in 0.522 s: 15 passed and eight native cases skipped in the ordinary headless run |
| Independent combined native gate with the four Upscale cases | 8/8 passed in 4.654 s; no Tcl diagnostics |

The native runs used Linux/Xorg, CTk 6.0.0 and Tcl/Tk 9.0.4. They are not a
substitute for the subsequent exact-commit Windows gate. The preceding Windows
checkpoint remains recorded as green with its five nonfatal messages; this
ledger does not retroactively describe that log as warning-free.

Independent source review is closed without blockers. It checked the exact
subtree token ownership, cancellation before normal command deletion,
unaffected other-widget/window jobs and preservation of the original native
assertions. No further product changes were required by that review.

Reproduction evidence is retained in task scratch as
`batch24-click-animation-before.json`, `batch24-click-animation-after.json` and
their `.log` counterparts, `batch24-widget-timers-before.log`,
`batch24-widget-timers-after.log`, `batch24-widget-timers-related.log`, and the
independent `batch24-upscale-native-final.log`. The reusable permanent native
regression is part of the repository; whole-suite and final publication
validation remain the root finalizer's responsibility.


## Final shared snapshot

The final batch24 combined native run passed **10/10 in 5.173 seconds** with
zero Tcl diagnostics, including all three original composite pointer/focus
methods and the new early-child-disposal cases. Whole-project frozen discovery
passed **4,308 tests: 4,242 pass and 66 platform/hardware skips** in 205.763
seconds. The exact new Windows CI remains a separate publication gate.
