# Image Draw Bot v1.0.148 — improvement ledger

**Development status:** 699 distinct behavior improvements are implemented, including the original 100-change baseline. The requested target is **1,000**. **301 remain; 1.0.148 has not been published.** Current verification is recorded below.

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

The [machine-readable registry](v148-improvements.json) maps every global ID to its area-local ID and evidence ledger. The [working plan](v148-improvement-progress.md) records release conditions and the next review cycle.

## Integration evidence

- Batch 05 reference: `5f3fcfb5c4519e5ed1b9b770ba951918819d725d`. Independent area reviews and count checks are closed. Final frozen-source integration passed **3,059 tests in 73.421 seconds**, with **26 platform/hardware skips** and unchanged source hashes. The final adaptive-probe/correction review is also closed. This new checkpoint still requires its own Windows/Linux CI.
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
