# Batch 22 — consistent low-VRAM portrait preprocessing

Baseline: `ec22fd8739573adc2df1b3e33dbe1a98a09b9c99`.

## P2201: keep focused portrait pixels independent of tile size

The full-frame CUDA enhancement applied contrast, gamma and the subject-focus
background lift to floating-point values, then rounded once to output bytes.
The low-VRAM branch disabled focus in each native tile, rounded those pixels,
then added the lift on the CPU and truncated its result. Consequently a change
in available VRAM could change the prepared image even with identical input and
settings. In the existing `small-detail-preservation.png` fixture resized to
96 × 80, the old tiled path differed from the full-frame result at **836 of
7,680 pixels** for core heights 1, 7, 23 and 79; each difference was one byte
level. The existing 24 × 24 focus threshold case differed at 100 of 576 pixels.

The related tiled saliency path used four overlap rows with a Gaussian sigma of
1.2 and the default truncate value of 4.0. That Gaussian needs five rows on each
side. Its incomplete support changed values near tile boundaries, and its
separate CPU centre-weight pass used a different numeric path. The original
one-row test differed at **4,500 of 7,680 saliency values**, with a maximum
absolute difference of approximately **0.000035882** even without subject focus.
These are numeric differences, not a claimed measured change in recognizability.

Both existing fused kernels now receive the original canvas dimensions and the
input tile's row offset. Focus calculations therefore use the same global
coordinates on full-frame and tiled calls. Enhancement keeps the complete float
calculation before the single final rounding, and saliency keeps its centre
weight in that same native calculation. The full-frame offset is zero. Gaussian
support is explicit and shared by the saliency planner, filtering and tile
slicing, including the actual remaining-VRAM allocation path.

The parity claim covers each operation given the same input samples. The
existing full-frame enhancement session still retains its unrounded float32
output for subsequent analysis, while a later call without that session uploads
the supplied byte image. This change preserves that session behavior; it does
not claim identical complete enhancement-to-saliency pipelines across those two
different input representations.

The two former full-frame host coordinate-grid/focus postpasses are removed.
This eliminates those allocations and duplicate focus computations from the
tiled implementation; no elapsed-time, RSS, physical VRAM or GPU-throughput
claim is made. Private tile images close after their existing blocking upload.
The caller's image and an explicitly supplied analysis session retain their
ownership. CPU fallback, driver quarantine, transient-OOM treatment and Stop
remain unchanged.

This is **one behavior group** covering consistent low-VRAM portrait output.
The two affected kernels, Gaussian halo, ABI regressions and owned tile cleanup
are not counted separately. Version, registry and publication status are owned
by the integration checkpoint.

## Verification

`test_v148_platform_batch22_portrait_tiles.py` opens the tracked fixture; it
creates no new image files. Its ABI boundary compiles the exact production CUDA
kernel bodies as ordinary C++, replacing only thread scheduling. An independent
separable Gaussian reference supplies the documented finite support. This
exercises the actual public full/tiled call paths, scalar ABI, uploads, tile
slicing and host result assembly without pretending a GPU is present.

The pre-fix run completed seven methods with seven reported failures: the four
tile sizes, the 24-pixel threshold, saliency and the actual halo allocation
path. The corrected source passes all seven methods:

- Exact enhanced bytes across all four tile sizes with subject focus enabled.
- Existing no-focus output and the original global 24-pixel minimum, including
  a narrow canvas that must keep focus disabled.
- Exact full/tiled saliency arrays, with and without focus, for core heights
  1, 7 and 23, including outer boundaries and partial final tiles.
- Reuse of a completed full-frame analysis session and its cached gradients.
- The real small-budget allocator reserves the complete five-row support.
- Stop after the first tile prevents later launches for enhancement and saliency.
- Native allocation and runtime failures retain CPU fallback; temporary OOM
  does not quarantine the backend, and the source image stays usable.

The existing scalar-ABI regression now verifies the added signed 32-bit offset
and canvas fields at every full/tiled kernel call, preserving its original
floating-point and numerical assertions.

The focused and adjacent gate passed **48 tests in 2.768 seconds**:

