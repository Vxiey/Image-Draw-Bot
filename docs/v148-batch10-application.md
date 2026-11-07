# v1.0.148 batch10 — prepare recovery images outside the UI callback

Baseline: `3c5fe8fc27ec3b503e2affa6f3ed00cb7856f973` (765 published
improvements). This area contributes **one distinct behavior group, A1001**.
Thread ownership, coalescing, publication identity, clear/shutdown and the
review-driven cancellation corrections are one complete autosave workflow.

## A1001 — asynchronous recovery PNG preparation

The real recovery timer called `SessionRecovery.save_snapshot` directly from
Tk. With an image checkpoint, that callback encoded a full PNG, flushed it to
disk, calculated its SHA-256 and published its state before returning. A
deterministic 2048×1536 RGBA source reproduced PNG preparation on `MainThread`,
with three preliminary callback durations of 1.211, 1.020 and 0.983 seconds.
Those are baseline reproduction samples, not a before/after speed claim.

The timer now enters `_queue_recovery_checkpoint`. When a new image is needed,
the UI captures one private source copy and `RecoveryImageJob` performs PNG
encoding, image-file flush/fsync and digest calculation on its encoder thread.
The worker does not read Tk, change the current image or publish a checkpoint.
Its private staging directory is outside ordinary final-image pruning.

The UI result consumer publishes the prepared PNG only if that exact job and
source identity are still current and recovery has not been suppressed or the
application closed. Primitive settings and subject selection are captured on
the UI thread at publication, so edits made while the image was encoding are
attached to the same accepted raster. The existing snapshot guard, content
digest and atomic state replacement retain the image/selection relationship.
A failed state publication preserves the previous checkpoint and source
reference. A later checkpoint can retry normally.

Only one private image copy/encoder is active. Later requests retain a pending
flag rather than more pixel copies or unbounded jobs. A replaced source
cancels obsolete preparation; completion starts preparation for the latest
source if still needed. Selection-only saves reuse the successfully cached
image. A late image publication does not erase render progress from a new draw
that started after the original image-adoption reset.

Explicit recovery clearing cancels preparation and, when it is still active,
waits in a tracked worker. Clear Drawing and application shutdown poll for
encoder cleanup without blocking Tk. Ready, superseded, cancelled and late
results close their private resources and cannot recreate cleared state.
Explicit clearing also removes an abandoned job's known PNG and empty private
directory after a crash; it refuses to recursively delete unexpected contents.

Independent review found two related clear-request completion gaps: a failed
thread start, and Stop before the tracked worker entered its task, could leave
autosave suppression permanently enabled. The startup rollback and matching
`done` path now restore the previous suppression when no successful clear was
reported. Both previously failing actual-worker regressions pass. They add no
new improvement IDs.

## Validation

`test_v148_application_batch10_recovery.py` contains ten regressions through
the actual timer, queue, owned PNG preparation and event consumer. They cover
thread boundaries, current settings, exact recovered pixels, twelve coalesced
source replacements, failed publication/retry, a cancelled ready result,
expired weak identities, new render-progress preservation, reused cached
images, thread-start failure and owned conversion/cleanup failures.

`test_v148_application_batch10_recovery_lifecycle.py` contains eight independent
reviewer-written cases with actual encoder and tracked clear threads, real
snapshot/resume files and event-controlled scheduling. UI callbacks continue
while the encoder is deliberately blocked. Stop, clearing failure and both
startup/cancellation boundaries preserve the previous usable resume; explicit
clear and shutdown wait for cleanup and cannot accept a late result.

All **18 new cases passed in 0.141 seconds** in root's combined run. The
reviewer independently repeated all eight lifecycle cases and closed the
source/order review. The existing recovery/subject-integrity suites passed
together with the new build-session suite: 46 tests in 1.724 seconds. The
old timer fixture now expects the asynchronous dispatch method and retains
its unrelated-timer/coalescing assertions. These are overlapping selections,
not additional unique test or improvement counts.

The explicit `closing()` corrections for owned RGBA conversion in the new
preparer and the synchronous compatibility path complete the existing IW08
image-resource contract at zero additional count.

## Performance and limits

