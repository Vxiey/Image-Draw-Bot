# Image Draw Bot v1.0.148 — improvement ledger

**Development status:** 262 distinct behavior improvements are implemented and locally verified, including the original 100-change baseline. The requested target is **1,000**. **738 remain; 1.0.148 has not been published.**

The count excludes tests, assertions, documentation, version changes, formatting and repeated implementations of the same correction. Each batch ledger explains the prior behavior, the runtime change and its regression evidence. Review-driven corrections within a new change retain its existing ID.

| Global IDs | Local IDs | Area | Count | Evidence |
| --- | --- | --- | ---: | --- |
| 001–100 | 001–100 | Original reliability/security baseline | 100 | [Original ledger](100-IMPROVEMENTS-v1.0.148.md); merged PR44 passed Windows/Linux CI. |
| 101–140 | CG01–CG40 | Batch 01 colour and GPU processing | 40 | [Colour/GPU ledger](v148-batch01-colour-gpu.md); independent storage-agent review. |
| 141–180 | PL01–PL40 | Batch 01 planning and geometry | 40 | [Planning ledger](v148-batch01-planning.md); independent integration-owner review. |
| 181–221 | SS01–SS41 | Batch 01 storage, security and resources | 41 | [Storage ledger](v148-batch01-storage-security.md); independent planner-agent review. |
| 222–262 | UI01–UI41 | Batch 01 UI, imports and previews | 41 | [UI/input ledger](v148-batch01-ui-input.md); independent colour/GPU-agent review. |

The [machine-readable registry](v148-improvements.json) maps every global ID to its area-local ID and evidence ledger. The [working plan](v148-improvement-progress.md) records release conditions and the next review cycle.

## Integration evidence

- Baseline commit for new-batch comparisons: `94a748ec7690eebb542c70311c594aa835434a98`.
- Full local unittest discovery: **2,202 tests in 70.676 seconds; passed, 19 platform/hardware skips**.
- Source package hygiene: **passed**, no forbidden or missing required files.
- Release source gate: **passed**, including 5,000 lifecycle/profile-isolation cycles.
- Eight engine fixtures preserve exact quantized target geometry (zero mismatched pixels in all cases); see [raw before/after measurements](v148-batch01-benchmarks.json).
- Native Windows/Tk, packaged executable and dependency CI: **pending for the batch checkpoint**.
- Physical CUDA/OpenCL devices and real target-application drawing speed are not established by local CPU or fake-device tests.

Benchmarks in the area ledgers disclose inputs, before/after medians, output checks and memory limits. They are specific workload measurements, not a claim that the whole application or every drawing is faster by the same factor.
