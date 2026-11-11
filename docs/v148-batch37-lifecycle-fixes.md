# v1.0.148 — recovery decisions and profile/canvas lifecycle fixes

## Scope and counting

Baseline: `e7c13861346129227c7696e348fecb396933cda7` on the draft
`improve/v1.0.148` branch. This batch completes four existing lifecycle
contracts in the application controller, profile portability and recovery
storage. It retains the current PNG preparation implementation and existing
profile/recovery file formats.

**Zero new improvement IDs: 843/1,000 implemented; 157 remain.** These are
corrections within existing reset/migration, failed-load protection,
cancellation and recovery contracts. Tests, assertions, feedback messages and
documentation are not additional improvements. The machine registry remains
byte-for-byte unchanged.

## Reproduced defects and implemented changes

### 1. Reset must retire the generic profile's legacy palette sources

Reset removed `calibration.json` but left `positions.txt` and `palette.json`.
The actual reload path through `_apply_profile_change`, `refresh_palette` and
`Colors.load_calibration` could then restore that old palette and report it as
calibrated. Reset therefore did not remain reset.

`profile_reset_paths` now includes both legacy files in the existing atomic
file-set transaction **only for Other drawing app / generic**. Other profiles
keep these shared files. The legacy reader remains available until an explicit
Reset, and later explicit calibration still works. If backing up either old
file fails, the existing transaction restores the complete previous file set
before any reload. This completes the existing migration boundary
**SR08/global412** and preservation contract **068/global68**.

### 2. Report saved profile changes separately from a failed settings reload

Import, Reset, Rename and Remove could complete their disk/register changes,
then fail to load the selected profile in the UI. The prior failed-load
protection correctly retained the source data, but these actions overwrote its
error with success status or displayed a success dialog.

The actions now keep the current settings-path error and show a warning that
states which saved change completed and which reload needs retry. Their
existing profile-name return values and publication behavior remain intact.
Selecting the same protected profile again retries the actual read without
saving fallback values or repeating an import. Copy import keeps the same
committed UUID and files. An unrelated protected path does not interfere with
normal successful feedback. This completes **AW08/global622**,
**AW10/global624** and **AW13/global627**.

### 3. A recovery dialog decision belongs to the checkpoint it offered

The recovery dialog runs a nested event loop. While it was open, a newer image
or checkpoint could be adopted. The old Yes answer could then restore stale
data, and the old No answer could delete a checkpoint the user had never been
offered. A pending autosave encoder could also publish the superseded source
while an accepted recovery was loading.

The controller captures the offered source identity and checkpoint, then checks
them again after the dialog, alongside its existing activity/shutdown guards.
A stale choice preserves current work and gives an explanatory status. A valid
Yes cancels the previous autosave timer and encoder before loading the offered
image through the existing owned worker path.

For No, `clear_snapshot_if_current` compares and deletes under the existing
reentrant snapshot/file guard. A newer publisher therefore cannot slip between
the comparison and deletion. When an encoder is still finishing, the existing
tracked clear worker waits for it and performs the same conditional deletion.
A late mismatch retains the newer files and restores the prior suppression
and render-resume state. The already-cancelled encoder stays cancelled; a fresh
autosave can run normally. Ordinary explicit Clear and unchanged Yes/No retain
their existing behavior. This completes **AW17/global631** and
**A1001/global766**, including their existing cancellation/ownership boundary.

### 4. Cancelled canvas analysis must not publish part of a new selection

`set_boundary` assigned new corners/target information and cleared setup state
before all cancellable analysis had finished. Stop during Gartic detection
could leave a new area with an old plan. Stop or shutdown during a native
target probe or anchor analysis could also accept and save the late selection.

The full analysis/adoption step now restores the previous corners, anchor
metadata, target window/client/DPI and browser drawing region on cancellation
or failure. Saved area, small-test state and color cache are committed after
the final cancellation check. The existing anchor detector receives the
existing cancellation callback and its `InterruptedError` is preserved.
Successful selection still saves settings, invalidates the old plan and input
authorization, schedules normal recovery and retains the existing crop
ownership/cleanup. This completes **UW12/global693** and **IW08/global582**.

## Executed regression evidence

Each accepted before/after pair uses identical frozen new test bytes. Before
runs use a separate worktree at the exact baseline above, with only the new
test module added. The final integration runs all four modules together.

