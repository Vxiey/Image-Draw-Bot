# v1.0.148 platform and diagnostics — batch 06

Baseline: `f59a57c6fc1eef1ace07e872ba50ed834e1bb924`, the published 699-change
checkpoint. The intervening Windows test-fixture correction at
`4c8aa247f852df7225b5e7d10ce4ac151e612226` has no product count.

This batch contains **five new behavior groups**, PF01–PF05. Tests, benchmark
files, documentation and completions of already counted contracts are not
additional improvements. Nothing here establishes antivirus clearance or
changes certificate trust, signing policy or native input authorization.

## New behavior groups

| ID | Previous behavior | Implemented behavior and evidence |
| --- | --- | --- |
| PF01 | Update checking inspected only the first 100 GitHub releases. A stable release after 100 newer prereleases was reported as absent, and an earlier-created higher semantic version could be missed. | `UpdateCenter.check_for_updates` selects the best allowed version across linked pages. It rebuilds every request using the fixed repository endpoint and validated consecutive page numbers, including GitHub's numeric repository-link form. All pages share the existing 30-second cooperative deadline and 16 MiB decoded-body budget, with a ten-page maximum. An incomplete history raises an actionable error instead of claiming the current version is latest. `test_v148_platform_batch06_pagination.py`: real Requests adapter calls cover the 100-prerelease case, semantic selection across three pages, endpoint boundaries, repeated/skipped/ambiguous pages, total size, Stop/deadline and response closure. |
| PF02 | Every update attempt downloaded and retained another uniquely named installer, even when identical verified bytes were already present. Successful loose downloads accumulated indefinitely. | `InstallerCache` and `UpdateCenter.download_installer` reuse a file only after a complete size/SHA-256/MZ check, and recheck Stop at completion. A cache hit works without network access or additional download space. Cooperating cache operations use a stable file transaction; concurrent completed downloads publish one hash-named installer. Normally retain the current installer and one recently used previous installer in an explicitly marked cache directory. Unknown/unmarked directories, links, other filenames and legacy loose downloads are not adopted or deleted. Busy-file eviction is deferred. `test_v148_platform_batch06_installer_cache.py`: public downloader tests cover repeated reuse, same-size corruption, missing files, cancellation, ownership/links, concurrent publication, locked eviction and inventory failure. The existing Windows locked launcher still rehashes immediately before execution. |
| PF03 | Elevated LocalDumps configuration wrote the administrator's already expanded absolute profile path into a machine-wide per-executable setting. An ordinary user running the app could therefore target another account's dump folder. | `CrashDumpConfig` writes the expandable `REG_EXPAND_SZ` value `%LOCALAPPDATA%\ImageDrawBot\dumps`; normal Windows app startup prepares its own account's folder and diagnostics inventories that same location. An already owned absolute setting can migrate without losing the original undo values. A validated transitional `previous_written` record permits Disable to recover after partial native writes or a final undo-file publication failure, while preserving later external registry changes. The existing full preflight and transaction remain. `test_v148_platform_batch06_diagnostics.py`: two-account path expansion, normal startup/report inventory, undo-before-migration and failure injection at each native write plus final publication. |
| PF04 | Invalid UTF-8 in a local dependency's real `METADATA` file caused `importlib.metadata.version` to abort the entire diagnostics ZIP, losing otherwise readable logs and other package versions. | `DiagnosticsPackage._package_versions` contains ordinary per-distribution read/metadata failures. `system.json` records the affected fixed package name and exception class in `collection_issues`; raw exception messages, local paths and credentials are not copied. Missing optional packages retain their existing normal omission behavior, and cancellation is not swallowed. Public archive tests use a real malformed `PathDistribution` and verify retained session logs, other package versions and privacy-safe failure details. |
| PF05 | The standalone diagnostics helper reported collection failure and returned exit code 1 when Explorer could not open the folder, even though the complete ZIP was already saved. | `DiagnosticsPackage.main` separates archive creation from folder presentation. Successful publication retains exit code 0 and the concrete saved path when automatic opening fails; the windowed frozen helper also shows the saved path in a notice. A real public-main regression creates and validates the ZIP, injects the shell-open failure and checks success, console result and windowed notice. |

## Existing contracts completed without new counts

- **SS03/SS04 — learned-state storage.** `RealSpeedBudget.load_all` now uses
  `RuntimePaths.read_json` with a 1 MiB limit and a strict integer schema version.
  Existing duplicate-key, finite-number, depth and node constraints apply.
  Sample read/modify/write and direct saves share the existing reentrant file
  transaction, and saves reject nonfinite JSON. Four tests cover oversized/deep
  and ambiguous state, 64 simultaneous completed samples for two profiles, and
  write failure followed by successful recovery. No learning formula changes.
