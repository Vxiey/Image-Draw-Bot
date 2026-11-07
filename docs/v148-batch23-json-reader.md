# Batch 23: bounded allocation while reading local JSON

## Scope and historical source

Verified and registered group **P2301 / global 828**, covers one shared reader change: `RuntimePaths.read_json` grows its input storage from bytes actually read, instead of asking the file object to allocate the whole allowed file size for every small document. The integrated correctness gate, final paired measurements and registry finalization are complete. The product edit is confined to `RuntimePaths.py`; its existing JSON decoder and duplicate-key, finite-number, depth and item checks are unchanged.

The integration and final historical benchmark baseline is `5c32b6883c454268e06e199a8f15264ca9ec26e9`. The initial reproduction used `92d5a86709a61802821780f5866409da6cd8cf2e`, before the test-only repair `be30fa54a0c58a8d2b6535d31cb6672727f4e6cc` and the independently published batch22 changes. The complete `RuntimePaths.py` bytes are identical at these baselines, with SHA-256 `ab1bba9cb165e134f2f3197ca99ddaea4dbbd9fbf3414737ab8383f70c06d1e7`. The final benchmark now loads the complete reader from `5c32`; both sides use the same current integrated consumer dependencies.

The reader work was moved from its provisional local batch22 name to **P2301** after the external batch22 was discovered. A read-only transfer review confirmed that `RuntimePaths.py` and the thirteen-method regression file are byte-identical to the reviewed local implementation. The benchmark changes only its baseline, renamed test import, scratch prefixes and report path. The shared reader, measurements, controls and assertions are unchanged. The earlier local evidence remains evidence for its recorded snapshot; the separate final integrated gate and paired measurements are recorded below.

No calibration lookup, context identity, writer/reset policy, application UI, safety limit, drawing geometry or image quality rule changes. There is no additional group for the individual consumers, failure cases or cleanup checks.

## Actual before behavior

The baseline reader used `stream.read(max_bytes + 1)`. On the available CPython regular-file implementation, this reserves a buffer based on the requested size even when the actual file is only a few hundred bytes. This is separate from the already optimized number of database observations in R2101.

The initial read-only probe used actual production writers to create private timing, speed, scheduler and recovery files, then called their real consumers. The public planning fixture used the real `DrawBot.make_plan` Paint Pixel route, a generated 128 × 96 RGBA image and a calibrated palette. Source and fixture files remained unchanged. Read-call observation and allocation tracing were separate; no elapsed times were collected.

| Actual consumer | Input bytes in the initial probe | Largest read request, B | Traced peak before, B |
|---|---:|---:|---:|
| `DrawTimeCalibration.correction_for` | 4,262 | 4,194,305 | 4,203,262 |
| `RealSpeedBudget.load_profile` | 416 | 1,048,577 | 1,056,600 |
| `ResourceScheduler.load_recommendation` | 235 | 262,145 | 268,267 |
| `SessionRecovery.load_render_progress` | 790 | 8,388,609 | 8,394,548 |
| `SessionRecovery.load_snapshot` | 522 state + 790 render | 8,388,609 | 8,398,200 |
| Complete public Paint Pixel plan | 4,262 timing | 4,194,305 | 4,644,975 |

The public Pixel plan already observed its timing database once through R2101. P2301 does not claim to remove another database observation; it changes the allocation within that one read.

An attribution control read the same 4,262-byte regular file with the same complete payload hash. Requesting 65,536 bytes gave a traced peak of 65,909 bytes; requesting 4,194,305 bytes gave 4,194,678 bytes. Both retained the same 4,295 bytes after the read. This directly isolated the requested-size reservation from schema validation or application work. The payload SHA-256 was `3ae4025f3e003dfc7d5141fd3a66fa225f38c220ff1c4679f80b8176afed1e33`.

The two new before-regression methods produced **seven real failures**: all six actual consumers requested more than one 64 KiB block, and a small valid JSON file with an 8 MiB allowance had a traced peak of about 8.39 MB instead of staying below the regression's 256 KiB bound. This was measured behavior on the complete old reader, not a missing-helper test. Initial evidence is retained under its original task scratch name, `batch22-json-reader-before.json`, and corresponding before logs; renaming the integration batch does not change that evidence's provenance.

## Read, ownership and error contracts

The new private `_read_json_bytes` helper opens no file itself. The public reader keeps its single existing `Path.open('rb')` context and supplies that descriptor. Each request is the smaller of 64 KiB and the remaining `max_bytes + 1` allowance. Positive short reads continue; only an empty byte string indicates EOF. The cumulative overflow sentinel remains authoritative even if a file grows while it is open. There is no pre-read `stat`, seeking, reopening, or assumption that a short positive read means the file ended.

