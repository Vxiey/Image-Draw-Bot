# v1.0.148 batch 42 — compact OpenCL results and bounded CPU gradients

## Scope and count

Baseline: `e33fa67d17e3c33ccda8e736e7e16c2582d9fc06`, tree
`72e55f2a6d3dad971a13e9ab9141aa521cf15177`, the public equivalent of the
local batch-41 checkpoint. This ledger proposes **two distinct groups**.
Parent integration owns the global registry and total. This document does not
claim that the 900-improvement target has been reached.

Product changes are confined to `UniversalGpuAcceleration.py` and
`ImageGradients.py`. Tests and measurements use committed reference images and
their resized or palette-preserving derivatives; no image artifact or source
motif is generated.

| Local group | Reproduced problem | Implemented behavior | Count boundary |
| --- | --- | --- | --- |
| P4201 | Successful OpenCL Lab conversion returned three-channel views backed by four-channel host buffers. The padding remained alive for the complete result lifetime, and paired analysis carried matching unused padding in both device Lab buffers. | Write packed scalar Lab channels directly into three-channel native buffers, download into the actual dense result owners, and make delta/pairwise consumers read the same packed layout. Input float4 alignment and all numerical formulas remain unchanged. | One producer/consumer layout defect across Lab, perceptual pair and pairwise distance; not three IDs. CP06 bounds CPU transform scratch. P2504 and its batch-26 completion concern palette host preparation. GP11 bounds pairwise arithmetic scratch; none removed retained OpenCL Lab padding. |
| P4202 | The shared CPU gradient helper retained full-frame horizontal/vertical and arithmetic scratch for every large floating-point grid, including otherwise bounded analysis consumers. | Compute exact finite differences in at most 256-by-256 output tiles with one-pixel source halos. Retain the required full output, preserve global boundary formulas and array layout, and keep small grids and non-NumPy backends on their existing dense expressions. | One shared gradient-stage memory group. GP09 fixes edge formulas; CQ14 changes later visual-importance arithmetic; RC02 avoids copying completed shadow outputs; R4002 tiles Pixel micro-detail neighbor masks. Those distinct stages remain unchanged. Cancellation/owned-buffer cleanup completes existing contracts and adds zero IDs. |

## P4201: packed OpenCL Lab ownership

The original public `perceptual_pair` result for a 64-by-48 committed-image
derivative retained 49,152 bytes behind each logical 36,864-byte Lab plane.
Together with its delta plane, the returned owners retained 110,592 bytes for
86,016 bytes of logical output. Native input/Lab/delta buffer requests were
49,152, 49,152, 49,152, 49,152 and 12,288 bytes. These are observed allocation
requests at the native API boundary, not physical VRAM measurements.

The new layout retains exactly 12 bytes per Lab pixel, and paired output
retains 28 bytes per pixel rather than 36. The pair's device buffer requests
total 60 bytes per pixel rather than 68. An independent Lab conversion uses
16-byte input plus 12-byte output per pixel instead of two 16-byte buffers.
Pairwise distance retains its required square output while its intermediate
Lab vector uses 12 rather than 16 bytes per color. No extra full-frame host copy
is added to obtain the packed layout.

The final fixed-baseline observation is retained in
`v148-batch42-runtime-opencl-layout.json`. All three complete outputs match
their real CPU route and each other across the historical/current native ABI.

| Actual public operation | Retained output owners, before → after | Native buffer requests, before → after |
| --- | ---: | ---: |
| Lab conversion, 64×48 | 49,152 → 36,864 B | 98,304 → 86,016 B |
| Perceptual pair, 64×48 | 110,592 → 86,016 B | 208,896 → 184,320 B |
| Pairwise distances, 31 colors | 3,844 → 3,844 B | 4,836 → 4,712 B |

