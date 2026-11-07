# 1.0.148 batch 15 — bounded rendering scratch and direct RGBA preparation

Baseline: `43a1c968eb56a63224827f1567e4ccc354acdadb` (796 recorded groups).

This ledger covers **two distinct behavior groups, R1501 and R1502**. Helper
boundaries, private-image cleanup, cancellation checkpoints, numeric tests and
public callers belong to their corresponding group. They are not separately
counted improvements. R1502 also completes existing cancellation/ownership
contracts without adding a separate count for that cleanup.
The global register and release state are maintained by the root coordinator.

## R1501 — release completed gradient passes before later Sketch work

`Sketch2Planner.structure_map` retained both the smoothed and unblurred RGB
gradient cubes, their source arrays and completed intermediate planes until
the component filter returned. Most of these arrays had no further consumer.
The later raw-gradient pass allocated its large arithmetic temporaries while
the complete smoothed pass was still alive.

A direct before observation on a generated 512×384 RGBA graphic found
**25,573,296 bytes of distinct NumPy arrays still alive at entry to the component
filter**, including six full RGB float32 cubes. A separate traced observation
peaked at 30,255,474 bytes. The resulting mask digest was
`8a5ddcbdcd386b49259cf8f61dc90a8ac45e9985da2671ff521f650656b4ccd1`;
the caller's image bytes were unchanged. This initial observation identifies
the retention problem; final paired measurement is recorded separately below.

The smoothed and unblurred gradient passes now have separate local scopes.
Completed luminance/color magnitude arrays become the two exact boolean
predicates needed for final metadata before the raw pass begins. Source and
derivative arrays leave scope before the next phase needs storage. At component
filter entry only the float32 strength plane, output mask and two metadata
predicates remain in the caller: **seven bytes per pixel**, independent of
component count. No persistent cache or full-image duplicate is introduced.

Every original float32 expression, operation order, threshold, Gaussian blur,
NMS direction, micro-detail rule and connected-component decision is preserved.
The original 1500-pixel analysis-size bound remains. Stop is checked before
allocation, between the completed numeric passes and through the unchanged
component traversal. Converted/composited/blurred Pillow images now have explicit
private ownership and close on success, Stop and errors, including retained
tracebacks. The returned contour remains an independent open RGBA image; the
borrowed source is never closed or modified.

The real public callers already use this same helper: Microsoft Paint's black
contour planner and the Sketch + Auto Fill composition. No DrawBot routing,
palette choice, native brush width, CanvasGuard, tool permission, renderer
selection or quality setting changes for R1501.

### Distinctness from earlier work

PB06 bounded the component flood's retained coordinate/peak evidence once a
component was already large enough to survive. R1501 changes the separate
full-frame numeric passes that run before that filter; its filter implementation
is unchanged. PL40 established size/cancellation guards. CP06 released accuracy
evaluation scratch; RC02 removed copies in shadow analysis. Those earlier
contracts and counts are retained.

### R1501 correctness evidence

`test_v148_rendering_batch15_sketch_memory.py` contains six tests. Its numeric
oracle retains the original float32 equations and uses independent union/find
component membership. It compares exact masks and every metadata field across
120 size/mode/detail combinations, including singleton/two-pixel axes, RGB,
RGBA, grayscale, LA and palette transparency with read-only input arrays.

The lifetime regression observes the actual component-filter boundary and
weak references to allocated RGB arrays. It requires that all RGB scratch is
gone and the caller's retained planes fit the seven-byte-per-pixel bound. Other
regressions retain injected failure/Stop tracebacks while checking all private
Pillow images are closed, keep the returned contour alive and independently
mutable, and confirm oversized/cancelled input cannot begin allocation.

Actual Paint outline and Sketch Fill `make_plan` calls compare every stable
returned field, including geometry, palettes, estimates, safety and all preview
pixels. An independent Pillow raster checks their executable paths and contour
ink. The public Sketch Fill cases also verify its initial sketch view and all
three phases. Only explicit profiler durations and their derived slowest-phase
label are omitted from stable-result comparison.

