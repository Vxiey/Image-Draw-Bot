# v1.0.148 batch03: GPU setup, execution and platform behavior

Baseline: `2fb7abf470a4ef498df9c53f42cddda62d8b652b`.

This ledger records **22 distinct behavior or performance improvements**. Tests,
benchmark data, documentation, cache-version changes, additional call sites of a
shared fix and completion of previously counted work are not extra entries.
No package was installed and no GPU/installer binary was downloaded to perform
this work. The implementation retains ordinary CPU fallback, explicit source
setup and the existing trust boundaries.

Test names below abbreviate `test_v148_platform_batch03_<name>.py`.

## Setup and current GPU evidence

| ID | Previous behavior | New behavior and implementation | Validation |
| --- | --- | --- | --- |
| GP01 | Optional GPU setup could upgrade pip/remove an existing CuPy distribution before discovering that its shipped requirements were missing or empty. | `GpuSetupRuntime.checked_requirements` validates a bounded, nonempty UTF-8 requirements document before any package mutation. `AutoGpuSetup` also requires the supported CuPy distribution to be present before conflict removal; both installers use the preflight. | `setup`: missing/empty requirements leave only read-only environment/configuration probes in the command record. |
| GP02 | CUDA setup accepted one correct value from a 32-element test, and runtime status downloaded a sample without verifying the arithmetic. | `GpuHardware.cupy_smoke_test` verifies the complete expected output; `GpuBackendStatus._cuda_probe` checks all 256 finite arithmetic results before reporting a working backend. A partially working or wrong kernel does not establish readiness. | `cuda`: partial-output fakes, all-partial rejection and corrupted arithmetic status. |
| GP03 | An explicit CUDA status could reuse indefinitely cached free-memory, availability and driver-health information. | `GpuBackendStatus` refreshes the current CUDA context/metadata on every explicit-CUDA status call, reusing only a successful arithmetic probe for 30 seconds and the same actual runtime ordinal. An unreadable identity disables probe reuse. The cache is locked, bounded to 32 records and returns independent data. | `cuda`: change current memory and then device health while the probe is cached; expire probes, verify bounded cache/returned-record isolation and reject bad arithmetic on a second card with the same model name. |

## Actual memory capacity and completed CUDA work

| ID | Previous behavior | New behavior and implementation | Validation |
| --- | --- | --- | --- |
| GP04 | Runtime budget floors could increase a small or zero free-memory allowance, pool limits ignored live allocations and simulation batches assumed at least 128 MiB. | `GpuAcceleration.available_vram_mb` accounts for pool-live and reusable bytes once. Runtime pool/tile/score planning and `PixelAccuracyGpu._plan` respect the remaining capacity without artificial minimum budgets. A zero pool limit is rejected because CuPy interprets zero as unlimited; work unable to fit one row plus its halo takes the controlled memory-failure path. | `memory`: zero/small budgets, live/reusable accounting, impossible-row rejection and bounded simulation batches; legacy allocation fixtures remain compatible. |
| GP05 | One temporary allocation failure permanently disabled the legacy CUDA backend for later, smaller work. | `GpuAcceleration._disable_backend` leaves the working backend available after a recognized allocation/OOM failure while still quarantining a genuine driver/runtime failure. | `memory`: a synthetic OOM preserves the selected context; an illegal-memory-access error clears it. |
| GP06 | A failed score tile's exception traceback retained device arrays while the retry attempted to trim the pool, so the memory needed for recovery was still live. | `PixelAccuracyGpu` isolates score-tile work and clears failed frames, including chained exceptions, before pool trim/retry. Simulation retry uses the same release boundary. The existing completed-tile accounting remains intact. | `memory`: weak references to all uploaded arrays are dead at the trim call; an 8-row failure recovers at 4 rows with correct metrics. |
| GP07 | A failure during the final CUDA score synchronization was ignored and could return an apparently verified score. | `PixelAccuracyGpu.score_cuda_host` requires final synchronization to succeed before publishing the score; a late native failure returns the existing CPU-fallback signal. | `memory`: an injected final-stream error cannot produce a score. |
| GP08 | Private ordinary/pinned host arrays could go out of scope after `cupy.asarray` queued an asynchronous host-to-device copy. | `GpuAcceleration._upload_gray` requests a blocking transfer before releasing its private host owner. This is a source-buffer lifetime guarantee; it does not change device selection or hide GPU execution. | `cancellation`: ordinary and pinned paths require completed upload, retain exact pixels and release the temporary pinned owner afterwards. |

## Numeric image work and preparation costs

