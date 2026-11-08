# Batch 30 — preserve Stop across image-copy worker handoff

## Classification and status

**Focused regressions and the adjacent image-worker gate pass. This completes
A1501/global797 and adds zero IDs.** The existing contract preserves a new Stop
from an accepted action through its synchronous preparation and worker handoff.
Its earlier drawing callers were already covered. Save PNG and Remove background
still handed their private source copy to a worker that cleared Stop again.
Snapshot cleanup remains the existing image-ownership contract; the regression
tests and compatibility changes are not separate improvements.

The focused implementation checkpoint is preserved below; completed integrated validation is appended. The new published head requires its own Windows CI.

## Actual before evidence

The original read-only probe ran against published batch28
`bfa43deb090c9ef858b04313fad9559ec4acfab1`. Its six cases used the actual Pillow
copy, actual keyboard-safe `_request_stop` callback on another Python thread,
real `begin_worker` and `Thread`, real background algorithm or PNG encoder and
atomic writer, and the actual event handler. Both actions lost a Stop delivered
after their source copy and before worker handoff. PNG export replaced the
previous complete PNG; background removal published and adopted a changed
source. The four old-Stop and thread-construction controls passed. There were
two expected contract failures, zero fixture errors and zero forbidden writes
or network calls. All 883 root Python files stayed unchanged.

That evidence is retained under `pending-batch30-stop-copy/before/summary.json`
(SHA-256 `f426485bbe5714c8a583c03918b24a2dbf50e1f057dd196ee40cf5b306abf10a`).
The original script and log are unchanged.

Before editing batch30, exact method-source hashes were compared across that
parent, published batch29 `4b90b715a9128a022774f411e14e8a1b45676339`, and the new
worktree. Both actions, `begin_worker`, `_request_stop` and `_handle_event` were
identical. The complete `BackgroundRemoval.py`, `RuntimePaths.py` and the two
shared fixture modules were also byte-identical between the published parents.
The linkage report is `pending-batch30-stop-copy/published29-linkage.json`,
SHA-256 `4379c3c82c68b0864adf93f74819e60aa064ba92dbd88907fc71647134142fc4`.

The permanent six-method module was then executed against the entirely
unchanged published batch29 checkout. It independently produced exactly two
expected failures: both actual backends ran after the new Stop had been erased.
The other four methods passed; there were zero errors or skips. Its 887-source
map remained
`48245acbd0a159956f998b1009f022a5d7b0245f977f741eef84016c9ffbb4bc`.

## Narrow change

Remove background clears a previous Stop after its closing, activity and
source-presence guards, immediately before taking the private source copy.
Save PNG does so after the file dialog accepts a destination and its existing
closing, activity and exact source-identity recheck succeeds. Both callers pass
`reset_stop=False` to the real worker handoff.

Consequently a new Stop during the copy remains set. The worker declines the
request, the caller's existing `finally` closes the copy, and neither the PNG
encoder nor background algorithm starts. A Stop at real worker construction
still follows the existing interrupted-worker cleanup and `done` path. A new
explicit accepted action still clears an earlier Stop and can finish normally.
Rejected requests and cancelled or invalidated PNG dialogs keep the old signal.

The refused, stopped request has no worker `done` event. A subsequent actual
status assertion exposed that this path otherwise left “Saving PNG…” or
“Removing…” visible. Both actions now set “Stopped.” on the calling GUI thread
when that handoff returns false with Stop set and the app remains idle and open.
The status update is after a normal return from `begin_worker`, so a primary
startup exception is not replaced. The existing Tk/RuntimeError/AttributeError
containment policy keeps unavailable feedback from changing the false return
or skipping snapshot cleanup. Busy and closing states do not receive this
replacement status. This is a completion of the same cancellation handoff.

The PNG encoder settings, atomic writer, orientation/alpha handling, background
algorithm, result adoption and borrowed source ownership are unchanged.
There is no new cancellation token, native-input action or background thread.

Four older `test_v148_ui_batch03.py` fake-worker signatures now accept the
existing keyword-only `reset_stop=True` argument. Their tasks and all original
success, refusal, cleanup and failure assertions remain unchanged. This is
test-double compatibility with the actual handoff, not a new behavior group.

## Tests and provenance

`test_v148_application_batch30_stop_copy.py` now contains eight methods covering:

- Stop from another real thread after the real PNG source copy, preserving the
  prior complete file and closing the private snapshot;
- the same boundary for background removal, preserving current source and Undo;
- explicit new actions after a previously latched Stop, including actual PNG
  decode, background pixels and event adoption;
- Stop during construction of the actual worker thread, with task omission,
  snapshot cleanup and final Stopped status;
- cancelled PNG dialogs and source, shutdown or busy changes during the dialog;
- rejected busy, closing or image-less actions without copying or clearing Stop.
- unavailable Stopped feedback without changing refusal or snapshot cleanup;
- a retained real worker-construction error without feedback masking the
  primary exception or leaving the copy open.

Only established UI/native-window ports and the file dialog are replaced.
Backend observers delegate to the real functions. No synthetic worker clears
Stop. The tests verify that callbacks and work run on the expected distinct
threads, borrowed pixels stay readable, private images close, and no success
event or file publication follows cancellation.

