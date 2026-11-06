# v1.0.148 application workflow — batch 07

Baseline: `8a9c848b9dd0f2c4738aee729dace75be2a5778d`; the follow-up Windows UI repairs through `ace8fd741b363ab9f7a01ccd1fad94231a70a1f4` add no count and passed complete Windows/Linux, CodeQL, dependency and packaged Windows checks.
This reviewed application batch contains **three distinct improvements**.

| ID | Reproduced problem | Implemented behavior and evidence |
| --- | --- | --- |
| AY01 | Importing a real unsigned 16-bit grayscale PNG containing values `0, 257, 32768, 65535` produced 8-bit gray values `0, 255, 255, 255`. The direct Pillow conversion clipped most of the tonal range. | `SourcePixelDepth.grayscale_8bit` maps the fixed unsigned range to `0, 1, 128, 255` using nearest rounding. File and borrowed bitmap-clipboard input pass through this conversion after EXIF orientation and before any ICC transform. Transparency keys are compared at their original precision, so adjacent values that become the same 8-bit tone retain different opacity. The source label identifies the conversion. Tests read real PNG and both-endian TIFF files, compare all 65,536 input values against an independent rounding oracle, exercise a real transparent PNG with and without a valid gray ICC profile, orientation, the actual clipboard handler, ownership and cancellation. |
| AY02 | Recording durations were first rounded to integer milliseconds and then independently truncated to GIF's 10 ms units. One hundred changing frames captured for 259 ms each encoded as 25,000 ms rather than 25,900 ms. | Retain fractional capture milliseconds until encoding; quantize cumulative frame boundaries to the GIF clock. Every boundary stays within 5 ms of the recorded timeline instead of accumulating truncation loss. Decode real GIFs to verify exact frame colors, variable durations, half-tick boundaries and identical-frame merging. An actual `record_screen` worker with a controlled capture clock retains a 25,949 ms recording as 25,950 ms. Timing validation occurs before staging and preserves an existing file on invalid input. |
| AY03 | The recorder retained every quantized frame until the final GIF encoder, even when adjacent captures were identical and Pillow would later merge them. A static 100-frame 800×500 recording retained 40,000,000 bytes of paletted pixel payload. | Coalesce exact adjacent captures during recording, summing their raw durations and releasing duplicate owned images immediately. Compare dimensions, mode, RGBA palette, transparency and pixel indexes; an identical index with another palette cannot merge. The static fixture retains one frame/400,000 pixel bytes. Changing footage still retains every distinct frame. Actual-worker tests verify early duplicate release, failure cleanup and the final decoded visible timeline. |

## Scope and limits

The conversion covers Pillow's unsigned `I;16`, `I;16L`, `I;16B` and `I;16N`
modes. It uses the format's complete range rather than stretching each image's
minimum and maximum, so equal source values retain equal brightness across
files. Existing 8-bit inputs remain byte-identical. This does not introduce
normalization of signed integer, floating-point or multichannel scientific
formats.

Temporary numeric work is tiled in both dimensions, at most 1,024 pixels wide
and 262,144 pixels per tile. The required final output and caller-owned source
remain full-sized. Cancellation is checked before allocation, between tiles
and before returning. Owned partial images close on failure; borrowed input
remains open and unchanged. File-provided conversion markers are discarded
before the application sets its own provenance label.

The independent review covered quantization, endianness, original-precision
transparency, ICC ordering, file and clipboard callers, metadata ownership and
the bounded cancellation path. **Eight new tests plus eight previous ICC tests
passed**, with no blocking review finding. The final local frozen-source gate is recorded below; Windows
integration on this new checkpoint remains pending.

## Existing contracts completed, no additional count

- **AX06/IW08:** the untagged final RGBA conversion now checks cancellation
  after Pillow returns and closes that owned output when Stop arrived during
  the native conversion.
- **AX04/MP02 integration:** mobile publication uses the desktop's shared view
  selection. Nine real UI-callback regressions cover coalescing, Manual plan
  invalidation, Undo, accepted file load, layer selection, stop/restart,
  shutdown/session replacement and capture retry. These belong to the two
  mobile groups in the platform ledger and add no application ID here.
