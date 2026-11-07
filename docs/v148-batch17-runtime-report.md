# Batch 17 — present the current execution's runtime safety evidence

Baseline: `e87bcf1b783b33ff866c2188e10c8b5d22a22707`.
This area implements **one verified behavior group, A1701**. Current-result ownership,
stale-event rejection, stopped evidence and the matching Open action are one
controller contract. The correction-retry Stop handoff below completes
**A1501 / global 797** and adds no new ID.

## A1701 — bind the safety card and Open action to the current execution

### Reproduced behavior

The executor already retains its final runtime report in the executed plan's
options, including independently available evidence when report saving fails.
The controller's `done(draw/dry-run)` refresh instead reloaded the most recent
report from disk. With an older saved PASS and a current stopped run whose
report could not be saved, the actual safety card showed the older PASS and its
99 drawn paths. Open also selected that older report. A successful current run
unnecessarily rescanned saved history rather than using the result it had just
produced.

Correction-only retry copied the base plan's options, including its previous
runtime report. An exception early in the real executor, before its report
finalizer was established, could leave that inherited report available as if
it belonged to the retry.

The initial actual-controller regression ran seven methods on the baseline:
six failed and the startup-history control passed. This included real drawing,
dry-run, correction retry, executor failure, failed report publication and Open.
The failure was in the normal worker-to-UI flow, not only in a helper test.

### Correction and ownership

`RuntimeSafetyView` owns one private request identity per accepted drawing or
correction attempt. Starting a request clears older current evidence. Worker
publication captures the executor's final report in a `finally` block and
deep-copies it without retaining the plan or any image. The UI accepts only its
current request and takes its own independent copy. Plan mutation after queuing
and event-payload mutation after adoption cannot alter the displayed result.

The current request survives Stop, so the executor's STOPPED evidence is
accepted even while the shared Stop flag remains set. A worker stopped before
entering its task, failed worker startup, or an executor with no report yields
an explicit current-attempt unavailable/STOPPED state. It never becomes an
older disk PASS. A new request, Clear, and closing reject retained old results.
The retry discards only its copied runtime-report field before execution; the
base plan's report remains intact.

The safety card and Open select the same current payload. A failed save leaves
the current results visible and explains why no saved current report can be
opened. Later unrelated report files cannot change the current card or Open's
destination. Saved history remains available at application startup, before a
local request or Clear takes ownership. Clear intentionally does not restore
older history as current evidence.

### Deduplication

- **DP48 / global 379** bounds and validates stored evidence and skips invalid
  newer files while searching history. Its reader remains the startup fallback.
- **DP49 / global 380** preserves runtime counts/fills when saving and full
  serialization fail. A1701 consumes that existing in-memory result in the UI;
  it does not count report production again.
- **P1701** independently derives historical Open destinations from the selected
  disk report and its real text sibling. A1701 selects which execution's report
  Open uses. The shared actual Open controller is tested with both changes.

## A1501 completion — preserve Stop during correction-only retry handoff

The correction-only action still used the worker's default `reset_stop=True`
after synchronous preflight and settings save. Its actual controller lost Stop
received during target preflight, settings save, or task-window construction.
It also entered native preflight and saved settings while profile selection or
Clear was pending, before the worker's later guard rejected the work.

Three added methods reproduced six failing subcases before this completion:
three lost-Stop boundaries and three pending profile/Clear boundaries. Stop
during thread construction and the positive case of a new explicit retry after
an earlier Stop already passed.

The action now uses the shared profile-action readiness guard before preflight,
clears an earlier Stop once at the start of the accepted explicit preflight,
and hands work to `begin_worker(..., reset_stop=False)`. Stop received afterward
remains authoritative. Existing prerequisites, correction eligibility, unlock,
target/palette checks and native-input guards are retained. This extends the
already counted A1501 start-to-worker contract to its correction-retry caller.

## Evidence and limits

`test_v148_application_batch17_runtime_report.py` uses the real draw/retry
controller, tracked worker wrapper, queue, event handler, planner, guarded mouse
and executor. The fixture replaces desktop/input/capture/wait boundaries and
unrelated local persistence; reports themselves use the real save/loader in a
temporary directory. The platform Open boundary is mocked, so no file is
launched. Tests cover current success, dry-run without clicks, current Stop,
failed save, early retry failure, retained base-plan evidence, stale events,
Clear, closing, stopped/rejected startup, both copy boundaries and matching Open.

All 18 methods in the new file passed with the four P1701 loader/Open methods
and the adjacent runtime-report, correction-review, explicit-start preflight,
plan-adoption and worker/UI lifecycle regressions: **100 tests passed in 1.003
seconds, with no skips**.

```sh
.venv/bin/python -m unittest \
  test_v148_application_batch17_runtime_report \
  test_v148_platform_batch17_report_paths \
  test_runtime_safety_report_v1057 test_runtime_safety_ui_v1058 \
  test_step15_correction_review_recovery_v10139 \
  test_v148_application_batch15_preflight \
  test_v148_application_batch15_plan_adoption \
  test_v148_ui_runtime test_v148_ui_lifecycle_batch02
```

Independent review and final batch-wide validation are recorded before
publication. No timing, rendering-quality or external-input claim is made;
elimination of history rescans is checked deterministically through the actual
loader call count.
