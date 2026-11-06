# v1.0.148 UI workflows — batch 07

Baseline: `8a9c848b9dd0f2c4738aee729dace75be2a5778d` (729 reviewed
improvements). The following `2b786884` and `2c492b480c5df1c0d8e549ea297b883ff0edab09`
commits correct existing Windows layout/verification contracts and add no count.
This development batch records **four distinct implementation groups**. It is
not a release announcement.

Regression modules: `test_v148_ui_batch07_keyboard.py` (**K**),
`test_v148_ui_batch07_workflow.py` (**W**) and the coordinator's
`test_v148_application_batch07_profile.py` (**P**). The separately approved
renderer-choice correction is covered by `test_v148_ui_batch07_renderer.py`
(**R**).

| ID | Reproduced problem | Implemented behavior and evidence |
| --- | --- | --- |
| UK01 | Application-created CustomTkinter buttons had pointer bindings but no consistent Tab traversal or Return/Space activation. Decorative labels could acquire their own focus stops through tooltip bindings. | `UiKeyboardNavigation.KeyboardButton` gives each live, mapped, enabled action one outer-frame Tab stop and a visible focus outline. Return, keypad Enter and Space invoke the existing button command once on release; autorepeat, focus loss, hidden/disabled controls and destruction cannot deliver a stale activation. Focus reveals the target through owned nested CTk scroll frames, and activation rechecks that its centre remains inside every viewport. Tooltips receive that logical focus while retaining pointer behavior. `StudioUI.button`, inline setting help and `UICompactLayout.CompactGroup` use the local subclass. K executes the inherited CTk `invoke()` with live states, cancellation and repeated-event sequences; actual tooltip callbacks and vertical/horizontal/nested/failing scroll models cover integration. Three Windows tests verify real Tk traversal, recreated labels, key delivery, focus rendering/tooltips, Tab-to-bottom visibility, owned Tcl-command deletion, unchanged global bindings and the actual controller's Start setup guard. One shared button-interaction group, not one per key or widget. |
| UK02 | The generic error card's Retry action always called `draw(test=True, user_initiated=True)`, even for an image import, disk-write or GPU failure. It could request drawing unrelated to the failed operation. | The card now offers Help. `StudioUI.show_error_help` reads the current classified error and displays its explanation and next step; resolved errors and shutdown do nothing. W extracts and executes the actual card callback for storage, import, GPU and palette errors, checks the live error after a status change, and asserts that drawing, Quick Start and worker methods are never called. Existing dedicated correction/retry workflows are unchanged. |
| UK03 | A native combobox selection event for the already active profile still saved settings, cleared the plan/area/resume and disarmed the drawing state. Choosing the same profile therefore discarded valid setup despite no configuration change. | `DrawBot.change_profile` treats an already active selection as a no-op and cancels an outstanding queued switch when the user returns to the active profile. The explicit internal `_apply_profile_change` path remains available for Import/Reset to reload that same profile. P calls the actual methods and verifies preservation of plan, area, resume, paths and permissions; no save/disarm; cancellation of the previous callback; and continued forced reload behavior. Root owns this implementation and its tests; it is counted only in this UI ledger. |
| UK04 | The UI advertised Sketch + Auto Fill, and its Paint renderer existed, but `DrawBot.options` rejected that selection as an invalid rendering style. Reading saved settings silently left Auto instead of restoring it. | Both existing rendering-style membership checks now include the already imported `SKETCH_FILL_RENDER_STYLE`. R reproduces the three failures before the change, then runs the actual Paint `options` → `make_plan` chain and verifies its ordered sketch/color-fill/re-outline sequence, actual save/read restoration, continued browser-target restriction and rejection of unknown style names. This is one advertised-renderer activation/persistence group; it does not change UP01's automatic profile policy or the renderer algorithm. |

## Earlier contracts completed without new counts

- **UC11 responsive focus:** `_focused_panel` in `ResponsiveWorkspace` now
  recognizes the separate outer frame of a CTk scroll frame. Focus on its
  scrollbar preserves that panel during a compact transition; explicitly
  selecting another page transfers focus away from the hidden wrapper. W
  covers both transitions.
- **AW15 profile transaction isolation:** worker and direct calibration entry
  points cannot use a pending/in-progress profile context. Profile creation
  rechecks the guard after its modal prompt. Per-request tickets prevent a
  stale callback from clearing a newer request; rejected callbacks restore the
  active identity. Shutdown callbacks return before accessing destroyed Tk
  variables. P covers actual worker/modal/profile methods, including a
  pending request with Stop already set. These complete the existing profile
  management contract and are not additional UK03 subcounts.
