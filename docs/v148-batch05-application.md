# v1.0.148 batch 05 — recovery and drawing execution

Baseline: `5f3fcfb5c4519e5ed1b9b770ba951918819d725d` (668 published improvements).
This batch contributes **seven distinct behavior improvements**, AP01–AP07.
Repeated callers, backend integrations, tests, documentation and completions of
previous contracts add no count. This checkpoint is part of the requested
1,000-improvement target; it is not a release or antivirus verdict.

## Implemented behavior

| ID | Reproduced previous behavior | Correction and evidence |
| --- | --- | --- |
| AP01 | A manually marked subject rectangle and its mode disappeared on session recovery. Simply saving the rectangle could also bind a new image's selection to an older cached image after a failed image checkpoint. | Save validated normalized subject geometry and mode against the cached image's SHA-256. Attach it only to its matching, successfully recovered raster. A weak source reference advances only after successful image publication, while selection-only checkpoints reuse the encoded image. Real application/disk round trips verify exact subject masks, changed-image failure/retry, malformed or mismatched selection rejection and legacy defaults. Recovery remains Manual and disarmed. |
| AP02 | Every deadline-sequence path copied the complete remaining suffix and all its dictionaries even when normal, unlimited or throttled policy could not reorder anything. | Check the existing eligibility policy before accessing the suffix. Eligible replanning retains its original algorithm and complete metadata. No-tail-access fixtures, 40 seeded active fixtures and an actual unlimited `execute_plan` route verify the adapter. Paired measurements below preserve complete entries and scheduler output. |
| AP03 | After a released-mouse pause, the same-color next path trusted cached color/brush state even though the user could change both while paused. | Invalidate verification samples on pause, restore the known tool and calibrated brush, reselect the current color and perform the configured ink checks before resumed drawing. Real execution fixtures change color and width during the pause, exercise both legacy and ordered paths, and verify Stop prevents resumed input. Unknown manual tool configuration is not claimed to be detectable. |
| AP04 | “Retry correction only” emptied drawing groups but retained executable background/region fill options. It could fill over the existing drawing before scoring a fresh correction. | Skip every canvas-clear/fill prelude for the explicit correction-only operation while retaining those descriptions as comparison evidence. An actual retry with both fill types issues only mandatory input cleanup and fresh snapshots when the correction planner declines patch input; ordinary full drawing still fills normally. |
| AP05 | The emptied retry retained the original total estimate but set path count to zero. Correction costing consequently used a full drawing's time as the cost of one correction path. | Derive a valid per-path reference from the original positive path count before emptying execution. A 60-second/6,000-path drawing supplies 0.01 seconds to the actual correction planner. Fill-only plans provide no fabricated per-path estimate. |
| AP06 | Each retry inherited the first drawing's “before correction” metrics, so even a skipped retry could claim the original cumulative improvement again. Shallow-copied mutable runtime counters could also modify the completed plan and carry old results into the retry. | Start a new before/after pair and runtime counters for each attempt; preserve the original comparison target and completed plan. Fresh scoring becomes the retry history baseline and is reflected in the current UI result. Actual execution/history tests verify a skipped retry reports zero gain, the original metrics/counters remain unchanged, and stale successful evidence cannot replace a failed fresh capture. The existing failed-evidence trust contract is completed without another ID. |
| AP07 | Strict/adaptive ink checks and the retry of a delivery check used the plan's default width, while an ordered entry could have selected a different actual brush. | Use the selected execution width for each check. Two-color execution fixtures verify widths 4→1; delivery retry checks use the same current width as the original check. This is the actual mouse verification boundary, distinct from PL31 simulation/cost inheritance and PB03 detail-batch snapshot ordering. |

## Existing contracts completed, no additional IDs

- **PL31:** `PreviewSafety` carries the last nonempty entry's brush width,
  matching the CPU/CUDA/checkpoint simulation changes in the colour ledger.
  Empty entries do not alter state. The preview regression uses the actual
  `PreviewSafetyPlan` result.
- **DP17:** an entirely clipped adaptive probe is unavailable evidence, not a
  verified color. Both execution routes defer verification to the next path;
  a drawable path cannot proceed without its real probe being approved. Empty
  probes never publish a color/sample cache or a verified-completion claim.
  The caller-side Paint perceptual check precedes adaptive color approval.
  Regression fixtures cover wrong/correct ink after a clipped first path in
  both routes, plus a wholly clipped legacy batch. A boundary-spanning scanline
  derives its short fallback probe from its guarded physical interior, without
  widening the inset or using an inverse coordinate conversion. Enabled
  correction-only execution uses the same fresh color verification contract.
- **RT32/RT34/RT35/RT37:** the application registers the positioned canvas drop
  overlay only after placement succeeds. Drop callbacks recheck the live window,
  expiry, activity, Stop and strict canvas interior before consuming payloads.
  Placement itself belongs to the UI ledger and is counted there once.
- **IW08:** the drawing-area consumer closes its delivered crop after synchronous
  analysis on success, failure or late Stop; the palette-calibration consumer
  can still retain its own crop. Post-draw correction also closes its snapshot.
- RegionPicker's cancellation contract is integrated with the actual application
  Stop/closing state. Delayed browser setup uses the existing `capture_job`
  cancellation slot and rechecks profile, corners, activity and Stop. These
  callers do not add to the UI ledger's selection contract count.
- **UI23:** opening a local file retains modal-time shutdown/activity checks and
  clears pending drop actions. Its file filter uses the shared supported-format
  list from the UI batch.
- **CP02:** the preview summary and diagnostic report expose unresolved spill
  that requires a white palette color. They do not claim the correction planner
  can repaint white when that color is unavailable.

## Validation and independent review

The five new application modules contain **34 tests**:
subject recovery 6, runtime/preview 12,
correction retry 8, overlay integration 4 and region integration 4. These are
application/contract fixtures; no physical mouse input was sent. The separate
runtime/correction cross-area review passed 59 new and related tests before the
additional fresh-counter and clipped-probe regressions. The updated runtime,
adaptive-color, legacy drawing, replanning and correction suite passed 45 tests
in 0.302 seconds. Recovery/UI review is closed; frozen whole-program gates are
recorded in the combined checkpoint ledger. The final independent runtime/
correction/deadline/visual/resume review passed 64 tests in 0.187 seconds; no
blocking finding remains.

## Reproducible paired measurement

Run `python benchmark_v148_runtime_batch05.py`. The earlier
`benchmark_v148_runtime.py` is preserved for reproducing batch02 measurements.
The new benchmark compares the historical `DrawBot` tail-copy call pattern and
the new scheduler adapter with a prepared 20,000-path sequence over 200 checks.
It warms both paths, takes five alternating timing pairs, verifies every entry
and the complete scheduler metadata, then measures traced allocation separately.

| Inactive policy | Before median | Updated median |
| --- | ---: | ---: |
| Normal | 1,152.680 ms | 0.045 ms |
| Unlimited | 1,038.748 ms | 0.042 ms |
| Throttled catch-up | 1,078.800 ms | 0.109 ms |

The raw samples, exact output digests, source hashes and allocation peaks are in
[v148-batch05-runtime-benchmarks.json](v148-batch05-runtime-benchmarks.json).
This measures avoided inactive eligibility work only. Scheduler construction,
active sorting, drawing, native input and real elapsed game time are excluded;
the results do not imply a corresponding whole-program drawing speedup.
