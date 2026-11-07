# Batch 26: complete shared GIF publication

Integration baseline: `5b0c22ac5dc620a911fa2a1f6216e272f644f7db`, with
837 published improvement groups. This completes the existing recording
publication contract **UI31 / global 252** using the existing shared storage
policy (**SS01 / global 181**, **SS02 / global 182**). It adds **zero IDs**.
Recording timing and adjacent-frame retention remain AY02/AY03; neither is
counted again.

The final coordinated freeze is based on
`a3b7b929b1332772a089e1819143471ae5d58c68`, whose intervening changes affect an
existing worker-poll test fixture and documentation only. The targeted gates
below ran on the preceding `5b0c22a`-based integration. The final full-suite
gate is reported separately by the root maintainer.

## Actual failure and correction

The user-triggered `DrawBot.record_screen` worker called
`ScreenRecording.save_gif_atomic`, which had its own unique temporary file,
unconditional `fsync` and single `Path.replace`. A temporary Windows sharing
failure or an explicitly unsupported sync operation therefore reported a
failed recording after capture had already ended. The previous destination
was preserved, but the newly captured recording was not published.

Four new actual-flow test methods produced **five expected assertion failures**
before the change: Windows sharing codes 32 and 33, plus unsupported sync
errors EINVAL, ENOSYS and ENOTSUP. The other two methods' permanent-failure and
input-ownership controls already passed. The before run had no test errors
and took 0.336 seconds; its log is `batch26-gif-publication-before.log`.

`save_gif_atomic` now delegates only staging, flushing, replacement and cleanup
to `RuntimePaths.atomic_binary_writer`. GIF encoding arguments, duration
validation and quantization, destination normalization, `None` return and
caller ownership of input frames are unchanged. The shared helper retries
only its existing Windows transient error classes with a bounded delay and
keeps the original destination on permanent failures. It tolerates only the
existing explicitly unsupported sync codes; a real I/O failure still fails.

**Recording Stop still means finish and save.** The recorder does not pass its
Stop event into the writer's cancellation callback. This preserves the existing
final captured frame, successful terminal status and actual worker completion
after the user stops recording. Other export cancellation policies are not
changed.

## Verification method

`test_v148_platform_batch26_gif_publication.py` uses the real controller,
`begin_worker`, background `Thread`, private application Stop handling, event
handler, recorder, quantizer, GIF encoder and filesystem publication. The
fixture joins the worker and drains its actual event queue, rather than
depending on a single timed poll slice. Existing fixture cleanup releases
its Tcl variables on their creating thread after all workers finish.

Only the save dialog, desktop capture, wait/clock and native storage-failure
boundaries are replaced. Capture generates three owned red/blue/green images;
the third capture invokes the actual Stop method. The successful output is
both byte-identical to an independently encoded real reference GIF and equal
after decoding all frame pixels and durations (260 + 260 + 260 ms). Sharing
retries reuse one staged file and perform one encode.

Permanent partial-encode, flush and publication failures retain the previous
complete GIF. All raw and quantized worker-owned images are closed, staging
is removed, unrelated user temporary files survive and no saved-success event
is emitted. The direct writer control verifies caller-owned input remains
readable, a secondary cleanup failure does not replace the primary error,
and successful publication still returns `None`.

The first after run passed **4/4 methods in 0.320 seconds**, with no skips.
After adding an explicit one-encode assertion, the final related gate passed
**63 methods: 62 passed and one existing native Windows skip, in 1.623
seconds**. It includes all four new methods, both original GIF timeline/frame
modules, original recording failure tests, capture/export ownership, the
shared publication policy and the incoming worker-handoff regressions.
The log is `batch26-gif-publication-related.log`.

One older fault-injection string in `test_v148_ui_runtime.py` was updated by
the root maintainer from `ScreenRecording.os.fsync` to the writer's actual
`RuntimePaths.os.fsync` boundary. Every original assertion and case remains
unchanged. This test compatibility adjustment adds no ID.

The root and an independent engine reviewer closed source/method review
without blockers. Both checked the actual worker/Stop/event chain, unchanged
duration and encoder arguments, one encode, input/image ownership and
publication failure assertions. The independent reviewer did not run an
additional overlapping test selection; the execution results above are the
recorded author gate.

No performance timing, native GPU or real Windows sharing measurement is
claimed; Windows error codes are injected at the actual OS replacement
boundary on Linux. Whole-project and native Windows acceptance belong to the
final batch gate.
