# Batch 25 — bounded native screen sampling and click ownership

Original reproduction baseline: `bb6dfa6a5e8a43bfcfc77c9e00f52dc2dfd7db9c`, with 828 recorded
improvements. N2501 is one new sampling behavior group. The click changes
complete the existing NR02 input-transaction contract and add zero IDs.

## N2501 — read a compact screen sample with one bounded transfer

`Colors.sample_screen_colors` previously acquired one desktop device context
but called Windows `GetPixel` separately for every requested pixel. The actual
one-pixel stroke verifier samples five 5 × 5 neighborhoods, making 125 native
pixel reads for one settling attempt. Wider brushes can require five 13 × 13
neighborhoods, or 845 reads. These are real sampler call counts, not a measured
drawing-time estimate.

The existing public entry point now delegates to `ScreenPixelSampling`.
Requests with at least 16 and at most 2,048 points can use a compact top-down
32-bit DIB readback. One `BitBlt` copies the bounded rectangle, and `GdiFlush`
completes the native writes before Python reads its BGR bytes as ordered RGB
triples. Duplicate points retain their positions in the result.

The rectangle is limited to 65,536 pixels (256 KiB of native pixel storage)
and at most 64 pixels of rectangle area per requested point. It must fit
entirely within one physical monitor. Negative monitor coordinates are valid;
monitor gaps, spanning requests, small/sparse requests and large iterables use
the original scalar `GetPixel` operation. In particular, a point outside a
readable monitor cannot turn into a plausible black sample from an unfilled
portion of a bitmap.

The native function signatures are private per invocation. Handle types retain
their full pointer width; Win32 coordinate/bitmap fields use explicit 32-bit
types on every host. The DC, selected bitmap and direct byte view belong only
to the current operation. Cleanup restores the selection, destroys the private
memory DC, deletes its bitmap and releases the borrowed desktop DC. A retained
exception does not retain a view of freed native bytes. There is no global
capture cache and no screenshot or pixel file is written.

An unsupported transfer, optional memory-DC/bitmap acquisition failure or
optional allocation failure falls back to the scalar reader after cleanup.
Failure to acquire the initial desktop DC still raises the existing read error.
The bounded prefix
retains a just-consumed point if its append fails. Each yielded point is
unpacked and converted before the iterator advances, so a producer that
reuses one mutable coordinate pair still supplies distinct observations.
Requests above the prefix limit continue from their untouched iterator tail;
the implementation does not copy an unbounded point stream.

The new path observes a compact area at one transfer instant. Pixel equality
with sequential reads is asserted for stable content; an animating desktop
can naturally change between any two observations. The existing target/focus
guards, sampling neighborhoods, matching thresholds, settling delays and
decision logic are unchanged.

### Reproduction and verification

Two public regressions execute the unchanged baseline reader extracted from
the exact baseline `Colors.py` function. They fail only after confirming the
same ordered RGB values or the same actual verifier verdict:

| Workload | Baseline native reads | New native reads |
| --- | ---: | ---: |
| 169-point patch with two duplicate requests | 171 `GetPixel` calls | One `BitBlt` plus flush |
| Actual `GuardedMouse` → `WindowMonitor.colors_near`, one-pixel stroke | 125 `GetPixel` calls | Five bounded `BitBlt` transfers plus flushes |

The consumer retains a 125-sample result, matching RGB, zero error and 100%
confidence in the controlled native-boundary fixture. The DLL functions alone
are replaced: public sampler, buffer addressing, monitor selection, cleanup,
guarded consumer and verdict logic execute normally. The boundary uses numeric
memory; no generated image or new image asset is involved. Baseline record:
`batch24-native-consumer-before.log` in the parent working directory.

The regression module also checks every intermediate native-acquisition
failure, desktop acquisition failure, scalar unreadable-point behavior,
optional buffer/prefix/conversion allocation failure, duplicate order, a
mutable one-shot iterator both below and above the prefix cap, and native
structure sizes. Review caught the prefix-allocation and mutable-iterator
issues in the first implementation; both are corrected without extra IDs.

The final related local selection completed **67 tests in 0.874 seconds:
66 passed and one native Windows case skipped**. Record:
`batch24-native-all-after.log`. Both independent reviewers approved the final
sampler; the final module has 13 methods, with 12 passing locally and one
explicit Windows skip. Test-run durations are not performance measurements.

The Windows-only subprocess loads the existing application icon into a real
Tk window. It compares actual native results with the exact preceding scalar
reader, verifies that twelve repeated DIB reads retain no GDI resources, and
records six opposite-order timing pairs for 8, 25, 81 and 169 points. The 8-point
case remains a scalar control. These native results are a separate exact-commit
CI gate; no Windows speed or resource result is claimed from the portable run.

This is distinct from N2201's numeric search across an already captured Paint
color spectrum and CAL69's slider scoring. It reduces native screen-reading
operations before the unchanged stroke/palette decision, with a separately
bounded memory cost. It does not establish a physical Paint drawing speedup
or a reduction in every request's peak allocation.

### Native API references

- [GetPixel return and clipping contract](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-getpixel).
- [CreateDIBSection storage, direct-byte synchronization and deletion](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createdibsection).
- [BitBlt transfer and color-format behavior](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-bitblt).
- [MonitorFromPoint](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-monitorfrompoint)
  and [MONITORINFO physical monitor rectangles](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-monitorinfo).

## NR02 completion — one click retains its own release

Arm, disarm, move, press and release already used the same per-instance
reentrant lock. A complete click did not: its pause allowed another thread to
disarm, rearm and press a new drag. The old click's `finally` could then release
the new drag. Two overlapping clicks could also mistake each other's held
button for a physical user button and abort.

`WindowsMouse.click` now keeps its press/pause/release within the same native
transaction. The backend exposes that existing lock through `input_transaction`
so both normal and calibrated-modal `GuardedMouse` clicks retain the same
ownership. The native 20 ms pause and guarded 15 ms pause remain unchanged;
injected backends without that optional transaction retain their established
press/release interface.

The three test methods exercise real production methods and coordinated
threads at the native-send/pause boundary. Both concurrency scenarios cover
all three click routes. Failed `LEFTUP` retains held-button ownership, revokes
input authorization, releases the transaction lock and permits a later cleanup
retry. The initial native implementation failed two methods; after fixing it
alone, expanded normal/modal consumer cases still failed four subcases. The
final combined native selection above passes, and an independent reviewer
also passed the three methods in 0.607 seconds. No physical input is sent by
these regressions. This closes the already-counted NR02 contract.

## Merged-source integration

The changes are integrated onto `586e12db5ea5142951c844f60dc2364f07a01c37`,
which preserves the concurrent manual-palette worker and component-queue work.
Those changes do not overlap these production modules. The combined platform
and native gate passed **36 tests in 4.606 s: 35 passed and one Windows desktop
sampling case skipped**. Physical desktop sampling is verified separately by
the published-commit Windows gate. Full merged-source evidence is in
[v148-batch25-validation.json](v148-batch25-validation.json).