The benchmark's separate historical-source correctness pass has also passed
**375 complete mask/metadata comparisons** against the full baseline module.
All four larger public fixtures (256×192 and 512×384, both renderers) have passed
complete-plan equality and independent ink checks before any timing run.

### R1501 measurement and shared gate status

The paired measurement is prepared in `benchmark_v148_rendering_batch15.py`:

```sh
.venv/bin/python benchmark_v148_rendering_batch15.py --repeats 6
```

It loads the complete historical Sketch2Planner module from the recorded Git
baseline. Both sides share current public callers and unrelated dependencies.
After one warm pair, six balanced AB/BA pairs compare the complete output on
every call. Tracemalloc probes run separately after garbage collection. Public
timings include the full `make_plan`, identical result fingerprinting and image
cleanup. All root Python sources are hashed before and after measurement.

The two direct structure fixtures are 512×384 and 1024×768. Both public renderers
are measured at 256×192 and 512×384. Direct observations separately record every
retained array's shape, dtype and bytes before component filtering. Traced peaks
cover Python/NumPy allocations, not RSS or most native Pillow storage. These CPU
fixtures do not establish interactive UI, native drawing or GPU performance.

The final coordinated measurement completed with all other test/timing jobs paused,
after the full batch's product/test sources, including R1502 and the final worker/UI ownership completion, became stable.
All 375 complete historical numeric cases, all four public-plan/ink checks and
every warm, timed, traced and lifetime-observation result matched exactly.
All **770 root Python source hashes** remained unchanged during measurement.
The recorded environment was Python 3.12.14, NumPy 2.3.5, Pillow 13.0.0,
Linux x86_64. The 57 focused Sketch/Paint/resource/ownership/UI-renderer checks
also passed; the shared batch integration gate remains separate.

### Traced allocation peaks

| Complete workload | Before (bytes) | After (bytes) | Peak reduction |
| --- | --- | --- | --- |
| `structure_map`, 512×384 | 29,315,376 | 14,945,060 | 49.0% |
| `structure_map`, 1024×768 | 117,230,984 | 59,771,684 | 49.0% |
| Paint outline `make_plan`, 256×192 | 7,342,486 | 4,723,863 | 35.7% |
| Paint outline `make_plan`, 512×384 | 29,324,166 | 16,782,263 | 42.8% |
| Sketch Fill `make_plan`, 256×192 | 8,202,471 | 7,693,371 | 6.2% |
| Sketch Fill `make_plan`, 512×384 | 30,577,639 | 26,465,091 | 13.4% |

At component-filter entry, retained caller arrays fall from **25,573,296 to
1,376,256 bytes** for 512×384 and **102,282,336 to 5,505,024 bytes** for 1024×768.
The optimized values are exactly seven bytes per pixel. This boundary observation
is distinct from the earlier peak: some gradient temporaries must still coexist
inside each numeric pass. The warmed paired peak is also distinct from the
initial cold observation above.

### Elapsed medians

| Complete workload | Before (ms) | After (ms) |
| --- | --- | --- |
| `structure_map`, 512×384 | 62.757 | 58.516 |
| `structure_map`, 1024×768 | 218.661 | 215.501 |
| Paint outline `make_plan`, 256×192 | 58.670 | 58.910 |
| Paint outline `make_plan`, 512×384 | 241.270 | 230.808 |
| Sketch Fill `make_plan`, 256×192 | 306.069 | 307.776 |
| Sketch Fill `make_plan`, 512×384 | 926.516 | 931.880 |

R1501 is a measured memory reduction. Elapsed changes are fixture-specific and
subject to ordinary run-to-run variation; no general speedup is claimed. Other phases of Sketch Fill own additional image, palette,
path and preview storage; its whole-plan memory gain is correspondingly smaller
than the isolated structure pass. Neither helper percentages nor reductions
from different fixtures are additive.

