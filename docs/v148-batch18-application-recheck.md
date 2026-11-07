# Batch 18 — re-check the visible result and apply saved planning settings

Baseline: `d7721a36975a36137b583beda9ff3c47c05208fd`. The independent native-menu
test follow-up `f2cf07bc13ee6e2c44c14096ead703ab9881d216` does not change these
application paths.

This area adds **one verified behavior group, A1801**: the actual read-only
result re-check action. The default-backend capture capability correction,
saved-hardware-recommendation follow-through and final-scoring CPU policy
propagation complete existing contracts and add **zero further IDs**.

## A1801 — make Re-check result a real, bounded read-only operation

### Reproduced behavior

The existing Correction Review state and dialog advertised **Re-check result**,
including a ready state, but the actual Studio review card bound only Review,
Correction only, Full retry and History. Review displayed cached metadata; no
controller action captured and scored the changed canvas. A user who manually
improved the drawing could not obtain a fresh observation without requesting a
new native drawing operation.

The initial three-method regression executed the actual review-card binding
statements, real review controller and guarded capture. Two methods failed:
the advertised action had no real button, and the shipped raw `WindowsMouse`
interface incorrectly failed the existing correction capability check. The
positive control captured through the real `GuardedMouse` without any raw
snapshot method or mouse input. The baseline ran in **0.080 seconds**.

### Accepted operation and ownership

The new visible **Re-check result** button enters a tracked `result-recheck`
worker. It requires a retained completed result and current source, applied
profile, target and canvas. It does not require native-input Unlock or a
previous native preflight. The existing correction-only action retains its
native-input prerequisites and gates.

Each accepted request owns an independent cancellation event and the exact
controller plan/source/profile/target/area/client/DPI identities. Stop cancels
that private event before publishing the reusable global signal. Clearing Stop
for later explicit work cannot revive an older request. Profile transitions,
pending Clear, closing, replaced images/plans and changed target geometry all
prevent old evidence from being adopted. Result, status and completion events
carry the request identity; an old completion cannot finish a newer re-check.

`ScreenTaskWindow` hides the Studio before capture and restores its previous
state after completion or startup failure. The worker gives a short
cancellable countdown so the user can expose the target. It never calls
`prepare_target`, activates the target, arms input, moves the mouse or sends a
click, press or release. The real `GuardedMouse.snapshot_canvas` validates five
target points before and after capture. The helper separately verifies the
stored window rectangle, client rectangle and DPI on both sides of capture;
it refuses changed geometry instead of rebasing an old comparison plan.

The real final-canvas scorer compares the capture with the retained original,
fitted frame, simulated result and quantized target. The capture and all newly
owned scoring buffers are closed on success, Stop and exceptions, including
when an exception traceback remains retained. Existing plan/source images are
borrowed and stay usable. Request references are released on completion,
rejection and failed startup. The worker publishes detached numeric/text
metadata, and the UI takes a separate copy at adoption.

### Fresh evidence without a fictional correction

The fresh observation replaces the current `post_draw_accuracy_meta`. Current
review fields from an earlier correction are retired, so their older
`post_correction_*` values cannot override the new capture. Previous correction
history remains available. A failed or occluded capture produces fresh
unavailable evidence rather than retaining an old successful score.

`CorrectionHistory.record_result_verification` records an explicit
`read-only-verification` operation with a `rechecked` or `recheck-unavailable`
state. It contains the new compact observation and profile context, with empty
before/correction/delta sections. It does not inherit earlier correction gain,
executed path counts, drawing time or throughput. History formatting displays
the single fresh visual/coverage score and labels it a read-only observation.
The existing profile isolation, atomic transaction and 30-entry history cap are
preserved. Stop is checked again before atomic history publication. A record
already committed before Stop is not deleted; the cancelled UI request still
rejects its queued result. A history-write failure leaves the fresh in-memory
observation visible and reports that it could not be saved.

The current runtime-safety report and its card are unchanged. No executor is
called, no completed draw is recorded, and no drawing-time or quality-learning
sample is produced. Observation duration is not supplied as drawing elapsed
time or as new drawing-deadline evidence.

### Bounds and limits

The new operation uses a **15-second cooperative analysis deadline**, including
its countdown. Existing capture bounds remain 64 million pixels and 32,768
pixels per side; the comparison validator limits scoring to 4 million pixels
and 16,384 pixels per side. Native capture/resize work already in progress is
not preempted. Optional history publication uses the existing separately
bounded local-file transaction, whose lock acquisition timeout is five
seconds. These are bounded local analysis/storage controls, not a hard
wall-clock guarantee for operating-system or native-library calls.

### Deduplication

- **AP04 / global 672** already owns correction-only execution without canvas
  clear/fill preludes. That native correction contract is unchanged.
- **AP06 / global 674** already owns a correction attempt's independent
  before/after evidence. A1801 introduces a distinct operation that sends no
  drawing input and writes no correction gain.
- The capability fix is existing **AP04/AP06 completion**: capture belongs to
  the `GuardedMouse` wrapper, while the normal raw `WindowsMouse` intentionally
  has no `snapshot_canvas`. Review readiness and correction retry now check the
  actual guarded-capture context instead of requiring an absent raw method.
- **A1701** presents the current execution's runtime-safety report. A1801 scores
  current visible pixels and leaves that report unchanged.

## Existing U1601/IW40 completion — apply saved hardware recommendations

The real Apply saved recommendation action changed nine planning settings but
kept the previous plan, preview-derived ETA, diagnostics and mobile preview.
It also ignored `save_settings() is False`, so a real atomic-write failure was
reported as a successfully applied hardware profile. Manual application could
run while a drawing, profile transition, Clear or shutdown owned the UI.

