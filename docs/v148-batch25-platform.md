# Batch 25 — usable performance recommendations and necessary numeric work

Original reproduction baseline: `bb6dfa6a5e8a43bfcfc77c9e00f52dc2dfd7db9c`, with 828 registered
improvements. This ledger records four distinct behavior groups. Integration
owns the final registry, complete source manifest and publication status.

## P2501 — let an automatic recommendation use measured compute preferences

The tuner previously selected `NVIDIA CUDA` when its legacy portrait CUDA probe
succeeded and `CPU` otherwise. Both choices bypassed the universal benchmark's
per-workload decisions. The actual preference builder could choose OpenCL on
AMD/Intel or a faster adapter, then the tuner's `CPU` setting disabled that
winner. A successful legacy CUDA probe instead forced CUDA even when measured
OpenCL or CPU was faster, including below the measured GPU crossover.

`PerformanceAutoTuner.build_recommendation` now selects `Auto` when a current
hardware profile contains usable measured preferences and either those
preferences enable GPU work or the legacy CUDA probe was successful. Normal
universal routing retains each workload's adapter, CPU preference and crossover.
Detection or an OpenCL summary without measured preference records is
insufficient. CPU-only evidence retains CPU; an isolated successful legacy
CUDA probe retains its existing CUDA recommendation. Explicit user CPU mode
continues to disable all accelerated routes.

The five routing methods in `test_v148_platform_batch25_tuner.py` use the actual
`build_preferences`, recommendation and `select_route` functions. Controlled
score records reproduce three failures in the unchanged source: disabled
OpenCL, forced slower CUDA, and overridden CPU winners. These are preference
contract tests, not newly measured hardware throughput. All five methods pass
after the change. The existing renderer/CUDA availability fields retain their
meaning, separately from the universal compute summary.

This is distinct from CG18 / 118's validation of forced-CUDA score data and
RD01 / 748's propagation of an already selected GPU policy. It repairs the
automatic recommendation that chose that policy incorrectly in the first place.

## P2502 — benchmark and apply the same resolved RAM policy

At 32,768 MiB available RAM, the real tuner previously benchmarked and saved an
8,192 MiB scheduler allocation, but recommended a 12,288 MiB setting. Applying
that result immediately changed the machine/budget signature and made the
just-saved worker recommendation unreadable. The same failure appeared at
28,000 MiB available (8,192 versus 9,800 MiB) and 65,536 MiB available (8,192
versus 12,288 MiB).

The tuner now uses the allocation's single live resource observation to resolve
its final RAM policy before the scheduler benchmark. The recommendation,
measurement, persisted signature and subsequently applied policy therefore
describe the same budget. Under low memory, the recommendation also reports
the allocator's existing headroom limit: for example, 256 MiB available yields
128 MiB for planning, while 900 MiB available yields 388 MiB. This preserves the
existing allocator safety policy instead of displaying an unachievable budget.

The three budget methods in `test_v148_platform_batch25_tuner.py` run the real
CPU tuner phase and file-set publication into temporary directories, apply the
returned allocation settings, and reload the exact resulting scheduler
signature. Only the optional hardware benchmark is withheld. The unchanged
source produced six failing budget subcases. The corrected cases pass, as do
the existing middle-budget behavior and rejection after CPU capacity changes.
The old assertion expecting a 256 MiB planning budget with only 256 MiB
available now checks the allocator's actual 128 MiB allowance.

This is one end-to-end recommendation-applicability correction. SS22 / 202's
coherent observation and GP04 / 556's capacity/headroom protections remain
controls, not additional improvements counted here. GP21 / 573's rollback
publication remains unchanged and is exercised by the adjacent regressions.

## P2503 — measure actual executor work before recommending worker counts

`ResourceScheduler._bench_once` previously ran nested integer loops serially on
the calling thread for every candidate. A public request labeled `Processes`
created zero process executors, and a `Threads` request created zero thread
executors. Varying the loop's worker label could therefore select a
recommendation without observing scheduling, serialization, startup or shutdown.

