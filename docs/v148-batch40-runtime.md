# v1.0.148 batch 40 — runtime completion and bounded numeric work

## Scope and count

Baseline: `888116094b91758dded968a7e3b5559683db9ad7`, with 846 registered
improvements. This ledger proposes **five distinct new behavior groups**. The
parent integration assigns global IDs; this document does not claim that the
900-improvement target has been reached.

The final product changes are confined to `ResourceAllocation.py` and
`UniversalGpuAcceleration.py`. Native device code, GPU discovery policy,
profile storage, UI code and rendering algorithms are not replaced. Tests and
measurements use committed source assets, their existing pixels, slices,
transposes and resized derivatives. No new image motif or image artifact is
created.

| Local group | Reproduced problem or measured repeated work | Implemented change | Evidence and count boundary |
| --- | --- | --- | --- |
| P4001 | A real executor task can complete successfully after `Future.result(timeout=.05)` expires but before `done()` is inspected. The old collector raised the expired polling exception, aborting successful work. | If the future is now complete, collect its actual result. A worker's own `TimeoutError` still propagates with its original identity. | `ExecutorCompletionRaceTests` uses an actual `ThreadPoolExecutor`, blocked workers and the real timed `Future.result`. Only the timing boundary is controlled. Ordered results are preserved. This is a completion race, separate from earlier bounded submission/Stop/shutdown work. |
| P4002 | Empty RGB/edge arrays could select a measured backend with a zero crossover threshold, open OpenCL and attempt illegal zero-size native buffers. That failed no-op could quarantine a healthy backend. | Route zero-pixel numeric work directly to CPU before reading the hardware profile or opening a device. Public functions retain their correct empty shapes/dtypes and Stop checks. | Zero-row and zero-column slices from the Paint reference exercise OKLab, paired perceptual error, channel error and edge magnitude. No profile/device call or health mutation occurs. CG17 covers the separate empty pairwise-palette API; it did not make these general numeric workloads inert. |
| P4003 | Per-pixel channel/perceptual reductions retained full-image RGB/Lab difference and absolute/squared scratch arrays, in addition to their required scalar output. | Reduce at most 65,536 pixels per slice, retaining the existing dense formula and float32 arithmetic. Basic slices retain noncontiguous input strides. Very wide and higher-dimensional inputs descend through leading axes without a full reshape copy. Small inputs keep the original dense operation and scalar return. | Independent dense formulas match exact output for contiguous/reversed/transposed/very-wide/higher-dimensional sources. Allocation boundaries enforce the tile limit, real CPU fallback is covered, and retained Stop releases the partial output. GP11 covers an N×N palette distance matrix; CP06 covers normalization borrowing and linear/LMS transform/evaluator lifetimes. This is the distinct paired scalar-reduction scratch stage. |
| P4004 | Integer and non-float32 RGB input first created a private float32 conversion, then allocated another full RGB array just to scale it; clamping could allocate another owner. | Reuse the already private conversion for scaling and clipping. Borrowed native float32 input is still read-only to the consumer; byte-scaled float32 input gets a separate owned result. | An independent historical formula covers byte/integer/wide-integer/floating/noncontiguous/empty inputs and out-of-range clamping. Retained read-only sources remain byte-identical, and the real dtype-conversion owner is the returned normalized buffer. CG16 established integer byte-scale semantics; CP06 established normalized-buffer borrowing. This group removes another allocation specifically when a dtype conversion already owns the storage. |
| P4005 | Ordinary CPU palette matching initialized custom-winner buffers even when custom-first selection was disabled, repeatedly initialized the ordinary winners to infinity, and rebuilt the same row indices. | For ordinary matching, initialize winners from the first candidate block and reuse one row-index vector. Strict-less ties and the original first-candidate fallback remain unchanged. The custom-first path retains its historical initialization, temporary row-index and custom-mask/argmin lifetime. | Exact public mapper arrays and route metadata are compared against the baseline across existing Paint/icon/screenshot sources, ordinary/custom modes and candidate-block boundaries. Ordinary traced peak falls by 16,616/20,768 bytes in the final samples. CG22 caches color features and bounds distance cubes; P3901 tiles host compositing. This group removes distinct winner-selection initialization work. No universal speedup is claimed. |

