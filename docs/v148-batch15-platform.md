# v1.0.148 batch15 — one checkpoint proof per execution

Baseline: `43a1c968eb56a63224827f1567e4ccc354acdadb`.

This ledger proposes **one behavior group, P1501**. It does not modify the global
registry, version or release status. Repeated checkpoints, initial cancellation,
resume seeding and visual verification are parts of this same execution-owned
checkpoint contract, not separately counted improvements.

## P1501 — reuse the final sequence proof while accumulating completed bits

The real sequence executor saves progress every 25 completed operations and at
completion, Stop and recoverable interruptions. Previously each call to
`checkpoint_sequence_progress` rebuilt and sorted the complete operation catalog,
hashed it, reread the complete source image/context/geometry, and rebuilt every
completion bit. The underlying plan had not changed between these checkpoints.

A deterministic baseline reproduction used the actual `execute_plan` and the
existing native-input raster fixture. It measured calls, not elapsed performance:

| Planned operations | Published completed counts | Catalog builds | Operation hashes inside catalogs | Full context fingerprints |
| ---: | --- | ---: | ---: | ---: |
| 51 | 25, 50, 51 | 3 | 153 | 3 |
| 101 | 25, 50, 75, 100, 101 | 5 | 505 | 5 |
| 201 | 25, 50, 75, 100, 125, 150, 175, 200, 201 | 9 | 1,809 | 9 |

On the 101-operation baseline, Stop was set while hashing operation 10 of the
first periodic checkpoint. Drawing correctly stopped after 25 native paths,
but 193 further catalog-key calls and two complete context fingerprints ran
with Stop already set. The same 25-operation state was created twice before
`InterruptedError` left the executor. The issue was repeated proof work and
delayed cancellation, not extra native input after Stop.

### Implementation and ownership

`SequenceCheckpointSession` belongs to one `execute_plan` invocation. Initialization
freezes the final effective context fingerprint, the canonical operation multiset
and each key's contiguous bit range. It retains hashes and counts rather than the
source image, geometry, plan, callbacks or a global cache. Identical operations
retain their separate canonical occurrences. A live read-only `completed_counts`
view exposes approved progress without allowing external mutation.

The root-owned integration materializes physical widths first, sets the effective
edge behavior and initializes the session before preparing the target or sending
input. It seeds only counts obtained from successful resume verification. A
resumed run still performs its independent initial compatibility check; the new
proof is then reused for all checkpoints in that invocation.

The two existing completion boundaries call `complete(key)`: an ordinary
processed sequence operation, or a contiguous batch after visual verification
has approved it. Deadline-skipped operations remain uncompleted. Unknown keys
and excess duplicate occurrences cannot advance the bitmap. Dynamic reordering
changes execution order without changing the canonical physical operation keys.

`snapshot` creates an independently owned schema-3 dictionary from the current
bitmap. It never rereads the source or rescans paths. Repeated snapshots without
new work reuse the immutable Base64 string; new approved work invalidates only
that encoded bitmap. A Stop snapshot can therefore save already approved work
without rebuilding proof or calling the cancelled initializer.

Catalog initialization polls cancellation while hashing operations, sorting
bounded chunks and merging their keys. Context hashing preserves the exact
historical byte stream, with polling between existing bounded RGBA strips and
JSON chunks. The separate base-metadata pass also forwards cancellation when
reading a repeated color order. Its review regression initially read another
4,930 visits after Stop in a 5,000-visit order; it now stops within the same
256-entry polling bound. Owned temporary strips close if cancellation or reading fails.
`InterruptedError` propagates before input. Other initialization failures disable
checkpointing for that invocation while preserving ordinary drawing behavior.
The existing 25,000,000-operation resume serialization limit does not become a
new drawing limit. Dry runs and executions without a checkpoint callback do not
construct a session.

The existing standalone `checkpoint_sequence_progress` API remains available.
Its raw-key translation, strict physical catalog compatibility, schema, field
values, duplicate occurrence ordering and packed-bit format are unchanged.
There is no promotion of older ambiguous inherited-width checkpoints.

### Distinction from earlier work

SR15 (global registry ID419) reduced duplicate context hashing **inside one
checkpoint call** and bounded its temporary image/flag allocations. Its regression
requires one context hash per call. P1402 established correct physical brush
identity. P1501 reuses that proof **between checkpoint calls during one execution**
and updates the completion bitmap incrementally. It does not recount either
earlier contract or introduce a second persistent checkpoint format.

