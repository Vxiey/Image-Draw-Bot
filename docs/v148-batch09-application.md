# v1.0.148 batch09 — clipboard preparation outside the UI thread

Baseline: `ab2a59bd1432aac7528d378cef2c4ebcf689a47b` (759 published
improvements). This ledger currently contributes **one new behavior group,
BA01**. Its ownership, cancellation and event-order fixes are one complete
clipboard workflow, not separate counted improvements.

## BA01 — tracked clipboard bitmap preparation

The public Paste command previously performed EXIF orientation, unsigned
16-bit conversion, ICC color management and RGBA normalization synchronously
on the GUI thread. These operations could allocate and transform a bitmap of
up to 25 megapixels before returning control to the interface.

The OS clipboard acquisition remains on the GUI thread. A bitmap returned by
that call is now held as a borrowed snapshot and prepared by the application's
tracked `load` worker. `ClipboardImport.prepare_bitmap` does not call Tk or
mutate or close the borrowed image. It returns one owned, oriented sRGB RGBA
image and releases its owned intermediate images on success, failure or Stop.
Already-normalized RGBA data transfers from the private orientation copy
without a second unconditional conversion copy.

The result is adopted by the ordinary UI event consumer. Stop before result
adoption discards and closes the candidate without replacing the current
image. Refused worker starts and busy, closing or pending profile/clear states
leave the current image in place. The new-image adoption keeps the existing
subject reset, background-removal/upscale reset, recovery and resume rules.

Automatic preview is requested only after the matching loader completion has
released the UI. Manual preview mode remains manual. Explicitly armed Drop-In
uses the same completion ordering as file/URL imports: it starts after the
loader becomes idle, and entering that worker cancels a pending automatic
preview. A subsequent Stop cannot restart either action from a stale event.

## Validation and scope

`test_v148_application_batch09_clipboard.py` contains six regressions using the
actual tracked worker, preparation code and controller event consumer. They
cover thread ownership, EXIF/pixel parity, borrowed metadata, refused starts,
Stop before/after normalization, color-management failure, queue failure and
discarded/cleared results. `test_v148_application_batch09_clipboard_preview.py`
adds four independent integration regressions through the actual
`pasted → done(load) → poll` sequence, including Manual, cancellation and
Drop-In ordering. All ten passed; an independent reviewer also checked the
ownership paths and sampled RGB, RGBA, L, LA, palette, unsigned 16-bit, EXIF,
transparency and embedded ICC inputs.

Existing clipboard fixtures now deliver the asynchronous worker result through
the real event consumer. The 28 related lifecycle, EXIF, depth and color-import
tests passed without changing their expected image pixels. Root independently
reran all ten new clipboard cases together with the ten diagnostics cases:
**20 tests passed in 0.046 seconds**. The later frozen whole-project run and
native CI are separate gates.

This establishes that explicit bitmap normalization no longer runs on the Tk
thread. It does not establish a universal latency or throughput improvement:
`ImageGrab.grabclipboard()` remains on that thread and may itself decode or
block inside a platform provider. Cancellation is cooperative at preparation
boundaries and cannot interrupt a native Pillow operation already executing.
No new wall-clock benchmark or antivirus-clearance claim is made.

The shared profile-action guard and release source inventory additions complete
existing lifecycle/packaging contracts at zero extra count.

## Frozen checkpoint validation

Batch 09: final frozen-source discovery passed 3,514 tests in 190.952 seconds (42 platform/hardware skips), with unchanged Python and batch-script hashes. All four area source reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. The published batch09 checkpoint `3c5fe8fc27ec3b503e2affa6f3ed00cb7856f973` passed complete Windows/Linux regressions, both dependency audits, CodeQL, Windows self-test, bundle build and packaged GUI/native drag-and-drop in [run 42320087469](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42320087469). All four jobs and all seven commit checks succeeded. No 1.0.148 release is published.
