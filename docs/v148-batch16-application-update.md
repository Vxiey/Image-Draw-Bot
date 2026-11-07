# v1.0.148 batch16 — own the deferred update handoff

Baseline: `d1a5e3a709745ee64263b5801cf1b9089cd6b707`.

This ledger implements **one behavior group, A1601**. Request identity, private
cancellation, worker handoff, duplicate callbacks and successful installer
completion are parts of the same user-triggered update lifecycle. They are not
separate improvement IDs.

## A1601 — a stopped update cannot be revived by another operation

The existing updater downloaded and verified an installer on a tracked worker,
then queued a 100 ms Tk callback to start installation after the worker finished.
Its request was an opaque identity token. The callback also checked the global
Stop event. The Stop button cleared the token, but the registered Esc hotkey
only set the global event. A later legitimate worker could clear that event
before the old installer callback ran.

The baseline reproduction executes the actual `DrawBotApp` constructor and
captures the callback it registers with `keyboard.add_hotkey('esc', ...)`. It
then runs the real update controller, `begin_worker` wrapper and event handler.
Tk surfaces and external update/download/launch boundaries are controlled local
doubles; no executable is downloaded or launched.

Six initial tests produced four passing controls and two failing regressions:

| Scenario | Baseline installer / close calls | Required result |
| --- | ---: | ---: |
| Current successful request, including a duplicate old callback | 1 / 1 | 1 / 1 |
| Esc without a later operation | 0 / 0 | 0 / 0 |
| Stop button, a new operation, then the old callback | 0 / 0 | 0 / 0 |
| An explicit new update replaces the previous request | Only the new request | Only the new request |
| Esc after deferred installation was queued, then a new operation | **1 / 1** | **0 / 0** |
| Esc before delivery of the queued update result, then a new operation | **1 / 1** | **0 / 0** |

The two regressions demonstrate both an unwanted installer handoff and app
closure. They do not depend on timing sleeps or a Tk poll between user actions.

## Implementation and boundaries

`UpdateRequest` owns a private cancellation event and short locked phase
transitions: `checking → ready → installing → started → consumed`. A check
without an installer ends at `finished`. There is no method that clears the
private cancellation flag. The request retains no Tk or application references,
and its lock is never held during network, filesystem or installer work.

The actual Esc registration calls the Tk-free `_request_stop`. It latches the
current request's private cancellation before publishing the reusable global
Stop signal. The same method serves the Stop button and worker startup failure.
Checking the private request therefore remains sufficient after another worker
clears global Stop. A new explicit update cancels the old request and creates a
fresh one.

A real-thread review regression parks the keyboard thread immediately after
the global `Event.set`, lets the GUI thread run a new legitimate operation and
then invokes the old callback without polling. The first implementation, which
signalled global Stop before private cancellation, still launched and closed
once. The corrected order closes that observable interval within A1601.

Metadata, download progress, completion and installer events carry their exact
request identity. Superseded or cancelled progress/results cannot alter the
new request's UI or schedule installation. An accepted installer callback must
claim the `ready → installing` phase once. Settings save is followed by a fresh
cancellation check, and both updater workers use `reset_stop=False` after the
explicit action has established their Stop boundary. Esc during settings save,
worker-window construction or thread construction cannot be erased at handoff.
Startup rejection or failure cancels the request.

The existing verified `UpdateCenter.launch_installer` remains the external
launch boundary, including its size/hash/header checks and Windows deny-write
handle. It receives the request-aware cancellation callback. Once that launcher
has successfully created the process, a later Esc cannot undo the process; the
worker records `started` and the matching completion consumes the close-for-update
handoff once. A duplicate callback cannot start another installer or close the
app twice. No forced process termination is added.

## Deduplication

- Original076 concerns Stop during release/metadata network reads.
- Original081 concerns verified installer bytes and the Windows file-lock
  boundary immediately before process creation.
- PF02 concerns verified installer reuse and cache retention.
- The AW13 completion in batch08 prevents installation after failed settings
  publication or a protected future settings schema.
- A1405 owns Browser One-Click's deferred drawing request.

A1601 owns the separate deferred **update installation request** across worker,
UI and keyboard-thread boundaries. The earlier transfer, binary verification,
cache and settings contracts remain in effect. The helper, phase representation,
late review correction and additional tests do not add IDs.

## Verification status

The new controller regression module,
`test_v148_application_batch16_update_handoff.py`, contains **17 tests**. They
cover the baseline failures and controls, the real keyboard-thread interleaving,
fresh explicit updates after an earlier Stop, cancellation during settings save
and both worker construction boundaries, startup failure, transfer-callback
cancellation after global Stop reuse, stale progress/results, actual shutdown
and the already-started process boundary. The real controller, constructor,
worker wrapper and event handler remain in the path.

The existing batch08 updater fixture now creates a real ready request and
verifies its actual installer event consumption. It retains the request through
`installing` and `started`, then verifies consumption at the real completion
handler. Its previous disk bytes, failed-save and future-schema assertions
remain intact.

The final focused/adjacent run completed **161 tests in 0.409 seconds: 157 passed
and four native Windows tests were explicitly skipped**. It included the new
module, batch08 settings-save boundaries, installer/update/security/maintenance
tests, batch02 update cleanup, batch05 update transport, batch06 pagination/cache,
UI runtime and lifecycle, batch15 drawing preflight/source ownership and batch14
Browser One-Click ownership. `git diff --check` also passed.

Root independently reviewed the request helper, all controller/event patches,
the actual constructor/hotkey tests, the keyboard-thread interleaving and the
already-started process boundary. The review is closed without blockers.
A separate 42-test updater/save/preflight/Browser One-Click run passed in
0.191 seconds. This overlaps the earlier gate and is not an additional count
of unique tests or improvements.

Native Windows installer launch and file-sharing behavior remain the existing
platform tests' responsibility. These local results do not claim Windows process
creation or a real installation. No timing or memory optimization is claimed.
Whole-program gates passed; see [final local validation](v148-batch16-validation.json).
Exact published-commit Windows/CI results are recorded separately in PR46.