| ID | Previous behavior | New behavior and implementation | Validation |
| --- | --- | --- | --- |
| GP09 | Centered-gradient code returned zero at every outer boundary and on an entire two-pixel-wide/high axis, losing real thin-image edges. | `ImageGradients.luminance_edges` uses centered interior and one-sided boundary differences, with zero only for singleton axes. `UniversalGpuAcceleration` CPU/CUDA/OpenCL formulas and the coordinated accuracy/planner/shadow/importance fallbacks agree. Nonfinite luminance is rejected before backend dispatch. | `numeric`: NumPy-gradient oracle for thin and ordinary shapes, NumPy-backed CUDA dispatch and the actual OpenCL kernel body compiled as a host C++ oracle; no physical-driver performance claim. |
| GP10 | RGBA-to-visible-RGB conversion materialized several full float RGB arrays, including unnecessary compositing for opaque input. | `UniversalGpuAcceleration._rgba_visible_rgb` uses one owned RGB output, preserves the exact previous arithmetic order for alpha and takes an opaque fast path. | `numeric`: exact old-formula float arrays for mixed alpha and alpha 0/1/254/255, unchanged caller data; paired measurements below. |
| GP11 | Pairwise OKLab distance allocated an `N×N×3` difference cube and its squared copy in addition to the required result matrix. | `UniversalGpuAcceleration._pairwise_lab_distance` computes row chunks with two-dimensional squared-distance scratch storage on CPU/CUDA. The full `N×N` result is still required. Typical chunks use at most 256 rows and 1,048,576 distance cells. | `numeric`: byte-identical dense-reference output for 777 colors, instrumented scratch shapes and between-chunk cancellation; paired 1,024-color measurement. |
| GP12 | A requested portrait limit below 80 was silently increased; dot mode ignored the caller's stroke cap. | `PortraitPlanner` honors strict nonnegative integral limits, including zero, in line and dot paths. Dot generation stops after the requested visible prefix. | `portrait`: limits 0/1/5/79 for both modes; a synthetic million-by-million canvas reads exactly five pixels for a five-dot limit. |
| GP13 | CPU portrait contrast performed Python rounding/clamping and list storage for every pixel. | `PortraitPlanner._enhance_local_contrast` uses bounded vector chunks with float64 arithmetic and banker rounding, preserving the prior byte result. | `portrait`: exact scalar-reference bytes for all three used strengths; paired 1,024×768 measurement. |
| GP14 | Selecting a small portrait stroke budget scored and retained/sorted every candidate, then built a second full remaining-candidate list. | `PortraitPlanner._select_tone_candidates` keeps only the best candidates for a small cap and streams evenly spaced coverage. When the requested priority set is large, it uses a full sort to avoid the heap's measured near-full-selection penalty. Tie order and coverage positions are preserved. | `portrait`: exact selection across small/full limits and priority fractions, internal Stop checks; both small-cap and near-full measurements are disclosed below. |

## Native lifecycle and trustworthy benchmark results

