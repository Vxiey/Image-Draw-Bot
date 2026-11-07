# v1.0.148 batch14 — ordered recovery and source/runtime diagnostics

Baseline: `f7b561f479d94f307924dbc779e5c8e365422f8d`.

This ledger proposes **four distinct behavior groups, P1401–P1404**. Their
failure cases and regression variants are parts of those groups. It does not
change the global registry or claim publication of release 1.0.148.

## P1401 — checkpoints identify repeated color-batch occurrences

The native color-batched executor accepts an explicit order such as
`[black, blue, black]`. `RenderResume.active_color_order` instead deduplicated it
to `[black, blue]`. The final checkpoint then rejected the executor's third
completed batch, and a path checkpoint could not identify that second visit to
black. The shorter and repeated schedules also shared a plan fingerprint.

Retain every nonempty requested occurrence. The first visit keeps its historical
batch key; later visits include their occurrence number in the key. Completed
and active-path checkpoint validation compare those occurrence-specific keys.
The existing rejection of duplicate completed keys remains in place, so this
does not relax corruption validation. A checkpoint made for the old, deduplicated
schedule is incompatible with the actual repeated schedule.

The tests call the actual `execute_plan` with `[0, 1, 0]`, persist its completion
state through JSON, and validate all three unique completed keys. A second
fixture resumes at path two of the second visit to color zero and records only
that one native path. Swapping its active key to the first visit is rejected.

## P1402 — resume and replan retain each operation's physical brush width

Execution-sequence rows may inherit the preceding nonempty row's brush width.
The baseline resume catalog hashed the raw rows, so a permutation that changed
an inherited physical width could still match the old catalog. Skipping a
completed width-changing row also removed the physical context of the next
row: a path intended for 1 px could resume using the initial 5 px brush. A
deadline skip before brush switching had the same consequence.

`execution_sequence_with_brushes` materializes the intended width before resume
filtering and runtime replanning. It does not modify the original sequence or
its rows; already explicit valid widths can reuse their row object. Empty-path
rows are not drawing operations and do not change width inheritance. The resume
catalog hashes these effective operations, and the executor uses the same rows.
Explicit-width permutations retain their existing order-independent identity.
A raw permutation that changes an implicit width, or an old ambiguous implicit
catalog, is rejected. Existing fully explicit checkpoints remain compatible.

The new iteration checks Stop every 256 raw rows and after the last row.
Serialization's 25,000,000-operation cap remains in the resume catalog, without
becoming a new limit on ordinary execution iteration. These cancellation and
limit details complete this group and add no separate count.

Review also caught an empty-normalization regression: a nonempty raw sequence
containing only empty or invalid operations became an empty normalized list,
which selected the old color-group fallback. The actual HEAD executor sent zero
canvas paths for that explicit sequence; the intermediate patch incorrectly
sent three legacy paths. The executor now preserves the raw sequence's presence
as its execution-mode decision while iterating only valid normalized operations.
An absent or empty raw sequence retains ordinary batch behavior. This is an
uncounted completion of P1402, covered by an actual native-input regression.

The integrated suite also exposed the public checkpoint-writer contract:
callers may pass `sequence_entry_key(raw_row)`, even when that row inherits its
width. Filtering those keys against the new physical catalog lost completed
work. Checkpoint creation now translates a requested raw key only when every
matching occurrence has the same effective operation key. Duplicate operations
retain their occurrence counts, and raw and materialized keys can coexist.
One raw key occurring at different inherited widths is rejected with a concrete
error requiring materialized keys. The ordinary executor already supplies those
keys and avoids this translation pass. Existing stored implicit catalogs still
fail compatibility checks; there is no legacy fingerprint fallback. Four public
API/native replay regressions failed before this correction and pass afterward.
This completes P1402 without adding a behavior ID. The older deduplication test
now asserts the actual repeated execution order while retaining its invalid
index and execution-only coverage; the older color-zero API test is strengthened
to require a compatible checkpoint with exactly one completed operation.

The independent native-input raster fixture proves the actual width after
resume and a real `DeadlineScheduler` skip. The real replanner can reorder
materialized rows while preserving both their widths and checkpoint identity.
The original plan remains unchanged. Stop during actual executor materialization
produces only mandatory mouse-release cleanup, with no moves, clicks or presses.

The root-owned `DrawBot.py` integration imports the helper and passes
`cancelled=stop.is_set` before execution filtering/replanning. Path-level resume
already compares `active_color_number`; it needed no weakening or replacement.

## P1403 — one source launcher owns its environment through application exit

`Start.bat` invokes `SourceStartup` before the application's own single-instance
check. Two source launches could therefore create or install into the same
`.venv` concurrently. `Start.bat --update` could also replace dependencies while
the first source application was still using that environment.