Six initial controller tests exercised real settings persistence, the real
planner and the actual runner-to-event-to-done flow. Four methods failed, with
nine failure records including six readiness subcases. Two controls passed:
an identical recommendation retained the plan, and a stopped benchmark's late
result was not applied.

Application now changes the settings as one transaction, suppressing
intermediate variable callbacks and restoring the previous values if saving
fails. Only an accepted change invalidates the cached plan and derived
feedback, once. The actual queued mobile publication receives the original
image and empty preview/safety views. An identical recommendation preserves the
current plan. Existing source-image runtime timing is not reset by a planning
recommendation.

Manual Apply uses the shared profile readiness guard. The real Run + apply
handler has an explicit internal completion flag so it can apply the finished
recommendation while its tracked `performance-auto-tuner` worker awaits `done`.
That path still checks Stop, closing, pending Clear and profile transitions.
This preserves the actual automatic-application caller without making the
visible Apply button usable during an active worker.

This completes **U1601** plan-feedback ownership and **IW40 / global 614**
hardware-worker/application ownership. It is not another improvement ID.

## Existing RD01 completion — preserve selected hardware policy in final scoring

The actual ordinary executor and the new result re-check both called the final
canvas scorer without passing the plan's selected `gpu_mode`. That scorer
made three independent comparisons against the source, simulated result and
quantized target; each comparison therefore used the default Auto policy even
when the accepted plan explicitly selected CPU.

The three-method baseline reproduced two failures in the actual executor and
re-check controller flows: each CPU operation attempted to create the saved
OpenCL backend three times. The default-Auto control passed. The controlled
native-context boundary raised an unavailable-backend error and exercised the
existing fallback; no physical GPU device was opened. The baseline completed
in **0.092 seconds**.

The final-canvas scorer now accepts an additive keyword-only `gpu_mode`, with
the same Auto default for existing callers. Both application callers pass the
current plan's policy, and all three comparisons forward it to the real
accuracy evaluator. CPU scoring now stays on its selected CPU route. Auto and
forced NVIDIA CUDA retain the existing measured-route selection, backend
health checks and safe fallback behavior. This change introduces no profile
cache and does not change hardware detection, availability or quarantine.

This finishes the existing **RD01** hardware-policy propagation contract and
adds **zero IDs**. The separate operation-scoped hardware-profile optimization
remains outside this batch.

## Validation

The three new modules contain **28 passing methods**: 18 for result re-check,
six for saved-tune application and four for final-scoring hardware policy.
Their final focused run completed in **0.999 seconds, with no skips**. They
exercise the actual controller, review-card bindings,
tracked worker, event handler, guarded capture, final scorer and temporary-file
history/settings publication. A real background-thread control verifies that
the worker does not read Tk variables or restore the window from that thread.
Only native desktop/input/capture/wait boundaries and unrelated persistence are
replaced; no real external input or installation occurs.

The re-check cases include current success, explicit start after an earlier
Stop, expired native Unlock/preflight, Stop before the task and during
countdown/capture/scoring/history, Stop followed by global-signal reset,
replaced plan/source/profile/target/area/client/DPI, old same-activity completion,
Clear, shutdown, occlusion, pre/post-capture geometry changes, bounded analysis,
startup rejection, history-save failure and retained-traceback buffer cleanup.
The success case also mutates both the scorer's returned object and the queued
event after their respective publication boundaries: the current UI and saved
history keep the independent fresh score. Actual completed-draw/runtime/quality
learning writers are asserted untouched.

Before the final RD01 completion, the re-check and saved-tune tests plus
adjacent controller, worker, settings, snapshot scoring,
correction-review/history and correction-delivery regressions passed:
**156 tests in 2.239 seconds, with no skips**.

```sh
.venv/bin/python -m unittest \
  test_v148_application_batch18_result_recheck \
  test_v148_application_batch18_saved_tune \
  test_v148_application_batch17_runtime_report \
  test_v148_application_batch16_studio_workers \
  test_v148_application_batch04_settings test_v148_ui_batch03 \
  test_step13_safe_canvas_snapshot_scoring_v10137 \
  test_step15_correction_review_recovery_v10139 \
  test_step16_correction_history_v10140 \
  test_v148_delivery_batch02_correction \
  test_v148_application_batch05_correction
```

After the RD01 completion, the policy tests and adjacent re-check, current
runtime-report, snapshot, correction and hardware-route regressions passed:
**104 tests in 2.021 seconds, with no skips**.

```sh
.venv/bin/python -m unittest \
  test_v148_application_batch18_snapshot_policy \
  test_v148_application_batch18_result_recheck \
  test_v148_application_batch17_runtime_report \
  test_step13_safe_canvas_snapshot_scoring_v10137 \
  test_step15_correction_review_recovery_v10139 \
  test_v148_delivery_batch02_correction \
  test_v148_application_batch05_correction \
  test_v148_rendering_batch08_gpu_policy \
  test_step23_universal_gpu_acceleration_v10146 \
  test_gpu_route_regressions
```

The policy regression observes the actual selector across all three scoring
comparisons for CPU, Auto and forced NVIDIA CUDA. It checks every route's
received policy, zero hardware-profile/context access in CPU mode, the existing
Auto/CUDA fallback and unchanged numeric scores. Only device-creation/import
boundaries are replaced; route decisions are not fabricated.

Independent source review closed without blockers. The reviewer separately
ran the initial 24 methods successfully in 1.042 seconds before the final extra
copy and no-learning assertions; product code was unchanged at that point.
The later RD01 source review also closed without blockers, and its four new
methods separately passed in **0.101 seconds**. Final batch-wide gates are
recorded before publication. These local portable tests do not claim a live
Windows screen capture, a drawing-quality improvement, a physical GPU run or a
performance speedup.
