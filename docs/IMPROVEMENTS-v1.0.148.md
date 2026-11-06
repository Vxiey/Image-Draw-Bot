# Image Draw Bot v1.0.148 — improvement ledger

**Development status:** 498 distinct behavior improvements are implemented and locally verified, including the original 100-change baseline. The requested target is **1,000**. **502 remain; 1.0.148 has not been published.**

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

The [machine-readable registry](v148-improvements.json) maps every global ID to its area-local ID and evidence ledger. The [working plan](v148-improvement-progress.md) records release conditions and the next review cycle.

## Integration evidence

- Batch 01 reference: `94a748ec7690eebb542c70311c594aa835434a98`; batch 02 reference: `1c09774ad22088c5c30a8f8220b6b451fdee9659`.
- Batch 02 complete local unittest discovery: **2,557 tests in 57.669 seconds; passed, 22 platform/hardware skips**.
- Release source gate: **passed**, including 5,000 lifecycle/profile-isolation cycles.
- Source-package hygiene: **passed**, no forbidden or missing required files.
- Eight deterministic engine fixtures: **zero mismatched pixels in all cases**; [raw measurements](v148-batch02-engine-benchmarks.json).
- Batch 01 Linux, dependency and CodeQL checks passed. Windows CI exposed a concurrent atomic-publication sharing failure. Batch 02 completes that existing change with bounded Windows sharing retries and independently reviewed transaction/publication lock ordering; it is **not counted again**.
- The new checkpoint still requires native Windows/Tk, packaged-executable and dependency CI.
- Physical CUDA/OpenCL devices and real target-application drawing speed are not established by local CPU or fake-device tests.

Benchmarks in the area ledgers disclose inputs, before/after medians, output checks and memory limits. They are specific workload measurements, not a claim that the whole application or every drawing is faster by the same factor. The batch 02 delivery measurements include slower visual sampling and detail-preview cases; those changes establish bounded memory or correctness, not a universal speedup.