| ID | Previous behavior | New behavior and implementation | Validation |
| --- | --- | --- | --- |
| GP15 | A real `TclError` during root destruction permanently marked the root destroyed, so a later close attempt did nothing while the window could remain alive. | `AppBranding._install_destroy_guard` marks successful destruction only after a successful/known-already-destroyed teardown and always releases the reentrancy flag. A real failure remains visible and retryable. | `native` and existing `test_app_branding`: failed-first/successful-second destruction plus successful/reentrant idempotence. |
| GP16 | Universal GPU benchmarks omitted source upload, downloaded only a sample and included compilation/startup asymmetrically. The legacy CUDA benchmark also computed huge throughput from a CPU/no-op fallback. | `UniversalHardwareBenchmark` warms each workload, times complete input-transfer/kernel/output-transfer work and validates after timing. CPU uses the same workload boundaries. `GpuAcceleration.benchmark` reports zero GPU throughput when the complete GPU pipeline did not run. Profile format 2 invalidates the old incomparable measurements. | `benchmark`: synthetic transfer clock and upload/download shape/counts for CUDA/OpenCL; `cancellation`: CPU fallback skips stimulus allocation and failed GPU work has zero throughput. |
| GP17 | Wrong GPU arithmetic could still produce an accepted performance score because only execution/transfer success was checked. | `UniversalHardwareBenchmark` validates every warm/timed output against the CPU workload reference: exact categorical palette output, finite shapes and bounded numeric tolerance for float workloads. Bad results remain failed probes. | `benchmark`: corrupted CUDA and OpenCL numeric outputs do not enter the successful score set. |
| GP18 | Direct benchmark calls could report the requested size even though stimulus creation silently used a larger floor, and repeats/size were not consistently bounded. | `UniversalHardwareBenchmark._benchmark_parameters` normalizes a strict integral size to 32–1,024 and repeats to 1–5 before stimulus creation and metadata calculation. Top-level small/large benchmark policy remains bounded. | `benchmark`: actual 32×32 output metadata for a requested size of 1, huge integers clamped safely, booleans/floats rejected. |
| GP19 | Reading one disconnected OpenCL adapter's metadata before the per-device error boundary aborted discovery of otherwise usable later adapters. | `UniversalHardwareBenchmark.benchmark_opencl` reads metadata inside each device's guarded attempt and continues to the next adapter on failure, releasing the completed attempt's resources. | `benchmark`: broken first-device metadata produces one failed probe followed by four healthy scores from the second device. |
| GP20 | Long hardware/resource benchmark work had no caller Stop callback, and CPU/GPU work could continue through many further phases before the UI regained control. | Optional callbacks now reach `UniversalHardwareBenchmark`, `GpuAcceleration` preprocessing/benchmark, `ResourceAllocation.benchmark_allocation`, `ResourceScheduler.benchmark_scheduler` and `PerformanceAutoTuner.run_auto_tune`. They check between workloads/repeats/devices/tiles, within CPU scheduler blocks and before publishing results. Existing `parallel_map` provides queue cancellation. Failed workload frames are released before device cleanup even when the error is retained. Root integrates the UI callbacks. | `cancellation` and `benchmark`: pre-cancel avoids work, mid-tile Stop stops further tiles without quarantine, late GPU results are discarded, scheduler/allocation work stops, retained mid-workload interruption does not retain device inputs, and tuning never publishes an interrupted recommendation. |
| GP21 | Tuning saved scheduler/hardware profiles during intermediate phases, so a later failure or cancellation could leave a mixed set of old and new recommendations. | `PerformanceAutoTuner.run_auto_tune` computes each phase with `save=False`, validates the final documents and publishes the tuner/scheduler/current hardware profiles through the existing rollback-capable `replace_text_files`. Invalid optional mocked/legacy payloads are not published as auxiliary profiles. | `benchmark`: phase arguments stay `save=False`, cancellation leaves publication untouched, the completed path supplies exactly three documents to one publication transaction. Existing file-set failure/rollback tests verify the shared primitive. |
| GP22 | Building the legacy GPU benchmark stimulus allocated a Python integer list for every pixel and spent substantial CPU time outside the measured GPU work. | `GpuAcceleration._benchmark_image` generates identical stimulus pixels in 64-row vector chunks, retaining cancellation points and avoiding that Python list. | `cancellation`: exact previous-formula bytes and early Stop; paired 1,024×1,024 measurement. |

## Shared work and corrections not counted again

- **Original 022:** target-venv verification is extended through the actual pip
  invocation. `-I -m pip --require-virtualenv --no-input` removes Python import
  overrides. A read-only pip configuration snapshot preserves proxy, certificate,
  index and ordinary settings while dropping target/prefix/root/user/interpreter
  relocation. `PIP_CONFIG_FILE=os.devnull` prevents global/user/site files from
  reintroducing relocation; each command receives its preserved settings through
  a private environment. Because pip's `--python` implementation re-invokes Python
  without preserving `-I`, all inherited `PYTHON*` startup overrides (including
  `PYTHONINSPECT`) are removed before controlled `PYTHONNOUSERSITE=1` and
  `PYTHONSAFEPATH=1` are added for the child. The real installed pip option parser
  and a harmless synthetic `sitecustomize` marker verify both boundaries without
  installing/resolving anything. Original configuration files remain untouched.
  This closes the existing target-boundary guarantee rather than adding another
  count for each installer.
- **Original 002/006:** the CUDA smoke test enumerates actual CUDA-visible
  ordinals and reads runtime names, including a later usable device, instead of
  inferring CUDA identity from SMI/native enumeration order.
- **Original 014 and SS03:** hardware profiles now use the bounded strict JSON
  reader and validate nested containers/numeric fields. Saving uses the existing
  atomic binary writer, with failure/cancellation preserving the old document.
  Malformed summary data and a current hardware-read failure produce controlled
  fallback/rebenchmark decisions. These extend prior malformed-cache/atomic-I/O
  behavior; cache version 2 is required by GP16 and is not an extra improvement.
- **Shared RP categorical contract:** `PixelMapValidation` is used by GPU palette
  candidates and rectangle compilation. Invalid/wrapped signed-short indices
  fail before dispatch. B owns the single count, including these consumers.
- **Shared RP raster clipping:** the GPU diagonal compiler uses B's phase-exact
  `RasterGeometry.clipped_bresenham`; the long-line cancellation fixture now
  measures genuinely visible points rather than discarded off-canvas traversal.
- **Shared IW08 owned-image cleanup:** portrait preparation tracks its owned PIL
  images, closes intermediates on success/failure and preserves the caller's
  source. Benchmark/late-cancel output cleanup follows the same ownership rule.
  Retained-exception tests verify closed cores. This is not a GP cleanup count.
- **Prior PL37/PL38, CG20 and SR03:** additional callback transport, final Stop
  checks, session finalization and direct `InterruptedError` propagation complete
  those paths. Only the newly cooperative benchmark execution is counted in
  GP20. Root's distinct GUI worker/busy/lifecycle work is recorded as IW40.