One new behavior group is counted once even when several APIs or regression
cases exercise it. Additional Stop checks, fallback coverage, diagnostics,
benchmarks and documentation do not receive separate IDs.

## Existing contracts completed, zero additional count

`HardwareProfileObservation` and `select_route` now propagate an interrupted
hardware-profile read instead of turning Stop into an unavailable-profile CPU
fallback. An interrupted observation remains retryable; a completed observation
is still read once. Ordinary storage failures continue to select CPU. This
completes **CG20** cancellation semantics and **P1901** observation ownership;
it does not add a sixth group.

The paired-reduction Stop and failed-device fallback cases complete those
existing contracts within P4003. No additional GPU backend implementation or
device execution is claimed.

## Final focused validation

The final focused run completed **157 tests in 14.020 seconds: 155 passed and
two environment-dependent tests skipped**. Every recorded product/test source
hash was unchanged throughout that run. Its command, raw output, source hashes,
historical negative results and rejected experiments are in
`v148-batch40-runtime-validation.json`.

```text
.venv/bin/python -m unittest -q \
  test_v148_runtime_batch40_completion \
  test_v148_runtime_batch40_error_tiles \
  test_v148_runtime_batch40_normalization \
  test_v148_storage_batch02_resources \
  test_v148_platform_batch19_profile_observation \
  test_v148_gpu_numeric \
  test_v148_platform_batch22_numeric_ownership \
  test_step23_universal_gpu_acceleration_v10146 \
  test_v148_colour_batch29_accuracy_inputs \
  test_v148_platform_batch39_cpu_palette \
  test_v148_platform_batch26_palette_boundaries \
  test_v148_platform_batch25_palette_preparation \
  test_gpu_pipeline_optimization \
  test_v148_platform_batch03_numeric \
  test_gpu_route_regressions \
  test_v148_resource_safety \
  test_v148_colour_batch05_resources \
  test_v148_platform_batch20_gpu_cache
```

The three new test modules contain 16 methods. Loading the exact baseline Git
objects for `ResourceAllocation` and `UniversalGpuAcceleration` and running the
unchanged final tests produces **14 failed assertions/subtests and seven
errors across those 16 methods**. The raw output and exact baseline/test hashes
are retained. These are failures/subtests, not 21 separate test methods or
improvements. The palette optimization preserves behavior, so its evidence is
historical output equality plus measured allocation/work reduction rather than
an intentionally different expected palette.

The executor regression does not substitute a fake executor or product
implementation. GPU failure fixtures inject failure at the existing native
context boundary and execute the real fallback. NumPy allocation/reduction
observers call the actual operations. Current source and output arrays remain
unchanged where the contract requires borrowing.

## Paired allocation and timing observations

`benchmark_v148_runtime_batch40_errors.py` compares the actual baseline module
to the changed numeric module using the committed 720×393 application
screenshot. It warms the operations, alternates six A/B and B/A pairs and
compares complete outputs, including route metadata, for each invocation.
Separate tracing excludes the correctness assertions from numeric allocation
probes. The complete evaluator uses each version's real numeric backend; other
shared dependencies are held at the current checkout.

| Workload | Before median | After median | Before traced peak | After traced peak |
| --- | ---: | ---: | ---: | ---: |
| Integer RGB normalization | 3.877 ms | 2.775 ms | 6,791,964 B | 4,246,082 B |
| Contiguous channel error | 14.781 ms | 14.640 ms | 6,792,832 B | 3,101,640 B |
| Strided channel error | 25.286 ms | 28.653 ms | 6,793,000 B | 3,101,808 B |
| Perceptual pair | 42.169 ms | 55.479 ms | 15,848,200 B | 10,924,608 B |
| Complete accuracy evaluator | 151.549 ms | 159.486 ms | 22,655,392 B | 17,732,376 B |

