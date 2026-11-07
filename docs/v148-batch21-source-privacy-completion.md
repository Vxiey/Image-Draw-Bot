# Batch 21 — verified-color cache source privacy

This completes the existing source-runtime privacy contract in **048** and the
batch 01 storage work. **Zero new improvement IDs.** The baseline is
`ec22fd8739573adc2df1b3e33dbe1a98a09b9c99` (821 registered improvements).

## Actual producer and archive gap

After a successful color verification, `DrawBot.execute_plan` calls
`ColorCache.put_verified`. The writer obtains its path through
`ProfileStorage.profile_verified_color_file` and stores local requested/detected
colors, verification metrics, workflow and calibration-context fingerprint in
`verified-colors-<profile>.json` beside a source installation.

The repository also shipped a small synthetic black-color seed at exactly that
mutable Paint filename. Earlier source-package tests and the batch 01 ledger
treated that filename as a public fixture. A normal source run could overwrite
it with local verification data, and other profiles could create additional
matching runtime files. The package policy did not distinguish either case.

The before probe used the real `ColorCache.put_verified` writer, with only the
data directory redirected to a temporary source tree. It then called the real
`validate_release_tree` and `create_source_archive`. Validation passed while the
ZIP included byte-identical runtime data for Microsoft Paint and a second
profile. The Paint write also demonstrably replaced the original seed. No real
calibration file, mouse input or repository runtime cache was used by the probe.

The final permanent before gate ran three methods: six expected failing
subcases exposed the two actual runtime files plus four root case/lock variants;
the separate-fixture control already passed. An earlier exploratory run had a
test-setup omission for its public `DrawBot.py` control; that setup was corrected
before this authoritative before gate and is not counted as a product failure.

## Completion

`ReleasePackage.RUNTIME_FILE_PATTERNS` now includes `verified-colors-*.json`.
The existing root-only matching, Windows case folding, known-file `.lock`
handling and nonfatal runtime exclusion rules apply unchanged. Nested
documentation examples remain eligible for source archives. Archive creation
does not alter or delete the local runtime files.

The synthetic seed is relocated to
`tests/fixtures/verified-color-cache-v2.json`, outside the live cache namespace.
Its **474 bytes are unchanged**, with SHA-256
`5f62e83ab4a0bef941bb34ee4e91b5b3db23c93daf3dcd96c20f67a87dc61930`.
The old source-file bytes were compared with the checked-in baseline before the
move, so no locally modified cache became the new fixture. The two older
positive fixture assertions now require the separated fixture instead of the
mutable root filename. The new regression also loads that fixture through the
actual `ColorCache.load_cache` reader and requires identical archived bytes.

The [batch 01 ledger](v148-batch01-storage-security.md) retains its original
historical statement and adds an explicit later correction dated 2026-11-07.
There is no new ID for the pattern, fixture relocation, case/lock controls or
documentation correction.

## Validation

- `test_v148_platform_batch21_color_cache_archive.py`: three methods covering
  actual writes for two profiles, successful validation and ZIP exclusion,
  unchanged on-disk runtime bytes, root case/lock variants, retained
  documentation examples, and the readable byte-identical separated fixture.
- Combined new, source-package privacy, storage-security, release-maintenance,
  historical-helper filtering and profile-calibration isolation gate:
  **69 tests passed in 0.604 seconds**, zero skips.
- Independent read-only source review closed without blockers. The reviewer's
  separate producer/archive, privacy, storage-security and release-inventory
  gate passed **51 tests in 0.448 seconds**, zero skips. That review independently
  confirmed the old and relocated seed share the same Git blob.
- `git diff --check` passed. No performance change or timing claim is made.

The runtime writer, profile/context validation and color-selection behavior are
unchanged. A clean installation learns its own verified colors; the synthetic
test seed is no longer placed on that runtime path.

## Full-suite runtime artifact

The complete local suite passed 4,198 tests (4,140 passed, 58 skipped). It also
recreated the old root cache name with the exact 474-byte synthetic seed. Two
older `test_paint_color_recovery_v10124` cases run real numeric color recovery
and call the actual cache writer without redirecting its storage boundary.
This further confirms that the filename is runtime state. It does not change
the archive policy or turn the file back into a distributable root fixture.

After all local gates, the recreated task artifact was compared byte-for-byte
against the Git baseline and the preserved fixture, then only that identical
root copy was removed before staging the relocation. The separate fixture
remains unchanged. The new archive regression already proves exclusion even
when an actual source run leaves such runtime files present.
