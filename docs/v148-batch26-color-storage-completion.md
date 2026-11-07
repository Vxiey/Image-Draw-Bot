# Batch 26: complete the palette and verified-color storage boundaries

Integration baseline: `5b0c22ac5dc620a911fa2a1f6216e272f644f7db`, with
837 published groups. The earlier two-file proposal was developed against
`586e12d` before an independent batch25 was published. Its historical evidence
is retained below with that original scope; it is not presented as testing
the later incoming commit. The proposal was merged into the new integration
tree and its test/ledger files renamed to batch26. The incoming native screen
sampling implementation in `Colors.py` is preserved.

The final coordinated freeze is based on
`a3b7b929b1332772a089e1819143471ae5d58c68`. That follow-up changes an existing
worker-poll test fixture and its documentation, with no product-code changes.
The targeted results below were obtained on the preceding `5b0c22a`-based
integration; final full-suite results are a separate root-owned gate.

## Scope and count

This is a completion of existing storage contracts and adds **zero improvement
IDs**. The strict JSON reader is **SS03 / global 183**; durable publication and
reuse of its shared helper are **SS01 / global 181** and **SS02 / global 182**.
The shared reader's allocation behavior is already **P2301 / global 828**.
Using that reader in these remaining callers does not create another
performance group.

The final product changes are confined to `Colors.py`, `ColorCache.py`,
`RuntimePaths.py` and the grid-preference read in `GetColorPositions.py`.
Calibration domain validation, native drawing and sampling, profile selection
and calibration coordinates are unchanged. The shared JSON reader's existing
implementation is reused; a bounded text wrapper handles the legacy positions
file without duplicating its chunk-reading loop.

## Reachable failures and before evidence

The before tests exercised the actual consumers through temporary files:

* `DrawBot.refresh_palette` calls `Colors.load_calibration`; palette metadata
  readers also use `Colors.calibration_metadata`.
* The legacy `load_calibration` fallback reads `positions.txt`, then
  `palette.json`, before committing the resulting palette.
* `CalibrationState.exact_color_state` reads `ColorCache.load_cache`, and
  `ColorCache.put_verified` reads the previous cache before adding new evidence.
* The real `GetColorPositions.CalibrationApp.save` calls
  `Colors.save_calibration`, then saves its grid preference and closes the
  dialog after a successful calibration write.

The final before run of the fourteen new methods produced **42 assertion
failures across twelve methods**, with two positive methods passing and no
test `ERROR`. It ran in 0.119 seconds. These are failing subcases, not separate
improvement claims. The two passing methods covered supported calibration
versions, metadata, ARGB and anchor translation, plus the real verified-color
writer, BOM input, context/profile/workflow isolation and detached return data.

The old palette readers accepted duplicate object keys, nonfinite values and
excessive nesting. `refresh_palette` could mark such a document ready, while
the verified-color status could report `verified` for an ambiguous cache.
The actual cache writer subsequently retained ambiguous old evidence while
adding a new verified color. Colors also read its JSON without a byte limit.

The actual save controller stopped on the first simulated transient Windows
sharing error. An unsupported `fsync` stopped saving, and an owned temporary
file's cleanup error could replace the primary storage error. The destination
and draft preservation checks remain part of the regression.

