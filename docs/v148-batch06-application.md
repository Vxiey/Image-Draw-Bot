# v1.0.148 application workflow — batch 06

Baseline: product source `f59a57c6fc1eef1ace07e872ba50ed834e1bb924`, followed
by the two Windows regression-fixture corrections in `4c8aa247`.
This developing batch currently contains **seven distinct improvements**.
Final frozen-source integration passed 3,201 tests in 71.794 seconds (31 platform/hardware skips), with unchanged source hashes. The 5,000-cycle source gate, source-package hygiene and eight exact-raster fixtures passed. Windows/Linux CI for this checkpoint is still pending.

| ID | Reproduced problem | Implemented behavior and evidence |
| --- | --- | --- |
| AX01 | A 120-second manual pause plus the three-second resume countdown made an otherwise completed 0.8-second fake-device run teach both speed and ETA models a 123.8-second duration. The analysis also recommended updating ETA from that idle time. | Record each pause explicitly and exclude manually paused runs from throughput, ETA and strategy learning. Keep the honest wall time and canvas-quality analysis, classify pause time separately, and avoid misleading ETA/efficiency recommendations. Actual `execute_plan` and public persistent-model tests prove the exclusion; an uninterrupted run remains eligible and clears old pause metadata. |
| AX02 | Strategy feedback counted only the report's `drawn` category as delivered. One hundred clipped or edge-following delivered paths plus one skipped path consequently produced a zero safety-delivery score. | Include all three exclusive delivered categories. Tests feed actual `RuntimeSafetySession` output through the public strategy writer and prove equivalent accepted proxy scores for interior, clipped and edge-following geometry. The result remains explicitly labeled a runtime delivery proxy. |
| AX03 | Queued worker status/progress could overwrite the explicit Stop status with “Drawing” or “Finished” before the worker exited. | Ignore ordinary status/progress after Stop, then confirm the matching worker's exit. Explicit terminal events preserve real failures and the recording tool's intentional Stop-and-save result. Tests cover queued success/progress, unrelated completion, ordinary completion, timeout text and recording success/disk failure. |
| AX04 | Export always saved the plan's base preview even when the user was inspecting a different layer, and it could differ from the displayed simulated final. | Resolve rendering and export from one shared view map. Export the selected complete original/target/final/heatmap/coverage/safety/detail/stroke/fill/color view with a descriptive PNG name, honor layer toggles, and explain unavailable layers. Actual worker exports are decoded and compared pixel-for-pixel for all 12 views. The modal-time stale image/view checks complete existing lifecycle contracts without extra IDs. |
| AX05 | Reset learned draw timing used raw UI options, whereas actual Auto planning records a resolved drawing-style/tool/brush context. Reset could erase a different record and retain both the learned current model and its displayed estimate. | Prefer the current plan's effective context only for the same active profile, invalidate its estimate after successful reset, preserve the plan on a failed reset, and prevent reset during an active worker or shutdown. Tests record two real calibration contexts and verify that exactly the effective context is removed. |
| AX06 | Image import copied an embedded non-sRGB ICC profile onto unchanged RGB numbers, but planners treated those numbers as sRGB. A generated valid RGB profile with exchanged red/blue primaries imported `(220,40,10)` instead of the independently expected `(10,40,220)`. | Convert tagged file and bitmap-clipboard input to sRGB with Pillow's CMS and relative colorimetric intent. Preserve alpha/indexed transparency and the borrowed clipboard image; retag converted output with sRGB so exported/reimported images do not convert twice. Bound profile bytes, explain invalid profiles, retain exact untagged pixels and close cancelled outputs. The source label identifies successful conversion. Tests use a generated ICC fixture and its independent channel mapping; no external binary fixture is downloaded. |
| AX07 | Verification flattened clipped paths, copied every adjacent pair and could search the same longest segment three times. When clipping left two isolated dots, its fallback sampled across the undrawn gap. | Select the first longest delivered segment once with constant scratch space; fall back to the first delivered dot. Reuse it for delivery, color and exact-color sampling. Preserve path order and native actions, poll cancellation during long paths and many dots, and use pairwise iteration without path slices. A real CanvasGuard/execute_plan regression reproduces two clipped dots and proves that the gap is no longer sampled; an independent brute-force oracle covers ordinary geometry and tie ordering. |

## Existing contracts completed, no additional count

- **SR06/SS19:** `execute_plan` now distinguishes processed, sent and
  guard-skipped paths. Progress still finishes for a clipped plan; sent-path
  reports and every learning/analysis caller receive only completed input
  paths. Entirely skipped sequence items do not create stroke timing. Adaptive
  probes and correction paths remain separate from completed original paths.
  Correction metadata also counts only delivered paths and colors. Fresh
  runtime counters replace prior-attempt values.
- **IW08/UI23:** release owned viewport images after PhotoImage conversion;
  clear stale navigation geometry on an empty/failed view; recheck source/view,
  activity and shutdown after export dialogs. No duplicate improvement IDs.
- Preview navigation and the full-canvas preview guard are cross-area
  integrations counted in the UI and rendering ledgers, respectively.

## Review and focused validation

The independent runtime/learning review covered the sent-path producer,
pause lifecycle, both learning writers, completed-drawing analysis and the
effective-context reset. **59 relevant tests passed** in that review; no
blocking finding remained. A second independent review covered ICC/export/Stop
and found transparent output from valid opaque GRAY input. Explicit alpha
restoration fixed that issue; the independent real-PNG reproduction and all
19 ICC/export/event tests now pass. LA/color-key transparency and opaque LAB
are also covered. The separate AX07 geometry review passed 56 relevant tests
with no blocker. One remaining native-loop tuple slice was replaced by
`islice` under the same AX07 contract.

The current six application regression modules contain **36 tests** and pass.
These are fake-device, file, model and UI-callback tests. They do not establish
real drawing speed, actual target-app color accuracy, or a new antivirus verdict.

The ICC API and conversion intent are documented by
[Pillow ImageCms](https://pillow.readthedocs.io/en/stable/reference/ImageCms.html).
This change concerns source-color interpretation; it does not claim that a
limited target palette can reproduce every out-of-gamut source color.

## Probe allocation measurements

`benchmark_v148_probe_geometry.py` compares the original geometry extraction
with the new selector, and separately runs the baseline/current actual
`execute_plan` bodies with the same no-wait fake device. The final paired
run reduced peak traced Python allocation for a 10,000-point compound stroke
from **750,808 to 592 bytes** in the selector. The whole fake-device execution
retained identical mouse actions and ink probes; its final medians were **148.040 and
145.780 ms**. An earlier pair was **156.161 and 156.262 ms**; this small, variable
whole-execution difference is not presented as a dependable drawing speedup. Full samples, baseline identity, source hashes and scope are in
`docs/v148-batch06-probe-benchmarks.json`. The final run uses the frozen source hashes.
