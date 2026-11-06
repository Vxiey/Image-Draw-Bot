# Image Draw Bot v1.0.148 — improvement ledger

**Development status:** 759 distinct behavior improvements are implemented, including the original 100-change baseline. The requested target is **1,000**. **241 remain; 1.0.148 has not been published.** Current verification is recorded below.

The count excludes tests, assertions, documentation, version changes, formatting and repeated implementations of the same correction. Each batch ledger explains the prior behavior, the runtime change and its regression evidence. Review-driven corrections within a new change retain its existing ID.

| Global IDs | Local IDs | Area | Count | Evidence |
| --- | --- | --- | ---: | --- |
| 001–100 | 001–100 | Original reliability/security baseline | 100 | [Original ledger](100-IMPROVEMENTS-v1.0.148.md); merged PR44 passed Windows/Linux CI. |
| 101–140 | CG01–CG40 | Batch 01 colour and GPU processing | 40 | [Colour/GPU ledger](v148-batch01-colour-gpu.md); independent storage-agent review. |
| 141–180 | PL01–PL40 | Batch 01 planning and geometry | 40 | [Planning ledger](v148-batch01-planning.md); independent integration-owner review. |
| 181–221 | SS01–SS41 | Batch 01 storage, security and resources | 41 | [Storage ledger](v148-batch01-storage-security.md); independent planner-agent review. |
| 222–262 | UI01–UI41 | Batch 01 UI, imports and previews | 41 | [UI/input ledger](v148-batch01-ui-input.md); independent colour/GPU-agent review. |
| 263–331 | CAL01–CAL69 | Batch 02 browser/Paint calibration | 69 | [Calibration ledger](v148-batch02-calibration.md); independent storage-agent review. |
| 332–404 | DP01–DP73 | Batch 02 delivery, verification and planning | 73 | [Delivery ledger](v148-batch02-delivery-planning.md); independent integration-owner review. |
| 405–442 | SR01–SR38 | Batch 02 storage, resources and release | 38 | [Storage ledger](v148-batch02-storage-runtime.md); independent planner-agent review. |
| 443–498 | RT01–RT56 | Batch 02 input, runtime and UI | 56 | [UI/runtime ledger](v148-batch02-ui-input.md); independent calibration-agent review. |
| 499–514 | CQ01–CQ16 | Batch 03 colour quality and analysis | 16 | [Colour-quality ledger](v148-batch03-colour-quality.md); independent platform-agent review. |
| 515–552 | RP01–RP38 | Batch 03 rendering, planning and exact previews | 38 | [Rendering/planning ledger](v148-batch03-rendering-planning.md); independent integration-owner review. |
| 553–574 | GP01–GP22 | Batch 03 GPU, benchmarks and platform behavior | 22 | [GPU/platform ledger](v148-batch03-gpu-platform.md); independent planner-agent review. |
| 575–614 | IW01–IW40 | Batch 03 image workflow, imports and UI | 40 | [Image-workflow ledger](v148-batch03-image-workflow.md); independent colour-agent review. |
| 615–641 | AW01–AW27 | Batch 04 application settings, recovery and planning policy | 27 | [Application ledger](v148-batch04-application.md); independent UI and planner reviews. |
| 642–650 | PB01–PB09 | Batch 04 colour planning, detail order and bounded working sets | 9 | [Planning ledger](v148-batch04-planning.md); independent integration-owner review. |
| 651–663 | UP01–UP13 | Batch 04 profiles, setup guidance and UI layout | 13 | [UI/profile ledger](v148-batch04-ui-profiles.md); independent integration-owner review. |
| 664–668 | NR01–NR05 | Batch 04 native input, helper lifecycle and diagnostic privacy | 5 | [Platform ledger](v148-batch04-platform-release.md); independent integration-owner review. |
| 669–675 | AP01–AP07 | Batch 05 subject recovery, runtime and correction retry | 7 | [Application ledger](v148-batch05-application.md); independent UI and platform reviews. |
| 676–681 | CP01–CP06 | Batch 05 colour consistency, canvas scoring and planning memory | 6 | [Colour/planning ledger](v148-batch05-colour-planning.md); independent UI-agent review. |
| 682–694 | UW01–UW13 | Batch 05 image drops, guide lifecycle and region selection | 13 | [UI/workflow ledger](v148-batch05-ui-workflow.md); independent planner review. |
| 695–699 | PR01–PR05 | Batch 05 source inventories and release publication | 5 | [Platform ledger](v148-batch05-platform-release.md); independent integration-owner review. |
| 700–706 | AX01–AX07 | Batch 06 learning, export, source color and ink probes | 7 | [Application ledger](v148-batch06-application.md); independent platform and planner reviews. |
| 707–713 | RB01–RB07 | Batch 06 canvas coordinates, budgets, color names and planning allocations | 7 | [Rendering ledger](v148-batch06-rendering.md); independent integration-owner review. |
| 714–724 | UC01–UC11 | Batch 06 calibration editing, preview navigation and responsive workspace | 11 | [UI/calibration ledger](v148-batch06-ui-calibration.md); independent platform and controller reviews. |
| 725–729 | PF01–PF05 | Batch 06 update history/cache and diagnostic lifecycle | 5 | [Platform ledger](v148-batch06-platform.md); independent integration-owner review. |
| 730–732 | AY01–AY03 | Batch 07 source depth and recording clock/storage | 3 | [Application ledger](v148-batch07-application.md); independent rendering and platform reviews. |
| 733–738 | RC01–RC06 | Batch 07 rendering priorities, admission, white ink and planning memory | 6 | [Rendering ledger](v148-batch07-rendering.md); independent integration-owner review. |
| 739–742 | UK01–UK04 | Batch 07 keyboard controls and workflow/renderer integration | 4 | [UI ledger](v148-batch07-ui-workflow.md); independent platform and controller reviews. |
| 743–745 | MP01–MP03 | Batch 07 mobile publication and raster import boundary | 3 | [Platform ledger](v148-batch07-platform.md); independent integration-owner review. |
| 746–747 | AZ01–AZ02 | Batch 08 image ownership and desktop preview reuse | 2 | [Application ledger](v148-batch08-application.md); rendering and UI source reviews. |
| 748–751 | RD01–RD04 | Batch 08 GPU policy, visible contrast, brush reductions and Fill contours | 4 | [Rendering ledger](v148-batch08-rendering.md); root and platform source reviews. |
| 752–757 | UW801–UW806 | Batch 08 profile maintenance, effective controls and keyboard selectors | 6 | [UI ledger](v148-batch08-ui-workflow.md); root and platform source reviews. |
| 758–759 | BP01–BP02 | Batch 08 coherent release publication and private build environments | 2 | [Platform ledger](v148-batch08-platform.md); UI source review. |