The baseline regression starts a real independent Python process running the
public startup flow, replacing only external venv/pip/application processes
with harmless fixtures. While the first invocation is held at dependency
installation or the live-application boundary, a second `main(['--update'])`
incorrectly succeeds and runs its package mutations. Both cases fail before
the product correction.

`start_source` now owns a nonblocking, cooperative file transaction from before
private environment setup through the launched application's exit. A contender
gets a concrete busy result before running venv, pip, optional GPU setup or the
application. The lock lives at `build/.source-startup.lock`, outside the
environment it protects and inside an already excluded source-package directory.
The persistent sidecar is intentionally retained; ordinary exit and failure
release the OS lock, and resolved checkout aliases share the same owner.
Independent checkouts remain independent.

This is distinct from BP02's private-interpreter/package-target policy and
P1001's release-builder ownership. It reuses the existing bounded local file
transaction instead of replacing its OS locking or exception-preservation
contract. Package policy, startup arguments, explicit GPU setup and the
application's exit code retain their previous behavior.

The process-termination fixture proves that an exited launcher does not leave
a permanent stale OS lock. Its external-process boundary is simulated: this
change does **not** supervise or terminate a real pip/application process that
outlives a forcibly killed parent. Direct launches or unrelated tools do not
participate in this cooperative source-launcher lock.

## P1404 — bounded diagnostics keep the active profile's evidence

The collector kept the lexically first 100 settings files and 100 calibration
files. With 101 saved profiles, that could exclude the profile for which the
user requested diagnostics. The summaries' intentionally opaque labels also
gave a reviewer no reliable way to identify the active record.

The UI context now supplies the applied profile name and its canonical storage
key. It uses `_active_profile_name` when a different combobox selection is
pending, keeping the context tied to the files actually in use. The collector
prioritizes that profile's canonical settings/calibration paths inside the
unchanged 100-candidate budget for each kind. Selection still uses a bounded
heap and checks cancellation while enumerating; it does not retain every path.

`profile-summary-selection.json` maps the active records to opaque entry labels
in the two existing summaries. Missing, unreadable or invalid JSON records
remain unassigned rather than pointing at some other profile. The storage key
and raw filenames are not included in that map. Standalone collection without
a profile retains its previous lexical selection. Generic legacy filenames
(`settings.json` and `calibration.json`) are supported.

Actual context-to-ZIP tests cover the 101-profile case, a pending profile
selection, generic/standalone collection, unavailable active files, linked
inputs and cancellation. Existing filename redaction, coordinate omission,
read limits, temporary-archive cleanup and earlier exports remain protected.
The bounded inventory/heap guarantee is the existing SR31 contract; it is not
counted again. Privacy and cancellation are likewise retained contracts.

## Local validation

| Area | New cases | Combined result | Evidence |
| --- | ---: | --- | --- |
| Ordered resume identity and physical widths | 17 | 132 tests passed in 0.788 s | `test_v148_platform_batch14_resume.py`, legacy batch/path/sequence recovery, storage resume, actual sequence execution, preview-order tests, the original hundred-improvements suite and rc4 recovery integrity |
| Source startup ownership | 4 | 11 tests completed in 2.665 s; 1 Windows-only batch-launcher case skipped on Linux | `test_v148_platform_batch14_startup.py` plus `test_v148_platform_batch08_startup.py`; real spawned owners and a real isolated temporary Python environment probe |
| Active-profile diagnostics | 5 | 77 tests completed in 0.208 s; 1 platform-specific case skipped on Linux | `test_v148_platform_batch14_diagnostics.py` plus existing diagnostics, privacy, recovery and Stop suites |

These are local focused results, not a claim about the integrated full suite,
Windows CI or a published checkpoint. No benchmark speed or memory improvement
is claimed. The startup process fixtures do not install packages or launch the
real application. Root owns integrated validation, registry reconciliation,
commits and remote checks.

## Release-publication path inspected without running it

The existing `.github/workflows/build-windows.yml` accepts a manual dispatch,
a `v*` tag, or a main push affecting `Version.py` or
`.github/release-build-trigger`. All release workflow invocations share one
serialization group. A feature-branch manual run can build workflow artifacts;
the publication step runs only for main or a version-tag ref.

Before publication the workflow runs source hygiene and the 5,000-cycle source
gate, complete tests/self-test, builds the Windows bundle and installer, validates
the asset set, and performs a silent install/self-test/uninstall round trip. It
checks the installed icon and shortcut. The round trip currently runs the
installed executable's `--self-test`; it does not run an installed GUI smoke
test. The separate CI workflow exercises the bundled GUI/native drag-and-drop.

Publication checks that the requested tag matches `Version.py`, refuses to
replace an already published version, requires a resumed draft to belong to
the exact build SHA, verifies or creates that exact tag, uploads the complete
asset set into a draft, rechecks tag identity and only then publishes. No
workflow, version, tag, draft or release action is changed by this batch.