The final frozen-source measurement is reproducible with
[`benchmark_v148_recovery_preparation.py`](../benchmark_v148_recovery_preparation.py).
The [raw paired results](v148-batch10-recovery-benchmarks.json) contain five
alternating baseline/candidate pairs, without warmup pairs, on Linux with
Python 3.12.14, Pillow 13.0.0 and NumPy 2.5.4. The source is an opaque
2048×1536 RGBA raster generated with seed 1001. Both variants use the same
current `SessionRecovery` implementation and a fresh temporary directory.
Only the two historical timer/save controller methods are compiled from
`3c5fe8fc27ec3b503e2affa6f3ed00cb7856f973`; their source file must match the
pinned SHA-256 before measurement. Current method/helper fingerprints are
recorded and remained unchanged throughout the run.

| Measured phase, median of five trials | Historical timer | Prepared-image timer |
| --- | ---: | ---: |
| UI timer dispatch, including any source copy | 841.214 ms | 3.484 ms |
| Separate UI final publication | Included in dispatch | 0.946 ms |
| Combined UI occupancy per trial | 841.214 ms | 4.384 ms |
| Total completion wall time, without Tk polling delay | 841.214 ms | 962.889 ms |

Combined UI occupancy is the median of each trial's dispatch plus publication,
not the sum of the two separate phase medians. The configured 40 ms timer wait
is excluded. The candidate waits for its actual encoder result and delivers
the real `recovery_image_prepared` event immediately for measurement; this
benchmark-only wait is not performed by the production UI. Source generation,
PNG decoding/output verification and final temporary-directory deletion are
outside the timed intervals. Identical lightweight PNG/copy observers and a
no-op diagnostic logger are applied to both variants.

The UI work is much shorter in this workload, while the candidate's median
total completion is approximately 14.5% higher. Individual paired total times
include both improvements and regressions; this measurement does not establish
a CPU-throughput or general end-to-end speedup. Historical completion times
ranged from 805.101 to 1000.023 ms and candidate times from 821.836 to
1084.028 ms. Filesystem and machine scheduling are part of these wall times.

Every trial produced the same 10,913,971-byte PNG with SHA-256
`3868bb6a631bed0b90104c4c82a77c043982a3fe05e672bfd2b4ec73e62a6a78`.
Decoded pixels, subject selection and checkpoint state excluding the creation
timestamp were identical; the borrowed source remained unchanged. PNG encoding
was observed on `MainThread` historically and `recovery-image-encoder` in every
candidate trial, while configuration reads stayed on `MainThread`. Each
candidate created and closed one private source snapshot: **12,582,912 bytes
(12 MiB) of additional RGBA pixel payload** for this raster. This figure is
not RSS and excludes the shared source, Python/native allocator overhead,
encoder/hash buffers and other temporary objects. Repeated-request coalescing
is validated by the separate lifecycle tests, not inferred from these serial
measurement trials.

- The source copy itself remains on Tk. One RGBA snapshot adds four bytes per
  pixel of image payload, bounded by the existing 40-million-pixel recovery
  limit. This is not a process-RSS or total native-allocation measurement.
- Final image rename, state JSON publication/fsync and normal metadata-only
  checkpoints remain on the UI thread. Legacy cache migration may still copy
  and hash an existing PNG there. This change does not claim all recovery I/O
  is asynchronous or that filesystem operations have a wall-clock bound.
- Cancellation is cooperative around PNG writes, hashing and operation
  boundaries. A native encoder or OS call already executing must return.
- The synchronous `save_snapshot(image=...)` compatibility API remains
  supported. The actual application timer uses the new preparation pipeline.
- No source image is uploaded, added to diagnostics or used to restore native
  input authorization. Existing recovery remains Manual and disarmed.

Whole-program frozen validation and the new checkpoint's native CI remain
separate gates. No release, new antivirus verdict or signing status is claimed.

## Frozen checkpoint validation

Batch 10: final frozen-source discovery passed 3,579 tests in 125.869 seconds (43 platform/hardware skips), with unchanged Python and batch-script hashes. All four area source reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. Paired rendering and recovery measurements bind the final source snapshot and disclose unchanged or slower total-work results. This checkpoint still requires its own Windows/Linux, dependency, CodeQL and packaged Windows checks. No 1.0.148 release is published.
