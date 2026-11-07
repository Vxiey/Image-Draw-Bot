# Batch 22 — Paint recovery test storage isolation

This is a **test-only completion with zero new improvement IDs**, following the
[batch 21 source-privacy completion](v148-batch21-source-privacy-completion.md).
The baseline is `92d5a86709a61802821780f5866409da6cd8cf2e`.

## Observed side effect

The batch 21 full suite passed 4,198 tests but recreated
`verified-colors-microsoft-paint.json` in the source checkout. The resulting
474 bytes matched the synthetic black-color fixture that had just been moved
to `tests/fixtures/verified-color-cache-v2.json`.

Source and full-suite log attribution identified two older methods in
`test_paint_color_recovery_v10124.py`: the palette-mismatch numeric recovery and
the active-swatch recovery. Both run the actual `DrawBot.execute_plan`, accept
verified black through the numeric method, and therefore call the actual
`ColorCache.put_verified`. Their storage boundary had not been redirected.

## Completion and evidence

Those two execution calls now use a private temporary directory through
`ProfileStorage.data_dir`. `ColorCache.put_verified` and `load_cache` remain the
real implementations. After each successful execution the test requires a real
cache file and reads it back, checking the single black RGB entry, numeric
method, confidence 100, DeltaE2000 zero and verified state. It also compares the
real runtime path before and after, preserving either its existing bytes or its
absence. All existing keyboard, session-cache, status and recovery assertions
remain in place.

The focused gate includes the five original Paint recovery methods, the three
actual source-archive regressions, Paint color verification and profile/context
isolation: **23 tests passed in 0.098 seconds**, zero skips. The source-checkout
cache remained absent, and `git diff --check` passed.

Independent read-only review closed without blockers. The reviewer ran the five
original recovery methods and three actual archive methods: **8 tests passed in
0.092 seconds**, zero skips, with no changes to the implementation or assertions.

There is no product behavior, cache schema, archive policy or improvement-count
change in this completion. No elapsed-time improvement is claimed.

## Windows checkout follow-up

The exact batch 21 commit's Windows CI ran 4,198 tests in 332.700 seconds, with
one failure and three optional-GPU skips. The one failure was the new seed's
exact-byte hash assertion: Git checkout had converted its 25 LF line endings to
CRLF. The resulting 499-byte file hashed to
`fe5f96cc208acc18c898a8db865e705c5860de704c5a57edef283e4a2d003b61`, exactly the CI
failure. The remaining Windows self-test, bundle and packaged GUI steps were
skipped after that failed regression step.

The fixture had no text/eol Git attributes. A single exact-path `-text` rule now
disables Git text conversion for this serialized fixture. The existing hard
hash assertion, actual reader and archive-byte equality assertion are retained.
No other file's checkout behavior changes.

The real Git filter command with `core.autocrlf=true` reproduced the 499-byte CI
hash before the rule. With the rule it returns the original 474 bytes and
SHA-256 `5f62e83ab4a0bef941bb34ee4e91b5b3db23c93daf3dcd96c20f67a87dc61930`.
The source-archive, privacy, maintenance and original recovery gate then passed
**11 tests in 0.115 seconds**, zero skips. This is checkout/test evidence; a new
exact-commit Windows CI run supplies the subsequent native packaging evidence.