The common small-file path keeps one returned block and confirms EOF without constructing an accumulator. Multi-block files use a locally owned `BytesIO`, which grows from actual input and closes before decoding begins. Both the native input file and the accumulator close on success or exceptions. A helper-level `finally` clears input block, stream and accumulator aliases so its retained traceback does not keep those buffers alive. Failure of a real read and failure while appending a block are tested separately. Unicode/JSON exceptions retain their normal diagnostic input and positions; the error contract is not weakened to avoid that existing diagnostic ownership.

`operator.index(max_bytes + 1)` retains the integer-index requirement of the native read. Limits outside the native signed-size range remain overflow errors. Invalid negative limits cannot accidentally turn into an unbounded `read(-1)` allocation. The existing public size rejection still occurs after the input file's context has closed, preserving close/error ordering for valid size limits.

The complete collected byte sequence is decoded once with the existing `utf-8-sig` policy. A BOM or multibyte character crossing a block boundary therefore receives the same treatment as in the old one-read decoder. Invalid UTF-8/UTF-16, duplicate keys, nonfinite numbers, excessive container depth, excessive item counts and malformed JSON preserve their decoder/validator behavior and real caller fallbacks.

The bounded approach does more reads. A small valid file normally needs one data read and one EOF read rather than one request for the full allowance. A valid exact-4-MiB file needs 65 requests, including the final sentinel/EOF check; an exact-8-MiB file needs 129. A file one byte over the 8 MiB limit also needs 129 requests but returns the actual overflow byte and is rejected without an extra unbounded read. Growing accumulator storage can increase work or peak allocation for large near-limit files. The final comparison includes those cases; no universal memory or elapsed-time reduction is assumed.

## Complete historical comparison and actual work

`benchmark_v148_platform_batch23_json_reader.py` loads the complete historical `RuntimePaths.py`. It installs that module for local imports and binds all six imported reader aliases used by these consumers: `DrawTimeCalibration`, `RealSpeedBudget`, `ResourceScheduler`, `SessionRecovery`, `ExactColorTools` and `CorrectionHistory`. All other consumer and planner code is identical on both sides, including the already published R2101 scope. This prevents the historical consumers from silently calling the new helper.

The original public-plan fixture has no optional exact-color-controls or correction-history files. Both readers keep their actual missing-file fallback; no extra history is seeded to magnify the comparison. A final review extended the explicit historical linkage to these two aliases as well, and the benchmark now asserts their absent fixture state. Root independently observed the same four actual public-plan paths, modes and order on both sides: exact controls, timing calibration, Real-Speed and correction history. The final run uses the complete six-alias linkage.

The original pre-integration verification-only run passed **79 complete reader pairs** and **11 workload pairs**, with all 830 root Python files unchanged during that exploratory run. These are the original snapshot's counts, not the final integrated source manifest. Reader comparisons include complete values; error class/message; UTF error encoding, reason, offsets and input hash; and JSON error position, line, column and input hash. Fixtures cover primitives, nested containers, BOMs, UTF-8 across block boundaries, exact/overflow byte limits, malformed data, accepted/rejected 100,000-item boundaries, deep nesting and missing files.

The eleven complete workloads comprise the six real consumers above, a small document with an 8 MiB allowance, an ASCII JSON string exactly 4 MiB long, a UTF-8 string just below that limit, an exact-8-MiB whitespace-padded valid value, and an 8-MiB-plus-one size rejection. All warm and observed outputs must match. The public plan comparison includes full image bytes, groups, selectors, paths, estimates and metadata; only explicitly named existing profiling-clock fields from the earlier public-plan comparator are excluded. No calibration, estimate, drawing budget or size-bound result is excluded.

Read observation is separate from timing and allocation tracing. In both the initial verification and final integrated run, each targeted consumer file remained opened once. Total returned file bytes were identical. Each small consumer file changed from one full-allowance request to two requests of at most 64 KiB; the two-file recovery snapshot changed from two requests to four. **The public Pixel plan's work counter observes its targeted timing file only.** The complete timed plan also invokes the real Real-Speed reader and the two optional missing-file readers described above. Its timing-file counter is not a count of all plan I/O.

The final timing file is 4,261 bytes, the speed file 416, the scheduler file 244, the render progress file 790 and the recovery state file 522. Independently seeded production timestamps can change a few file bytes between the initial probe and final benchmark. The scheduler fixture also uses `controlled-reader-fixture` as its explicit matching signature, where the initial probe used `controlled-probe`; this accounts for its 235-to-244-byte fixture difference. Each before/after pair uses the same unchanged files, recorded with their own sizes and hashes.