The full samples, retained-array inventories, public options, output digests,
comparison exclusions and source hashes are in
[`v148-batch15-rendering-benchmarks.json`](v148-batch15-rendering-benchmarks.json),
SHA256 `901b71484a56bbd3d9218d0ae8bd3fa10501abd44b69fe1b0056f10e3a77ea14`.
The complete historical Sketch2Planner source used for comparison has SHA256
`f4271b40277912919eb3a2dd609f7f3d893cdcbd33b8253bf673690b83da1e08`.

## R1502 — prepare already oriented RGBA without two full-source copies

`PixelData.prepare_image` previously called
`ImageOps.exif_transpose(image).convert('RGBA')` unconditionally. Pillow copies
an image when there is no orientation to apply, and its same-mode conversion
copies again. An already oriented RGBA image therefore made two full-source
copies before the actual resize. This is the ordinary decoded-image path used
by the public planner, not an unused utility branch.

The before reproduction used a 640×480 RGBA source and a 160×120 target. It
observed **two actual full-source `Image.copy` calls**, representing 2,457,600
nominal copied pixel bytes. The corresponding real `make_plan` call made four
full-source RGBA copies in total; this change removes the two preparation
copies while leaving the other planner work intact. The byte count measures
avoidable copy work, not process RSS or simultaneous native allocation peaks.

Preparation now loads the borrowed source before inspecting its actual EXIF
orientation. An identity orientation borrows the existing pixels; any other
orientation retains Pillow's existing transposition behavior. A real mode
conversion still happens before the same resize, and only when the image is
not already RGBA. This preserves premultiplied-alpha resampling, palette and
color-key transparency, metadata and lazy-reader behavior. The fit, sampling,
pixel-budget, preview-detail and resize formulas are unchanged.

Every image produced by transposition, conversion or resizing has explicit
private ownership. A converted intermediate releases its superseded oriented
image before resizing. Stop or a resize error closes all unpublished private
images, even when the exception traceback is retained. A successful output
remains a separate, open, mutable image, including when its dimensions equal
the input. The caller's source remains open and unchanged throughout.

### Distinctness and existing contracts

R1502 counts the elimination of repeated full-source identity copies in the
actual drawing preparation path once. SR14's earlier MobilePreview work changes
a separate caller's resize/conversion ordering; R1502 does not reorder those
operations. CG09 already established cancellation around preparation/resize,
and IW08 established private-image ownership. Closing the unpublished result
and intermediate images on those existing exits completes those contracts and
adds **zero** additional groups.

### R1502 correctness evidence

`test_v148_rendering_batch15_prepare.py` contains seven regression tests.
Its original-pipeline oracle compares exact image bytes, mode, size, `info`,
EXIF, fitted geometry and all preview-detail metadata across **216 cases**:
RGBA, RGB, L, LA, P and RGBa; absent orientation and EXIF orientations 1–8;
ordinary resize plus Fast, Detailed and Microdetail preview preparation.
Read-only source arrays, alpha, palette transparency and RGB/L color keys are
included. Lazy PNG and TIFF readers with orientation metadata use actual
encoded streams and retain the original source's ownership.

Other regressions observe the removed `Image.copy` calls, retain cancellation
and failure tracebacks while checking private images have closed, verify Stop
after orientation prevents the next conversion, and prove that equal-size
results do not alias the source. A real public `make_plan` compares every stable
returned field and confirms exactly two fewer full-source copies. The focused
preparation/color/detail/resource gate passed **32 tests**. Root independently
reviewed the full source change and passed 27 combined R1502/R1501/P1501 checks.

The benchmark also loads the complete historical PixelData module and compares
72 additional mode/orientation/detail cases. Both larger public fixtures
(1536×1152→256×192 and 3072×2304→384×288) compare complete plans and independently
rasterize executable paths before timed measurement. Only the already declared
profiler durations and derived slowest-phase labels are excluded.

### R1502 measurement protocol

```sh
.venv/bin/python benchmark_v148_rendering_batch15_prepare.py --repeats 6
```

