# v1.0.148 — preserve the primary recovery PNG failure

## Scope and counting

Baseline: `b41af0d5e947f451232ec46ee5189dd8f7da0679` on
`improve/v1.0.148`. The profile-export lifecycle and UI corrections from the
preceding continuations remain in place.

**Zero new improvement IDs: 843/1,000 implemented; 157 remain.** This completes
the owned-image contract **IW08/global582** within asynchronous recovery
preparation **A1001/global766**. The [batch10 ledger](v148-batch10-application.md)
already assigns owned RGBA-conversion cleanup to IW08 without an additional
count. The machine registry is byte-for-byte unchanged.

## Reproduced problem and correction

`RecoveryImagePreparation.prepare_image` used `contextlib.closing` for the
private RGBA conversion of a non-RGBA source. If PNG encoding failed or observed
Stop, and the converted image's `close()` also raised, the secondary close error
replaced the primary error. The original error survived only in the exception
context. A real cancelled `RecoveryImageJob` could consequently deliver an
`OSError` instead of `InterruptedError`; the controller would classify that as
a preparation failure rather than cancellation.

The conversion now has explicit success and failure cleanup paths. On an
encoding failure, the existing `_close_preserving` helper attempts the close,
adds a note identifying any secondary cleanup error, and a bare `raise` retains
the primary exception object and traceback. After successful encoding, a
standalone close failure still propagates and discards the staged PNG.

The change is limited to this owned conversion. PNG settings, pixel and byte
limits, cancellation checks, flush/fsync, hashing, worker notifications,
publication identity and the borrowed source's lifetime are unchanged.
No data loss, stale publication or hanging worker was established for the
reproduced defect; the demonstrated correction is error priority and cancellation
classification.

## Verification actually executed

Linux, Python 3.12.14, Pillow 13.0.0. The same unchanged test file was run before
and after the production correction. Source and fixture hashes were checked
around each execution.

| Selection | Before | After |
| --- | --- | --- |
| Seven focused recovery methods | 3 passed, 4 assertion failures; 0 errors/skips | **7 passed**, 0 failures/errors/skips |
| 21 existing adjacent methods | Not rerun on the baseline | **21 passed**, 0 failures/errors/skips |

The four failing baseline methods reproduce Stop, a primary write error, the
actual byte limit, and cancellation of a real encoder thread, each combined
with a failure when closing its owned conversion. They assert exception identity
while retaining the traceback, the cleanup note, one close attempt, usable
unchanged source pixels and removed staging. The worker case additionally
checks a bounded join, idle state, exactly one notification, one-time result
consumption and closed snapshot ownership.

Positive controls retain standalone-close failure behavior and successful RGB
and RGBA preparation, with actual PNG decoding, exact pixels, SHA-256 and
explicit result cleanup. The primary write-error case also performs a successful
retry after the injected faults are removed.

All focused pixel data comes from the existing
`assets/paint-tools-reference.png`. The test converts that existing raster to
RGB in memory where needed. The PNG encoder, temporary files, cancellation
checks and worker are real production code; failures are injected only at the
write and owned-close boundaries. No synthetic test motif, generated artwork,
replacement preparer or UI mockup is introduced.

The adjacent selection exercises image-free recovery timer/coalescing, hashing
cancellation, explicit clear and failure retention, disarming, safe checkpoint
preferences and render-progress publication, plus all 12 existing profile-export
lifecycle methods. Exact selections, timings, results and log/source hashes are
in [the validation record](v148-batch34-recovery-validation.json).

Focused command:

```bash
python -m unittest -v test_v148_application_batch34_recovery_cleanup
```

Independent source/test review found no blocker. Source-package hygiene passed
for **1,381 files**, with no missing/forbidden paths or warnings.
`git diff --check` also passed.

## Limits and remaining work

This patch does not change the synchronous compatibility encoder in
`SessionRecovery._store_image`, whose converted-image `closing()` has the same
potential error-priority gap. It also does not establish a general guarantee
against failures in outer file-stream or directory cleanup. Those boundaries
remain separate follow-up work.

No full local test discovery, native Windows visual/Paint interaction, physical
drawing, GPU execution or release was performed as part of these local runs.
The existing Windows/Linux CI workflow validates the new commit separately;
its exact-head results are recorded in [PR #46](https://github.com/Vxiey/Image-Draw-Bot/pull/46).
The successful parent checks are historical evidence, not a substitute for the
new commit's checks. The PR remains a draft; merge and release require explicit
user approval.
