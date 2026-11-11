# PR #46 — history through batch 34

This is the PR description captured on 11 November 2026 before the next
synchronous-recovery continuation. Its verified draft head was
`66948b321a3d7a17d984c0db2304e59205ea6cc0`.
Historical wording such as "current head" refers to the checkpoint described
in that section. The live PR and the improvement registry report current status.
The captured description below is preserved verbatim.

---

## Recovery continuation — preserve the primary PNG failure (zero new IDs)

Current head: [`66948b321a3d7a17d984c0db2304e59205ea6cc0`](https://github.com/Vxiey/Image-Draw-Bot/commit/66948b321a3d7a17d984c0db2304e59205ea6cc0), continuing from verified parent `b41af0d5e947f451232ec46ee5189dd8f7da0679`.

A secondary error while closing an owned RGBA conversion could replace an encoding error or cooperative Stop. The asynchronous preparer now preserves the primary exception object/traceback and records secondary cleanup as a note. A standalone close error still fails preparation. Encoding, cancellation checks, digest, publication and source ownership remain unchanged. The synchronous compatibility encoder is outside this patch.

**Actual local verification:** the same seven focused methods reproduced **four assertion failures and three passes before**, then **7/7 pass after**, with zero errors/skips. **21 existing adjacent methods pass**, including all 12 profile-export lifecycle methods. Tests use the existing `assets/paint-tools-reference.png`, actual PNG writes, disk files and a real encoder thread; only write/close fault boundaries are injected. They cover Stop, write error, byte limit, standalone cleanup error, successful retry, exact decoded pixels/digest and resource ownership. No synthetic image fixture was introduced. Source-package hygiene passes for **1,381 files**, with no warnings.

**Count remains 843/1,000; 157 remain.** This completes **IW08/global582** within **A1001/global766**, adding zero IDs. The machine registry is byte-for-byte unchanged.

- [Review the full continuation](https://github.com/Vxiey/Image-Draw-Bot/compare/b41af0d5e947f451232ec46ee5189dd8f7da0679...66948b321a3d7a17d984c0db2304e59205ea6cc0)
- [Change, executed tests and limits](https://github.com/Vxiey/Image-Draw-Bot/blob/66948b321a3d7a17d984c0db2304e59205ea6cc0/docs/v148-batch34-recovery-cleanup.md)
- [Recorded execution evidence and source hashes](https://github.com/Vxiey/Image-Draw-Bot/blob/66948b321a3d7a17d984c0db2304e59205ea6cc0/docs/v148-batch34-recovery-validation.json)

<!-- recovery34-ci-status -->
**All seven GitHub checks succeeded for current head `66948b321a3d7a17d984c0db2304e59205ea6cc0`.** [CI run 43021957536](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43021957536) and [CodeQL run 43021949674](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43021949674) completed successfully.

[Windows job 130527068964](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43021957536/job/130527068964): **4,593 tests, 4,590 passed, three GPU skips** (473.131s). All seven new recovery methods, the corrected real-process scheduler case and all five existing native UI methods ran and passed. Windows self-test, bundle build/validation and packaged GUI/native drag-and-drop also passed.

[Linux job 130527068535](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43021957536/job/130527068535): **4,593 tests, 4,515 passed, 78 skipped** (235.656s). All seven recovery methods and the corrected scheduler case passed. The five native UI methods were skipped without a display; their current Windows execution passed.

The first recovery commit `892ba62` passed all seven new methods on both platforms but [Windows CI 43019822262](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43019822262/job/130519925718) reported one older scheduler-fixture error: an empty record in a shared PID file (4,589 passed, one error, three skips). Each process now owns its observation file; strict PID validation and every original process/engine/shutdown assertion remain. Seven scheduler methods also passed locally. The initial failure and skipped Windows package steps remain documented in the linked validation record; the successful current run verifies the correction.

No physical target-app drawing or manual Windows visual/DPI review is claimed. This draft continuation adds zero improvement IDs.
<!-- /recovery34-ci-status -->

**This PR remains draft. No merge, tag or release was performed. Merge/release requires the user's explicit approval.**

---

## Previous verified continuations (zero new IDs)

- **UI, `b41af0d5e947f451232ec46ee5189dd8f7da0679`:** full-width settings, dark CTk surfaces, disclosure readability, contrasting primary focus and wrapped error actions. Five native Linux methods reproduced three failures on the baseline and all five passed after the patch; 35 adjacent methods passed. All seven exact-head checks succeeded. [CI 42935172530](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42935172530): Windows 4,586 tests (4,583 passed, three GPU skips), Linux 4,586 (4,508 passed, 78 skips); Windows self-test, bundle and packaged GUI/native drag-and-drop passed. The first UI Windows run had three fixture cleanup failures; parent-owned temporary data fixed them without weakened assertions. [Change and limits](https://github.com/Vxiey/Image-Draw-Bot/blob/b41af0d5e947f451232ec46ee5189dd8f7da0679/docs/v148-batch33-ui-readability.md); [recorded validation](https://github.com/Vxiey/Image-Draw-Bot/blob/b41af0d5e947f451232ec46ee5189dd8f7da0679/docs/v148-batch33-ui-validation.json).
- **Profile export, `61f8d5812cfeb85df7ae432e3b5d704028e37aa6`:** the save chooser rechecks idle state and the exact captured profile identity before atomic export, and suppresses shutdown dialogs. The 12 new methods reproduced 22 failing subcases across eight methods before the fix, then all 12 passed; 64 adjacent methods passed. All seven exact-head checks succeeded in [CI 42927504392](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42927504392). Completes AW15/global629. [Change and limits](https://github.com/Vxiey/Image-Draw-Bot/blob/61f8d5812cfeb85df7ae432e3b5d704028e37aa6/docs/v148-batch32-profile-export.md); [recorded validation](https://github.com/Vxiey/Image-Draw-Bot/blob/61f8d5812cfeb85df7ae432e3b5d704028e37aa6/docs/v148-batch32-profile-export-validation.json).

These are historical parent results, not evidence for an unverified newer head. Both continuations retain **843/1,000; 157 remaining**. No merge, tag or release was performed.

---

## Batch 31 checkpoint — 843 / 1,000 verified improvements

Saved commit: [`71a87ed659676ea5c4e72e40fbae5f72b7f354b3`](https://github.com/Vxiey/Image-Draw-Bot/commit/71a87ed659676ea5c4e72e40fbae5f72b7f354b3) on `improve/v1.0.148`. This batch adds exactly **one** group, **R3101/global843**. All 842 earlier registry entries and 80 earlier benchmark JSON reports remain unchanged. **157 improvements remain; version 1.0.148 is not released and this PR remains a draft.**

<!-- batch31-ci-status -->
**GitHub validation for exact commit `71a87ed659676ea5c4e72e40fbae5f72b7f354b3` passed on the first attempt.** All seven checks succeeded: Windows and Linux core regressions, both dependency audits, both CodeQL analyses and the CodeQL aggregate. [CI run 42439070761](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42439070761) and [CodeQL run 42439067328](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42439067328) are both completed/success with `run_attempt=1`.

[Windows job 128604188836](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42439070761/job/128604188836) passed all 14 steps, including the source gate, exact raster regressions, complete regressions, self-test, Windows bundle validation and packaged GUI/native drag-and-drop. The full suite ran **4,569 tests: 4,566 passed and three GPU tests skipped, zero failures/errors, in 527.471 seconds**. All 18 new batch31 regression methods passed. The separate portable/raster gate passed 56 tests in 10.861 seconds; the source gate completed 5,000 cycles.

The runner checked out PR merge commit `d024e269a9296dce264f2cf3cafc1347c597846a`. Its tree is exactly `3cb6cccd83e30757a05c57178fe46fc9ea071295`, identical to the published head above, independently verified from both Git commit objects. The successful artifact gate logged ZIP SHA256 `e24ec36b2d026ad4a5705e68e1477cdb3c1593dce2a030c791430ecf6270c5d3`; this is build-log evidence, not a separately downloaded artifact or a published release. Independently fetched complete Windows log: 1,069,026 UTF-8 bytes, SHA256 `9cf77469fd7689861fe2af495bef8bb56f98d51e8ac68932c7a920902c58814f`, with no observed test-error, Actions-error, `invalid command name` or `Tcl_AsyncDelete` lines.

**Progress remains 843/1,000; 157 remain.** The next recovery PNG-storage and profile-export lifecycle completions have before-probe evidence but no batch32 product or regression edits. Their implementation/testing is paused because the development environment disconnected. This PR remains draft; no merge, tag or release has been performed.
<!-- /batch31-ci-status -->

### Changes and measured scope

- **R3101:** pass the existing Portrait contour budget into selection. For the actual small-budget fixture, 19,107 unchanged cell winners feed a stable bounded selection that returns 6 or 65 contours, without first sorting and returning the whole pool. Larger budgets retain the full stable sort and omit the unused returned suffix. Sobel processing, scanning, strongest-per-cell selection, ties, geometry and metadata remain exact.
- **Existing contracts, zero extra IDs:** close the importer-owned local file generator when its snapshot consumer stops or fails; preserve the original exception and borrowed iterators/readers. Complete outer Portrait image ownership across first/second finish, real time fitting and quality rescue/fallback; keep borrowed inputs and returned results alive while retiring unpublished private images.
- The two ownership changes are existing-contract completions. Tests, diagnostics, evidence packing and metadata add no improvement IDs.

### Completed local validation

- **4,569 tests in 244.002 s:** 4,496 passed and 73 platform/hardware cases skipped, on the first full attempt. All **947 source/configuration hashes** remain unchanged.
- **14/14 real Linux/Xorg native UI cases**, zero skips and zero lifetime/invalid-command diagnostics; these retain their separate platform scope.
- **5,000 lifecycle/profile-isolation cycles**, **eight exact existing-raster fixtures**, and source-package hygiene passed. Package inventory is **1,370 initially and 1,372 after final metadata**, with no warnings, forbidden paths or missing requirements.
- Seven complete public-plan pairs compare the full published e49 `DrawBot` and `PortraitPlanner` together with the current pair, sharing the other recorded dependencies. Actual two-pass time fitting and quality rescue retain complete results and borrowed inputs.
- The contour experiment separately compares the full historical Portrait module with current shared DrawBot/dependencies: **three complete preparations, 39 exact helper/public comparisons, nine workloads, 54 balanced AB/BA timing pairs and 18 separate allocation observations**.
- Final history, benchmarks and integrated gates bind **897 root Python files**. The earlier 893/895-file before/focused checkpoints retain their original maps; the real intervening Portrait product change is explicitly recorded.
- Independent source, counting, raw provenance and final metadata reviews are closed. All initial probe/fixture diagnostics and complete successful results are preserved.

### Performance evidence and limits

The two small-prefix helper medians change **191.684 → 186.523 ms (−2.693%)** and **187.247 → 184.347 ms (−1.549%)**, each faster in five of six pairs. Their traced Python peaks decrease by **457,292 and 450,540 bytes**, while retained-with-result allocations increase by **400 and 4,248 bytes**. The full scan and occupied-cell dictionary remain.

Whole public planning has a different scope: the 3 s setting is effectively unchanged (**1205.756 → 1205.331 ms**, only two of six faster pairs), with **6,471 more peak bytes and 6,523 more retained bytes**. The 30 s fixture changes **983.612 → 958.481 ms (−2.555%, six of six pairs)**. The unbounded-helper and flat controls are slower by **0.743% and 1.155%**; all nine workloads, individual samples, slower controls and allocation costs remain in the raw report.

These CPU fixture observations establish a bounded contour-work/temporary-allocation reduction. They do not establish a general application-speed, whole-public-call peak-memory, process-RSS, physical GPU, Windows-performance or physical drawing improvement. Configured 3 s/30 s drawing budgets are separate from measured software runtime and final execution counts.

### Evidence

- [Registry and progress](https://github.com/Vxiey/Image-Draw-Bot/blob/71a87ed659676ea5c4e72e40fbae5f72b7f354b3/docs/IMPROVEMENTS-v1.0.148.md)
- [Final validation and exact source bindings](https://github.com/Vxiey/Image-Draw-Bot/blob/71a87ed659676ea5c4e72e40fbae5f72b7f354b3/docs/v148-batch31-validation.json)
- [Contour selection, every timing/allocation result and limits](https://github.com/Vxiey/Image-Draw-Bot/blob/71a87ed659676ea5c4e72e40fbae5f72b7f354b3/docs/v148-batch31-portrait-edge-budget.md)
- [All raw paired contour observations](https://github.com/Vxiey/Image-Draw-Bot/blob/71a87ed659676ea5c4e72e40fbae5f72b7f354b3/docs/v148-batch31-portrait-edge-benchmarks.json)
- [Portrait plan ownership and historical comparison](https://github.com/Vxiey/Image-Draw-Bot/blob/71a87ed659676ea5c4e72e40fbae5f72b7f354b3/docs/v148-batch31-portrait-plan-ownership.md)
- [Local import-stream ownership](https://github.com/Vxiey/Image-Draw-Bot/blob/71a87ed659676ea5c4e72e40fbae5f72b7f354b3/docs/v148-batch31-import-stream-ownership.md)
- [Lossless complete diagnostic evidence](https://github.com/Vxiey/Image-Draw-Bot/blob/71a87ed659676ea5c4e72e40fbae5f72b7f354b3/docs/v148-batch31-completion-evidence.json)

<details>
<summary>Preserved preceding checkpoint: 842 improvements</summary>

## Batch 30 checkpoint — 842 / 1,000 verified improvements

Saved commit: [`e49e2535c5f8edea80e47824fe56cae58781b971`](https://github.com/Vxiey/Image-Draw-Bot/commit/e49e2535c5f8edea80e47824fe56cae58781b971) on `improve/v1.0.148`. This batch adds exactly **two** groups: **R3001/global841** and **R3002/global842**. All 840 prior registry entries and 78 prior benchmark reports remain unchanged. **158 improvements remain; version 1.0.148 is not released and this PR remains a draft.**

**Exact-commit GitHub validation is green: all seven checks passed on `e49e2535c5f8edea80e47824fe56cae58781b971`, on the first attempt.** [Windows job 128590299263](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42434481898/job/128590299263) completed all 14 steps successfully: 4,551 tests in 404.561 s (4,548 passed, three skipped), Windows self-test, bundle/artifact validation, and packaged GUI/native drag-and-drop. Linux, both dependency audits and CodeQL also passed. The Windows ZIP SHA256 is `fabdf821929f671888c2cfa3dc643d46fa15ee539f80ad6fe060663d85aa305f`; this is CI validation, and version 1.0.148 remains unreleased. The complete Windows log has no Actions-error, invalid-command or Tcl_AsyncDelete diagnostics.

### Changes and measured scope

- **R3001:** background cleanup can retract the original border-flood mask but cannot promote protected foreground into background. Actual Remove BG, worker delivery, UI adoption, PNG export and Undo preserve the reproduced thin features. Twenty historical controls remain exact; 24 intended corrections are recorded. Proxy sampling and feather behavior remain unchanged.
- **R3002:** growing picture palettes compare only the appended center while transformed previous centers remain identical. Strict first-center ties, full fallback, cancellation and the full medoid reassignment loop are preserved. All 32 complete historical comparisons match, including four public plans. Six balanced pairs per workload retain every sample: the cold red 24-color builder median changes from 246.641 to 178.919 ms (27.46% faster, 6/6 pairs), and direct refinement from 154.559 to 68.455 ms (55.71%, 6/6). Unchanged-work controls and small traced-allocation increases remain visible; these are not whole-app, peak-memory, RSS, physical GPU or Windows performance claims.
- **Existing contracts, zero extra IDs:** preserve Stop through background/PNG source-copy handoff and its refused-worker status; close private Portrait stroke image views/blur and score closure owners while preserving borrowed images, original native diagnostics and all numerical results.
- **Test infrastructure, zero IDs:** reproduce and correct an older calibration fixture retaining Tcl references until a later worker collected them. Real native cleanup happens before fixture aliases are retired. Two child-process regressions retain real callbacks and exception frames while requiring all six Tcl owners and 134 original Variable finalizers to finish on the creator thread.

### Completed local validation

- **4,551 tests in 231.751 s: 4,478 passed, 73 existing platform/hardware skips; zero failures or Tcl diagnostics.**
- **14 actual Linux/Xorg/Tk GUI cases**, no skips or diagnostic errors.
- **5,000 source cycles**, **eight exact raster fixtures**, and final package hygiene across **1,361 files** with no warnings.
- The final **893 root Python / 943 source/configuration** hashes are unchanged across all gates. The earlier **892-file** background/Portrait historical comparisons and palette experiment retain their original map; only two explicitly recorded fixture files differ afterward.
- All interrupted/failed attempts remain visible: incomplete attempts 1 and 3, the actual Tcl abort in attempt 2, isolated before/after ownership proofs and the unchanged final test command. No test assertion, skip or timeout was weakened.
- Independent source, counting, raw-data and metadata reviews are closed. The lossless completion artifact retains **389 original artifacts and 11 source maps**.

Evidence: [final validation](https://github.com/Vxiey/Image-Draw-Bot/blob/e49e2535c5f8edea80e47824fe56cae58781b971/docs/v148-batch30-validation.json), [background detail](https://github.com/Vxiey/Image-Draw-Bot/blob/e49e2535c5f8edea80e47824fe56cae58781b971/docs/v148-batch30-background-details.md), [palette growth and limits](https://github.com/Vxiey/Image-Draw-Bot/blob/e49e2535c5f8edea80e47824fe56cae58781b971/docs/v148-batch30-palette-growth.md), [paired raw measurements](https://github.com/Vxiey/Image-Draw-Bot/blob/e49e2535c5f8edea80e47824fe56cae58781b971/docs/v148-batch30-palette-benchmarks.json), [Portrait ownership](https://github.com/Vxiey/Image-Draw-Bot/blob/e49e2535c5f8edea80e47824fe56cae58781b971/docs/v148-batch30-portrait-stroke-ownership.md), [Stop handoff](https://github.com/Vxiey/Image-Draw-Bot/blob/e49e2535c5f8edea80e47824fe56cae58781b971/docs/v148-batch30-stop-copy-completion.md), [fixture correction](https://github.com/Vxiey/Image-Draw-Bot/blob/e49e2535c5f8edea80e47824fe56cae58781b971/docs/v148-batch30-fixture-ownership.md), and [complete lossless evidence](https://github.com/Vxiey/Image-Draw-Bot/blob/e49e2535c5f8edea80e47824fe56cae58781b971/docs/v148-batch30-completion-evidence.json).

---

## Current checkpoint — batch 29

**840 of 1,000 distinct improvements are registered; 160 remain. Version 1.0.148 is not released, and this PR stays draft.**

Saved commit: [`4b90b715a9128a022774f411e14e8a1b45676339`](https://github.com/Vxiey/Image-Draw-Bot/commit/4b90b715a9128a022774f411e14e8a1b45676339) on `improve/v1.0.148`. This batch adds exactly **one** group, **R2901/global840**. All 839 preceding entries and 76 preceding benchmark reports are preserved.

### What changed

The actual preview worker reuses the main sequence's immutable full-precision cost for its second ETA pass only when the same plan and typed cost inputs still match. Late calibration, throughput, Fill, fixed overhead and projection remain fresh. Changed, unsupported or foreign inputs still calculate fresh costs. The observation is local to its owning worker and is released through consumption, Stop and errors.

The two image changes complete existing contracts with **zero additional IDs**:

- Accuracy borrows matching, already normalized opaque RGB inputs in its private numeric consumer, avoiding two identity copies while preserving every metric and heatmap. Public normalization still returns an independently owned image.
- Portrait borrows already oriented RGBA, preserves white-composite → grayscale → resize order and closes private gray/PixelAccess owners through Stop and errors. The actual imported 1024×768 cases avoid two redundant copies, or 6,291,456 nominal copied pixel bytes; this is not a peak-memory claim.

### Measured scope and controls

Six balanced pairs per workload retain exact complete output and full-precision cost parity. The following measures **both actual ETA calls together, including construction of the first snapshot**:

| Actual worker case | Before → after | Median change | Faster pairs |
| --- | ---: | ---: | ---: |
| Native | 4.705 → 3.609 ms | −23.30% | 5/6 |
| Projected | 47.668 → 36.835 ms | −22.73% | 6/6 |
| Full detail | 4.611 → 3.699 ms | −19.78% | 6/6 |
| Dense | 30.020 → 23.824 ms | −20.64% | 6/6 |

**Whole-pipeline times remain mixed.** Dense has a −1.13% median but only two faster pairs; full detail is +0.54%. The standalone control is +4.05% with three faster pairs. Changed-delay fallback correctly recalculates and costs about 1.060 ms more in total ETA (+22.24%, all six pairs slower). The separate late helper improves its elapsed median but increases traced Python peak from 120,376 to 243,119 bytes; that helper excludes initial observation construction. No general app, pipeline, Windows, GPU or RSS improvement is claimed. The rejected slower tuple experiment and the intermediate byte experiment remain preserved separately.

### Verification on this frozen source

| Gate | Result |
| --- | --- |
| Full local discovery | **4,522 tests: 4,449 pass, 73 platform/hardware skips**, 240.202 s |
| Native Linux/Xorg UI | **14/14**, no skips or Tcl diagnostics |
| Source stability gate | **5,000 cycles**, passed |
| Existing-raster fixtures | **8/8 exact**, zero differing plan pixels |
| Final package hygiene | **1,346 files**, no warnings, missing or forbidden files |
| Complete image history | Accuracy **4/4** full plans/metrics/heatmaps; Portrait **47 helper + 5 public** exact pairs, including two actual time-fitting finalizations |
| Shared source binding | **887 Python / 937 source-and-configuration files**, unchanged throughout final gates |
| Independent reviews | Product, tests, method, all raw arithmetic/expansion, count and final metadata closed |

**Exact-head GitHub validation is now green: all seven checks passed on `4b90b715a9128a022774f411e14e8a1b45676339`.** The single unchanged-source Windows rerun, [attempt 2 / job 128576201162](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42429074401/job/128576201162), completed all 14 steps successfully: 4,522 tests in 522.663 s (4,519 passed, three skipped), source self-test, bundle validation and packaged GUI/native drag-and-drop. Linux, both dependency audits and CodeQL are also green. The generated Windows ZIP SHA256 is `e7e76ed68495bdd4d88d3ebd8525fe11eb85057b2cfd6f4b8758ae606d0eed99`; this is CI validation, not a published release. The complete successful Windows log has no Actions errors, invalid-command or Tcl_AsyncDelete diagnostics.

The first Windows attempt remains part of the record: [job 128573693324](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42429074401/job/128573693324) ran 4,522 tests in 525.375 s with 4,518 passed, three skipped and one older MobileBrowser Node subprocess timeout at its existing five-second limit; subsequent package steps were skipped. The one rerun passed without modifying product code, tests, timeouts or skips. The exact startup/execution phase of the original timeout is not established; the failed attempt is not omitted.

Evidence: [final validation](https://github.com/Vxiey/Image-Draw-Bot/blob/4b90b715a9128a022774f411e14e8a1b45676339/docs/v148-batch29-validation.json), [ETA ledger](https://github.com/Vxiey/Image-Draw-Bot/blob/4b90b715a9128a022774f411e14e8a1b45676339/docs/v148-batch29-estimate.md), [final paired raw data](https://github.com/Vxiey/Image-Draw-Bot/blob/4b90b715a9128a022774f411e14e8a1b45676339/docs/v148-batch29-estimate-benchmarks.json), [Accuracy](https://github.com/Vxiey/Image-Draw-Bot/blob/4b90b715a9128a022774f411e14e8a1b45676339/docs/v148-batch29-accuracy-inputs.md), [Portrait](https://github.com/Vxiey/Image-Draw-Bot/blob/4b90b715a9128a022774f411e14e8a1b45676339/docs/v148-batch29-portrait-preparation.md), and [complete image evidence](https://github.com/Vxiey/Image-Draw-Bot/blob/4b90b715a9128a022774f411e14e8a1b45676339/docs/v148-batch29-completion-evidence.json). The latter preserves 244 original artifacts, five exact source maps and all initial diagnostic checkpoints, with documented lossless JSON compression.

No merge, tag, release or public installer has been created for 1.0.148.

<details>
<summary>Previous batch28 checkpoint</summary>

## Status

**839 / 1,000 distinct behavior improvements are implemented; 161 remain. Version 1.0.148 is not released.**

Current checkpoint: `bfa43deb090c9ef858b04313fad9559ec4acfab1`, based on published `f800da5785731bbe0b0f8e3908bc330a65ac79c6`. Batch 28 completes existing contracts with **zero new IDs**. All 839 registry entries and all 75 preceding raw benchmark reports are preserved. This pull request remains a draft.

## Problem and resulting behavior

Scaled Sketch + Auto Fill previews enlarged source-grid brush coverage even though drawing keeps the brush width fixed in physical pixels. A real 67×50 → 96×72 horizontal-stroke control displayed **32 pixels** for **15 delivered pixels**. The final preview and all three phase views now follow the already accepted execution sequence, effective physical brush width, protected fragments and precision moves, including signed origins and fractional letterboxes. The five fixed public/controller-to-executor controls now match their independent/native delivery model exactly; their original native actions, path counts and delivered pixels remain unchanged.

Source-relative Accuracy and delta-E now describe the corrected image. An active tuner can legitimately make a different rescue choice from that corrected quality; this is not a universal tuner-plan parity claim.

Safe axis segments avoid unnecessary interpolated point lists and repeated rectangle stamps, with unchanged endpoint/convex-inset checks and precision validation, including the 100,000-step limit. Compared with the first corrected physical renderer, two actual public work controls reduce protect/stamp calls from **15,476 to 1,252** and **25,405 to 5,278** across the four views. These are bounded work counts, not general speed, memory or physical-paint measurements.

The PNG worker also copied its already isolated snapshot a second time during identity orientation. Only that owned worker path now reuses its snapshot; the GUI's required first copy and the public helper's independent borrowed-input behavior remain. Actual RGBA/RGB/L/P exports use **one identity copy instead of two**, with identical reopened pixels/alpha and ICC. Stop, retained errors and atomic publication preserve the prior destination and close private buffers.

These complete RP38/global552, R1004/global770, S1101/global777, IW08/global582 and AZ01/global746. Tests, evidence, work observations and historical replay maintenance add no IDs.

## Final local validation

- **4,498 tests in 224.479 s:** 4,425 passed and 73 platform/hardware cases skipped.
- All **933 source/configuration hashes remained unchanged**.
- **14/14 actual Linux/Xorg native UI cases**, no skips or Tcl-lifetime diagnostics.
- **5,000 lifecycle/profile-isolation cycles**, **1,333-file final package hygiene**, and **eight exact existing-raster fixtures** passed. The initial 1,330-file package result is preserved separately from the final report inventory.
- **13 Sketch regressions** cover the independent physical footprint, phases, signed coordinates, clipping/split paths, reduced preview, diagonal precision, Stop/native Pillow failure and the exact precision-length boundary.
- **Four actual PNG worker regressions** cover private snapshot reuse, mode/alpha/EXIF/ICC behavior, source mutation after enqueue, retained failures, cancellation and default borrowed-input ownership.
- Final five-case Sketch replay, PNG observer, native/raster gates and historical replay share **883 root Python sources**, canonical SHA `74a659994b8f25037a6b233eb05efcafd2f60bffd3fa0de073d3623355c7929c`.
- Complete raw evidence retains **84 artifacts**, six distinct full source manifests, actual before/after plan/action records, exact PNGs, original fixture-error diagnostics and focused logs. Manifest references and whitespace compaction are lossless and independently reviewed.

The batch27 experiment is now replayed against its published `8e0` / `f800` caller graphs, with shared dependencies explicitly declared. The new verify-only report preserves **22 public cases over three graphs and eight native-raster cases**, without new timing samples. It does not compare the corrected batch28 preview against the old presentation experiment.

## Evidence

- [Final validation](https://github.com/Vxiey/Image-Draw-Bot/blob/bfa43deb090c9ef858b04313fad9559ec4acfab1/docs/v148-batch28-validation.json)
- [Sketch physical-preview completion](https://github.com/Vxiey/Image-Draw-Bot/blob/bfa43deb090c9ef858b04313fad9559ec4acfab1/docs/v148-batch28-sketch-preview.md)
- [PNG snapshot completion](https://github.com/Vxiey/Image-Draw-Bot/blob/bfa43deb090c9ef858b04313fad9559ec4acfab1/docs/v148-batch28-png-snapshot.md)
- [Complete before/after evidence](https://github.com/Vxiey/Image-Draw-Bot/blob/bfa43deb090c9ef858b04313fad9559ec4acfab1/docs/v148-batch28-completion-evidence.json)
- [Pinned historical replay](https://github.com/Vxiey/Image-Draw-Bot/blob/bfa43deb090c9ef858b04313fad9559ec4acfab1/docs/v148-batch28-historical-replay.json)

This establishes the application's fixed square-brush model and actual issued native coordinates, not a physical Microsoft Paint capture or a general performance/RSS/GPU result.

## Exact-commit GitHub checks

**All seven exact-head checks are green for `bfa43deb090c9ef858b04313fad9559ec4acfab1`.** [CI run 42424661319](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42424661319) and [CodeQL run 42424655766](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42424655766) completed successfully. Windows passed all 14 job steps, including **4,498 regressions in 388.558 s with 3 skips**, 56 raster tests, self-test, bundle construction/validation, and the packaged GUI/native drag-and-drop gate. The complete Windows log has no invalid-command, Tcl_AsyncDelete or Actions-error lines; nonfatal dependency/CTk/PyInstaller warnings remain visible. The Windows ZIP SHA-256 is `2d468135dd897ff987a54580738120722a0a1ffa11ebfb29bf2c22abdc8e9eab`. Linux core, both dependency jobs and the two CodeQL analyses/aggregate check are also successful. This pull request remains a draft; version 1.0.148 has not been released.

<details>
<summary>Previous batch27 checkpoint and earlier review history</summary>

## Status

**839 / 1,000 distinct behavior improvements are implemented; 161 remain. Version 1.0.148 is not released.**

Current checkpoint: `f800da5785731bbe0b0f8e3908bc330a65ac79c6`, based on published `8e0a0e4c61ca0742dfb7857649103477cd307516`. All 838 preceding registry entries and all 73 earlier benchmark reports are preserved. Only **R2701 / global 839** is new. This pull request remains a draft.

## Problem and resulting behavior

Ordinary Sketch + Auto Fill built the private color sub-plan's complete target, auxiliary layers, source-accuracy evaluation, ETA and diagnostics, then discarded those presentations before building the composed sketch → color fill → re-outline result.

The private handoff now omits that unused late presentation. Original color geometry, Pixel correction decisions, path caps, deadline admission, optimizer, physical base simulation and PreviewSafety still run. The final composite retains its complete presentation. Active auto-tuner/rescue, nested Adaptive Hybrid and standalone consumers keep their full inner presentation. This does not reduce all of `finish_plan` or physical simulation to one pass.

Existing-contract completions add **zero IDs**:

- Validate a saved scheduler recommendation against the current already-resolved CPU/RAM allocation in the actual GUI-to-planner path.
- Decide legacy CPU Skip white from composited source RGB before nearest-palette mapping, preserving transparency, run order, worker/fallback and Stop behavior.
- Make both shipped direct GPU installers participate in the existing private source-environment lock and preserve helper flags and failure exit codes.
- Keep Mobile Preview address discovery off Tk with one live resolver and one replaceable pending intent; prevent late adoption after Stop/Close/reopen and remove reverse DNS from the locked TCP bind.
- Close owned monochrome, Sketch and presentation images/native drawing cores on return, Stop, failure and real outer tuner rescue, preserving borrowed inputs and returned plans.

## Final local validation

- **4,481 tests in 218.814 s:** 4,408 passed and 73 platform/hardware cases skipped.
- All **931 source/configuration hashes remained unchanged**.
- **14/14 actual Linux/Xorg native UI cases**, no skips or Tcl-lifetime diagnostics.
- **5,000 lifecycle/profile-isolation cycles**, **1,325-file package hygiene**, and **eight exact existing-raster fixtures** passed.
- **22 complete public-plan cases over three complete caller graphs**, including real active cap/timer, tuner/rescue, nested Hybrid and standalone controls.
- **Eight actual-executor raster cases** preserve delivered pixels, sent/skipped path counts and ordered native-color actions across those three graphs.
- **Eight separate complete historical current-ink/outline pairs** cover RGB, RGBA, L and P with explicit Balanced sketch detail.
- Every final source-bound report shares the same **881 root Python hashes**. Independent source, actual-flow, ownership, deduplication, raw-evidence and metadata reviews are closed.

## Measurement evidence and limits

Eight workloads have six balanced AB/BA pairs, with separate peak and retained-allocation observations. Timings compare complete old DrawBot/SketchFillRenderer callers against current callers while holding current PixelData constant on both sides. DrawBot/Sketch image-ownership completions remain part of the measured difference; the whole delta is not attributed solely to R2701.

| Public workload | Before → after median (ms) | Change | Faster pairs |
| --- | ---: | ---: | ---: |
| Balanced RGB 320×256 | 117.676 → 93.980 | −20.136% | 6/6 |
| Balanced RGBA 384×288 | 146.757 → 121.255 | −17.377% | 6/6 |
| Pixel RGB 192×160 | 273.921 → 245.939 | −10.215% | 5/6 |
| Pixel RGBA 192×144 | 257.710 → 253.419 | −1.665% | 5/6 |
| Balanced full preview 256×192 | 104.880 → 88.036 | −16.060% | 6/6 |
| Actual active target cap 96×72 | 144.727 → 135.581 | −6.320% | 5/6 |
| Active tuner/rescue control 40×32 | 150.510 → 132.780 | −11.780% | 4/6 |
| Standalone control 192×144 | 42.070 → 40.753 | −3.129% | 4/6 |

The six eligible callers remove one unused inner target/auxiliary/source-accuracy/diagnostic pass while preserving both geometry/safety passes. The two controls remove no presentation passes. All seven slower individual pairs are retained. The active tuner has **+5,765 bytes traced peak and +8,193 bytes retained**; standalone peak increases **1,338 bytes**. These single allocation probes are not RSS measurements. No universal planner, drawing or GPU speed claim is made.

## Known follow-up

The expanded comparison exposes an existing scaled Sketch-preview discrepancy: a 67×50 planning grid fitted to 96×72 scales source-grid brush coverage, while the executor retains physical brush width. The same delivered rasters and preview differences exist in all three graphs; this checkpoint does not claim that issue fixed. A separate axis-path probe confirms 32 preview pixels versus 15 correctly modeled delivered pixels. Continue that correction as an existing-contract completion, with zero new IDs.

## Exact-commit CI

All **seven checks passed for exact commit `f800da5785731bbe0b0f8e3908bc330a65ac79c6`**. [CI run](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42421246829) and [CodeQL](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42421243688) are successful. The [Windows job](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42421246829/job/128549929938) passed all 14 steps: **4,481 tests in 502.507 s, 4,478 passed and three hardware skips**, plus 56 exact-raster/portable cases in 11.479 s, source and packaged self-tests, bundle validation, and packaged GUI/native drag and drop. Both new Mobile Preview native cases and the actual batch-entrypoint regression passed. The log contains zero `invalid command name`, zero `Tcl_AsyncDelete` and zero Actions-error lines; other nonfatal library/build warnings remain. Windows ZIP SHA-256: `b822a711364a39d5fd63f8e8d143a5b3bc84b213f91cd122a246d130234b4ec4`. No 1.0.148 release was published.

## Evidence

- [Integrated validation](https://github.com/Vxiey/Image-Draw-Bot/blob/f800da5785731bbe0b0f8e3908bc330a65ac79c6/docs/v148-batch27-validation.json)
- [Sketch Fill ledger and all measurement costs](https://github.com/Vxiey/Image-Draw-Bot/blob/f800da5785731bbe0b0f8e3908bc330a65ac79c6/docs/v148-batch27-sketch-finalization.md)
- [Raw paired measurements](https://github.com/Vxiey/Image-Draw-Bot/blob/f800da5785731bbe0b0f8e3908bc330a65ac79c6/docs/v148-batch27-sketch-finalization-benchmarks.json)
- [Preserved completion before/after evidence](https://github.com/Vxiey/Image-Draw-Bot/blob/f800da5785731bbe0b0f8e3908bc330a65ac79c6/docs/v148-batch27-completion-evidence.json)

<details>
<summary>Published batch26 checkpoint and earlier history</summary>

## Status

**838 / 1,000 distinct behavior improvements are implemented; 162 remain. Version 1.0.148 is not released.**

Current checkpoint: `8e0a0e4c61ca0742dfb7857649103477cd307516`. All 837 preceding registry entries, the incoming batch25 implementation, its native-calibration/poll-fixture repairs and original raw reports are preserved. Only **R2601 / global 838** is new. The pull request remains a draft.

## Problem and resulting behavior

A complete Pixel plan with Lines and Subject Off extracted the same connected target regions during stroke construction and again during regional accuracy scoring. The second extraction rebuilt labels and component data that were already available.

This checkpoint passes one bounded owner between those stages. It retains existing labels and seven scalar fields per region, checks the current visible colors and mask before consuming them once, and releases the owner before finalization or on failure. Changed inputs, capacity/allocation limits, dots and subject-specific targets retain fresh extraction. Complete plans, scores, active-timer admission and original execution order remain exact.

Existing-contract completions add **zero IDs**:

- **P2504 / 836:** keep CUDA host allocation outside native GPU failure handling, preserve incoming Stop checks and release private host inputs from retained errors. Successful OpenCL already avoided this preparation in batch25; it is counted once.
- Use the existing bounded strict readers for calibration, palette, grid, legacy coordinates and verified-color cache. Publish calibration through the shared finite atomic writer.
- Publish GIF recordings through the existing shared writer, including bounded sharing retries and unsupported-sync handling. Stop still finishes and saves captured frames.
- Check normalized serialized UTF-8 dictionary size before saving/adoption, so accepted saved lists remain readable at startup and rejected imports preserve the previous dictionary.
- Retire unused shadow-analysis outputs before later consumers without changing used guidance, metadata or another owner's mapping.
- Pin older benchmark12/24/25 caller graphs to their published versions and preserve their original raw evidence. Narrow legacy test updates retain their original assertions or replace a source-string check with the actual public flow.

## Final local validation

- **4,431 tests in 215.945 s:** 4,361 passed and 70 platform/hardware cases skipped.
- All **923 checked source/configuration hashes remained unchanged**.
- **10/10 real Linux/Xorg native UI cases**, 5.238 s, no skips or Tcl-lifetime diagnostics.
- **5,000 lifecycle/profile-isolation cycles**, **1,305-file package hygiene** and **eight exact existing-raster fixtures** passed.
- Topology parity: **36 complete regional score pairs, 38 complete public-plan pairs and 24 independent brush-one raster pairs**. Two public pairs use an active timer with actual omitted paths; all budget and order metadata remain exact.
- The active-timer workload keeps 119 regions, 92 final paths, 71 omitted paths and correction reserve 13; component analyses change **2 → 1**, row-statistics work **200 → 100**.
- GPU caller parity: **692 cases against each of two complete historical modules**, plus six complete caller/transfer/work comparisons.
- Final untimed replay12 and replay24 retain their original causal scopes: two complete public plans; 72 scheduler, 24 complete public-plan and 24 independent raster pairs plus nine workloads. Replay25 exactly reproduces its published before/after quality and geometry results. Shadow ownership has 48 complete historical/current caller comparisons.
- All final native/raster/paired reports and the full-test root subset share **873 unchanged root Python hashes**. Independent source, real-flow, ownership, raw-result and metadata reviews are closed.

## Measurement evidence and limits

Eleven topology workloads have six balanced AB/BA pairs and separate peak/retained-allocation probes. Eight eligible workloads reduce component extraction from two calls to one. The three controls keep their original call counts.

| Complete public workload | Before → after median (ms) | Change | Faster pairs |
| --- | ---: | ---: | ---: |
| Checkerboard 64×64 | 388.435 → 374.543 | −3.576% | 3/6 |
| Checkerboard 128×128 | 1,784.750 → 1,778.826 | −0.332% | 2/6 |
| Checkerboard 256×192 | 3,293.444 → 2,983.639 | −9.407% | 6/6 |
| Blocks 384×256 | 153.614 → 141.672 | −7.774% | 6/6 |
| RGBA 128×96 | 47.766 → 44.990 | −5.811% | 6/6 |
| Flat 384×256 | 142.209 → 135.358 | −4.817% | 6/6 |
| Empty 128×96 | 25.228 → 24.464 | −3.028% | 5/6 |
| Dots control | 431.720 → 460.401 | +6.643% | 2/6 |
| Subject first control | 55.633 → 55.881 | +0.447% | 2/6 |
| Subject only control | 44.467 → 46.161 | +3.809% | 1/6 |
| Existing image, active timer | 176.122 → 170.123 | −3.406% | 6/6 |

The two smaller checkerboards and all slower controls remain visible; these observations establish no general planner speedup. Checkerboard128/256 traced peaks fall by 2,828,471/9,908,917 bytes, while Dots increases by 244 bytes peak and 349 bytes retained. Reuse can retain up to **8 MiB labels plus about 3.5 MiB records between stages**, so no universal memory reduction is claimed. Traced allocation is not total RSS or every native Pillow allocation.

The six OpenCL workloads reproduce the **already-counted** eager-to-lazy change from `586e12d` with a typed portable facade. The incoming `5b0c22a` already has identical successful-route work counts. CPU controls are +0.784%/+0.751%; direct CPU peak is 920 bytes higher and all retained-result values are slightly higher. The facade performs synthetic CPU arithmetic, so these data establish neither an additional gain over837 nor physical GPU throughput.

## Exact-commit Windows and package checks

**All seven checks passed for `8e0a0e4c61ca0742dfb7857649103477cd307516`:** Windows and Linux core jobs, both dependency jobs, both CodeQL analyses and the aggregate CodeQL check. [CI run 42416126653](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42416126653) · [CodeQL run](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42416122186).

The [exact Windows job](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42416126653/job/128534511846) passed all **14 steps**. Its complete suite ran **4,431 tests in 465.277 s: 4,428 passed and three hardware cases skipped**. All 56 exact-raster/planner regressions passed in 10.621 s. Source and packaged self-tests, Windows bundle build/validation, the RC artifact gate, packaged GUI and native drag-and-drop passed. The full Windows log contains **zero invalid-command and zero Tcl_AsyncDelete diagnostics**. Native screen sampling retained **31 → 31 GDI objects**.

The built `ImageDrawBot-1.0.148-Windows-x64.zip` has SHA-256 `14656d42946941d619558489112daa2f414a948afc890e9e9d9228c40d1f5d62`. This is CI build evidence; version 1.0.148 has not been released.

The exact parent `a3b7b929b1332772a089e1819143471ae5d58c68` passed all seven checks and all fourteen Windows job steps. Windows ran 4,373 tests in 463.446 s with three hardware skips; source/packaged self-tests, bundle validation and packaged GUI/native drag-and-drop passed. Its ZIP SHA-256 is `6f74025837eb4d89402b01888d64e984a8b921ec4fe87154876c436ec44a17c5`. That parent evidence is kept separate from this new checkpoint.

## Evidence

- [Registry and overview](https://github.com/Vxiey/Image-Draw-Bot/blob/8e0a0e4c61ca0742dfb7857649103477cd307516/docs/IMPROVEMENTS-v1.0.148.md)
- [Final validation and source bindings](https://github.com/Vxiey/Image-Draw-Bot/blob/8e0a0e4c61ca0742dfb7857649103477cd307516/docs/v148-batch26-validation.json)
- [Topology method, all results and retention limits](https://github.com/Vxiey/Image-Draw-Bot/blob/8e0a0e4c61ca0742dfb7857649103477cd307516/docs/v148-batch26-topology.md)
- [Raw topology comparisons](https://github.com/Vxiey/Image-Draw-Bot/blob/8e0a0e4c61ca0742dfb7857649103477cd307516/docs/v148-batch26-topology-benchmarks.json)
- [OpenCL host completion and historical reproduction](https://github.com/Vxiey/Image-Draw-Bot/blob/8e0a0e4c61ca0742dfb7857649103477cd307516/docs/v148-batch26-opencl-host.md)
- [Calibration/grid/cache storage](https://github.com/Vxiey/Image-Draw-Bot/blob/8e0a0e4c61ca0742dfb7857649103477cd307516/docs/v148-batch26-color-storage-completion.md)
- [GIF publication](https://github.com/Vxiey/Image-Draw-Bot/blob/8e0a0e4c61ca0742dfb7857649103477cd307516/docs/v148-batch26-gif-storage-completion.md)
- [Dictionary persistence](https://github.com/Vxiey/Image-Draw-Bot/blob/8e0a0e4c61ca0742dfb7857649103477cd307516/docs/v148-batch26-word-storage-completion.md)
- [Shadow ownership](https://github.com/Vxiey/Image-Draw-Bot/blob/8e0a0e4c61ca0742dfb7857649103477cd307516/docs/v148-batch26-shadow-ownership-completion.md)

Release remains paused until the requested 1,000 independently verified behavior improvements and the final release checks are complete.

<details>
<summary>Preserved preceding checkpoint: 837 improvements</summary>

## Status

**837 / 1,000 distinct behavior improvements are implemented; 163 remain. Version 1.0.148 is not released.**

Current checkpoint: `a3b7b929b1332772a089e1819143471ae5d58c68`. All 830 preceding registry entries and the concurrent batch24 palette/queue implementation are preserved. Existing-contract completions, tests, documentation and version metadata add no IDs. The pull request remains a draft.

## Problem and resulting behavior

Timed Pixel admission could replay cleanup before fine detail and erase already correct protected pixels. Scaled Fill diagnostics projected ideal source spans instead of the categorical footprint of the native contours and bucket seeds. Resource recommendations could disable measured GPU winners, invalidate their own RAM signature, or recommend worker counts without running an executor. Compact native screen verification repeated one OS read per pixel.

This checkpoint fixes those paths while retaining the current planner, profile policies and public execution geometry where specified:

- **R2501 / 831:** retain admitted path occurrences in their original execution order. Phase quotas and physical brush sizes stay intact.
- **R2502 / 832:** replay color-batched contours, seals and Fill seeds in a bounded sparse categorical canvas. Preview and physical diagnostics consume the same footprint; allocation failure retains the complete base plan.
- **P2501 / 833:** let Auto use valid measured per-workload compute preferences, including CPU winners and GPU crossover thresholds.
- **P2502 / 834:** benchmark, persist, recommend and apply the same resolved RAM budget and scheduler signature.
- **P2503 / 835:** measure the real bounded thread/process executor lifetime with identical verified integer workloads, balanced rounds and actual results. Reject the former serial-proxy recommendation format.
- **P2504 / 836:** prepare host RGB and visibility only when CPU/CUDA consumes them. Successful OpenCL mapping avoids those unused arrays; fallback and Stop retain ownership.
- **N2501 / 837:** read eligible compact screen neighborhoods through one bounded DIB/BitBlt transfer, with scalar fallback for unsuitable requests and optional acquisition failure.

Zero-ID completions preserve Stop through native preparation, release unpublished decoded images, restore failed calibration dialogs, serialize complete click transactions and retain owned widget-timer cleanup. The identical incoming batch24 button correction is kept once, alongside both regression selections.

## Final local validation

The frozen local evidence below belongs to `e669376`; the follow-ups change only test fixtures and documentation. Product code is byte-for-byte unchanged.

- **4,372 tests in 209.654 s:** 4,302 passed and 70 platform/hardware cases skipped.
- All **919 source/configuration hashes remained unchanged** during the full run.
- **5,000 lifecycle/profile-isolation cycles**, **1,284-file package hygiene** and **eight existing-raster geometry fixtures** passed.
- Merged focused gates: **68/68 rendering**, **56 UI passes plus 13 native skips**, and **35 platform/native passes plus one Windows desktop skip**.
- Three public rendering workloads have **six balanced AB/BA pairs** and separate traced-allocation probes, bound to **863 unchanged root Python files**.
- Independent source, integration, ownership and final metadata reviews are complete.

## Quality and measurement limits

The focused 3 px component counterexample improves protected accuracy **80% → 100% with the same 30 admitted paths**. The existing-asset timed plan retains its prior final score; this is not a universal image-quality gain.

For the existing-asset Fill plan, execution geometry, two Fills, 478 paths and the estimate remain unchanged. The corrected model reports **666 previously hidden missing native pixels**, and the scaled preview matches all sampled categorical executor pixels. The model uses palette indices, square brushes and four-neighbor bucket behavior before CanvasGuard; it does not claim RGB-alias, antialiasing or physical-Paint equivalence.

| Public workload | Before → after median | Before → after traced peak |
| --- | ---: | ---: |
| Timed Pixel, 3 px | 192.995 → 189.762 ms | 4,593,589 → 4,593,373 B |
| Two accepted Fills | 624.316 → 626.557 ms | 32,400,528 → 32,424,260 B |
| No-Fill control | 614.637 → 620.020 ms | 31,724,331 → 31,745,212 B |

The unchanged/slower controls, overlapping ranges and extra Fill storage are retained. These observations establish no general planner speedup or memory reduction. Traced allocation is not total RSS, and the CPU scheduler's integer workload is not a universal NumPy/planner optimum. No physical CUDA/OpenCL throughput was measured locally.

## Exact-commit Windows and package checks

**All seven checks passed for `a3b7b929b1332772a089e1819143471ae5d58c68`:** Windows and Linux core jobs, both dependency jobs, both CodeQL analyses and the aggregate CodeQL check. [CI run](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42413376803) · [CodeQL run](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42413372484).

| Runner | Tests run | Passed | Skipped | Full-suite duration |
| --- | ---: | ---: | ---: | ---: |
| Windows | 4,373 | 4,370 | 3 hardware cases | 463.446 s |
| Linux | 4,373 | 4,303 | 70 platform/hardware cases | 207.837 s |

The [final Windows job](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42413376803/job/128526075709) also passed all 56 exact-raster/planner regressions, the source app self-test, Windows bundle build/validation, packaged app self-test, packaged GUI launch and native drag-and-drop smoke. Its RC Windows artifact gate reports **PASS**. The full Windows log contains **zero invalid-command and zero Tcl-lifetime diagnostics**.

The built `ImageDrawBot-1.0.148-Windows-x64.zip` has SHA-256 `6f74025837eb4d89402b01888d64e984a8b921ec4fe87154876c436ec44a17c5`. This is CI build evidence; no 1.0.148 release has been published.

### Native screen sampling on the final Windows commit

The test displays an existing shipped icon in a native window. All sampled RGB values match the former GetPixel reader, all twelve repeated 169-point bulk reads use the native path, and GDI resources remain **31 → 31**. Six balanced AB/BA pairs per size produced these per-call medians:

| Sample points | Previous scalar reader | Current public reader |
| --- | ---: | ---: |
| 8 (scalar control) | 134.435 ms | 126.811 ms |
| 25 | 411.497 ms | 15.905 ms |
| 81 | 1,345.913 ms | 15.853 ms |
| 169 | 2,801.692 ms | 15.943 ms |

These measurements cover this screen-reader call on one Windows CI host, including the small-request scalar control. They do not establish whole-drawing speed or physical CUDA/OpenCL throughput.

<details>
<summary>Raw native sampling observations for the final commit</summary>

```json
{
  "points": 169,
  "gdi_before": 31,
  "gdi_after": 31,
  "measurements": [
    {
      "points": 8,
      "paired_ms": {
        "scalar": [
          126.74679999997807,
          126.68339999999034,
          126.87149999999292,
          142.13979999999538,
          158.39019999998527,
          141.9988000000103
        ],
        "public": [
          126.73720000003641,
          126.82879999999841,
          126.5870000000291,
          127.15130000003683,
          141.83819999999514,
          126.79329999997435
        ]
      }
    },
    {
      "points": 25,
      "paired_ms": {
        "scalar": [
          427.9272999999648,
          396.029800000008,
          411.358000000007,
          427.76530000003277,
          410.86709999996174,
          411.6367999999966
        ],
        "public": [
          15.909199999953216,
          15.601300000014362,
          15.926799999988361,
          15.846699999997327,
          15.95559999998386,
          15.900799999997162
        ]
      }
    },
    {
      "points": 81,
      "paired_ms": {
        "scalar": [
          1330.2869999999984,
          1345.3169000000003,
          1346.5096000000472,
          1360.7370000000287,
          1315.4370000000313,
          1391.618200000039
        ],
        "public": [
          16.113700000005338,
          15.864899999996851,
          15.661999999963427,
          15.985099999966224,
          15.825699999993503,
          15.841299999976854
        ]
      }
    },
    {
      "points": 169,
      "paired_ms": {
        "scalar": [
          2770.3399000000104,
          2849.3160000000444,
          2802.4687999999855,
          2786.318699999981,
          2816.6175000000067,
          2800.9152999999856
        ],
        "public": [
          15.955200000007608,
          15.936800000019957,
          16.05509999996002,
          15.749900000002981,
          15.949500000033368,
          15.675999999984924
        ]
      }
    }
  ]
}
```

</details>

### Retained failure history and fixture corrections

The initial `e669376` [Windows run](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42410649217/job/128517831680) ran 4,372 tests in 475.089 s with one native calibration-lifetime failure and three hardware skips; packaging did not run. The fixture simulated Capture before CustomTkinter's initially withdrawn dialog had become visible. The correction waits for the actual initial Visibility event before interaction; all 17 prior assertions, the platform gate and the 20-second subprocess bound remain. That native test passed both subsequent Windows runs.

The next `5b0c22a` [Windows run](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42411930802/job/128521730990) ran 4,372 tests in 482.580 s with two older edit-history fixture failures and three hardware skips; packaging did not run. Its shared fixture disabled recurring polling and pumped only one real 15 ms GUI slice, which could leave the terminal `done` event queued after slower image adoption. The actual worker was already joined; the product's busy guards correctly deferred the next edit.

The final fixture drains its finite queue through real poll slices with strict progress, without running unrelated scheduled callbacks. All 127 prior assertions remain. Twenty-four focused methods and deterministic reproductions passed locally, and an added regression loads the existing shipped icon through the real loader/worker, raising discovery to 4,373. Both corrections affect tests/documentation only: product source, the frozen local benchmark bindings and the **837** improvement count are unchanged. The final full CI, native and package results above close these failures.

## Evidence

- [Numbered registry and overview](https://github.com/Vxiey/Image-Draw-Bot/blob/e669376de8083975074f0ec079dd7a393657cf64/docs/IMPROVEMENTS-v1.0.148.md)
- [Final merged-source validation and bindings](https://github.com/Vxiey/Image-Draw-Bot/blob/a3b7b929b1332772a089e1819143471ae5d58c68/docs/v148-batch25-validation.json)
- [Rendering quality, complete method and tradeoffs](https://github.com/Vxiey/Image-Draw-Bot/blob/e669376de8083975074f0ec079dd7a393657cf64/docs/v148-batch25-rendering.md)
- [Raw paired rendering observations](https://github.com/Vxiey/Image-Draw-Bot/blob/e669376de8083975074f0ec079dd7a393657cf64/docs/v148-batch25-rendering-quality.json)
- [Resource recommendations and preparation](https://github.com/Vxiey/Image-Draw-Bot/blob/e669376de8083975074f0ec079dd7a393657cf64/docs/v148-batch25-platform.md)
- [Native sampling and click ownership](https://github.com/Vxiey/Image-Draw-Bot/blob/e669376de8083975074f0ec079dd7a393657cf64/docs/v148-batch25-native-sampling.md)
- [Worker, import and calibration lifetime](https://github.com/Vxiey/Image-Draw-Bot/blob/a3b7b929b1332772a089e1819143471ae5d58c68/docs/v148-batch25-ui-workflow.md)

Release remains paused until 1,000 independently verified behavior improvements and the final release checks are complete.

<details>
<summary>Preserved preceding checkpoint: 830 improvements</summary>

## Status

**830 / 1,000 distinct behavior improvements are implemented; 170 remain. Version 1.0.148 is not released.**

This draft continues the application-wide correctness, performance and maintenance work. The original 100-change baseline is included in the count. Existing-contract completions, tests, documentation and version metadata do not add IDs. All 828 prior registry entries are preserved.

Current checkpoint: `586e12db5ea5142951c844f60dc2364f07a01c37`. Its own [CI run](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42407814245) completed successfully, and both [CodeQL analyses](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42407810364) and the aggregate CodeQL check succeeded. Windows ran **4,308 tests in 240.153 s, with three hardware skips**, plus 56 raster/planner regressions. Source and packaged self-tests, Windows bundle validation, packaged GUI and native drag-and-drop passed. The complete Windows log contains **zero invalid-command or Tcl lifetime diagnostics**; the five animation-timer diagnostics observed at the preceding checkpoint are absent.

The previously recorded dependency-check status lag is resolved: all seven checks for this parent checkpoint are now completed successfully. Windows ZIP SHA-256: `960cfdcb4fc7d83434851aa88a15b64a9abed13e2b99224900c2f38e9a168baf`.

## Latest changes

- **U2401 / 829:** keep manual palette calibration responsive while the existing detector and Pillow preview run in a cancellable worker. Tk adoption stays on the GUI thread. Cancel, stale settings, failed startup/polling and presentation errors preserve or retire the correct image/draft owner.
- **R2401 / 830:** maintain the existing first-72 Pixel candidate window without shifting the entire unseen component tail on each choice. Candidate order, ties, all cost calls, phases, Stop, metadata and complete drawing plans remain exact.
- **Zero new IDs:** prepared Paint colors respect the resolved Manual/Auto policy and accepted profile resets; Upscale uses the existing keyboard controls; early widget destruction cancels its owned animation timers; retained scanner/preview exceptions release private image, NumPy and generator references.
- An older Sketch Fill fixture now reaches prepared colors through the actual accepted result handler. Every original selector, execution and raster assertion is retained.

## Final local validation

- **4,308 tests in 205.763 s:** 4,242 passed and 66 platform/hardware cases skipped. All **900 source/configuration hashes stayed unchanged**.
- **10/10 real Linux/Xorg native UI cases** passed in 5.173 s, with no invalid-command, Tcl lifetime or ignored-destructor diagnostic.
- **5,000 lifecycle/profile-isolation cycles**, **1,265-file source-package hygiene** and **eight exact existing-raster fixtures** passed.
- Complete historical modules verify **54 palette-controller cases**, **72 scheduler pairs**, **24 complete public plans** and **24 independent public rasters**.
- Nine scheduling workloads have **six balanced AB/BA pairs** each and separate allocation probes. The native gate, historical checks, measurements, existing-raster gate and full-test subset share **850 root Python hashes**.
- Independent source, real-flow, ownership and benchmark/result reviews are closed.

The initial full run exposed four subcase failures in one old fixture that directly installed a prepared palette while leaving Calibrated palette selected. The fixture now uses the real preparation handler and plan invalidation. Its ten-case related gate and the repeated full gate passed; the initial result remains recorded in the evidence.

## Performance evidence and limits

The demonstrated queue improvement is bounded reference movement: for the 32,768-component helper, **535,599,125 → 1,068,569 list-pop shifts**; for a complete 192×192 Pixel plan, **142,822,158 → 751,362**. The new linear reverse and window append work is included in elapsed measurements but not in the pop counter.

There is **no general whole-planner speedup or meaningful peak-memory reduction** in this run. The 32,768-item helper median changes from 1,955.209 to 1,923.385 ms (−1.628%); the complete 64×64 checkerboard changes from 371.807 to 395.884 ms (+6.476%, slower in five of six pairs). The 128×128 and 192×192 public checkerboards are +0.933% and +1.194%; the RGBA case is +2.544%. All samples and unchanged/slower controls are retained. Helper traced peaks increase by 56 bytes.

The palette worker adds a private rescan copy and thread/poll overhead. Its evidence establishes responsiveness and ownership, not reduced detector CPU work. No physical drawing-speed, GPU throughput, total-RSS, signing or antivirus claim is made.

## Evidence

- [Numbered registry and overview](https://github.com/Vxiey/Image-Draw-Bot/blob/586e12db5ea5142951c844f60dc2364f07a01c37/docs/IMPROVEMENTS-v1.0.148.md)
- [Final validation and exact source bindings](https://github.com/Vxiey/Image-Draw-Bot/blob/586e12db5ea5142951c844f60dc2364f07a01c37/docs/v148-batch24-validation.json)
- [Manual palette analysis and ownership](https://github.com/Vxiey/Image-Draw-Bot/blob/586e12db5ea5142951c844f60dc2364f07a01c37/docs/v148-batch24-palette-scan.md)
- [Complete historical palette report](https://github.com/Vxiey/Image-Draw-Bot/blob/586e12db5ea5142951c844f60dc2364f07a01c37/docs/v148-batch24-palette-scan-parity.json)
- [Component queue method, all timing/allocation results and tradeoffs](https://github.com/Vxiey/Image-Draw-Bot/blob/586e12db5ea5142951c844f60dc2364f07a01c37/docs/v148-batch24-component-queue.md)
- [Raw paired queue measurements](https://github.com/Vxiey/Image-Draw-Bot/blob/586e12db5ea5142951c844f60dc2364f07a01c37/docs/v148-batch24-component-queue-benchmarks.json)
- [Prepared Paint policy and Upscale keyboard flows](https://github.com/Vxiey/Image-Draw-Bot/blob/586e12db5ea5142951c844f60dc2364f07a01c37/docs/v148-batch24-ui-workflow.md)
- [Native widget timer completion](https://github.com/Vxiey/Image-Draw-Bot/blob/586e12db5ea5142951c844f60dc2364f07a01c37/docs/v148-batch24-widget-lifetime-completion.md)

Release stays paused until the requested 1,000 independently verified behavior improvements and the final release checks are complete.


</details>


</details>


</details>


</details>


</details>


</details>
