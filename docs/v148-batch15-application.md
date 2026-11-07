# v1.0.148 batch 15 — application handoff

Reference: `43a1c968eb56a63224827f1567e4ccc354acdadb`.
This working ledger does not itself advance the global registry or release.

## A1501 — preserve emergency Stop throughout an explicit drawing start

The real global Esc hotkey calls `self.stop.set()` directly. `draw` performs
target, calibration, browser, brush/tool and settings checks synchronously before
calling `begin_worker`. The latter unconditionally cleared the same event.
Reproductions at the visual preflight and late `save_settings` boundary both
reached the planning worker with Stop reset, despite no intervening new Start.

A fresh explicit `draw` now clears an old Stop before beginning preflight.
Its worker handoff uses `reset_stop=False`; checks before and after the native
worker construction preserve any subsequent Stop, including the narrow handoff
window. A cancelled start transitions to ABORTED. `InterruptedError` from a
brush/tool detector propagates to the preflight failure path instead of being
mistaken for ordinary low-confidence detection. Ordinary detector errors retain
their conservative fallback and can still reach planning.

This concerns an accepted synchronous drawing start, after authorization. The
earlier A1405 group owns deferred Browser One-Click requests before this stage;
its source/profile/request guards and private cancellation remain unchanged.

`test_v148_application_batch15_preflight.py` exercises real `draw` and
`begin_worker`, with platform operations and the final planning boundary replaced.
It covers Esc during preflight, settings persistence and worker construction,
Dry run, small-test confirmation, a later explicit Start after Stop, interrupted
detectors, normal detector fallbacks and retained source ownership. Eight tests
pass; the two original Stop reproductions fail on the reference behavior.

## A1502 — retire the drawing source snapshot at the planning handoff

`draw` copied the full loaded image even for its independent small-test plan,
before asking whether the user wanted that test. A real drawing kept this
private source copy open throughout execution even after the planner had
returned its independent image resources. An accepted worker stopped before
calling its task also had no explicit way to release the captured snapshot.
All three behaviors were reproduced through the actual controller and worker.

Small tests now take no unrelated source snapshot. A normal drawing takes one
private source after confirmation/settings and keeps it across any watchdog
retry. It releases that copy as soon as the final plan owns its images, before
execution. A planner that deliberately returns the input in one of its declared
owned image fields transfers that image to the final plan's explicit owner.
Failed publication still releases it after the worker exits; successful UI
adoption retains it for preview and subsequent use.

The tracked worker accepts an optional resource-only cleanup callback, invoked
even when Stop prevents the task from starting. Failed thread startup and
rejected work keep cleanup with the caller. The release operation is idempotent
and never touches Tk or the app's original image. Existing image-ownership
cleanup is part of this one handoff change, not additional IDs.

Eleven regressions in `test_v148_application_batch15_source_snapshot.py` cover the
three original failures, retained planner exception tracebacks, native-thread
startup failure, rejected work, accepted/declined small tests, a timed-out first
attempt followed by a successful retry, deliberate ownership transfer, failed
event publication and a real public `make_plan` whose image resources all stay
usable after release.
This removes the private source's retention during execution; it does not claim
lower planning peak allocation, native memory RSS or faster drawing.

## Existing RT12 capture ownership completion — no new ID

`grab_area` and browser brush-control capture now use the existing bounded
`ScreenGuard._grab_rgb` ownership helper. An already-RGB capture transfers to its
caller without another raster; conversion failure releases the raw capture.
The independent Setup+Verify worker closes its capture before publishing a
result, including failure and Stop. Drawing's brush/opacity/tool preflight shares
one owned capture and closes it after its last consumer, before planning begins.

The existing RT12 contract already counts owned screen-capture cleanup and
borrowed source preservation, so these call-site completions add **zero** IDs.
`test_v148_application_batch15_capture_ownership.py` uses real Pillow images,
retained exception tracebacks, the actual capture callers and independent setup
verification. The preflight tests also verify that both detectors receive the
same live RGB image and that it is closed before planning. No claim is made
about GPU throughput or native screen-capture performance.

## Other existing-contract completions — no new IDs

Final draw plans also complete the existing RT40/RT44 generation and rejected
result ownership contracts. Only preview builds previously stamped
`preview_generation`. The real final drawing plan therefore reached the UI with
no generation, was rejected as stale and had its images closed while the
executor was still using them. An actual `draw → make_plan → execute_plan`
reproduction failed its final canvas scoring with `Operation on closed image`.

Each drawing start now captures its own preview generation and keeps a
`WorkerPlanPublication` outside the plan dictionary. It pins owned images before
publication, records UI adoption or rejection and releases rejected/unpublished
images only after the worker exits. An executor that finishes before the UI
consumes its queued result keeps those images alive for adoption. Stop and
pending clear may reject the UI result immediately without closing images still
being read by execution. Cancellation also rejects an unconsumed publication,
so shutdown does not depend on draining every queued event. Previously adopted
UI images remain owned by that UI. Dry-run sampling shares the same image owner;
publication failures and deliberate source aliases follow the same cleanup.

`test_v148_application_batch15_plan_adoption.py` interleaves the real worker and
UI handler on separate threads. It checks live images, accepted final preview
and time estimate, retained older UI images, delayed UI delivery, cancellation,
stale generation and the real executor's final canvas score. These are
completions of already-counted contracts, not another behavior-group ID.

The same worker cleanup callback now covers owned snapshots in background
removal, PNG source export, captured-screen PNG export and selected-preview
export when Stop arrives before their task begins. Existing rejected-work and
in-task cleanup still apply. These complete IW08/RT12 rather than counting each
caller separately. Three actual-worker regressions exercise Stop before all four
tasks, successful atomic files from all three export paths and successful
background-removal result adoption. Omitting only the cleanup callback reproduces
the four still-open snapshots after accepted work is stopped before its task.

The generic locked-Start help now distinguishes Paint Auto from a selected
manual Paint tool. It directs manual tools through setup, Unlock and Start,
completing A1402's already implemented policy without another improvement ID.

## Review and integration

Independent A1501/RT12 source and actual-flow review is closed without blockers;
the reviewer passed 52 new and adjacent Browser/Paint/budget/setup checks. A1502
review is also closed: the reviewer independently followed the source through
rejected/start-failed work, accepted-before-task Stop, retries, success and
ownership transfer, then passed 75 new and adjacent controller regressions.
The final RT40/RT44 ownership review is closed without blockers. Its 12 actual
worker/UI adoption regressions are included in the full-suite gate: **3,851
tests passed in 103.373 seconds, with 48 platform/hardware skips**.
All 820 source/configuration hashes remained unchanged. Exact package,
raster and measurement evidence is in `v148-batch15-validation.json`; published
Windows results are recorded separately in PR46.
