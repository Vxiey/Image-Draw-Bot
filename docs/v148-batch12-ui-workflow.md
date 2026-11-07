# v1.0.148 UI workflow — batch 12

Baseline: published batch11 commit
`b0eedca7d8d63fde5c9da6a1cffb394613ff95bf`, tree
`fa09dfb415b7d851ff33625f38bff68981bfcbf8` (777 recorded improvements).
This area records **one distinct behavior group, U1201**. Independent source
review and the combined local checkpoint gates are complete. The native Windows checks also passed for the saved batch12 checkpoint
`4704a94d` in run `42331930641`.
This is development work, not a release.

## U1201 — keyboard access to existing boolean settings

`DrawBotApp` builds its real workspace through `StudioUI.build_ui`. Its buttons
and option selectors already supported keyboard operation, but twelve active
boolean controls still constructed raw CustomTkinter switches. The installed
`CTkSwitch._create_bindings` registered only pointer Enter, Leave and Button-1;
its focus methods forwarded to a decorative text label. Space therefore had no
route to change those existing settings.

The baseline was reproduced before product edits with the installed switch's
real `_create_bindings` and `toggle`, a real Tcl `StringVar`, and replacement
canvas/label surfaces only. Dispatching Space left `Off` and issued no command.
Dispatching the existing Button-1 binding changed the value to `On`, then called
the original command exactly once with the updated value visible. This is a
local callback reproduction, not a claim about physical keyboard input.

`UiKeyboardNavigation.KeyboardSwitch` now provides one logical Tab stop, a
visible focus mark and local Space/Return/keypad Enter activation on release.
It delegates the change to CTk's ordinary `toggle()`: the configured on/off
values, variable trace and original no-argument command retain their existing
order and semantics. Programmatic settings updates, `select` and `deselect`
still update the displayed state without issuing another user command.

The active StudioUI callers now use that local class:

| Existing setting | Existing callback |
| --- | --- |
| Single-color sketch (current ink) | `paint_mode_changed` |
| Browser One-Click Mode | `options_changed` |
| Auto clear target canvas before full drawing | `canvas_clear_changed` |
| Black contour sketch | `sketch_mode_changed` |
| Read Gartic timer at Start | `options_changed` |
| Adaptive deadline renderer | `options_changed` |
| Use Region Fill Engine | `options_changed` |
| Skip white | `options_changed` |
| Emphasize centered subject | `options_changed` |
| Show background | `schedule_previews(delay=15)` |
| Show fill regions | `schedule_previews(delay=15)` |
| Show stroke paths | `schedule_previews(delay=15)` |

The original nine settings remain registered with the controller's busy-state
handling. The three preview-only toggles keep their existing independent
availability. The change does not add a settings value, alter a profile default,
change persistence or call drawing/arming operations.

## Focus, lifetime and shared behavior

The existing button release/repeat machinery is extracted into a small shared
support class. Buttons still use their original `invoke()`; switches use
`toggle()`. Repeated key presses and X11 release/press repeat pairs do not issue
multiple activations. Focus loss, unmapping and disabled state cancel a pending
switch activation. Delivery rechecks live state, mapping, focus and visibility
inside each owned scroll viewport. Destruction cancels its idle callback before
CTk removes the widget and variable trace.

CTk switches toggle on pointer press. The local wrapper therefore cancels any
pending keyboard release before that original pointer callback can run or pump
nested Tk events. Its normal variable/command behavior remains unchanged.

Focus reveals a switch through the existing owned nested scroll-frame helper;
a clipped target cannot activate when reveal fails or the viewport moves away.
StudioUI tooltips receive the logical focus while retaining their pointer
bindings. Decorative canvases and labels are not additional Tab stops. All
activation bindings belong to the widget; no global keyboard hook is introduced.

## Validation

`test_v148_ui_batch12_switches.py` contains **15 tests: 13 portable tests and two
Windows-native tests**. Portable tests retain the real local constructor,
installed CTk toggle/configuration/variable callback methods, and Tcl variables;
they replace only the native drawing/widget boundaries.

- The actual twelve constructor calls and loops execute from `build_ui`,
  preserving variable identity, callback kind and controller registration.
- Boolean and explicit string values verify variable-before-command order,
  repeat suppression, programmatic changes, replacement variables and optional
  command callbacks.
- State, focus, unmapping, destruction, reentrant pointer callbacks and nested
  scroll geometry verify that stale or invisible activations do not change a
  value. The real CTk destroy path removes its variable trace.
- The actual settings callback reaches `DrawBotApp.options`, invalidates the
  plan once after a deliberate edit, and does not request drawing or workers.
  The real `set_busy` method disables the nine settings; a preview-only toggle
  still schedules the actual preview callback without invalidating the plan.
- Windows tests use real Tk mapping/focus events and the actual UI constructors
  to check Tab order, all decorative children, repeated Space/Return delivery,
  focus indication/tooltips, disabled/re-enabled state, scroll reveal and Tcl
  callback cleanup. They also check unchanged global key bindings. They do not
  inject operating-system input. These tests passed in the saved batch12 Windows CI run `42331930641`.

The new module passed its 13 portable tests; its two Windows checks were skipped
on Linux. The combined new and related regression selection completed **68 tests
in 0.361 s: 59 passed, nine Windows-only checks skipped**:

```text
python -m unittest test_v148_ui_batch12_switches test_v148_ui_batch07_keyboard test_v148_ui_batch08_keyboard test_v148_ui_batch10_numeric test_v148_ui_batch06_workspace test_ui_bindings_v1093 test_modern_ui_v109
```

This includes the existing KeyboardButton suite after the shared release-support
extraction. The duration is a test observation, not a performance claim.

## Deduplication and review status

U1201 adds the missing boolean state-toggle workflow. UK01 covers button command
activation, UW806 covers enumerated option-menu selection, U1001 covers numeric
edit commits, and UK03 covers unchanged profile selection. UW803's effective
Region Fill option propagation remains unchanged. Shared focus, tooltip,
lifetime and busy-state integration are included in U1201 without extra counts.
The twelve callers and individual regression cases are not separate improvements.

The coordinator independently read the product changes, installed CTk behavior,
actual factory/controller harness and Windows fixtures, then repeated the exact
68-test selection successfully in 0.436 s (nine Windows skips). Source review is
closed without a concrete blocker. Product/test source remains stable for the
combined gates and new Windows CI. No stage, commit, remote write or release
operation has been performed by this area worker.

## Frozen checkpoint validation

Batch 12: final frozen-source discovery passed 3,626 tests in 150.380 seconds (45 platform/hardware skips), with unchanged Python and batch-script hashes. Independent source reviews are closed for both new behavior groups and the uncounted physical-brush completion. The 5,000-cycle source gate, source-package hygiene and eight exact-raster fixtures passed. Paired full public-planner measurements bind the final source and retain identical results while reducing repeated score preparation. Timing and traced allocations are reported separately; these are not native drawing or GPU benchmarks. The published batch12 checkpoint `4704a94df364df9ceeefb113f5273f26ec4ee988` passed all four Windows/Linux and dependency jobs in [CI run 42331930641](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42331930641). All seven checks on that commit succeeded, including [CodeQL analysis run 42331925857](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42331925857). Windows self-test, bundle validation and packaged GUI/native drag-and-drop also passed. These results apply to that saved checkpoint; subsequent source changes require their own verification. No 1.0.148 release is published.
