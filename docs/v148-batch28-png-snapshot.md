# Batch 28 — reuse the PNG worker's private image snapshot

## Status and classification

**Focused regressions, independent source review and integrated batch gates pass. This completion adds zero improvement IDs.** It completes the
existing IW08/global582 image-ownership and AZ01/global746 unnecessary private
image-copy contracts at the actual PNG export caller. The registry remains
839/1,000 with 161 remaining, and version 1.0.148 is not released.

The GUI must copy the selected source before handing it to a background worker:
the user can edit or replace the original while the export waits. The worker
already owns that isolated snapshot. Previously its orientation helper called
`ImageOps.exif_transpose(snapshot)` without in-place ownership, which makes a
second whole-image identity copy even for an unrotated image. An RGBA image then
needed no conversion, so the extra buffer served no remaining consumer.

## Narrow product change

`png_export_ready` now accepts the keyword-only `reuse_owned=False`. Only the
actual PNG worker passes `True`, for the snapshot it already owns. Pillow
normalizes EXIF orientation in that private buffer; an RGBA snapshot becomes
the encoder input directly, while RGB, grayscale and palette inputs still
receive the necessary RGBA conversion. Real rotations may still allocate their
required transposed pixels. The GUI's first isolation copy remains intact.

The default public helper still returns an independent owned RGBA image and
does not change a borrowed caller input. Background removal keeps that existing
default. The encoder still writes PNG with its existing options and uses the
same atomic publication and Stop checks. ICC and pixel/alpha output are
preserved. Existing PNG publication does not explicitly forward source EXIF to
the encoder, and this change does not alter that behavior.

The outer snapshot owner closes it even if normalization fails before the
encoder context is entered. Converted output has its own closing context.
Pillow image closure is idempotent when the RGBA encoder input is the snapshot
itself. Existing worker-start, stopped-before-start and final cleanup paths
continue to retire the private snapshot. Borrowed GUI pixels stay usable.

## Concrete published before behavior

The new fixture was loaded by explicit module path while product and old
fixture imports came from frozen batch27 commit
`f800da5785731bbe0b0f8e3908bc330a65ac79c6`. Bytecode writes were disabled; an
audit hook rejected repository mutations and network operations. All 881 root
Python files remained unchanged at canonical SHA-256
`59de95e5201bf591c7c7118aee9c20e40aa0dbfc020fd5e8714c65ba5903853f`.

The observer calls the real `save_png_copy`, tracked worker runner, Pillow
normalization and PNG encoder, atomic file writer and decoder. Only scheduling
is deferred at the thread boundary so the borrowed source can deliberately be
edited after enqueue. It observes actual `Image.copy` calls and independently
calculates expected mode, alpha and orientation pixels.

| Unrotated input, 64 × 48 | Before copies | Before copied pixel payload | Required isolation payload |
| --- | ---: | ---: | ---: |
| RGBA | 2 | 24,576 bytes | 12,288 bytes |
| RGB | 2 | 18,432 bytes | 9,216 bytes |
| Grayscale L | 2 | 6,144 bytes | 3,072 bytes |
| Palette P with partial transparency | 2 | 6,144 bytes | 3,072 bytes |

All four old exports already had correct reopened pixels, alpha and ICC,
unchanged/open borrowed sources and closed private images. The before failure
is avoidable copying, not an old resource leak or corrupted PNG claim. Four
test methods produced **four expected copy-count failures and zero errors**;
the other functional, publication and ownership checks passed. The preserved
before observer has SHA-256
`4f66630a1df833f105052907246210fea5970d6b31baf11dee68a51c1f430063`.

Copy payload is width × height × bands for observed identity-copy calls. It is
not peak allocation, process RSS, encoded file size or elapsed-time evidence.
Necessary mode conversion and rotated buffers are outside that count.

## Regressions and review

The four new methods in `test_v148_application_batch28_png_snapshot.py` cover:

- Actual unrotated export for RGBA/RGB/L/P, exactly one isolation copy, a source
  mutation after enqueue, decoded independent pixels and alpha, ICC, events and
  private image retirement.