- **Shared GP09:** A integrates the gradient helper in `AccuracyEvaluator`,
  `ShadowDetailEngine` and `VisualImportanceMap`; B integrates the last-resort
  `PixelAccuratePlanner` fallback. Their ledgers do not recount this behavior.

## Reproducible measurements

Run from the repository with the existing Python environment:

```console
python benchmark_v148_gpu_platform.py --baseline 2fb7abf470a4ef498df9c53f42cddda62d8b652b --repeats 5
```

The script reads only the local Git baseline. Full samples, interpreter/library
versions, output hashes and source hashes are in
`docs/v148-batch03-gpu-platform-benchmarks.json`. It makes one exact-parity warm
call, alternates five old/new timed calls and measures traced allocation peaks
separately after garbage collection. These are synthetic CPU measurements on
this Linux environment; traced allocations are neither RSS nor VRAM and omit
some native Pillow storage. They are not physical CUDA/OpenCL performance claims.

| Workload | Median before → after | Peak traced bytes before → after | Interpretation |
| --- | --- | --- | --- |
| Mixed-alpha compositing, 1,024×768 | 30.11 → 16.37 ms | 36,210,680 → 19,662,052 | Identical float RGB and visibility buffers. |
| Opaque compositing, 1,024×768 | 29.49 → 7.39 ms | 36,210,680 → 11,011,713 | Opaque fast path avoids unnecessary alpha work. |
| Pairwise OKLab, 1,024 colors | 45.86 → 8.98 ms | 29,453,728 → 8,548,544 | Identical full output matrix; smaller scratch workspace. |
| Portrait contrast, 1,024×768 | 299.31 → 13.67 ms | 8,250,206 → 2,502,858 | Identical output bytes. |
| Select 200 of 30,000 candidate strokes | 245.87 → 214.17 ms | 6,839,316 → 47,532 | Exact ordered selection with a small retained priority set. |
| Select 26,000 of 30,000 candidates | 242.72 → 244.29 ms | 6,839,316 → 6,840,196 | No meaningful speed/memory improvement is claimed for near-full selection; full sorting avoids the earlier heap regression. |
| Benchmark stimulus, 1,024×1,024 | 136.26 → 3.95 ms | 8,449,640 → 1,644,752 | Identical source image; generation remains outside reported GPU timing. |

## Primary technical references

- [pip configuration loading and precedence](https://pip.pypa.io/en/stable/topics/configuration/),
  [pip config CLI](https://pip.pypa.io/en/stable/cli/pip_config/) and
  [pip general options](https://pip.pypa.io/en/stable/cli/pip/): configuration
  inheritance, null config disabling, per-command options and venv/interpreter controls.
- [Python isolated mode](https://docs.python.org/3.12/using/cmdline.html#cmdoption-I):
  environment/user-site/current-directory import isolation and documented
  `PYTHONNOUSERSITE`/`PYTHONSAFEPATH` startup controls. The
  [pip interpreter dispatch implementation](https://github.com/pypa/pip/blob/main/src/pip/_internal/cli/main_parser.py)
  confirms that `--python` re-invokes a runner without the original `-I` flag.
- [CUDA environment variables](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/environment-variables.html):
  visible-device order and ordinal remapping cannot be inferred from SMI order.
- [CuPy MemoryPool](https://docs.cupy.dev/en/stable/reference/generated/cupy.cuda.MemoryPool.html)
  and [memory guide](https://docs.cupy.dev/en/stable/user_guide/memory.html):
  live/cached blocks and the unlimited meaning of a zero pool limit.
- [CuPy array upload](https://docs.cupy.dev/en/stable/reference/generated/cupy.asarray.html)
  and [performance guide](https://docs.cupy.dev/en/stable/user_guide/performance.html):
  asynchronous host-copy lifetime, synchronization and benchmark warm-up.

## Verification and practical limits

All **60 new focused tests** pass locally. The related suite includes existing
setup, CUDA memory and ABI, scoring, routing,
portrait, tuner, resource and branding regressions. Physical
CUDA/OpenCL driver behavior and native Windows GUI behavior still need their
existing platform/CI coverage; array-backed fakes and the host-compiled kernel
oracle do not replace that evidence.

Cancellation is cooperative: an already-running native kernel/driver call cannot
be forcibly interrupted, and already-running parallel workers finish during
executor shutdown. The tuner file-set guarantees rollback on an in-process
publication exception, not crash-level or all-readers atomicity. Memory plans are
conservative estimates, not hard process RSS limits; pairwise output remains
quadratic, and a single exceptionally wide row can exceed the usual scratch-cell
target. CuPy's shared default pool remains a process-wide facility; this batch
does not claim global serialization of every independent GPU consumer.