The focused short-read, file-growth/truncation and retained-exception tests provide independent behavioral oracles. They are not described as historical byte-for-byte concurrency comparisons: splitting a read necessarily exposes different possible mutation interleavings. The preserved contract is one descriptor, bounded actual consumption, complete decoding before acceptance and safe fallback on invalid data.

## Tests and independent review

The thirteen new methods cover actual consumer output/file parity; the measured small-file allocation; exact size/sentinel boundaries; positive short reads and valid-prefix rejection; cumulative short-read limits; invalid index types/ranges; BOM/multibyte boundaries; invalid Unicode, duplicate/nonfinite/depth/node rules; growth without `stat`; truncation; retained read/Stop/allocation errors; append-allocation errors; and real caller fallback behavior.

Before integration onto `5c32`, the focused storage/security/I/O/learning/runtime-paths/R2101 gate ran **89 tests in 2.767 s, with one existing skip**. The independent platform agent read the entire product diff and new tests, then ran **all thirteen new methods successfully in 0.745 s**. That source review is closed without blockers. Root also reviewed the bounded-size, one-descriptor, accumulator and error-ordering design, and the independent transfer review confirmed the identical product and regression code.

The final integrated unittest discovery ran **4,270 cases in 206.108 s: 4,211 passed and 59 were skipped**. All **891 checked source/configuration hashes** stayed unchanged. The subsequent 5,000-cycle source gate, eight existing exact-raster fixtures and hygiene check over 1,245 files also passed. These integrated results supersede the earlier separate local tree's full-suite result for publication purposes.

## Final integrated measurements

Root ran the following command after the integrated correctness gate, alone in the coordinated quiet source/CPU window:

```text
.venv/bin/python benchmark_v148_platform_batch23_json_reader.py --repeats 6
```

The final report is [v148-batch23-json-reader-benchmarks.json](v148-batch23-json-reader-benchmarks.json), SHA-256 `d112a988335bc2f79009d08ef6de6bf3e8e86708b78edda85956d85e467d1385`. It records the `5c32b6883c454268e06e199a8f15264ca9ec26e9` historical baseline and **841 unchanged root Python source hashes**, identical to the final C2301 report's source map. The canonical compact JSON source-manifest SHA-256 is `da8476e1df16766ea79af307b38077622a637f960fcdad22a851fb06e92c2c82`, using `json.dumps(source_sha256, sort_keys=True, separators=(',', ':')).encode()`.

The current reader, regression file and benchmark hashes are, respectively, `01cdb6e63da84583666188c8a5cfdbd051a15bdfb5ccbd9ab19e63b31453538c`, `2686833f2ddbf5ab7f704125db156d66c9a2f1be1e2fdbfbbcf2ca383648ff5e` and `df8adcb02682a1b3fdacc811e006bbd9ee3891e71368440c78cba7b9a2d730a2`. The historical complete reader hash remains the one recorded in the provenance section.

All **79 complete historical reader pairs**, all **eleven workload comparisons**, and every warm, timed, separately traced and read-observed output comparison passed. Optional exact-color-controls and correction-history files were confirmed absent. Each workload has six elapsed pairs, with three AB and three BA orders; no sample was discarded. Traced peak and retained-with-result were measured separately after garbage collection. One actual public call is timed per sample; fixture creation, module linking, output comparison and image cleanup are outside both sides' intervals.

Positive elapsed changes below mean a longer measured median. The public-plan row times the complete actual plan; its request count covers the targeted timing-calibration file as noted above.

| Workload | Before median, ms | After median, ms | Elapsed change | After shorter in paired samples | Observed read calls, before → after |
|---|---:|---:|---:|---:|---:|
| Timing correction consumer | 0.129607 | 0.128465 | −0.881% | 3/6 | 1 → 2 |
| Real-Speed profile consumer | 0.035352 | 0.039138 | +10.708% | 2/6 | 1 → 2 |
| Scheduler recommendation consumer | 0.021712 | 0.022694 | +4.520% | 3/6 | 1 → 2 |
| Render progress consumer | 0.053109 | 0.044426 | −16.349% | 5/6 | 1 → 2 |
| Complete recovery snapshot consumer | 0.086403 | 0.077494 | −10.310% | 5/6 | 2 → 4 |
| Complete public Paint Pixel plan | 103.186526 | 106.650373 | +3.357% | 1/6 | 1 → 2, timing file only |
| Small 3,612-byte file, 8 MiB allowance | 0.020760 | 0.022839 | +10.009% | 2/6 | 1 → 2 |
| ASCII JSON string, exactly 4 MiB | 6.275170 | 6.513688 | +3.801% | 3/6 | 1 → 65 |
| UTF-8 JSON string, 4,194,302 bytes | 5.908346 | 7.258086 | +22.845% | 0/6 | 1 → 65 |
| Valid value with padding, exactly 8 MiB | 9.003591 | 10.048755 | +11.608% | 0/6 | 1 → 129 |
| Rejected file, 8 MiB plus one byte | 0.543936 | 1.222391 | +124.731% | 0/6 | 1 → 129 |