The benchmark isolates historical versus current `prepare_image` while keeping
the current public planner and every unrelated dependency identical. One warm
pair precedes six balanced AB/BA pairs, with complete-output equality on every
call. Tracemalloc runs separately after garbage collection. Identical result
fingerprinting and image cleanup are included on both sides. The script hashes
all root Python files before and after the entire run.

Three preparation workloads cover ordinary 1536×1152 and 3072×2304 RGBA sources
and the larger source's Detailed preview route. Two complete public planners
use the same source sizes. Actual full-source `Image.copy` counters and nominal
RGBA bytes copied are reported separately from traced Python allocations;
neither is labeled native peak memory or RSS. No native drawing, GUI or GPU
performance is inferred from these CPU fixtures.

### R1502 final measurements

The final run used the same frozen **770 root Python source files** as the
R1501 refresh above, with no other test/timing jobs running. Every historical
correctness case, public-plan/ink check, warm result, timed pair, traced result
and instrumented copy-count result matched exactly. Both before/after source
manifests were unchanged, and the two benchmarks' complete manifests match each
other. The canonical JSON hash of that shared source-hash map is
`17a88908be9bb8e3f425a2dae8732f3ef93a4cf81577ea0cbcf22732e7e93fec`.

| Complete workload | Before (ms) | After (ms) | Elapsed reduction |
| --- | --- | --- | --- |
| Preparation, 1536×1152→256×192, ordinary Lanczos | 30.386 | 27.128 | 10.7% |
| Preparation, 3072×2304→384×288, ordinary Lanczos | 117.852 | 105.393 | 10.6% |
| Preparation, 3072×2304→384×288, Detailed preview | 178.456 | 166.544 | 6.7% |
| Public `make_plan`, 1536×1152→256×192 | 424.909 | 451.311 | -6.2% |
| Public `make_plan`, 3072×2304→384×288 | 901.426 | 872.785 | 3.2% |

The complete public-plan effect is smaller because resizing, palette analysis,
path generation and previews still perform their ordinary work. These fixture
medians establish the effect in those measured paths, not a general percentage
for every source, renderer or interactive drawing task. Small elapsed differences
remain subject to ordinary run-to-run variation.

| Workload/source | Full-source RGBA copies before→after | Nominal copied pixel bytes before→after |
| --- | ---: | ---: |
| Preparation, 1536×1152 | 2→0 | 14,155,776→0 |
| Preparation, 3072×2304, ordinary or Detailed | 2→0 | 56,623,104→0 |
| Public `make_plan`, 1536×1152 | 4→2 | 28,311,552→14,155,776 |
| Public `make_plan`, 3072×2304 | 4→2 | 113,246,208→56,623,104 |

Traced Python allocation peaks are essentially unchanged: 395,333→395,269 bytes
and 887,081→887,017 bytes for the ordinary preparation cases;
30,093,452→30,092,835 bytes for Detailed; 17,752,482→17,751,819 bytes and
62,148,722→62,148,626 bytes for the two complete plans. The eliminated full-size
Pillow pixel buffers are native allocations outside this tracing scope. The
observed copy counters prove their avoidable allocation/copy work directly;
no native peak-memory or RSS reduction is inferred from the traced figures.

The full six pairs, memory probes, copy counts, exact-output digests, options,
comparison exclusions and source hashes are in
[`v148-batch15-prepare-benchmarks.json`](v148-batch15-prepare-benchmarks.json),
SHA256 `13c4ac5aad161f9f05450fac32bd4e97c31d8e6a31948586192b544a88f45422`.
The complete historical PixelData source has SHA256
`3dba56479a5ce5b7385e5356fd0f3a99c537de64a89e74a42bdf0d57456bbc6c`.
The root coordinator's independent source/correctness reviews of **R1501 and
R1502 are closed without remaining blockers**. Product, test and benchmark code
were stable before the final measurement window and remain frozen afterward.
The shared integration gate and release decision remain with the root
coordinator; this rendering ledger adds exactly R1501 and R1502.
