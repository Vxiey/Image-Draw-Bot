# Batch 24 — prepared Paint colors and Upscale keyboard completions

These are **existing-contract completions with zero new improvement IDs**.
The baseline is `bb6dfa6a5e8a43bfcfc77c9e00f52dc2dfd7db9c` (828 recorded
groups). The prepared-palette work completes the existing Manual profile-policy
and accepted profile-reset/import isolation contracts (UP01/UP02 and Step 27).
The Upscale caller completes the existing UK01 button and UW806 selector
keyboard behavior; the underlying resampler, size limit and editing ownership
already existed. No option, gesture, test method or additional caller is counted
as a separate improvement.

## Prepared Paint palette: before evidence

The actual `picture_palette_complete` controller validates a complete palette
for the current Paint image, adopts it, selects Adaptive exact and saves the
profile. That successful preparation is intentional. The final part of
`DrawBotApp.options`, however, subsequently forced the prepared colors and
Adaptive exact back into the result even after the user selected Manual /
Manual settings / Calibrated palette. The selected workflow had already been
used to resolve the calibration fingerprint and profile policy. The late
override contradicted that selection. After RGB controls were removed, the
public planner refused the supposedly calibrated-palette job because its old
prepared colors still required exact RGB controls.

The same image is retained when a profile is replaced or reset. The accepted
`_apply_profile_change` path reset settings and calibration but retained the
old transient `picture_custom_palette_state`. Its image identity consequently
still matched after real `ProfilePortability.import_package_into_app` and
`reset_profile` operations.

`test_v148_ui_batch24_picture_palette.py` reproduces both routes with real
picture-palette construction, completion adoption, settings callbacks,
`options`, public `make_plan`, temporary profile files, and the actual
replace/reset/reload implementation. Only native variable allocation and
unrelated presentation are replaced. The initial five-method gate produced
four relevant assertion failures and one real planner `ValueError`; the Auto
promotion and rejected/cancelled-result control methods passed. The error was
the existing “Picture palette needs Paint RGB controls” guard, not a fixture
setup failure. Evidence is preserved in
`/workspace/scratch/97bfc35400fb/batch24-picture-palette-before-initial.log`.

## Prepared Paint palette: completion and checks

The options handoff now adds prepared RGB colors only when the already
resolved workflow is Adaptive exact or Exact custom + palette fallback. It
keeps that workflow unchanged. New palette completion still validates the
state before explicitly selecting Adaptive exact; `active_picture_palette`
is not filtered by the old workflow. The accepted profile-apply boundary
also releases the transient preparation after its stale-ticket, busy,
closing and selected-profile guards.

The tests verify all of the following through real controller/planner calls:

- Manual Calibrated uses the calibrated palette with and without RGB controls,
  and its selected setting survives actual save/read.
- Valid prepared completion still reaches the exact colors and exact runtime
  selectors, including when Exact custom + palette fallback remains selected.
- Auto can still promote calibrated colors according to its existing policy;
  current ink and outline retain their existing prepared-palette bypass.
- Accepted replacement import and Reset clear the preparation while preserving
  the current image, its pixels, Stop and the absence of native mouse input.
- A same-profile menu no-op, rejected/stale apply, Stop and an obsolete source
  completion preserve the currently valid preparation.

The first combined after gate passed **46/46 tests in 0.392 seconds**, including
the five new methods plus existing picture-palette, actual profile reload,
settings and advertised-renderer tests. Log:
`/workspace/scratch/97bfc35400fb/batch24-picture-palette-after.log`.
Additional retained-current-ink/outline and same-profile no-op assertions were
then added to the same five methods. That final palette gate also passed
**46/46 in 0.408 seconds**, in
`/workspace/scratch/97bfc35400fb/batch24-picture-palette-after-final.log`.
Independent source and actual-flow review is closed without blockers; the
reviewer ran the five final methods independently (**5/5 in 0.323 seconds**).

## Upscale dialog: native before evidence

`DrawBotApp.upscale_dialog` created raw CTk option menus and a raw CTk button.
These controls were outside the app's existing local keyboard factories. In
the actual native dialog, Tab remained on the dialog instead of reaching the
factor selector; End left a 2× selection unchanged; Return on the Apply control
did not start the existing upscale worker.