The elapsed results do not establish a general speed improvement. The complete public plan has a **3.357% higher median**, approximately 3.464 ms, with only one shorter pair. Several small readers differ by only a few microseconds and have substantial sample variation: the Real-Speed pairs range from −6.6% to +590.4%, while the timing correction pairs range from −51.0% to +19.2%. Their median differences must not be promoted into general latency claims.

The near-limit costs are concrete: UTF-8, padded 8 MiB and size-rejection controls are slower in all six paired samples. Rejection increases by approximately **0.678 ms**, from 0.544 to 1.222 ms. These costs remain in the report; the implementation was not adjusted or the measurement repeated to seek a positive result.

| Workload | Traced peak before, B | Traced peak after, B | Retained with result before, B | Retained with result after, B |
|---|---:|---:|---:|---:|
| Timing correction consumer | 4,202,335 | 77,860 | 9,740 | 9,740 |
| Real-Speed profile consumer | 1,056,455 | 73,863 | 5,688 | 5,580 |
| Scheduler recommendation consumer | 268,250 | 71,918 | 3,105 | 3,105 |
| Render progress consumer | 8,394,531 | 72,281 | 4,109 | 4,109 |
| Complete recovery snapshot consumer | 8,398,233 | 75,983 | 5,615 | 5,827 |
| Complete public Paint Pixel plan | 4,646,057 | 2,271,938 | 551,783 | 549,117 |
| Small 3,612-byte file, 8 MiB allowance | 8,394,580 | 75,152 | 5,520 | 5,520 |
| ASCII JSON string, exactly 4 MiB | 12,586,851 | 12,586,639 | 4,196,057 | 4,195,845 |
| UTF-8 JSON string, 4,194,302 bytes | 25,167,656 | 25,167,656 | 4,195,862 | 4,196,074 |
| Valid value with padding, exactly 8 MiB | 16,780,986 | 16,780,928 | 1,612 | 1,554 |
| Rejected file, 8 MiB plus one byte | 8,394,580 | 8,992,818 | 8,391,056 | 8,391,056 |

The measured small real consumers have lower traced peaks: about **98.15%** for the timing reader, **93.01%** for Real-Speed, **73.19%** for the scheduler and **99.10–99.14%** for recovery. The complete public plan's traced peak decreases from **4,646,057 to 2,271,938 B**, about **51.10%**, while its elapsed median rises as reported above. The independent small-file control has a **99.10%** lower traced peak.

Large valid-file peaks are effectively unchanged because the complete raw bytes, decoded text and parsed result still need their normal storage. The overflow control has a **598,238-byte higher peak**, approximately **7.13%**, reflecting the growing-buffer tradeoff. Its retained-with-result measurement intentionally includes the caught size exception and its normal diagnostic frame on both sides; the two retained values are identical. The actual file and accumulator have already closed. Other retained-result differences are small and separate from peak allocation; a single traced invocation per side is not a distribution of process memory use.

Files are already in the operating-system cache. The result concerns local reader/consumer CPU and tracked Python allocations, not disk throughput, total RSS, most native Pillow memory, startup latency or drawing speed. The demonstrated benefit is allocation proportional to the input actually read for small documents, with the original byte and validation bounds preserved. Near-limit cost, extra EOF reads and the slower complete-plan median remain explicit limitations; there is no general application speed or RSS claim.

## Deduplication

SS03/global183 established bounded JSON parsing and structural validation. Group053 established the recovery state/render byte limits and Unicode fallback. DP48/global379 covered the bounded runtime-safety report reader; SR02/global406 covered resource-tuning validation; SR05/global409 covered timing writer storage budgets. Those contracts remain intact. R2101/global822 reduced the number and lifetime of validated timing database observations, while P2301 changes the amount initially reserved inside each actual bounded input read. The independently published P2201 concerns consistent low-VRAM portrait tile output and does not change this reader. Existing bounded collectors and metadata scans do not implement this shared regular-file allocation behavior. This is at most one group across the common reader and all its consumers.