| Gate | Result | Evidence SHA-256 |
| --- | --- | --- |
| Six permanent methods against frozen published29 | 2 expected failures, 0 errors/skips; 0.063 s | `7b2472815f1be9b8d4f8550383eb1adb1c3ac0a863d3c735b07eae96d1545563` (`permanent-before.json`) |
| Same six methods after the fix | 6 pass, 0 errors/skips; 0.043 s | `005a5986894cc81563cf684a972af8138d89280087a43cd9e81f7e275268fde9` (`permanent-after.json`) |
| Focused plus adjacent gate | 57 pass, 0 errors/skips; 1.792 s | `e2e213c0f65e2aed6de6f99d68d0a8500f91fe28dac8590bc5a2e41dd294c4d1` (`related.log`) |
| Later status assertion before the presentation completion | 2 expected failures in six methods, 0 errors/skips; 0.047 s | `6347f95d1c78612be46cc0bbd7071f7d8a66fb204a4a47868466d51aa76069c1` (`status-before.json`) |
| Final eight methods, including feedback and primary-error cases | 8 pass, 0 errors/skips; 0.067 s | `83fdcf17e7a7b5df6568ba6d8d41eb5d575c6d53580b352d22aa45751ddc9943` (`status-after.json`) |
| Final focused plus adjacent gate | 59 pass, 0 errors/skips; 1.764 s | `25c7e7205b63293c8134a826c2ec859f6ddde9c64f8543611498918ab6c571ae` (`related-final.log`) |

All these runs redirect runtime paths to private temporary directories and
reject repository writes and network access. Each reports zero audit
violations. The after-only focused run has its own unchanged 888-file WIP map
`3799deb050a5312ea05e326da236fe9ff915ceb4b60016c7c1deac2ffca391fd`;
that initial checkpoint is not the final batch30 source manifest. The later
eight-method run records its separate unchanged 892-file WIP map
`6b0e24371a7e95598e145bfde52bff8fa0f12ded0e7226cca55d9becb54becae`.
Concurrent batch30 work between these checkpoints is not attributed to this
completion. The adjacent gate
includes the actual image-worker cleanup, PNG28 ownership, UI03 export/failure,
modal preview identity, background ownership, worker startup, source timer and
edit-history regressions.

Reproducers are `pending-batch30-stop-copy/run_focused.py` and
`pending-batch30-stop-copy/run_related.py`. For example, from the new worktree:

```sh
.venv/bin/python -B ../pending-batch30-stop-copy/run_focused.py \
  --repo . \
  --tests ./test_v148_application_batch30_stop_copy.py \
  --output ../pending-batch30-stop-copy/a-new-focused-report.json
```

The output must be new; the runner opens it exclusively. The preserved before
and after files are not overwritten. These are portable Linux tests of actual
application methods and Python threads, not native Windows keyboard injection
or performance measurements. Exact-parent CI is recorded separately from this
unpublished fix.

Root independently reviewed the initial handoff and six-test boundary, then
closed the final status and eight-test review without blockers after the
59-test gate. No global count is changed here.


## Integrated frozen-source result

Batch 30 records **842 distinct improvements, 158 remaining**. 2 new behavior groups are registered: R3001, R3002. Background cleanup preserves detail already protected by the border flood; picture-palette growth avoids retesting unchanged centers. Portrait stroke ownership, Stop across image-copy handoff and test-fixture Tcl disposal complete existing contracts with zero IDs. All 840 prior registry entries and 78 earlier benchmark JSON reports are preserved. Completed frozen discovery ran **4,551 tests in 231.751 seconds: 4,478 passed and 73 skipped**; all 943 source/configuration hashes were unchanged. Fourteen Linux/Xorg native cases, the 5,000-cycle source gate, eight exact raster fixtures and initial package hygiene (1,359 files) passed. The package check after final metadata passed with 1,361 files and no warnings. The incomplete process attempts and the Tcl-aborted attempt remain negative evidence. A proved old calibration fixture released borrowed Tcl aliases after real cleanup; no product GC policy, skip, assertion or timeout was weakened. The final background and Portrait historical comparisons and the six-workload/six-pair palette measurement retain their original 892-file map; the final 893-file map differs only in the two explicitly recorded fixture files. Historical checks retain 20 exact background controls and 24 intended corrections, 14 Portrait helper and seven public pairs, and 32 palette comparisons including four public plans. The cold red picture-palette helper and direct refinement improve in all six pairs; unchanged-work controls are not treated as algorithm gains. No universal speed, peak-memory, process-RSS, physical Paint or GPU improvement is claimed. Parent 4b90 has seven green checks after one unchanged Windows-job rerun; the new head requires its own exact-commit CI. Version 1.0.148 remains unreleased.

The final gates bind **893 root Python files**, compact SHA256 `0da8de7641efb47fea77c62ece22629b27f9425c137e9d8ccd8d7e9933ae5845`, and **943 source/configuration files**, compact SHA256 `5f6b89f5b52c9ae6f0335345f744fb887936afdab1e847eb5c22d73f3c155b41`. The original measured/evidence map remains **892 root files**, SHA256 `ce9691bce3bdb6b6e992ab3383b323e803f85e8df95c6a99ff6f409a9d345abd`. The only later differences are the old calibration fixture cleanup and its new subprocess regression; their exact sources, hashes, import boundary and diff are recorded in [raw evidence](v148-batch30-completion-evidence.json) and [final validation](v148-batch30-validation.json). No timing or image checkpoint is silently rebound. The final metadata review and post-metadata package check are recorded separately; publication of the new head does not imply its remote checks have completed.