The [machine-readable registry](v148-improvements.json) maps every global ID to its area-local ID and evidence ledger. The [working plan](v148-improvement-progress.md) records release conditions and the next review cycle.

## Integration evidence

- Batch 08 reference: `73788a51c1a3502f03f007e4d2ffe0152f56b7e6`. Batch 08: final frozen-source discovery passed 3,462 tests in 81.280 seconds (39 platform/hardware skips), with unchanged source hashes. All four counted-area source reviews are closed; review findings were corrected with regressions. The 5,000-cycle source gate, source-package hygiene and eight exact-raster fixtures passed. The earlier full-suite failure was an outdated fake cost-model interface; its swap-selection assertions are preserved. This checkpoint still requires its own Windows/Linux CI. No 1.0.148 release is published.
- Batch 08 paired brush reductions retain complete output parity. Background removal reduces copied pixel payload without an established CPU speedup; desktop preview tests verify avoided repeated bitmap work. [Eight exact-raster fixtures](v148-batch08-engine-benchmarks.json) remain exact.

- Batch 07 reference: `8a9c848b9dd0f2c4738aee729dace75be2a5778d`. Batch 07: final frozen-source discovery passed 3,355 tests in 71.096 seconds (35 platform/hardware skips), with unchanged source hashes. All four area reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. Checkpoint `73788a51c1a3502f03f007e4d2ffe0152f56b7e6` passed complete Windows/Linux regressions, both dependency audits, CodeQL, Windows self-test, bundle build and packaged GUI/native drag-and-drop checks in [run 42302890291](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42302890291). No 1.0.148 release is published.
- Batch 07 retains complete output parity in the paired recording, mobile and rendering measurements. Memory scopes and unchanged/slower cases are stated in each ledger. [Eight exact-raster fixtures](v148-batch07-engine-benchmarks.json) have zero mismatched pixels.

- Batch 06 reference: `4c8aa247f852df7225b5e7d10ce4ac151e612226`. Batch 06: final frozen-source discovery passed 3,201 tests in 71.794 seconds (31 platform/hardware skips), with unchanged source hashes. All four area reviews and the separate ICC/alpha and delivered-probe reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. The existing Windows scaling and compact-height repairs through `ace8fd741b363ab9f7a01ccd1fad94231a70a1f4` passed complete Windows/Linux regressions, both dependency audits, CodeQL, Windows self-test, bundle build and packaged GUI/native drag-and-drop in [run 42300520218](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42300520218). These repairs add no duplicate improvement IDs. No 1.0.148 release is published.
- Batch 06 source hygiene and all eight exact-raster fixtures passed; [raw engine results](v148-batch06-engine-benchmarks.json). The only full-suite correction updated an older diagnostics fixture to the already implemented opaque settings label, preserving all privacy assertions. It adds no improvement ID.