The before test was run from scratch while the batch24 repository was frozen.
Its product files are byte-identical to the published
[`586e12db5ea5142951c844f60dc2364f07a01c37`](https://github.com/Vxiey/Image-Draw-Bot/commit/586e12db5ea5142951c844f60dc2364f07a01c37)
baseline:

| File | Before SHA-256 |
|---|---|
| `Colors.py` | `a89301a8397484092714431771a3d9cb5fe1ab7e22aa6ebe9755a3d3dbd0f942` |
| `ColorCache.py` | `646ae6933ac0d7de88182ecf74f8666dfb7673cfefd3a40e6fbc1f761aec6f95` |

The initial scratch run was superseded after isolating each consumer's global
palette setup. Its log is retained, but the final counts above come from the
corrected fixture. In this Python runtime a 2,000-level JSON value was accepted
by the old reader. This demonstrates missing depth validation; it does not
demonstrate a `RecursionError` or an application startup crash.

## Completed behavior and preserved data

`load_palette`, `calibration_metadata` and the JSON branch of
`load_calibration` now use `RuntimePaths.read_json` with an **8 MiB** byte limit.
This is a new bound for the previously unbounded Colors readers, harmonized
with `ProfileStorage.MAX_CALIBRATION_CONTEXT_BYTES` and the existing profile
export budget. It is not described as an already-existing Colors limit.

`ColorCache._read` uses the same shared reader with its **unchanged 1 MiB**
limit. Both paths inherit rejection of duplicate keys, nonfinite values,
excessive depth and excessive item counts. Reads request at most 64 KiB at a
time and stop after the configured limit plus one byte. Exact-limit valid
documents remain accepted. A malformed verified-color document remains a
cache miss, allowing valid evidence to be learned afresh.

All calibration domain checks remain in their existing order after JSON
decoding. Supported versions 1–4, RGB/ARGB conversion, Unicode names, native
color indices, state and verification metadata, profile ownership and anchor
translation are preserved. A metadata-only read does not mutate the global
palette. A rejected direct load does not publish partial colors. In the legacy
path, even a failure after positions have been provisionally loaded restores
the prior positions and colors. Successful replacement still invalidates the
nearest-color lookup cache.

`save_calibration` validates the same data, serializes complete finite JSON
with `allow_nan=False`, then uses the existing `atomic_write_text` helper. It
still returns `None`. The existing destination survives failed serialization,
flush or publication; each attempt owns its staging file. The shared publisher
retains its bounded retries for Windows error codes 5, 32 and 33, its explicit
unsupported-sync fallback and its preservation of a primary failure when
temporary cleanup also fails. A failed controller save retains the reviewed
draft and keeps the dialog open. A successful save preserves the metadata and
native index map, saves the grid preference and then closes normally.

## Historical verification before integration

The original `test_v148_platform_batch25_color_storage.py` had fourteen
actual-flow methods; they are now in
`test_v148_platform_batch26_color_storage.py` without assertion changes.
It uses real temporary files, JSON readers, calibration writers, cache writers
and controller methods. Only UI objects without a native interpreter and the
OS failure/wait boundaries are replaced. Storage paths stay in each test's own
temporary directory, and the original global palette objects and their
attributes are restored after each method.

| Gate | Result |
|---|---|
| Final before, same fourteen methods | 42 assertion failures across twelve methods; two methods passed; no test errors; 0.119 s |
| After implementation | 14/14 passed, no skips, 0.077 s |
| Independent after review and execution | 14/14 passed, no skips, 0.100 s; no source-review blockers |
| Initial adjacent calibration/cache/storage/UI gate | 183 methods: 175 passed, seven existing native skips, one older injection-boundary mismatch; 2.038 s |
| Final adjacent calibration/cache/storage/UI gate | 183 methods: 176 passed and seven existing native skips; 1.987 s; no failures |

The initial adjacent failure was in the older
`test_atomic_calibration_failure_keeps_previous`: it injects failure into
`Path.replace`, while the shared publisher correctly uses `os.replace`.
The root maintainer updated only that injection to `RuntimePaths.os.replace`.
The original exception, destination-byte and temporary-cleanup assertions are
unchanged and all pass in the final adjacent rerun. No production change was
needed after the first fourteen-method after gate.

The adjacent run includes real verified-cache reload/eviction behavior, profile
isolation, native index and anchor handling, Paint verification and numeric
recovery, source-archive privacy, reviewed UI drafts and the asynchronous
palette-controller tests. It also exercises the shared storage writer,
Windows-retry policy, strict JSON reader and its legacy storage regressions.
The seven skips are the existing two native PowerShell parser cases, two
Windows calibration-layout cases, one native Windows sharing test and two
native Tk palette-scan cases; no skip condition was changed.

Scratch evidence is retained as `batch25-color-storage-before.log` (superseded
fixture), `batch25-color-storage-before-final.log`,
`batch25-color-storage-after.log`, `batch25-color-storage-independent.log` and
`batch25-color-storage-related.log` / `batch25-color-storage-related-final.log`.
## Remaining grid and legacy-position boundaries

`CalibrationApp.__init__` still read its saved grid preference with unbounded
`read_text` and `json.loads`. The actual constructor accepted duplicate keys,
nonfinite extra metadata, a 40-level extra value and an over-budget document
as a valid 1-by-3 preference. The legacy `load_calibration` fallback similarly
accepted an over-budget `positions.txt` whose whitespace preserved all integer
coordinates and the required line count, then published a replacement global
palette.

The initial scratch probe on the earlier frozen tree ran two actual methods
with 11 expected assertion failures and no test errors in 0.053 seconds
(`batch25-remaining-palette-boundaries-before.log`). Its observed text read
count was characters after CRLF translation, not bytes; the real oversized
file was 8 MiB plus one byte. A fresh before gate in the new `5b0c22a`-based
integration tree repeated both actual consumers and added accepted-boundary
read assertions: **13 expected assertion failures, no errors, 0.088 seconds**.
The two additional failures identify unbounded reads even for otherwise
accepted inputs. The log is `batch26-palette-boundaries-before.log`.

The constructor now uses the existing strict JSON reader with its default
**4 MiB** budget. This is a newly applied bound for this formerly unbounded
preference file. Invalid data leaves the existing 2-by-9 defaults and does not
rewrite the file. The existing integer, positivity and maximum-color rules
still run after decoding. The valid exact-limit and UTF-8 BOM cases are covered.

`RuntimePaths.read_bounded_text` opens one binary stream and borrows the
existing bounded chunk reader. It reads at most limit plus one byte, rejects
overflow before decoding and closes the stream before decoding. It preserves
CR/LF characters and the requested encoding. `Colors.load_positions` uses it
with the same **8 MiB** calibration budget as the JSON paths, before its
unchanged full coordinate-count and integer validation. Valid negative
coordinates and CRLF files, including the exact byte limit, remain supported.
Malformed encoding, a UTF-8 BOM in the legacy numeric format, invalid numbers,
wrong coordinate count and overflow all preserve the global palette through
the actual legacy fallback. No new recovery or recursion-crash claim is made.

`test_v148_platform_batch26_palette_boundaries.py` adds four methods. They
execute the actual dialog constructor, legacy calibration fallback and shared
text reader using real temporary files; only native widgets/mouse creation
are replaced. File-read observers change no bytes. The text-reader control
also verifies exact newline preservation and closed streams while a decoding
exception remains referenced.

## Current integration verification

| Gate on the new integration tree | Result |
|---|---|
| Fresh before, two remaining actual consumers | 13 expected assertion failures, no errors; 0.088 s |
| Fourteen merged storage methods plus four new boundary methods | 18/18 passed, no skips; 0.154 s |
| Storage, calibration, actual UI-save/scan, shared-reader and incoming native-sampling regressions | 221 methods: 215 passed, six existing platform skips; 2.753 s; no failures |

The final related selection includes the incoming
`test_v148_native_batch25_screen_sampling.py` and palette-preparation tests,
the earlier atomic-save failure assertion, actual source-archive privacy and
the strict JSON reader's own regression module. Native Windows execution is
not inferred from Linux skips. Current logs are
`batch26-color-storage-after.log` and `batch26-color-storage-related.log`.

The root and an independent UI reviewer closed source/method review without
blockers. The independent reviewer read the entire product diff and all
eighteen methods, including incoming native-sampling preservation, the single
bounded stream, exact-limit/encoding controls, palette rollback, grid defaults
and actual save/close ordering. No additional overlapping test run was made;
the execution results above are the recorded author gates.

No performance measurement or universal speed claim is made. Windows sharing
failures are injected at the actual writer's OS boundary on Linux. The native
Windows gate, whole-project validation and publication belong to the batch
finalizer; earlier commits' CI does not validate this new work.