- EXIF orientations 3, 6 and 8 for all four modes, independently mapped integer
  coordinates, unchanged borrowed pixels/metadata and no double orientation.
- Stop and a retained real error after actual PNG encoding: the old destination
  survives, no partial temporary file remains, no saved event is sent and owned
  images close while the original stays usable.
- Default public-helper independence for all four modes, including orientation,
  caller metadata and returned image ownership.

The new methods and 47 adjacent image-worker, background-removal, edit-history
and UI tests passed: **51 tests, zero skips, 0.852 seconds**. This is a test-run
duration, not an export benchmark. An independent reviewer read both product
hunks and all four tests and separately ran the four methods successfully in
0.070 seconds. Review is closed without a blocker. The final integrated source
binding is recorded separately so these focused runs are not misrepresented as
the later frozen whole-program gate.

Two initial fixture mistakes are preserved explicitly in the evidence. One
incorrectly expected EXIF Artist in the existing encoded PNG; actual pixels and
ICC were already correct. The next fixture used text under Pillow's binary
`info['xmp']` key and hit Pillow's bytes-regex type check. The final fixture uses
decoder-style UTF-8 XMP bytes and asserts the encoder's established EXIF output.
Neither diagnostic is counted as a product failure, improvement or passing
before run. The original fixtures and logs remain preserved with hashes.

The final frozen-source observer repeats the actual worker flow for all four
modes and the four regression methods: all pass, with one isolation copy per
unrotated export and identical decoded SHA-256 values to the published before
cases. Observed copied payload is 12,288 bytes for RGBA, 9,216 for RGB and 3,072
for L/P. All borrowed inputs remain open and unchanged, private outputs close,
and ICC is preserved. All 883 source hashes remain unchanged at
`74a659994b8f25037a6b233eb05efcafd2f60bffd3fa0de073d3623355c7929c`.
The final observation has SHA-256
`9e411ddc7b1ef4a54af8f2c7e00147be381a000a2c43b8ff8e55c0f2a5ee458d`
and is preserved in the raw completion evidence linked below.

## Limits

The change removes one unnecessary whole-image identity copy in the actual
unrotated PNG path. It makes no general speed, memory-peak, RSS, GPU or physical
Windows-input claim. The shared helper's borrowed-input default and the
application's existing encoder/publication semantics remain covered. Integrated suite, native UI, source, package and final observer results are recorded below.


## Integrated frozen-source result

Batch 28 completes existing Sketch physical-preview and private PNG-snapshot contracts with zero new IDs: **839 total improvements, 161 remaining**. All 839 registry entries and 75 preceding raw benchmark reports are preserved. Frozen discovery completed **4,498 tests in 224.479 seconds: 4,425 passed and 73 platform/hardware cases skipped**. All 933 source/configuration hashes remained unchanged. Fourteen real Linux/Xorg native cases, the 5,000-cycle source gate, eight exact existing-raster fixtures and package hygiene passed on the same 883 root Python sources. Five actual public/controller-to-executor Sketch comparisons now have exact physical-model previews, including the prior 32-versus-15-pixel axis failure and both scaled Balanced fixtures. Native actions and delivered pixels are unchanged in those fixed controls. Corrected Accuracy/delta-E may legitimately change an active tuner rescue decision. PNG export removes one unnecessary identity copy for unrotated private snapshots while preserving decoded pixels, ICC, borrowed inputs, Stop and atomic publication. Historical batch27 replay is pinned to its published caller graphs and adds no timing samples. This is no physical Paint, general speed, peak-memory or GPU claim. Parent f800 has seven green exact-commit GitHub checks; the new published head requires its own Windows/package checks in PR46. Version 1.0.148 remains unreleased.

The common root-Python manifest is `74a659994b8f25037a6b233eb05efcafd2f60bffd3fa0de073d3623355c7929c`; the full 933-file source/configuration manifest is `680f297ff6c85d9e054e26a6b3108ccfe8eeb8c7729bdb891c7ea85e672b2683`. [Final validation](v148-batch28-validation.json) records the exact gates and platform boundaries. [Raw completion evidence](v148-batch28-completion-evidence.json) retains the original observations, logs, fixtures and complete source maps with documented lossless references.