Full samples are in `v148-batch40-error-benchmark.json`. That measurement used
numeric module SHA-256
`5adbd974a2796b57a901bb774ccb3b97b33d6aab59a8afad6393b6851be63cbb`.
The later palette-only restriction described below and a helper docstring
correction change the final module hash; the measured normalization/error
arithmetic and evaluator call paths are unchanged. This is disclosed instead
of relabeling an earlier measurement as a final-module run. No additional timing
run was started while the parent performed frozen full-project discovery.

The lower scratch peaks are observed benefits. The strided and perceptual
cases are slower in these samples, and the complete evaluator median is about
5.2% higher. Required source, converted Lab and scalar output arrays still
exist; this is not a hard process-memory bound or an assertion that any image
size can fit. Tiling trades some dispatch overhead for a bounded intermediate
working set and intermediate Stop opportunities.

`benchmark_v148_runtime_batch40_palette.py` compares the complete public
mapper with the fixed baseline and retains exact output hashes/metadata. Its
separate allocation probes include the identical output-comparison wrapper on
both versions. Final-module samples are in
`v148-batch40-palette-benchmark.json`.

| Workload | Before median | After median | Before traced peak | After traced peak |
| --- | ---: | ---: | ---: | ---: |
| Paint reference, 76×76, 20 ordinary Faithful candidates | 15.170 ms | 17.543 ms | 4,250,566 B | 4,233,950 B |
| Application screenshot, 480×262, 20 ordinary RGB candidates | 61.597 ms | 51.132 ms | 2,420,678 B | 2,399,910 B |
| Icon, 192×192, 70 sparse custom Faithful candidates | 314.942 ms | 308.204 ms | 7,418,820 B | 7,418,820 B |
| Screenshot, 192×105, 70 sparse custom RGB candidates | 30.085 ms | 31.126 ms | 2,471,196 B | 2,471,196 B |

Custom-first traced peaks return to the baseline exactly. The elapsed samples
are visibly noisy in the shared Linux environment: the final small ordinary
Paint case is slower despite earlier lower medians, while the larger ordinary
case is faster. No claim is made that the unchanged custom branch became
faster, or that ordinary matching is always faster. The deterministic change
is less unnecessary winner initialization and lower ordinary traced peaks.

## Rejected approaches and retained negative evidence

An initial P4005 experiment also reused custom masks, skipped custom argmin for
candidate blocks without a custom swatch, and retained the row-index vector in
custom-first mode. Although it removed repeated operations, that longer-lived
vector raised custom traced peaks by about 32–33 KB. Timing was mixed: one
custom screenshot sample was about 11.1% slower, while later samples varied in
both directions. The custom change was rejected, and the final implementation
retains the historical custom-first buffer and comparison path. Raw later
experiment samples are retained in the validation JSON; the earlier observed
11.1% regression is recorded here rather than treated as a gain.

One palette experiment ran alongside a focused test selection. It is preserved
under `concurrent_validation_experiment` and excluded from the final table.
Other samples still run in a shared environment and are not isolated hardware
performance claims. The final palette run completed before the parent asked
agents to stop timing work for full-project discovery.

An initial bounded-error implementation gathered noncontiguous inputs through
flat-iterator copies. Its excessive strided overhead was rejected in favor of
basic slices that preserve the original input strides. The full experimental
report is retained under `rejected_flat_gather_error_experiment`.

An audit suspicion about CUDA asynchronous host input lifetime was rejected
after tracing the real closures: normalized source arrays were already held by
the surrounding operation. No transfer policy was changed and no improvement
was counted for that suspicion.

## Product freeze and practical limits

Final product SHA-256 values at the focused gate:

| File | SHA-256 |
| --- | --- |
| ResourceAllocation.py | `59c6d69cc8247251bcc666aa79ac7a1005c8122d6fa121592b2cb1868b5e1595` |
| UniversalGpuAcceleration.py | `10be233a5eb89b26008097b624f3a43fb0762d90e4cfff14b7f1683fb209042b` |

Tests run on Linux with CPU execution and real Python executors. Compiled
kernel-formula/reference tests are not physical GPU execution. No live Paint,
Gartic, Windows input, driver memory or process-RSS claim is made. Parent
integration owns full-project discovery, release/package gates, global registry
admission and exact-commit CI. This work does not publish a release or change
the application version.
