# Batch 31 — release the local import stream after a retained failure

Baseline: published `e49e2535c5f8edea80e47824fe56cae58781b971`, with **842**
implemented groups. This is an **IW08 / IW35 / IW38 completion, zero new IDs**:
it finishes existing import resource ownership, same-descriptor snapshot and
cancellation contracts. It adds no source format, decoder, byte limit or input
authorization.

Status: product, independent source review and the coordinated batch gate pass.
The completed integrated evidence is recorded below; no release is claimed.

## Actual before behavior

The public application loader `DrawBot.load_image` calls
`ImageImport.read_image`. A local import constructs its own `_local_chunks`
generator, which holds a regular source file inside a `with` block while
suspended at `yield`. `_write_chunks` can fail after receiving that chunk:
Stop can arrive after the real read, the private snapshot write can fail, or
actual file growth can reach the cumulative byte-limit sentinel.

Previously, the consumer did not close its private generator. The private
snapshot was closed, but retaining the original exception and traceback also
retained `_write_chunks.chunks`, the suspended generator and the open source
descriptor. This is a lifetime dependent on traceback retirement, not a claim
that every ordinary UI error permanently leaks a file.

The before probe ran against the untouched batch30 checkout with private
runtime/temp state and filesystem/network auditing. It recorded real
`stream.closed` and `os.fstat(fd)` observations while keeping the original
exception and traceback alive, without clearing frames:

| Actual boundary | Source stream / descriptor before | Private snapshot before |
| --- | --- | --- |
| `read_image`: Stop after a positive read | Open / open; 102 source bytes read | Closed |
| `DrawBot.load_image`: the same post-read Stop | Open / open; 102 bytes read | Closed |
| Partial snapshot write followed by `MemoryError` | Open / open | Closed |
| Partial write plus a secondary source-close failure | Open / open | Closed |
| Real file growth after the size check | Open / open; exactly limit + 1 bytes consumed | Closed |
| Successful exact RGBA decode | Closed / closed | Closed |

The new regression module ran **7 methods, with 5 expected failing subcases
across 4 methods, zero errors and zero skips** on the baseline. Success,
ordinary source-close failure and generic borrowed-iterator controls passed.
All **893** root Python hashes stayed unchanged, canonical digest
`0da8de7641efb47fea77c62ece22629b27f9425c137e9d8ccd8d7e9933ae5845`.
The scoped audit reported zero violations.

Before evidence is retained under
`pending-batch31-import-stream/before-scoped/`; its `summary.json` SHA-256 is
`c6219bee6a85708898d4046b12e405f29f78a4333b4cac0dcfd2e0daadbc2db4`.
`probe_import_stream.py` and the full per-method `tests.log` accompany it.
The initial `before/` and `before.log` are also preserved: that harness rejected
a harmless `/dev/null` open during library import and therefore failed its
final audit assertion. The scoped rerun permits that null destination in
addition to its exclusive private output directory; it still prohibits
checkout mutations and network access. The first run is diagnostic evidence,
not the accepted audit gate.

## Narrow ownership correction

Only the local-source branch of `read_image` changes. It explicitly owns the
fresh `_local_chunks` generator and closes it before propagating a consumer
failure. If closing reports a secondary ordinary exception, the original
failure object and traceback survive, with a short cleanup note. Ordinary
source-close errors on exhaustion still fail the import through the previous
error type and cause; a successful decode is never fabricated.

The generic `_write_chunks` consumer remains borrowing. It does not close
caller-provided iterators or destinations. HTTP/data-URI routing, all read
sizes and byte accounting, actual-growth rejection, format detection,
orientation, color conversion and returned image ownership remain unchanged.
There is no general traceback clearing or change to borrowed OS handles.

## After evidence and controls

The same source-bound probe passed on the initial integrated batch31 snapshot:

- All five retained-failure observations now show both the owned source stream
  and its real descriptor closed. Their private spools are also closed.
- Primary partial-write exceptions remain the identical objects. The retained
  original traceback remains inspectable; the secondary close error is a note.
- Exact successful RGBA bytes, dimensions, format metadata and borrowed-reader
  position match the before observation.
- Seven regression methods pass with no errors or skips. They additionally
  cover RGB/RGBA/palette-transparency PNGs, independently opened borrowed source
  handles, an ordinary close failure, and generic borrowed iterator/destination
  lifetime on success and Stop.
- The adjacent import, decoder, redirect, transfer-encoding and actual
  clipboard-to-loader gate passed **57/57 methods in 0.165 seconds**, no skips.
  This is regression-suite elapsed time, not a product performance measurement.

The initial after probe binds **895** unchanged root Python files, canonical
digest `c845b2b6025e917fd8f054c34ec953a6a019986e8ffb22dfa8f2efab7b9e91e0`,
and reports zero audit violations. Its raw report is
`pending-batch31-import-stream/after-initial/summary.json`, SHA-256
`03a1a0f1fe8f29be77f5d9fd279ae87cfae8daee806d6d9b6e096c0ccefa1939`.
This is an explicit checkpoint, not a substitute for the later final batch
source manifest.

Reviewed product SHA-256:
`ImageImport.py` — `0db85320504a83769ee977c02dba9d1cd984e0481cd1983963b1a776a121a751`.
The unchanged seven-method before/after test file SHA-256 is
`293b928f4b28e030b61857426b274943f354d66654874186c10453559ec75bee`.

The descriptor observations use real local files on Linux. They establish
deterministic source-stream cleanup; no physical Windows sharing-lock test,
RSS reduction, elapsed-time improvement or decoder-interruption guarantee is
claimed. Native filesystem and decoder calls already in progress remain
subject to the existing cooperative cancellation boundary.


## Integrated frozen-source result

Batch 31 records **843 distinct improvements, 157 remaining**. One contour-prefix work-reduction group is registered as R3101/global843. Local import-stream and outer Portrait-plan ownership complete existing contracts with zero IDs. All 842 preceding registry entries and 80 prior benchmark JSON reports are preserved. Completed frozen discovery ran **4,569 tests in 244.002 seconds: 4,496 passed and 73 skipped**, with all 947 source/configuration hashes unchanged. Fourteen Linux/Xorg native cases, the 5,000-cycle source gate, eight exact existing-raster fixtures and initial package hygiene (1,370 files) passed. The package check after final metadata passed with 1,372 files and no warnings. Seven complete historical Portrait public-plan pairs retain finite time-fitting, actual rescue and borrowed inputs. The contour experiment compares the whole published Portrait module within shared current dependencies: 3 complete preparations, 39 exact helper/public comparisons and 9 workloads with six balanced pairs and separate traced allocations. Scanning and the cell-winner dictionary remain; whole-helper and whole-public-plan observations, slower controls and allocation costs are kept separate. Early source maps, expected red proofs and initial harness diagnostics remain explicit. No universal application speed, RSS, physical drawing or GPU improvement is claimed. Published parent e49 passed seven exact-head checks and all fourteen Windows steps on attempt one; the new head requires its own CI. Version 1.0.148 remains unreleased.

Final gates bind **897 root Python files**, compact SHA256 `325d536b457d8b384a0738efab531ae0f6d773db5fb30fa569e56dbc0d7e329f`, and **947 source/configuration files**, compact SHA256 `1ae580174ddabeb86dc289c6fdfbc17eddcea9085b9c4671ce71ae6b3182501e`. Earlier red and focused checkpoints retain their original maps and labels; no failed harness or expected before failure is presented as a passing integrated gate. The parent Windows run is separate from the new head. Independent metadata review and post-metadata package hygiene are recorded separately in [final validation](v148-batch31-validation.json).
