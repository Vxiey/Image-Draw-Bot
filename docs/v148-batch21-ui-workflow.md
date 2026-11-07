# v1.0.148 batch 21 — retained-image Undo completions

Baseline: `ec22fd8739573adc2df1b3e33dbe1a98a09b9c99` (821 registered
improvements). This UI work completes the existing image/Undo boundary in
RT42 and the IW08/AZ01 owned-image/copy contract; it adds **zero improvement
IDs**. It does not publish version 1.0.148.

## Clearing the drawing cache preserves source-edit Undo

The actual StudioUI source section provides separate **Clear image** and
**Clear cached drawing** buttons, followed by Upscale and its Undo button.
The cache-only controller explicitly retains the current source and reports
“Cached drawing cleared; source image kept.” Nevertheless,
`DrawBotApp._finish_clear_drawing` unconditionally cleared `upscale_original`.
It preserved the corresponding background-removal Undo snapshot, so the two
source editors behaved differently after the same cache-only action.

The before reproduction runs public upscaling in its actual worker, consumes
the queued result, builds a real plan, clears the cached drawing and invokes
the actual Undo controller. A 32 × 24 source was still displayed at 64 × 48
after Undo, with “No upscaling to undo for this image.” The same
background-removal sequence correctly restored its original pixels. Native
window/queue scheduling presentation and recovery persistence are the
substituted boundaries; image processing, worker lifetime, event adoption,
planning and clear/Undo controllers remain real.

The minimal controller change clears the upscale snapshot only when the
source image is actually removed. Cache-only clearing still stops pending
work, discards its plan/resume/recovery state and preserves the current source.
Clear image continues to discard both edit histories. No new history stack or
cross-editor Undo behavior is introduced; the existing rule that Undo belongs
to the most recent edit type remains intact.

`test_v148_ui_batch21_edit_history.py` has four methods covering:

- Actual upscale → worker/adoption → public plan → cache clear → exact
  source dimensions and pixels after Undo.
- The unchanged equivalent background-removal path.
- Clear image after either edit, with neither Undo able to restore a removed
  source.
- Stop/clear before a real queued edit is adopted, candidate-image closure,
  and a retained old clear callback invoked after a new legitimate load and
  upscale have cleared Stop. The old callback cannot erase the new Undo or
  reintroduce discarded image state.

Before the patch, the four-method gate had **one failure and three passes in
0.425 seconds**; only the retained-upscale-history assertion failed. The same
original controller probe now restores the exact 32 × 24 pixels for Upscale
and preserves the working background control. The combined new and adjacent
edit, plan-feedback, source-timer and Auto-preview suite passed **49/49 in
3.700 seconds**, without skips.

Evidence remains in the parent scratch directory:
`batch21-cache-undo-before.json`, `batch21-cache-undo-tests-before.log`,
`batch21-cache-undo-after.json` and `batch21-cache-undo-after.log`. The before
records are retained separately from the after run. The four-method module
uses the existing creator-thread fixture teardown and verifies its cleanup
result, rather than retaining Tcl state for later worker collection.

This fixes a missing branch of the existing source-edit history contract.
Rows, test cases and separate Clear variants are not counted as new features.

## Transfer the consumed background-removal Undo image

The background remover already creates its independent Undo snapshot only
when a successful edit is adopted. Undo then copied that entire private image
again on the UI thread and immediately discarded the history field. That
second copy served no remaining history consumer. A real 512 × 384 removal,
queued adoption and Undo recorded one RGBA Undo copy containing **786,432
pixel bytes**. The worker's source preparation and the adoption snapshot are
separate, retained operations.

The accepted Undo now transfers that private snapshot into `original` and
consumes its history field. Successful adoption still creates an independent
snapshot, including the previous `assertIsNot` ownership control. Busy/closing
guards, source feedback, invalidation, recovery and preview handoffs are
unchanged.

The exact same work-count probe after the one-line change records **zero Undo
copies and zero copied pixel bytes**, with the preparation/adoption copies
unchanged. Restored source pixels match exactly. This is a count of copied
pixel payload at one actual controller operation, not a measurement of total
process memory, peak allocation, native Tk latency or general CPU speed.
Original and after evidence are retained separately as
`batch21-background-undo-copy-before.json` and
`batch21-background-undo-copy-after.json` in the parent scratch directory.

The seven-method final UI module adds real cross-editor, no-op and stopped
follow-up worker routes to the four clear/Undo cases. The transfer case proves
exact pixels and metadata, including an actual sRGB ICC profile. A subsequent
real PNG-export worker closes only its own export snapshot; decoding that
PNG yields the exact restored pixels/profile and the live restored source
remains usable. Cross-editor changes still retain only the latest edit's Undo.
A rejected/no-op follow-up keeps the currently accepted Undo snapshot intact.

Before transfer, this seven-method gate had **one failure and six passes in
0.666 seconds**; its copy-count assertion observed the extra RGBA copy.
After both completions, the final new/adjacent image history, ownership,
plan-feedback, source-timer, Auto-preview and UI gate passed **86/86 in 4.163
seconds**, without skips. Logs are `batch21-undo-transfer-tests-before.log`
and `batch21-edit-history-final.log`. Earlier before/after records above are
kept as the corresponding smaller-scope evidence.

Independent source and actual-flow review is closed without blockers. The
reviewer reran all seven Undo methods with the five adjacent profile-warning
methods: **12/12 passed in 0.701 seconds**. The review checked accepted-image
ownership, cache-only versus image clear, Stop/stale-result rejection, the
retained old callback, metadata/export parity and creator-thread fixture
cleanup. Both changes remain completions with zero new improvement IDs.