| Area | New methods | Baseline result | Patched result |
| --- | ---: | --- | --- |
| Legacy palette Reset | 5 | 3 passed; 2 methods failed, with 4 failing subtests | 5/5 passed in 0.026 s |
| Profile reload feedback | 5 | 1 passed; 4 methods failed | 5/5 passed in 22.238 s |
| Recovery dialog identity | 10 | 3 passed; 7 methods failed | 10/10 passed in 1.373 s |
| Canvas adoption | 6 | 2 passed; 4 methods failed | 6/6 passed in 1.536 s |
| Final combined integration | **26** | — | **26/26 passed in 23.993 s; zero errors/skips** |

The native Rename/Remove test has two failing child subtests in its baseline.
Child tracebacks are repeated in the parent log; they are not additional test
methods. The 26 cases are the four modules' unique methods, not an addition of
overlapping test selections.

The final combined run used Linux Python 3.12.14, Pillow 13.0.0 and a real
Xorg/Tcl/Tk/CustomTkinter display. All **919 source, asset and registry hashes**
were unchanged throughout that run. Its command was:

```bash
python -m unittest -v \
  test_v148_application_batch37_legacy_palette \
  test_v148_application_batch37_recovery_dialog \
  test_v148_ui_batch37_boundary \
  test_v148_ui_batch37_profile_reload_feedback
```

The five profile-feedback cases exercise the actual native application,
profile files/registry, reload and selector retry in isolated child processes.
They require a display and are skipped on a headless runner. The other 21
cases run without native windows. Recovery uses real PNG encode/decode,
workers, storage locks and result adoption. Canvas tests use real Tcl, both
detectors, controller adoption, settings persistence and plan invalidation;
only OS picker delivery/native metadata and explicit interleaving/fault
boundaries are controlled.

Executed adjacent selections also passed:

- **11/11** existing profile storage, completion and legacy palette-reader cases.
- **8/8** existing asset-based recovery-resume and image-free Clear cases.
- **11/11** existing image-free picker lifecycle and profile-transaction cases.

These selections are not additional new tests. Commands, per-run hashes,
observed results, retained failure output and the combined source map are in
the [validation record](v148-batch37-validation.json). New exact-head
Windows/Linux CI and packaged-app results are recorded in
[draft PR #46](https://github.com/Vxiey/Image-Draw-Bot/pull/46).

## Provenance, compatibility and limits

New raster tests read only the repository's existing
`paint-tools-reference.png`, `image-draw-bot-icon.png` and
`image-draw-bot-app-screenshot.webp`. No synthetic image motif, mockup or AI
image was introduced. Existing dependency versions, rendering engines and
version number were not changed.

The first legacy rollback fixture observed the transaction's deliberately
retained lock sidecar. The final fixture establishes that real transaction
before taking the complete disk snapshot; it does not filter files from the
rollback comparison. Both final before/after runs were repeated using the
same frozen test bytes. An early unfrozen canvas test draft produced several
per-field subtest failures; those are not the accepted four-method baseline.
No separate raw log or frozen hashes were saved for that early canvas draft;
the record identifies it as reported initial diagnostics only. A preliminary
recovery baseline run repeated the same seven expected failures with unchanged
test bytes; it is not a second distinct test set. These attempts are kept
separate from the accepted comparisons in the validation record.

The canvas-specific after run and its adjacent run have different complete
`DrawBot.py` hashes because the independent recovery edits landed between
them. Each run's files were stable while it executed, and its `set_boundary`
scope hash is identical. The final combined run binds both changes to one
unchanged complete source snapshot.

Independent source/test reviews approved the profile feedback, legacy Reset,
recovery and canvas corrections without blockers. A separate static inventory
confirmed 26 unique new methods and no imported TestCase duplication or newly
generated raster fixtures.

Source-package hygiene passed for **1,402 files**, with no warnings,
forbidden paths or missing required files. `git diff --check` passed. These
checks and all four identical frozen before/after test hashes are recorded in
the validation JSON.

Local runs do not operate physical Microsoft Paint, real Win32 window capture,
Windows display scaling, the system clipboard or GPU hardware. The native
target probe retains its existing bounded execution time; cancellation rejects
its result when it returns. No new performance claim is made. Recovery
identity checks do not claim to freeze another process for the whole modal
dialog or subsequent restore; conditional deletion is the operation protected
by the atomic guard.

The previous PR description, including batch36's exact-head CI and failed
attempt history, is preserved in
[the batch36 history](pr46-history-through-batch36.md). Earlier green checks
are not verification of this patch. PR46 remains draft. No merge, tag or
release is authorized without the user's explicit approval.
