# PR #46 history through batch 35

This is the complete PR description captured at verified commit
`b22df12d9e17807edc43de7dabf29a113c81edc5`. References to the current head
and current results below belong to that historical checkpoint.
The linked history through batch 34 remains unchanged.

---

## Image Draw Bot v1.0.148 — 843 / 1,000 implemented improvements

**Draft development checkpoint. 157 distinct improvements remain. No merge, tag or release has been performed; merge/release requires the user's explicit approval.**

Current head: [`b22df12d9e17807edc43de7dabf29a113c81edc5`](https://github.com/Vxiey/Image-Draw-Bot/commit/b22df12d9e17807edc43de7dabf29a113c81edc5), based on verified parent `66948b321a3d7a17d984c0db2304e59205ea6cc0`.

## Current continuation: synchronous recovery storage

A secondary close or staging-unlink error could replace the original PNG encoding, copying or size-validation failure. The synchronous storage path now preserves the primary exception object and traceback, attaching secondary cleanup errors as notes. Standalone close/unlink failures still abort before checkpoint publication.

A local close context owns the converted RGBA image, temporary writer, legacy reader and digest reader. The temporary file keeps `delete=False` and explicit unlink ownership; file handles close before digest/rename. No asynchronous preparer, renderer, controller, snapshot lock, PNG setting or JSON format changes.

**Counting: zero new IDs.** This completes **IW08/global582** and the existing **056/global56** recovery-storage contract. The 843-entry machine registry is byte-for-byte unchanged. Tests, helper extraction and documentation are not counted as behavior improvements.

## Verification actually executed locally

| Selection | Result |
| --- | --- |
| Ten new methods on unchanged parent product code | 4 passed, 6 expected assertion failures; 0 errors/skips |
| Same frozen ten methods after the patch | **10 passed**, 0 failures/errors/skips |
| Nine existing adjacent methods | **9 passed**, 0 failures/errors/skips |
| Source-package hygiene | **1,385 files**, no warnings, forbidden paths or missing requirements |
| Independent source/test review and diff check | Passed |

The public `save_snapshot` tests use real Pillow encoding, temporary files, readers, publication and retry/pruning. Only I/O/cleanup faults are injected. They verify primary exception identity, nested cleanup notes, borrowed source lifetime, previous state/image/render-progress bytes, standalone cleanup failures, exact pixels/digest and legacy migration.

Pixel data comes from the existing icon and Paint-reference PNGs, with distinct old/new image identities. No synthetic test motif was introduced. An OS-denied unlink can leave staging; the tests observe that file and prove a later successful save prunes it. The injected `InterruptedError` checks error identity, **not** cooperative cancellation in this synchronous API.

## Exact-head GitHub verification

<!-- recovery35-ci-status -->
**All seven checks succeeded for `b22df12d9e17807edc43de7dabf29a113c81edc5` on 11 November 2026.** [Application CI 43028707145](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43028707145) and [CodeQL 43028699731](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43028699731) both completed successfully.

| Exact-head full suite | Executed | Passed | Skipped | Failures/errors | Test runtime |
| --- | ---: | ---: | ---: | ---: | ---: |
| [Windows Python 3.12](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43028707145/job/130549873033) | 4,603 | 4,600 | 3 GPU | 0 | 414.058 s |
| [Linux Python 3.12](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43028707145/job/130549873123) | 4,603 | 4,525 | 78 | 0 | 387.318 s |

All ten new synchronous recovery methods and all seven existing asynchronous recovery methods ran and passed on **both** systems. These methods are included in the full-suite totals above; the focused runs are not additional unique tests or improvement IDs.

Windows also passed the application self-test, bundle build/validation, and packaged GUI/native drag-and-drop checks. Both systems passed source-package hygiene, the 56-test exact-raster/portable-planner selection and Extra Fast benchmark smoke; both dependency audits and the Python/Actions CodeQL checks succeeded.

The Windows skips were the CUDA/CuPy and two OpenCL device checks. This run does not establish physical Paint drawing, manual visual/DPI review or actual GPU execution. No merge, tag or release was performed.
<!-- /recovery35-ci-status -->

## Review and evidence

- [Isolated code/test/documentation patch](https://github.com/Vxiey/Image-Draw-Bot/commit/b22df12d9e17807edc43de7dabf29a113c81edc5)
- [Scope, executed commands and limits](https://github.com/Vxiey/Image-Draw-Bot/blob/b22df12d9e17807edc43de7dabf29a113c81edc5/docs/v148-batch35-recovery-storage.md)
- [Machine-readable execution evidence and source hashes](https://github.com/Vxiey/Image-Draw-Bot/blob/b22df12d9e17807edc43de7dabf29a113c81edc5/docs/v148-batch35-recovery-validation.json)
- [Improvement ledger](https://github.com/Vxiey/Image-Draw-Bot/blob/b22df12d9e17807edc43de7dabf29a113c81edc5/docs/IMPROVEMENTS-v1.0.148.md)
- [Unchanged 843-entry registry](https://github.com/Vxiey/Image-Draw-Bot/blob/b22df12d9e17807edc43de7dabf29a113c81edc5/docs/v148-improvements.json)

## Earlier verified checkpoints

The complete prior PR description is preserved verbatim in [the history through batch 34](https://github.com/Vxiey/Image-Draw-Bot/blob/b22df12d9e17807edc43de7dabf29a113c81edc5/docs/pr46-history-through-batch34.md), including all previous checkpoint counts, measurements, limits and CI failures/corrections. This keeps the live description below GitHub's body-size limit without discarding the evidence.

The immediate parent `66948b3` passed all seven checks in [CI 43021957536](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43021957536): Windows 4,593 tests (4,590 passed, three GPU skips), Linux 4,593 (4,515 passed, 78 skips), plus Windows self-test, bundle validation and packaged GUI/native drag-and-drop. Those are historical parent results.

## Remaining release conditions

The target remains **1,000 distinct improvements**. The planned final verification and release are still pending. These local runs do not establish native Windows visual/DPI review, physical Paint drawing or GPU execution. The PR stays draft until the work is complete and the user explicitly approves merge/release.