- **UI22 paste routing:** enabled readonly comboboxes allow image paste;
  editable or disabled controls retain native text behavior. An inaccessible
  Tcl widget path does not redirect a text paste into image import. P covers
  the actual shortcut method and native Tk/ttk widget types.
- **Earlier layout and fixture corrections:** the successful CTk pack call's
  cached DPI replay no longer depends on a sibling that may later be unpacked.
  Native fixtures process window mapping events and wait for CustomTkinter's
  temporary native min/max size lock to release before requesting and asserting
  exact client dimensions. All visibility, containment, selected-page and
  Start/Stop assertions remain. The subsequent exact-size Windows run exposed
  a real vertical-budget failure at 650×500 with 150% widget scaling: the header
  and footer left only the panel selector's 43 pixels. Compact-height chrome
  now omits redundant branding/badges, retains all action controls and reduces
  surrounding spacing. It runs even before a starved main panel is mapped.
  Four height models cover physical-size/scaling transitions, the observed
  geometry budget, initial starvation and scoped root-binding teardown; the
  native test additionally requires useful panel headroom. These complete
  UC11's existing compact-layout behavior and add no new group here.

UK01 is distinct from UP04's F1/Shift+F1 conflict correction and UW08's guide
navigation shortcuts: it adds standard local activation and traversal to the
application's own button class. It makes no claim of complete assistive-
technology coverage. UK02 changes the error card's actual action, not error
classification or the separate correction-only retry workflow. UK03 preserves
work on an unchanged explicit profile choice; the accompanying worker/modal
guards remain AW15 completions.

## Validation and limits

The focused new keyboard/workflow and root integration modules passed
**31 tests in 0.166 seconds**, with **three native Windows skips**. The broader
related UI/calibration/profile run passed **141 tests in 0.855 seconds**, with
**ten native Windows skips**. The independent profile integration review
reran **11 tests in 0.022 seconds**, all passing, and closed after correcting a
shutdown-variable-access regression. The tests exercise controller callbacks,
not physical mouse or keyboard input. Disabled-state and Start authorization
checks stay in the existing controller and CTk `invoke()` implementation.

UK04's three new regression tests pass in **0.066 seconds**. Its additional
eight-module renderer/settings/options run passed **77 tests in 1.538 seconds**,
with no skips. The independent reviewer read the exact two-line membership
change and independently passed all three new tests; review is closed.

```text
python -m unittest test_v148_ui_batch07_keyboard test_v148_ui_batch07_workflow test_v148_application_batch07_profile test_v148_ui_batch07_renderer
python -m unittest test_v148_ui_batch07_keyboard test_v148_ui_batch07_workflow test_v148_application_batch07_profile test_v148_ui_layout_batch04 test_v148_ui_profiles_batch04 test_v148_ui_batch06_calibration test_v148_ui_batch06_preview test_v148_ui_batch06_workspace test_v148_ui_batch06_scaling test_v148_ui_batch06_height test_ui_bindings_v1093 test_ui_compact_layout_v10144 test_step11_ui_profiles test_profile_switch_safety test_profile_isolation_v107 test_modern_ui_v109
python -m unittest test_v148_ui_batch07_renderer test_sketch_fill_v10131 test_hybrid_renderer3_v10128 test_step25_quick_sketch_fill_contour_v10148 test_v148_application_batch04_settings test_profile_engine_v1045 test_precision_v102 test_draw_quality_v103
```

No speedup is claimed: these are interaction/correctness changes, not measured
performance optimizations. Native Windows keyboard and full-workspace results
remain pending. Independent keyboard/helper review is closed after correcting
logical-focus tooltip delivery and scrolled-out target visibility; the reviewer
independently reran all 31 focused tests successfully (three Windows skips).
The four groups' source and tests are frozen. Whole-project frozen-source and
exact-head CI gates are coordinated separately. `git diff --check` passes.

## Final local integration gate

The frozen source passed **3,355 tests in 71.096 seconds**, with **35 platform/hardware skips** and no failures. Source hashes were unchanged during the run. All independent area reviews are closed. The 5,000-cycle source gate, source-package hygiene and all eight exact-raster fixtures passed, with zero mismatched pixels. Windows/Linux CI on this new checkpoint remains pending; version 1.0.148 is not published.
