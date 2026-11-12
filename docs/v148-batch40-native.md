# v1.0.148 batch 40 — native input and calibration

## Scope and count

The reviewed baseline is `888116094b91758dded968a7e3b5559683db9ad7`.
Five distinct groups are implemented. They do not count tests, cleanup branches,
documentation or repairs to an already counted contract as additional fixes.
The aggregate registry owns global numbering and the new target of 900.

| Group | Earlier behavior | Implemented behavior |
| --- | --- | --- |
| N4001 | A recycled native window handle with the same rectangle and foreground status could pass the active draw's checks after its owning process or UI thread changed. | Bind the process and thread identity before activation, validate it through the existing native window checks, and refuse to refresh an old guard onto a different owner. Failed identity reads stop before input is armed. |
| N4002 | During an owned left-button drag, native movement ignored right, middle and side-button input. A retry could also move after a new physical button press. | Check competing buttons immediately before every native position send, including cursor and SendInput retries. Preserve the bot's left-button ownership so the established cleanup can release it. |
| N4003 | Five nearby ink-verification neighborhoods required five separate native desktop transfers. | Group dense nearby neighborhoods into one bounded transfer, preserving exact RGB order and duplicates. Sparse, large and cross-monitor unions retain the existing individual-patch path; optional union allocation failure falls back safely. |
| N4004 | Ink/fill settling, short click settling and transient-cover retries used unconditional sleeps after the draw had been stopped. | Bind the active Stop event and wait on it, checking Stop at the existing guarded-input boundaries. A stopped click still releases its owned button. Existing is_set-only cancellation tokens remain supported. |
| N4005 | Browser brush detection converted the entire captured screenshot to RGB before reading a few tiny control patches. | Crop first and convert only the bounded patches. Preserve complete plans across RGB, RGBA, grayscale and palette inputs, while keeping the borrowed screenshot usable. |

N4001 addresses reuse of a native target identity during an active guard. It is
not a claim to detect every possible handle reuse within the same process and
thread, or replacement before the first identity observation. Existing rectangle,
visibility, foreground, covered-point and DPI checks remain necessary.

N4003 builds on N2501/global837, which accelerated one dense neighborhood. This
group removes repeated transfers **between** nearby neighborhoods in the actual
ink consumer. The established emulator records five transfers before and one
after, with the same 125 ordered pixel observations. This native call reduction
is not a physical Windows timing or overall drawing-speed measurement.

N4005 preserves the same candidate locations, scores, confidence and selected
control. The conversion work is bounded to patches of at most 31 by 31 pixels.
Twelve complete historical/new plan comparisons over an existing application
screenshot, four image modes and three browser profiles were exactly equal.
The comparison includes both verified-relative and conservative fallback plans;
it does not assert that a screenshot of this app calibrates a real browser.

## Uncounted completions and review

Ink and Fill now revalidate the target after reading screen pixels, before
accepting a matching sample. This completes the established RT14/RT17 capture
and settling contracts and receives zero new IDs. Closing every private brush
patch on success, failed crop or failed scoring completes existing image
ownership and also receives zero additional IDs.

Independent rendering review found the initial N4002 implementation missed
position retries. The final gate is inside `send_position`, under the existing
serialized input lock, and both native move backends have a regression test.
The same review checked process binding, grouped sampling, cancellable waits,
crop-only calibration and overlap with earlier registry entries. Minimal legacy
Stop tokens retain an is_set check before and after their ordinary wait.

## Verification

New regression modules are:

- `test_v148_native_batch40_target_identity.py`
- `test_v148_native_batch40_drag_takeover.py`
- `test_v148_native_batch40_ink_sampling.py`
- `test_v148_native_batch40_stop_waits.py`
- `test_v148_calibration_batch40_brush_patches.py`

The existing actual ink-consumer test in
`test_v148_native_batch25_screen_sampling.py` now asserts one grouped transfer
instead of five, retaining pixel values, verdict and native resource balance.
Failure-injection tests exercise the real guard, mouse and sampling code at
their native API boundaries; they do not replace the product implementation.
Image cases read committed screenshots and do not introduce source images.

The selected historical comparison runs 19 methods against the exact four
baseline modules, with current shared dependencies and current regressions.
It produces 25 failed assertions/subtests and two unexpected OSError records
from the old retry implementation. Those two errors are the old pointer timeout
after an extra movement, not fixture/import failures. The same 19 methods pass
on the new source. These records are evidence of five behavior groups, not 27
independent bugs. Exact tests, source hashes and diagnostics are retained in
`v148-batch40-native-historical.json` and
`v148-batch40-native-current.json`.

The brush-specific selection passed 50 tests. The final retry/Stop selection
passed nine tests; independent review passed 40 related input/focus tests.
The aggregate full-discovery receipt provides the final integrated result.

Validation here uses Linux and the existing native API boundary emulator.
Actual Windows input, DPI scaling, GDI ownership and live Paint/browser checks
require the published commit's Windows gate. A failed local Xorg launch exposed
the workspace's Unix-socket restriction; no GUI skip or sandbox policy was
weakened to claim native coverage.