```sh
.venv/bin/python -m unittest \
  test_v148_platform_batch22_portrait_tiles \
  test_gpu_execution_regressions \
  test_v148_platform_batch03_cancellation \
  test_gpu_v106 test_gpu_memory_fill_v106 -q
```

The host-kernel class skips explicitly when a C++ compiler is unavailable.
These results are Linux source regressions, not native CUDA-driver, Windows GUI
or packaged-application validation. The integration run and published commit's
CI determine those remaining gates. No new release is claimed here.

Primary Gaussian support reference:
[CuPy `gaussian_filter`](https://docs.cupy.dev/en/stable/reference/generated/cupyx.scipy.ndimage.gaussian_filter.html)
documents the default `truncate=4.0` and radius derived from sigma and truncate.

## Existing numeric ownership and allocation contracts completed — zero new IDs

These two completions extend **CG20 / 120** (numeric Stop), **GP04 / 556**
(remaining allocation capacity) and **GP06 / 558** (failed-frame ownership) to
actual callers that still bypassed those contracts. They do not add further
behavior groups to this batch, and do not count cache maintenance or individual
backend branches again.

### Release a failed numeric attempt before CPU fallback

The six universal numeric APIs previously allocated native arrays directly in
the same function frame that caught a native failure and performed CPU work.
Those arrays could remain live during fallback. A retained Stop traceback also
kept private uploaded arrays or a just-completed CPU/downloaded result alive.
The existing late-Stop publication check correctly withheld the result, but did
not release its ownership.

`UniversalGpuAcceleration` now scopes each unchanged native calculation in a
separate attempt. Its shared failure boundary clears completed failure frames,
including chained exceptions, before marking the route and starting the real
CPU fallback. The outer completion wrapper drops its private references when
an exception escapes. Exception identity and stack locations remain available.
CUDA device scopes and borrowed OpenCL sessions exit normally; caller arrays,
cached contexts and successful returned arrays keep their owners. There are no
explicit releases of borrowed objects or changes to numeric formulas. Stop
arriving with a native failure prevents a second heavy CPU attempt, while
`InterruptedError` still avoids both fallback and backend quarantine. Temporary
OOM still preserves backend health for later work.

Before this change, the new numeric ownership suite completed **seven methods
with 14 reported failures**, including subtests for five numeric operations.
The corrected source passes all seven. Tests keep actual exception tracebacks
alive and observe private arrays with weak references. They cover late CPU and
CUDA Stop, failure-time ownership before `_mark_failed`, exact real CPU fallback
results, successful caller-owned output, read-only borrowed inputs and an
OpenCL palette allocation failure that preserves its borrowed context. NumPy
executes the actual array formulas; only the unavailable native allocation and
transfer boundaries are substituted. This is reference-lifetime evidence, not
a physical VRAM or process-memory measurement.

### Budget resized output as well as uploaded input

`resize_gray_advanced` previously passed only its source dimensions to the
allocation planner, even though interpolation, blur and sharpening allocate at
the destination dimensions. With the tracked 360 × 240 fixture, the existing
five-plane estimator reports **3 MiB** for the input and **9 MiB** for a
720 × 480 output. With 4 MiB remaining, the former check admitted the upload
despite its destination estimate exceeding the planner's existing headroom.
The same failure occurred when another live owner used the rest of the pool.

The scaler now uses the larger pixel footprint of its already pre-reduced
source and its destination. It retains the existing plane count, safety factor
and remaining-capacity calculation. Equal-area inputs with opposite aspect
ratios do not incur an imaginary maximum-width-by-maximum-height rectangle.
Existing large-source pre-reduction remains effective. A rejected full-frame
plan returns the original Pillow Lanczos fallback with CPU execution metadata
and the rejected workspace estimate, without uploading first. The estimate is
still conservative planning evidence, not a guarantee against concurrent
native memory pressure; the existing runtime fallback remains necessary.

The unchanged scaler failed **four of six** new focused methods: two oversized
destination cases and Stop arriving after preflight or together with native
allocation failure. The corrected source passes all six. Both Stop cases now
avoid a needless full CPU resize. The successful controls retain dispatch for
equal-area opposite aspect ratios and for the existing pre-reduced source.
Each ordinary allocation failure executes real Pillow fallback and returns
exactly its expected pixels and target size. The native interpolation boundary
deliberately raises `MemoryError` to observe dispatch; no simulated CUDA image
quality is claimed. The tests read the existing fixture and create no image
files.

### Combined verification

The final focused and adjacent gate completed **101 tests in 3.707 seconds**:
99 passed and two existing physical-GPU cases were explicitly skipped.

```sh
.venv/bin/python -m unittest \
  test_v148_platform_batch22_resize_budget \
  test_v148_platform_batch22_numeric_ownership \
  test_v148_platform_batch22_portrait_tiles \
  test_gpu_execution_regressions test_v148_gpu_numeric \
  test_gpu_route_regressions test_gpu_pipeline_optimization \
  test_v148_platform_batch20_gpu_cache \
  test_v148_platform_batch03_cancellation \
  test_gpu_v106 test_gpu_memory_fill_v106 -q
```

Independent source review of both completions found no blocker and repeated
all 13 new ownership/allocation methods successfully. `git diff --check` is
clean. Test durations identify the runs; they are not performance benchmarks.
The physical CUDA, Windows and packaged-application limitations stated above
also apply to these completions.

Integration note: this batch was rebased onto concurrent checkpoint
`92d5a86709a61802821780f5866409da6cd8cf2e` (823 improvements).
The initial reproductions above used `ec22fd8`; final validation and paired
measurements use the integrated source and are recorded separately.

## Windows checkout of the unchanged cache fixture — zero new IDs

The integrated checkpoint's
[Windows core job](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42399848702/job/128485058668)
completed 4,198 regressions with one failure and three skips. Its sole failure
was `test_separate_synthetic_seed_is_unchanged_readable_and_shipped` in
`test_v148_platform_batch21_color_cache_archive.py`: the raw-byte checksum of
`tests/fixtures/verified-color-cache-v2.json` differed on Windows. The later
self-test, bundle and native drag-and-drop steps were consequently skipped.

The original Git blob contains 474 bytes with LF newlines and SHA-256
`5f62e83ab4a0bef941bb34ee4e91b5b3db23c93daf3dcd96c20f67a87dc61930`.
Converting only those newlines to CRLF produces 499 bytes and
`fe5f96cc208acc18c898a8db865e705c5860de704c5a57edef283e4a2d003b61`,
exactly the failed job's observed hash. No existing text or EOL attribute
applied to the fixture. An isolated Git repository with `core.autocrlf=true`
and a fresh index checkout reproduced that same 499-byte failure.

An initial local trial pinned this one fixture with `text eol=lf` and passed
three archive regressions plus an isolated Windows-style checkout. Concurrent
checkpoint `be30fa54a0c58a8d2b6535d31cb6672727f4e6cc` independently fixed the
same failure with an exact-path `-text` rule. Integration retains that published
rule, disabling conversion for this immutable serialized fixture. The raw-byte
assertion and original fixture blob remain unchanged; no other path changes
its checkout behavior. This is **zero new improvement IDs**.

The final `git check-attr text eol` reports `text: unset` and `eol: unspecified`.
With `core.autocrlf=true`, the actual Git checkout filter returns the canonical
474 bytes and SHA-256 exactly. The retained concurrent commit also isolates the
two older Paint recovery tests' real cache writes in temporary storage; its
[separate completion ledger](v148-batch22-test-storage-completion.md) preserves
that evidence and the original Windows failure attribution.

The first integrated whole-suite run passed 4,246 tests with 59 skips but still
changed the test-generated root color cache through the older Paint tests.
An independent probe of all four new detail-test executor replays observed
zero real ColorCache reads or writes: those palette-only plans do not select
the Microsoft Paint verification/cache branch. Their temporary observation
directory stayed empty and the real cache stayed absent. No speculative
change was added to that test. The final full-suite gate verifies the retained
concurrent storage fix with the runtime cache initially absent. No product
cache behavior or schemas are changed for these test completions.
The final source/configuration manifest includes `.gitattributes`; the published
commit's Windows run supplies the native regression and packaging evidence.