## Correctness evidence

`test_v148_platform_batch15_checkpoint_session.py` contains **14 tests**. The two
initial actual-executor regressions failed against the baseline with five and
two full context fingerprints where one per fresh invocation was required.

The integrated focused run passed **66 tests in 0.310 seconds**: the new module,
batch14 resume/progress, actual sequence execution, detail-zoom visual
verification, storage resume, rc14 sequence compatibility and rc4 integrity.
The tests cover:

- Exact complete-dictionary parity with the standalone API at every checkpoint,
  plus JSON round trips through the normal resolver.
- One proof for 101 actual operations and five checkpoints, reducing operation
  key calls from 606 to 202 while retaining every native operation.
- Stop after a saved checkpoint, preserving the same approved 25-operation
  snapshot twice without another source/context scan.
- Duplicate canonical occurrences, partial-byte seeding across adjacent ranges,
  unknown/exhausted key rejection and an externally read-only count view.
- Verified resume plus the real replanner and inherited physical widths; a real
  resumed deadline skip remains absent from the bitmap.
- Actual visual verification failure after a 30-path first batch leaves zero
  approved operations, while a later failure preserves only verified base work.
- Stop during initialization before input; owned strip cleanup; independent
  source changes and fresh sessions; snapshot ownership; initialization failure;
  the separate resume capacity limit; no session for dry-run/no-callback paths.

These are focused local results. Integrated full-suite and remote platform
validation belong to the batch checkpoint report.

## Performance measurement protocol

`benchmark_v148_checkpoint_session.py` compares the recorded baseline
`execute_plan` and complete `RenderResume` with the candidate executor/session.
All other dependencies remain identical. It checks the complete checkpoint and
event streams, every deterministic input-boundary command, final checkpoint and
runtime counters on warm, timed and separately traced invocations.

The default fixture has 1,001 operations, a 1,500 × 1,000 RGB source and a
600 × 400 physical canvas. Six alternating AB/BA pairs measure the whole executor
boundary, including identical fixture construction, output hashing and cleanup.
Logical waits and clock values are fixed; this is not a Windows native-device,
GUI, disk-write or real-time drawing throughput measurement.

Separate `tracemalloc` runs report peak Python allocation and live retained
allocation at matching checkpoint callbacks after snapshot creation has returned.
The latter includes the session's retained catalog proof. A faster checkpoint
does not imply less retained memory. Neither metric is RSS or a measurement of
most native Pillow pixel storage. All relevant source hashes must remain
unchanged during the coordinated measurement window.

The final coordinated run includes the base-metadata cancellation completion
described above. It passed every warm/timed/traced comparison; the earlier
independent 31-operation smoke also passed. All 247 recorded source/helper files
remained unchanged during the final run. Full results, raw samples and retained
allocation checkpoints are in `v148-batch15-platform-benchmarks.json`.

| Whole-executor fixture metric | Baseline | Final candidate |
| --- | --- | --- |
| Median of six balanced timing samples | 850.873 ms | 101.189 ms |
| Full context fingerprints | 41 | 1 |
| Operation-key calls, including actual completion | 42,042 | 2,002 |
| Peak traced Python allocation | 3,690,806 B | 3,328,122 B |
| Maximum retained checkpoint allocation above pre-execution baseline | 549,386 B | 661,413 B |

For this fixture the final candidate took 88.1% less measured time and had 9.8%
less peak traced allocation. Its retained checkpoint allocation increased by
112,027 bytes (20.4%), reflecting the longer-lived proof. These figures apply to
the disclosed CPU fixture and do not predict Windows drawing speed.

The final run used Python 3.12.14 and Pillow 13.0.0 on Linux. Every comparison
retained 1,001 processed and sent paths, zero guard skips, and exactly the same
input-boundary, event and checkpoint streams. The raw report records all source
hashes, including `RenderResume.py` at
`2c548265cfc0e9b04fc7fbd84865b6f15348e28bb160bc7a693b4a01dfbcbe9a`
and `DrawBot.py` at
`1468e2134bfc728eb6d88c1ea434bdf25a3beeded6de3d96ba07ca787c00e267`.
No additional improvement is counted for the cancellation review completion or
its final rerun.