The four native methods in `test_v148_ui_batch24_upscale_keyboard.py` run the
actual controller-created modal dialog in bounded child processes. On Linux /
Xorg / Tk 9.0.4, the before gate produced **three expected failures and one
passing Escape control**, in 2.012 seconds. The complete log is
`/workspace/scratch/97bfc35400fb/batch24-upscale-native-before-final.log`.
The earlier `batch24-upscale-native-before.log` is retained: its Escape driver
incorrectly sent KeyRelease to a widget that Escape had already destroyed.
The final driver sends that release to the surviving root, as a real input
event must, without weakening the dialog's close or no-edit assertions.

The new cases keep actual Tk focus and key delivery, modal grab ownership,
the real public upscale worker and queued adoption, exact Pixel art pixels,
metadata, Undo, Stop/source-identity rejection, and the 25-megapixel disabled
Apply gate. The successful flow also uses the existing bounded native popup
driver to verify that F4 / Escape closes the real selector popup while leaving
its editing dialog alive. It never substitutes `menu.invoke` or an artificial
menu-selection state. Native callback errors and Tcl background errors fail
the fixture; original files, source image ownership and global key bindings
are checked.

The applied caller patch uses `KeyboardOptionMenu` and `KeyboardButton`
locally. A dialog-local Escape binding on the logical selector preserves the
existing close behavior when no native popup owns focus. This introduces no
global CTk, Tk or keyboard patch and changes no resampling or start policy.

## Final validation and review

After the controller patch, all **four actual native Upscale methods passed in
1.844 seconds** on Linux / Xorg / Tk 9.0.4. Log:
`/workspace/scratch/97bfc35400fb/batch24-upscale-native-after.log`.
The first after attempt, retained as `batch24-upscale-native-after-initial.log`,
reached two new readout assertions and exposed a fixture API mistake:
`cget('textvariable')` returns a native Tcl token, not necessarily a Python
Variable. The assertions now read the actual native label's visible text;
no callback, limit or expected output was weakened.

The adjacent upscale/edit-history/source-timer/Auto-preview and keyboard gate
completed **67 tests in 3.521 seconds: 62 passed and five existing Windows-only
cases skipped**. Log:
`/workspace/scratch/97bfc35400fb/batch24-upscale-adjacent.log`.
Independent source review of the Upscale caller and tests found no blocker.
The final native rerun after the separate KeyboardButton timer-cleanup
completion passed **8/8 tests in 4.654 seconds**: the four actual Upscale flows,
the new native widget-timer case and all three existing composite pointer/focus
methods, including the real popup. No Tcl error diagnostic was emitted. Log:
`/workspace/scratch/97bfc35400fb/batch24-upscale-native-final.log`.
Independent Upscale review is now closed without blockers; the reviewer read
the final native report and controller/helper boundaries. A separate
independent review of the widget-timer change used this same combined run.
A final headless palette/upscale/edit-history/keyboard gate against that helper
completed **44 tests in 1.111 seconds: 39 passed and five unchanged
Windows-only cases skipped**, in
`/workspace/scratch/97bfc35400fb/batch24-ui-final-focused.log`.
The final frozen-source full-project gate is recorded below.

Linux native evidence does not certify the Windows menu implementation.
The preceding exact baseline `bb6dfa6` passed
all seven remote checks (Windows 4,270 tests / 326.944 seconds / three existing
GPU skips, plus packaged GUI and native drag/drop); those results do not claim
validation of this new candidate.


## Frozen combined gate

The final combined native run passed **10/10 in 5.173 seconds** after the manual
palette-worker change, with no native/Tcl diagnostics. The complete frozen
project run passed **4,308 tests in 205.763 seconds: 4,242 pass and 66
platform/hardware skips**, with all 900 source/configuration hashes unchanged.

The initial full run also found four subcase failures in one older Sketch Fill
prepared-palette fixture. Its direct state assignment skipped the actual
`picture_palette_complete` handler's explicit workflow selection. The fixture
now uses that real handler and real plan invalidation, additionally checks
adoption/selection/save/show, and keeps every original selector, execution and
raster assertion unchanged. The selector plus UI24 palette gate passed
**10/10 in 0.730 seconds**; the full gate was repeated on the final snapshot.
This fixture correction adds zero IDs and does not relax Manual workflow policy.
