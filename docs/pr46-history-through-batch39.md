# Draft PR46 history through batch39

## Status — v1.0.148 remains a draft

**846 / 1,000 distinct improvements implemented; 154 remaining.** Batch 39 adds two independently reviewed behavior groups, **R3901/global845** and **P3901/global846**, while completing two existing lifecycle contracts with **zero new IDs**. All 844 preceding registry entries are preserved.

**Current head:** `888116094b91758dded968a7e3b5559683db9ad7`  
**CI for this head is incomplete: GitHub startup error and queued test workflow.** The local results below bind the published tree `bd2f73f9d43613b488e22e211e31c97fbb5af376`. Earlier green CI belongs to its earlier commits and does not verify this head; the preceding PR history is preserved [through batch 38](https://github.com/Vxiey/Image-Draw-Bot/blob/888116094b91758dded968a7e3b5559683db9ad7/docs/pr46-history-through-batch38.md).

[Review the complete batch](https://github.com/Vxiey/Image-Draw-Bot/compare/74c3a510416b56bff84e70353622e3a91884f09e...888116094b91758dded968a7e3b5559683db9ad7) · [Current CI workflow](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43098405290)

## What changed

| Area | Resulting behavior | Counting |
| --- | --- | --- |
| Required recovery images | A missing, invalid or unreadable required PNG stops recovery before checkpoint settings or the saved area replace current work. Settings-only recovery and valid retry remain supported; Stop retains priority. | Completes 075/global75 and AW16/global630; **0 new IDs** |
| Preview ownership | Completed plan images remain owned until successful queue publication. Expired results close before fallback; failed publication and retained exceptions release unpublished images while preserving borrowed inputs and the previous UI plan. | Completes IW08/global582 and existing Stop/timeout ownership; **0 new IDs** |
| Pixel source groups | The component collector shares its exact immutable horizontal segments with the source color groups, eliminating the duplicate scan and segment allocations. Geometry, ordering and semantic metadata are preserved, as are Dots and standalone consumers. | **R3901/global845** |
| CPU palette preparation | Large normal-CPU and OpenCL-to-CPU fallback inputs composite the current **4,096-pixel scoring block**. Alpha, ties, fidelity, white filtering and metadata remain exact; existing CUDA preparation is reused. | **P3901/global846** |

## Verification actually completed locally

Linux, Python 3.12.14, Pillow 13.0.0 and NumPy 2.3.5:

| Check | Final result |
| --- | --- |
| All four new test modules together | **32/32 passed**, no failures/errors/skips, **4.298 s** |
| Complete unittest discovery | **4,768 methods: 4,682 passed, 86 platform/display/hardware skips**, no failures/errors, **263.504 s** |
| Real Linux/Xorg workspace, profile, error actions and shutdown selection | **4/4 passed**, no skips, **20.254 s** |
| Source gate | Structural checks and **5,000 lifecycle/profile-isolation cycles passed** |
| Source-package hygiene | **1,423 files**, no forbidden paths, missing required files or warnings |
| `git diff --check` | Passed |

Integration, complete discovery and native UI checks bind the same **958 unchanged source/configuration/fixture hashes**. The identical frozen new tests reproduce 22 failing methods on the old product, with ten positive controls; all 32 pass after the fixes. Overlapping focused, adjacent and full runs are not added together as unique tests.

The shared recovery fixture now releases its window and dialog-mock Tcl references on the creator thread. Both dialog assertions remain intact. Initial Tcl aborts, runner diagnostics and the earlier full run with the preceding fixture are retained separately and are not presented as the final gate. The 32 new methods use existing assets or their derivatives; older suites retain their established fixtures.

## CI for the published head — incomplete

Observed **2026-11-11 21:00 UTC** for `888116094b91758dded968a7e3b5559683db9ad7`:

| Run | Observed result |
| --- | --- |
| [CodeQL attempt 1](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43098274541) | **`startup_failure` before any job was created.** The run page reports an unexpected internal GitHub error. No CodeQL analysis ran. |
| [Windows/Linux CI attempt 1](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43098405290) | **Queued; zero jobs created at this observation.** No Windows/Linux CI test results exist for this head yet. |

An attempt to rerun the failed CodeQL workflow was rejected by GitHub with **HTTP 403: `This workflow run cannot be retried`**. This is recorded as an unsuccessful retry request, not an executed second attempt. The source patch and workflow definitions were not changed to bypass the failure.

**The seven-check CI gate has not passed for this commit.** Local test results above are completed and source-bound; prior commits' green checks remain historical. Windows packaged-app verification and CodeQL for the new head remain outstanding. The PR remains a draft and the release gate remains closed.

## Measurements and limits

- **Pixel planning:** exact semantic output/metadata parity, excluding documented elapsed-time diagnostics, across 216 timed calls and 24 separate allocation calls. The duplicate scan and separate segment tuples are removed, but whole-caller timings are mixed, including slower controls. Whole-plan traced peaks are nearly unchanged; no general planning-speed or overall memory reduction is claimed.
- **CPU palette mapping:** all 48 public-mapper outputs match. Measured live RGB-composite array payload is bounded to **49,152 bytes**. The three larger cases are **0.48%, 1.50% and 2.23% slower** locally; the small Paint-reference case is **4.59% faster**. This payload is not total memory or RSS; required image-sized inputs and outputs remain.

These local checks do not establish physical Paint drawing, native GPU execution or Windows and packaged-app CI for this commit. No AI images or new source motifs were introduced.

## Evidence and next checkpoint

[Batch 39 ledger and measurements](https://github.com/Vxiey/Image-Draw-Bot/blob/888116094b91758dded968a7e3b5559683db9ad7/docs/v148-batch39-recovery-preview-and-pixel.md) · [Validation and exact source bindings](https://github.com/Vxiey/Image-Draw-Bot/blob/888116094b91758dded968a7e3b5559683db9ad7/docs/v148-batch39-validation.json) · [Lossless raw evidence](https://github.com/Vxiey/Image-Draw-Bot/blob/888116094b91758dded968a7e3b5559683db9ad7/docs/v148-batch39-evidence.json) · [Progress register](https://github.com/Vxiey/Image-Draw-Bot/blob/888116094b91758dded968a7e3b5559683db9ad7/docs/v148-improvement-progress.md)

Continue the remaining **154 distinct improvements** toward 1,000, then complete final verification. **Keep this PR as a draft. No merge, tag or release has been performed. Merge and release require explicit approval; version 1.0.148 remains unreleased.**

