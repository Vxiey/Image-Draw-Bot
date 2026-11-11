# v1.0.148 — preserve synchronous recovery storage failures

## Scope and counting

Baseline: `66948b321a3d7a17d984c0db2304e59205ea6cc0` on the draft
`improve/v1.0.148` branch. This continues the owned-resource review in the
synchronous `SessionRecovery.save_snapshot` storage path.

**Zero new improvement IDs: 843/1,000 implemented; 157 remain.** The correction
completes **IW08/global582** and the existing **056/global56** recovery-storage
contract. The [batch10 ledger](v148-batch10-application.md) already classifies
synchronous RGBA cleanup as an uncounted IW08 completion. Tests, helper
extraction and documentation do not add IDs. The machine registry is unchanged.

## Reproduced problem and correction

An error while closing an owned RGBA conversion or file stream could replace
the original encoding, reading or size-validation failure. The final staging
`unlink()` could replace that error again. Six focused baseline methods
reproduced these error-priority failures through the public `save_snapshot` API.
The previous checkpoint's bytes remained intact in those reproductions;
this patch does not claim that the observed defect caused checkpoint loss.

A local `_closing_preserving` context manager now owns the converted image,
temporary writer, legacy reader and digest reader. On a body failure it attempts
close, attaches any secondary close error as a diagnostic note, and re-raises
the original exception object and traceback. On success it performs ordinary
close, allowing a standalone close error to propagate.

`_store_image` retains the primary failure separately for its final staging
cleanup. A secondary unlink `OSError` adds a note; a standalone unlink error
still propagates. The temporary file retains `delete=False`, with explicit
unlink ownership. File handles close before digest/rename, including on Windows.
PNG options, limits, flush/fsync, content addressing, snapshot locking, state
publication and legacy file formats retain their existing behavior.

## Executed local verification

Linux, Python 3.12.14, Pillow 13.0.0. The same frozen test file ran before and
after the product change, with recorded source hashes unchanged during each run.

| Selection | Actual result |
| --- | --- |
| Ten new methods on the baseline | 4 passed, 6 expected assertion failures; 0 errors/skips |
| Same ten methods after the patch | **10 passed**, 0 failures/errors/skips |
| Nine existing adjacent methods | **9 passed**, 0 failures/errors/skips |

The six baseline failures cover converted-image close, writer close, legacy
reader close, digest-reader close after the actual byte limit, staging unlink,
and a chain of three secondary cleanup failures. Checks retain the primary
exception and traceback, verify diagnostics and resource release, and compare
the previous state, image and render-progress bytes.

Controls cover standalone failures at all four close boundaries, standalone
unlink failure after successful image rename, successful RGB/RGBA storage,
legacy migration with/without prior state, unchanged borrowed pixels, real
PNG decoding and SHA-256. When unlink is deliberately denied, the test observes
the remaining staging file and verifies that a later successful save prunes
that exact file through the existing production cleanup.

Every raster comes from existing repository assets: the old checkpoint uses
`assets/image-draw-bot-icon.png` and the replacement uses
`assets/paint-tools-reference.png`. Their different image content makes the
previous-checkpoint checks meaningful. The encoder, readers, temporary files,
snapshot publisher and retry/pruning are real implementations. Fault injection
is limited to I/O and cleanup boundaries; neither `_store_image` nor
`save_snapshot` is replaced. No synthetic test motif is introduced.

The adjacent selection is the seven existing asynchronous batch34 methods plus
two image-free checkpoint preference/render-progress tests. Exact commands,
counts, source/log hashes and timings are in the
[validation record](v148-batch35-recovery-validation.json).

```bash
python -m unittest -v test_v148_application_batch35_recovery_storage
```

An initial fixture check corrected an expectation to use RenderResume's
actually persisted, normalized progress fields. That check is separate from
the frozen before/after pair and is not counted as product-defect evidence.

Independent source/test review found no blocker. Source-package hygiene passed
for **1,385 files**, with no forbidden/missing paths or warnings.
`git diff --check` passed.

## Limits and review history

- This API has no cancellation callback. The chained-error test injects an
  `InterruptedError` object; it does not establish cooperative Stop support.
- Close failures are injected after real close. The tests do not prove that
  native cleanup that itself fails before releasing a resource can always be
  recovered. An OS-denied unlink can leave staging for a later cleanup attempt.
- No full local discovery, native Windows/Paint interaction, physical drawing,
  GPU execution or release was performed in these local runs. Exact-head CI
  results are recorded separately in [PR #46](https://github.com/Vxiey/Image-Draw-Bot/pull/46).
- The previous PR description had reached 65,366 characters. Its complete text
  is preserved in [the checkpoint history](pr46-history-through-batch34.md),
  allowing the live PR to present the current patch and verification clearly.
- The PR remains draft. Merge and release require the user's explicit approval.
