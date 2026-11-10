# Profile export — complete the modal lifecycle guard

Baseline: `71a87ed659676ea5c4e72e40fbae5f72b7f354b3` on
`improve/v1.0.148`, the verified batch31 checkpoint in draft PR #46.

This patch completes **AW15/global629** and adds **zero improvement IDs**.
The registry remains byte-for-byte unchanged at **843/1,000**, with **157
remaining**. It does not constitute the planned final verification or a release.

## Reproduced problem

`ProfilePortability.export_profile_dialog` captures a validated package and opens
the native save chooser. That chooser permits nested event processing. On return,
the original code immediately published the captured package, even if shutdown,
a worker, a pending clear or a profile transition had started. A completed profile
switch, rename, removal or same-name storage-key replacement could also leave an
outdated selection eligible to overwrite the chosen export file.

Success and error message boxes were unconditional, including during shutdown.
The import and reset flows already use the shared idle guard and suppress feedback
when closing; the export flow had not completed that existing contract.

The new regression module was run against the unmodified baseline first:
**12 methods, 22 failing assertions/subcases across eight methods, zero errors
and zero skips**. Four control methods passed. These are failing subcases of one
lifecycle defect, not 22 separately counted improvements.

## Change

Only `export_profile_dialog` changes in product code:

1. After a nonempty chooser result, call `_require_idle_profile` before reading
   any profile variable or publishing a file.
2. Compare the current profile's exact name and storage key with the captured
   package; require a fresh Export action when that identity changed.
3. Suppress both success and error message boxes while the application is closing.

The existing package snapshot, validation, JSON format, extension handling and
atomic writer remain in use. Same-profile setting changes during the chooser do
not silently replace the captured snapshot. Cancellation remains a no-op for the
export destination. A live application still reports ordinary I/O failures.

The closing check precedes `game.get()`: the shutdown regression installs a
getter that raises if the export callback touches destroyed UI state.

## Executed verification

Environment: Linux x86-64, CPython **3.12.14**, with the project's application and
development requirements installed. These are local controller/file regressions.

| Gate | Actual result |
| --- | --- |
| New regression module on original product source | 12 methods; 22 expected failures, no errors or skips; 0.057 s |
| Same unchanged regression module after the patch | **12 passed**, no failures, errors or skips; 0.042 s |
| Seven adjacent existing profile/settings modules | **64 passed**, no failures, errors or skips; 0.126 s |
| Source-package hygiene (`ReleasePackage.py --check`) | **Passed**, 1,374 files, no warnings, forbidden paths or missing requirements |
| Independent source/test/counting review | No required changes found; AW15 completion confirmed |

The 12 new methods and 64 existing methods are disjoint: **76 passing methods**
after the patch. The reported durations are unittest's own suite durations,
not application-performance measurements. The test source hash is identical
between the before and after runs.

Reproduce the focused checks with:

```sh
python -m unittest -v test_v148_ui_batch32_profile_export
python -m unittest -v test_profile_portability_step27 test_v148_storage_batch02_profiles test_v148_application_batch04_settings test_v148_ui_batch08_profiles test_v148_ui_batch08_profile_management test_v148_ui_batch09_profile_completion test_v148_ui_batch10_profile_completion
```

[Machine-readable execution evidence](v148-batch32-profile-export-validation.json)
records commands, results, source hashes and the before/after failure identities.

The tests use actual temporary settings/calibration files, package construction,
validation, atomic publication and exported-file readback. Native dialog boundaries
and lifecycle/failure transitions are injected; package validation and atomic file
operations use real temporary files.
They verify supported suffixes, frozen snapshots, absent/existing destinations,
all shared idle guards, exact identity changes, shutdown feedback and staged-file
cleanup on I/O failure. No images are generated for these tests.

## Scope and limits

- The local runs do not exercise the native Windows file chooser, a packaged EXE,
  physical drawing, Paint calibration or GPU behavior. No full local discovery,
  Windows smoke test or release build was run for this scoped patch.
- The seven successful checks on the baseline commit remain historical evidence;
  they are not validation of the new commit. New GitHub check results must be read
  for that exact commit separately.
- `RecoveryImagePreparation.py` was reviewed but is unchanged. A separate
  double-failure case can let converted-image cleanup replace a primary PNG
  cancellation; it is a follow-up candidate, not an implemented improvement here.
- UI design references were reviewed as future guidance. This patch contains no
  UI redesign or new UI improvement IDs.
- The PR stays draft. Merging and release require the user's explicit approval.

Counting references: [AW15's original contract](v148-batch04-application.md),
[uncounted modal completions](v148-batch08-ui-workflow.md) and the unchanged
[numbered registry](v148-improvements.json).