- Batch 05 reference: `5f3fcfb5c4519e5ed1b9b770ba951918819d725d`. Independent area reviews and count checks are closed. Final frozen-source integration passed **3,059 tests in 73.421 seconds**, with **26 platform/hardware skips** and unchanged source hashes. The final adaptive-probe/correction review is also closed. Published checkpoint `4c8aa247` passed Windows/Linux, dependencies, CodeQL and packaged Windows checks in [run 42289019482](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42289019482).
- The 5,000-cycle source gate, source-package hygiene for 918 files and eight exact-raster fixtures passed; [raw engine results](v148-batch05-engine-benchmarks.json).
- Historical fixture updates preserve the changed contracts: runtime replanning now uses its allocation-avoiding adapter; palette goldens are checked pixel for pixel against the canonical scalar matcher after the neutral-chroma correction. Review completions cover actual Pillow pixel-buffer disposal, numeric protected-mask parity and unavailable clipped color probes. None adds another improvement ID.

- Batch 04 product reference: `1d48eabaf349a5fd8049a2c96ef5426745c3078c`; subsequent `2aca72a` only repairs test fixtures.
- Final batch 04 frozen-source discovery: **2,934 tests in 75.509 seconds, passed with 23 platform/hardware skips**. Source hashes stayed unchanged; independent area reviews and the coordinated detail-order/verification review are closed. Published checkpoint `5f3fcfb5c4519e5ed1b9b770ba951918819d725d` passed Windows/Linux, dependencies, CodeQL and packaged Windows GUI/native drag-and-drop checks in [run 42280910774](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42280910774).
- Batch 04 source gate passed 5,000 lifecycle/profile cycles and source-package hygiene passed. Eight engine fixtures have zero mismatched pixels; [raw results](v148-batch04-engine-benchmarks.json).
- One old mouse-cleanup assertion was updated: failed native LEFTUP retains ownership for a later cleanup attempt while input remains disarmed. The production semantics and retry tests are documented under NR01.

- Batch 03 reference: `2fb7abf470a4ef498df9c53f42cddda62d8b652b`.
- Final batch 03 frozen-source discovery: **2,800 tests in 70.634 seconds, passed with 22 platform/hardware skips**. Source hashes stayed unchanged during the run; all four independent area reviews are closed. Checkpoint `2aca72acb36b547d75e12a0a59d78325552c21a8` passed Windows/Linux regression, dependencies, CodeQL and packaged Windows GUI/native drag-and-drop checks in [run 42273234504](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42273234504). Its Ubuntu browser test initially timed out during Node startup; an unchanged-source rerun passed without increasing its timeout.
- Batch 03 source gate passed 5,000 lifecycle/profile cycles and source-package hygiene passed for 860 files; its eight exact-raster engine fixtures have zero mismatched pixels. [Raw engine results](v148-batch03-engine-benchmarks.json).

- Batch 01 reference: `94a748ec7690eebb542c70311c594aa835434a98`; batch 02 reference: `1c09774ad22088c5c30a8f8220b6b451fdee9659`.
- Batch 02 complete local unittest discovery: **2,557 tests in 57.669 seconds; passed, 22 platform/hardware skips**.
- Release source gate: **passed**, including 5,000 lifecycle/profile-isolation cycles.
- Source-package hygiene: **passed**, no forbidden or missing required files.
- Eight deterministic engine fixtures: **zero mismatched pixels in all cases**; [raw measurements](v148-batch02-engine-benchmarks.json).
- Batch 01 Linux, dependency and CodeQL checks passed. Windows CI exposed a concurrent atomic-publication sharing failure. Batch 02 completes that existing change with bounded Windows sharing retries and independently reviewed transaction/publication lock ordering; it is **not counted again**.
- Published checkpoint `2fb7abf470a4ef498df9c53f42cddda62d8b652b` passed Windows/Linux, dependency, CodeQL and packaged Windows GUI/native drag-and-drop CI in [run 42260646614](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42260646614). The failed Windows job initially had three subprocess startup timeouts; a rerun passed without changing the code or test timeouts.
- Physical CUDA/OpenCL devices and real target-application drawing speed are not established by local CPU or fake-device tests.

Benchmarks in the area ledgers disclose inputs, before/after medians, output checks and memory limits. They are specific workload measurements, not a claim that the whole application or every drawing is faster by the same factor. The batch 02 delivery measurements include slower visual sampling and detail-preview cases; those changes establish bounded memory or correctness, not a universal speedup.

Batch 03 likewise reports slower cluster-minimum timing and spatial summaries where the gain is bounded memory. Root review found and corrected preview sampling at floating-point boundaries and NumPy-integer budget overflow; these corrections remain within their original IDs. Owned-image disposal and repeated cancellation/API integrations are counted once in their corresponding shared groups.