The scheduler now runs the existing deterministic
`ResourceAllocation._resource_benchmark_worker` through the real bounded
`parallel_map` implementation. Each candidate receives the same ordered task
and iteration payload. A serial reference establishes every expected result;
incorrect, incomplete or failed candidate work cannot become a successful
score. Ordinary failed candidates retain their error and leave valid serial or
other candidates eligible. Interruption aborts the operation and publication.

Timing starts before executor construction and ends after ordered result
collection and owned executor shutdown. Two rounds use opposite candidate
orders. Scores use the median complete elapsed time and actual iteration count;
the former fabricated headroom multiplier is removed. The safe CPU cap remains,
and the selector prefers fewer workers within five percent of the fastest
completed candidate. Work is bounded to 1,000–100,000 iterations per task,
at most 32 tasks per candidate, and two measured rounds plus one serial
reference. Running bounded tasks finish during the existing executor shutdown;
the implementation does not kill native threads or interrupt OS process startup.

**Measurement scope:** this measures a bounded integer CPU workload and its
executor overhead. Python Threads often select one worker because that workload
holds the GIL. These scores do not establish an optimum for NumPy/native
preprocessing, every planner, drawing speed or the whole application. The
current actual `parallel_map` consumers are basic and advanced color row
planning; existing per-phase policies remain unchanged. No second workload or
phase-policy rewrite is claimed without a concrete regression. Auto tuning
continues to request Threads. Explicit Processes uses the existing process
executor and top-level picklable worker, preserving the application's existing
Windows/frozen multiprocessing entrypoint.

Only scheduler recommendations advance to format 3. Their established file
path remains `resource-scheduler-v2.json`; version-2 serial-proxy recommendations
are rejected so they cannot masquerade as measured executor evidence. A fresh
benchmark creates current evidence. The separate universal hardware profile
version and its measured GPU preferences are unchanged. The existing file-set
rollback regression uses the current scheduler schema while retaining every
original publication/rollback assertion.

All seven methods in `test_v148_platform_batch25_scheduler.py` failed on the
unchanged source and pass on the corrected source. They observe real thread
workers, force actual spawn-process workers even on Linux, verify identical
payloads/results and the timer/shutdown order, reject corrupted parallel
results, preserve the prior saved profile after Stop, and confirm child-process
cleanup. These tests establish execution and ownership; their elapsed test-run
times are not product speed benchmarks. Native frozen-Windows spawn behavior
remains an integration concern, rather than a claim of this Linux run.

GP16 / 568 and GP17 / 569 previously corrected the independent universal GPU
benchmark's transfer boundaries and numeric verification. This group removes
the separate CPU scheduler's serial proxy. GP20 / 572's Stop and SR37 / 441's
bounded queue ownership are preserved, not counted again.

## P2504 — prepare visible host RGB only when the selected route consumes it

Universal palette mapping previously composited every source into a full
float32 RGB array and built a full visibility mask before selecting a route.
Its OpenCL branch consumed neither: the existing OpenCL kernel receives raw
RGBA and returns its own visibility result. A failure allocating that unused
host RGB buffer therefore prevented otherwise bounded OpenCL work from starting.

Visible RGB and its mask are now prepared lazily inside their actual CPU or
CUDA consumer. One private operation-local result is reused if CUDA falls back
to CPU. Preparation is published internally only after compositing and optional
white filtering finish. Successful OpenCL processing skips these arrays
entirely; a failed OpenCL attempt releases its native work before preparing the
real CPU fallback. Stop concurrent with native failure skips that fallback.

The avoided buffers are 12 bytes per pixel for float32 RGB and one byte per
pixel for its Boolean visibility mask, plus the former transient compositing
and white-filter work. For the existing 360 × 240 fixture, those two arrays
alone contain 1,123,200 bytes. This is the eliminated array payload, not a
measured process-RSS or physical-VRAM reduction. Raw RGBA input, palette data,
native buffers and the required output maps remain necessary.