- **SR34 — log rotation failure.** `CrashDiagnostics` no longer deletes the old
  backup before attempting atomic replacement. Injected replacement failure
  preserves both current and previous evidence; successful rotation still
  replaces the older backup.
- **SR32 — diagnostic metadata privacy.** Settings/calibration summary filenames
  are opaque numbered labels. Two secret-bearing names cannot leak credentials
  or collapse into one record when redacted. Existing filename-dependent test
  fixtures now assert the opaque labels; their content/privacy assertions remain.
- **Existing diagnostic serialization contract.** Summary JSON uses ASCII
  escapes, so an isolated surrogate in damaged local text does not make UTF-8
  ZIP writing fail. Parsed values and the existing content allowlist are retained.
- **026 — system DLL loading.** The Windows RAM diagnostic uses the shared
  System32-only library loader with explicit function types and fixed-width
  DWORD fields, consistent with the already counted native loading contract.
- **Windows fixture portability.** The already published batch05 source-walk
  failure-injection fixture resolves its temporary root before comparing it
  with the builder's canonical path. The production traversal/error behavior
  is unchanged.

## Measured installer I/O

Reproduce with `python benchmark_v148_platform.py`. The complete paired raw data
is in `docs/v148-batch06-platform-benchmarks.json`.

The benchmark executes the baseline `UpdateCenter.py` from the exact commit
above and the current downloader against the same in-process byte transport.
Each round requests the same 8,388,610-byte synthetic installer three times in
an initially empty temporary directory. Both implementations have one warmup;
five measured pairs alternate execution order. Every returned file is checked
byte for byte against the same input, outside the timed interval. The synthetic
bytes are never submitted to an executable loader.

| Measurement per three requests | Before | After |
| --- | ---: | ---: |
| Transport requests | 3 | 1 |
| Transport body bytes | 25,165,830 | 8,388,610 |
| Retained installer files | 3 | 1 |
| Retained installer bytes | 25,165,830 | 8,388,610 |
| Median local elapsed time, five paired rounds | 24.296 ms | 23.249 ms |

This establishes two avoided transfers and copies for repeated identical assets,
with exact output parity. It does not measure internet latency, antivirus or
Windows installation performance. Cache hits still read and hash every byte;
the small local timing difference is not presented as a broad speedup.

## Validation and limits

The four new platform modules run **31 tests successfully**. The related updater,
installer, WER, diagnostics, privacy and regression run completes **154 tests,
with five native Windows skips**, in 0.371 seconds locally. The tests use mocked
GitHub transports, synthetic nonexecuted installer bytes, temporary files and a
fake registry. No production registry, releases or downloaded binaries were
mutated or executed.

- WER path expansion and recovery are exercised offline. Actual crash-dump
  collection across two Windows accounts is not claimed to have been run.
  Native validation and filesystem sharing behavior remain Windows CI/manual
  platform checks; no root-certificate or trust-store changes are involved.
- Transfer budgets remain cooperative between redirects/body reads; they do not
  forcibly interrupt a blocked OS/socket operation. Cache transaction acquisition
  uses the existing storage API's maximum five-second wait, which itself is not
  cancellable. Hash loops and subsequent completion honor Stop.
- Cache retention is normally two owned installers, each already subject to the
  published-asset 2 GiB cap. Windows can keep an installer busy; blocked deletion
  or a directory inventory error is reported locally and retried on later use,
  so an in-use cache can temporarily exceed this retention target. Unknown files
  and earlier loose downloads are preserved because this cache cannot establish
  their ownership. Cache contents never replace the locked launch verification.
- GitHub pagination is bounded. Histories that cannot be completely checked
  within the shared limits produce an error with the Releases-page alternative;
  a partial list is not represented as authoritative.

Primary API references used for the design:

- GitHub pagination and Link semantics:
  https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api
- GitHub release-list page and page-size parameters:
  https://docs.github.com/en/rest/releases/releases#list-releases
- Windows per-application LocalDumps, expandable DumpFolder and account access:
  https://learn.microsoft.com/en-us/windows/win32/wer/collecting-user-mode-dumps

## Final batch06 integration checkpoint

The frozen-source whole-project run passed **3,201 tests in 71.794 seconds**, with
**31 platform/hardware skips** and unchanged source hashes. The 5,000-cycle source
gate, source-package hygiene and eight exact-raster fixtures passed. Windows/Linux
CI and the packaged Windows checks for this new checkpoint remain pending.