- **RP28/admission integration:** final application estimates charge retained
  custom-color selections, including progressive phase resets and executed
  fill selections. Empty retained plans do not pay for unused source groups.
  Visual checks follow the ordinary-batch/Detail Zoom execution branch instead
  of charging progressive passes that skip them. This is included with the
  rendering admission group and its regression evidence.
- **AW15/UI22 integration:** pending profile transactions block worker/modal
  startup; queued identity and active profile remain consistent on rejected
  work. Profile creation rechecks the modal boundary. Readonly comboboxes allow
  image paste while editable controls retain native text paste. The new
  same-profile no-op is counted once in the UI ledger, with forced profile
  reload retained for Import/Reset.

Relevant format documentation: [Pillow image modes and transparency](https://pillow.readthedocs.io/en/stable/handbook/concepts.html).

```text
python -m unittest test_v148_application_batch07_depth test_v148_application_batch06_color_import
python -m unittest test_v148_application_batch07_mobile test_v148_platform_batch07_mobile_queue test_v148_platform_batch07_mobile_snapshots
```

The second command currently passes **29 tests**. These are local file,
in-memory publication and UI-callback checks. They do not establish a new
antivirus verdict, code signing or physical-device drawing performance.

## Recording evidence and performance limits

`test_v148_application_batch07_recording.py` and
`test_v148_application_batch07_recording_frames.py` contain nine new tests.
Together with the existing recording publication/ownership and Stop/status
tests, **17 tests pass**. Atomic replacement and owned-image cleanup extend
UI31/UI32; they are not additional IDs. AY02 concerns the recording clock,
and AY03 concerns storage retained during capture.

The [Pillow GIF writer](https://pillow.readthedocs.io/en/stable/_modules/PIL/GifImagePlugin.html)
converts a supplied duration to integer centiseconds. The application now
performs cumulative rounding before that conversion. Real GIF readers still
choose their own playback scheduling; these tests verify encoded times, not
browser animation timing.

Run `python benchmark_v148_recording.py` for the paired actual-worker benchmark.
Raw samples and source fingerprints are in
`docs/v148-batch07-recording-benchmarks.json`. It uses exact baseline `8a9c848b`,
one warmup pair and three alternating pairs per case, with 100 deterministic
800×500 captures and a controlled 259.49 ms capture interval. It uses no screen
capture or native input. The timed region is the real recording worker,
including quantization, comparison, GIF encoding and atomic publication.
Decoding and pixel verification occur outside the timed interval.

| Recording | Retained frames, baseline → current | Retained paletted pixel payload, baseline → current | Median complete worker time, baseline → current | Encoded duration, baseline → current |
| --- | ---: | ---: | ---: | ---: |
| Unchanged captures | 100 → **1** | 40,000,000 → **400,000 bytes** | 1.706 → **1.734 s** | 25,900 → **25,950 ms** |
| Every capture changes | 100 → **100** | 40,000,000 → **40,000,000 bytes** | 1.952 → **1.931 s** | 25,000 → **25,950 ms** |

Every pair has identical decoded frame pixels/order and the same decoded frame
count. Duration changes are intentional: the captured interval totals
25,949 ms. The old still-image case lost less time because Pillow merged its
frames before GIF quantization. The current result is within one millisecond
of that controlled timeline in both cases.

The retained-byte figure is the P-mode pixel payload (`width × height`), not
measured process RSS or a native-memory ceiling. Palette/core allocation
overhead, captured RGB images, comparison buffers, encoder scratch and Python
objects are additional. Comparison work is bounded by one thumbnail pair;
retention savings depend on adjacent captures being exactly equal. The static
worker was slightly **slower** in this measurement, and changing footage had
no retention reduction. No general recording-speed improvement is claimed.

## Final local integration gate

The frozen source passed **3,355 tests in 71.096 seconds**, with **35 platform/hardware skips** and no failures. Source hashes were unchanged during the run. All independent area reviews are closed. The 5,000-cycle source gate, source-package hygiene and all eight exact-raster fixtures passed, with zero mismatched pixels. Windows/Linux CI on this new checkpoint remains pending; version 1.0.148 is not published.
