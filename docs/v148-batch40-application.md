# v1.0.148 application continuation

## Scope and counting

The starting public checkpoint is
`888116094b91758dded968a7e3b5559683db9ad7` on `improve/v1.0.148`.
Earlier conversation context described additional local work after that commit,
but no published source or downloadable artifact for it was recovered. The
corrections below were reproduced against the actual checkout and implemented
again; prior claims of completion are not used as source evidence.

**One new behavior group is proposed: A4001, background Undo snapshot handoff.**
The export and unpublished-result corrections finish already established
profile/export/worker ownership contracts and receive **zero additional IDs**.
Tests, assertion branches, documentation and count changes are not improvements.
The overall target is now 900; the aggregate registry owns the integrated count.

## A4001 — reuse the existing detached source snapshot for background Undo

The Remove BG controller already copied its accepted source before starting a
worker. Previously it closed that exact snapshot after segmentation, then made
another full source copy on the UI thread immediately after accepting a
successful result. Both copies represented the same pre-edit pixels.

`BackgroundEdit.BackgroundEditResult` now carries the existing private snapshot
through the queued result, bound to the borrowed source's identity. The main
controller adopts it as Undo state only after accepting the matching result.
Undo remains detached from the original source, with identical pixels and
metadata. The ordinary background-removal algorithm is unchanged. Legacy direct
result producers retain their prior detached-copy fallback.

Stop, changed source identity, failed publication and rejected results release
the result image and unpublished Undo snapshot. A no-op result does not keep a
new Undo image. Subsequent removals preserve the first Undo image and close
their unnecessary private input snapshots. An accepted worker skipped by Stop
still runs source cleanup. Retained exceptions do not retain the owned pixel
buffers, and a secondary cleanup failure does not replace its primary error.

This removes one full source copy from the actual UI adoption path. For an RGBA
source that is `4 × width × height` bytes of avoided pixel-copy work; the
360 × 240 existing fixture avoids a second 345,600-byte payload copy. This is
not an overall RSS or peak-memory measurement. The queued result intentionally
retains its input snapshot until UI adoption or rejection, so that buffer lives
longer than before. No general speedup or physical drawing claim is made.

This is separate from AZ01/global746, which transfers a buffer **inside** the
background algorithm before alpha replacement, and from IW18/global592's rule
that Undo must be created only after a successful edit. Here the redundant
copy between the actual controller's worker and Undo consumer is removed.

Files: `BackgroundEdit.py`, `DrawBot.py`,
`test_v148_application_batch40_background_undo.py`. Two historical image-worker
tests now check the intentional live snapshot handoff on successful background
edits, while retaining their exact pixels, original ownership, cancellation and
failed-start assertions. Four new tests drive real workers, the real background
algorithm, the queue, result adoption and Undo using an existing golden image.

## Zero-ID completion — confirm the actual profile export destination

The file chooser could confirm replacement of a typed `brushes.backup` file,
while `write_profile_file` normalized it to `brushes.drawprofile` and silently
replaced that different existing file. `profile_export_path` supplies one
destination calculation to the chooser workflow and writer. When normalization
changes the path and its actual target already exists, the dialog names that
target and defaults to declining replacement. Supported suffixes keep native
chooser confirmation; a new destination needs no extra prompt.

The additional confirmation is a nested event loop, so the controller checks
activity, shutdown, pending profile work and the exact profile identity again
after approval. Declining or losing that ownership keeps both existing files
intact. Five new tests use real package validation, temporary files and the
atomic writer. The earlier lifecycle fixture explicitly accepts this newly
required replacement prompt; its package and cancellation assertions remain.

Files: `ProfilePortability.py`,
`test_v148_application_batch40_export_destination.py`,
`test_v148_ui_batch32_profile_export.py`.

## Zero-ID completion — own image outputs through publication and preparation

Background removal, upscale and screenshot workers previously closed completed
images on some Stop paths but left them open when their result could not be
queued. Screenshot capture also lacked a post-capture Stop check.
`DrawBotApp._publish_image_result` consistently checks Stop/shutdown and closes
unpublished image results, retaining the original publication exception if
cleanup also fails. Load and clipboard publication use that same boundary;
their existing borrowed source-image contract is unchanged.

Remove BG, PNG export and preview construction now keep their feedback calls
inside the already existing snapshot-cleanup boundary. A failing status update
before worker startup can no longer retain the private input snapshot.
Independent review also moved Remove BG's outer startup cleanup through the
same idempotent release function. Feedback and thread-start exceptions retain
their identity when closing the owned snapshot itself fails; cleanup adds a
note and does not run the same disposal twice.

Seven new tests use actual image operations and workers with existing icon,
Paint-reference and golden assets. They retain queue exceptions, verify late
Stop/shutdown, successful publication, failed pre-start feedback and borrowed
source preservation, including secondary startup cleanup failures. No new
source motifs or generated images were introduced.

Files: `DrawBot.py`, `test_v148_application_batch40_image_publication.py`.

## Verification

- All 16 new methods passed in the final selection with no errors or skips.
- The final application selection passed **142/142 methods**, with no errors,
  failures or skips. Unittest execution took **22.825 seconds**; loading plus
  execution took **24.0539 seconds**. The 19 recorded production/test file hashes
  were unchanged across that run.
- Seven selected new methods were also run with the relevant historical
  controller/export function bodies from `8881160`. They produced **18 failed
  assertion/subtest records and no fixture errors**. These are seven methods
  demonstrating the earlier failures, not 18 bugs or extra improvement IDs.
  Current dependencies and fixtures were kept; this component-level red proof
  is not described as a complete historical package gate.
- `git diff --check` passed.

[Area validation and hashes](v148-batch40-application-validation.json) and
[historical component red proof](v148-batch40-application-red-proof.json)
retain the exact selections and raw results. Earlier overlapping focused runs
are not added to the final method count. Integration, complete-suite validation,
native UI, Windows packaging and remote CI are separate parent-task gates.