Before the change, five preparation methods produced 12 premature allocation
errors across rendering/fidelity/white-filter subcases and two ordering/Stop
failures. The corrected methods pass. They preserve exact real CPU outputs,
CUDA transfer inputs/output/visibility, first-candidate ties and custom-color
policy; CUDA fallback reuses one preparation. The OpenCL boundary supplies a
NumPy numeric-result oracle and observes actual production buffer transfers,
partial native failure cleanup, lazy CPU fallback and retained Stop tracebacks.
No OpenCL kernel arithmetic is replaced in the product, and no physical-device
throughput is claimed by that boundary. Existing scalar/native-kernel and
optional physical-device regressions remain the arithmetic controls.

This is distinct from GP10 / 562, which made necessary RGBA compositing more
efficient, and CG22 / 122, which reuses color transforms inside CPU palette
tiles. This group removes an entire unused route-specific preparation. P2001 /
820's cache maintenance and existing failed-frame ownership remain unchanged.

## Verification

All new numeric input is an in-memory array or the tracked
`golden-regression/small-detail-preservation.png`. No images or new visual
assets are generated. Test score records are controlled routing fixtures, not
pretend physical-device benchmark observations.

The tuner/scheduler focused and adjacent gate completed 116 tests in 5.659
seconds, all passing. The palette/numeric gate completed 54 tests in 0.892
seconds: 51 passed and three physical-device cases were explicitly skipped.
The combined gate completed **170 tests in 6.443 seconds: 167 passed and the
same three physical-device cases were skipped**. `git diff --check` was clean.
No application-wide CPU, GPU or drawing-speed improvement is inferred from
these test durations.

```sh
.venv/bin/python -m unittest \
  test_v148_platform_batch25_tuner \
  test_v148_platform_batch25_scheduler \
  test_performance_auto_tuner_v1060 \
  test_resource_scheduler_v1044 \
  test_resource_allocation_v1014 \
  test_v148_resource_safety \
  test_v148_storage_batch02_learning \
  test_v148_platform_batch03_benchmark \
  test_v148_platform_batch03_cancellation \
  test_step22_universal_hardware_auto_benchmark_v10145 \
  test_v148_application_batch18_saved_tune \
  test_v148_platform_batch23_json_reader \
  test_v148_platform_batch25_palette_preparation \
  test_v148_platform_batch22_numeric_ownership \
  test_v148_gpu_numeric \
  test_gpu_pipeline_optimization \
  test_v148_colour_batch05_matching \
  test_gpu_route_regressions \
  test_step23_universal_gpu_acceleration_v10146 -q
```

Integration independently reviewed the recommendation/scheduler source and
scheduler tests without a blocker, and requested the explicit bounded-workload
qualification above. It also reviewed the lazy palette-preparation flow and ran
all 20 new platform methods together with three rendering methods: all 23
passed in 4.500 seconds.

The independent UI/lifecycle reviewer approved P2504's source and ownership
tests without a blocker. Its five methods passed in 0.111 seconds. An additional
retained CUDA-OOM/Stop probe released both cached host arrays despite keeping
the exception traceback, preserved the caller's source/device context, and
started neither a second preparation nor backend quarantine. The independent
review logs are `batch24-palette-preparation-independent.log` and
`batch24-palette-preparation-retained-stop-review.log` in the parent scratch
directory; they are local review evidence, not shipped product files.

Full-repository regression, physical-device evidence and publication belong to
the integration gate.

## Merged-source integration

The changes are integrated onto `586e12db5ea5142951c844f60dc2364f07a01c37`,
which preserves the concurrent manual-palette worker and component-queue work.
Those changes do not overlap these production modules. The combined platform
and native gate passed **36 tests in 4.606 s: 35 passed and one Windows desktop
sampling case skipped**. Physical desktop sampling is verified separately by
the published-commit Windows gate. Full merged-source evidence is in
[v148-batch25-validation.json](v148-batch25-validation.json).