OpenCL three-component vector objects still have four-component size/alignment;
the kernel therefore writes scalar `float*` storage and consumers use
`vload3`. This follows the Khronos
[data-type alignment specification](https://registry.khronos.org/OpenCL/specs/unified/refpages/man/html/alignmentOfDataTypes.html)
and [vector-load specification](https://registry.khronos.org/OpenCL/specs/unified/refpages/man/html/vloadn.html).
The scalar addressing changes storage only; conversion, distance arithmetic,
route selection, health accounting and fallback policies stay the same.

`test_v148_runtime_batch42_opencl_layout.py` exercises real public functions
through a controlled native allocation/transfer/kernel boundary. The boundary
checks the actual scalar argument types, buffer sizes, shapes and transfer
owners and supplies deterministic CPU arithmetic. It does not replace product
routing, ownership or fallback. The six methods cover dense/strided/transposed
and four-dimensional inputs, paired and single-pixel shapes, the pairwise
producer/consumer layout, failed native completion and late Stop. Results are
compared exactly with the real CPU route. The existing route regression's
native facade is updated to the same three-channel ABI.

## P4202: exact bounded gradient work

Each tile borrows its source halo and retains the established formula:
one-sided differences only at original-image boundaries, centered differences
inside them, and zero contribution from singleton axes. Both axes are bounded,
including long one-row and one-column sources. NumPy floating-point output uses
`empty_like(..., order='K')` so the original dense operation's shape, dtype and
C/Fortran layout remain available. Empty grids, small inputs, integer/casting
behavior and native array backends keep the original dense dispatch.

The dense threshold is **262,144 pixels**. It includes ordinary small analysis
inputs and a complete 258-by-258 halo input. The concurrent Pixel chromatic-edge
change therefore does not trigger another nested tile loop when calling this
shared helper. The two groups alter different things:
Pixel selects an additional chromatic signal; this helper preserves whichever
scalar finite differences its caller requests.

`test_v148_runtime_batch42_gradients.py` contains eight methods. An independent
`np.gradient` oracle checks exact values and layout across real-source tile
seams, reversed/transposed views, empty axes, singleton axes, two-pixel axes,
float32/float64 and Fortran order. The bounded-allocation regression observes
real NumPy scratch requests through the public helper, so it also exercises
the historical implementation without depending on the new private helper's
name. Additional exact 262,143/262,144/262,145-pixel controls and their reversed
views verify dispatch at the new boundary; the original small-halo, integer
and native-backend controls remain. Read-only source arrays are supported.
Retained Stop/allocation
tracebacks must release private output owners, and the actual universal CPU
and failed-native fallback routes must preserve the complete result.

Whole-consumer comparisons cover `AccuracyEvaluator.evaluate_preview`,
`VisualImportanceMap.build_importance_map` and
`PixelAccuratePlanner.build_pixel_map`, including palette labels, shadow maps,
protected masks, metadata and caller-image preservation. The dense control is
the same real computation with the tile threshold raised, not a substitute
planner.

`benchmark_v148_runtime_batch42.py` prepares a fixed historical comparison for
the helper and complete consumers. It loads exact baseline Git objects and
holds the historical universal CPU caller constant in both directions; all
other consumer source is current and held constant. It checks complete output
digests, alternates four AB/BA elapsed pairs, and observes traced peaks in
separate calls. Required returned arrays and all traced scratch inside each
consumer call are included. Source/preview preparation is outside the call.
It reports traced allocations, not process RSS, physical GPU usage or native
drawing speed. Raw slower observations must remain in the report.

The follow-up `benchmark_v148_runtime_batch42_edge_consumer.py` compares the
actual old/new public `edge_magnitude` functions, including validation, route
selection and completion. It also uses a real strided Lab channel, matching the
input layout consumed by source-relative accuracy. The results are recorded in
`v148-batch42-runtime-edge-consumer.json`.

| Complete operation/input | Traced peak before → after | Median elapsed before → after |
| --- | ---: | ---: |
| Public edge, dense 384×256 control | 1,588,624 → 1,588,920 B | 0.694 → 0.533 ms |
| Public edge, strided Lab 384×256 control | 1,588,464 → 1,588,752 B | 0.784 → 1.063 ms |
| Public edge, dense 1536×1024 | 25,181,416 → 7,372,960 B | 22.330 → 16.961 ms |
| Public edge, strided Lab 1536×1024 | 25,181,416 → 7,372,960 B | 26.026 → 19.266 ms |
| Complete accuracy, 1536×1024 | 97,539,924 → 97,539,924 B | 762.378 → 588.528 ms |
| Complete importance, 1536×1024 | 61,472,501 → 61,472,533 B | 263.726 → 204.157 ms |
| Complete PixelMap, 771×517 | 24,840,244 → 24,840,690 B | 477.568 → 482.940 ms |

All complete outputs are exact, including route/consumer metadata. The large
public edge operation reduces traced peak by about 70.7%; the complete
Accuracy/Importance/PixelMap peaks remain effectively unchanged because other
stages dominate them. The small control paths deliberately retain dense
arithmetic. Timings vary, and the table retains slower strided-control and
PixelMap observations. No universal CPU, app, drawing-speed or whole-analysis
peak reduction is claimed.

The initial 66,564-pixel cutoff was rejected after small public-edge controls
showed only about 126 KB of scratch savings and slower medians. Immediately
above that cutoff, full output plus one tile could also exceed the dense
working set. The three `*-initial.json` reports preserve those raw measurements
and the exact initial gradient/harness source. Their larger complete-accuracy
observations include a slower median (672.513 → 730.881 ms); they are not
discarded in favor of the later faster median. The stable benefit established
here is the bounded large-gradient working set. The OpenCL layout did not
change between these observations.

## Validation status

The initial OpenCL layout selection completed **10 methods, all passing, in
0.122 seconds**: the six new layout methods and four existing palette
normalization methods. This functional selection overlapped the batch-41
discovery and is not performance evidence. No timeout or skip was changed.

The final 14 new methods passed in **4.054 seconds**, without skips. The exact
historical `ImageGradients.py` fails the same public bounded-allocation test:
it requests a 398,607-cell full-grid scratch array, exceeding the 66,564-cell
tile bound. That intentional negative check ran one method with one failed
assertion and no errors. The OpenCL report separately demonstrates the old
retained padded owners while using its correct historical native ABI; it does
not manufacture fallback by forcing the new ABI onto old code.

The final related selection completed **168/168 methods in 7.330 seconds**,
without failures, errors or skips. It includes the 14 new methods, current
rendering fidelity tests, numeric/route/cache/ownership/fallback regressions,
source-relative accuracy and the existing shadow/micro-detail consumers.
Two additional unchanged native-device checks were attempted and skipped:
`pyopencl` and CuPy are unavailable. No timeout or skip condition changed.

`v148-batch42-runtime-validation.json` contains the portable command equivalents,
full captured unittest output, negative-proof command/result, final source/test
hashes and report inventory. Parent reserved one sequential runtime test and
measurement window after rendering completed. All runtime processes exited
before the app measurement handoff. Product source is frozen for integration;
parent owns full discovery, native Windows verification, packaging and remote CI.

An independent read-only review of both product files and all 14 new methods
found no blocker. No OpenCL-capable compiler was found on PATH or in the usual
LLVM/Swift installation paths. The available `g++` cannot establish actual
OpenCL-C compilation, so a host C++ surrogate is not counted as that evidence.
Physical OpenCL/CUDA execution and driver compilation remain unavailable in
this environment. This limitation applies to the new packed kernel as well.

| Frozen product | SHA-256 |
| --- | --- |
| ImageGradients.py | `5eb52ff00ea04ae46cf1116eb55e84f201fc3abc3e81e83f92764313a2fcfd5b` |
| UniversalGpuAcceleration.py | `a2554c90ca03e9853cf8a2669eaeb943dc71b62c64779d95e33800aa47adf5d7` |

## Audit exclusions

`configure_runtime(1)` was observed leaving an already loaded OpenBLAS pool at
nine threads; environment variables alone do not reconfigure that native pool.
However, product dot-product consumers are small, and actual multi-threaded
work or a practical benefit has not yet been demonstrated. No dependency,
global thread-pool policy or third group is added on that observation alone.

Related independent reviews of rendering fidelity and native delivery/DPI
changes are reviews, not runtime IDs. Existing cancellation and ownership
contracts, test-fixture ABI updates and compatibility checks also add zero IDs.
