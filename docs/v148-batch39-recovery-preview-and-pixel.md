# v1.0.148 — recovery, preview and Pixel planning continuation

## Scope and counting

Baseline: `74c3a510416b56bff84e70353622e3a91884f09e` on the open draft
`improve/v1.0.148` branch. Four corrections address required recovery images,
preview result ownership, repeated Pixel source-run work and CPU palette
preparation. Image formats, profile formats, dependencies and the application
version remain compatible.

**Two new groups: R3901/global845 and P3901/global846. The implemented total
is 846/1,000; 154 remain.** Recovery and preview lifetime corrections complete
existing contracts and add zero IDs. All 844 preceding registry objects and
134 preceding JSON reports, including 84 benchmark reports, are preserved.
Tests, fixtures, failure branches, documentation and cleanup are not separate
behavior improvements. Version 1.0.148 remains unreleased.

| Area | Correction | Counting |
| --- | --- | --- |
| Recovery | Reject a required PNG that is missing, invalid or unreadable before applying its checkpoint settings | Completes 075/global75 and AW16/global630; zero new IDs |
| Preview | Own completed plan images until successful publication, and retire expired results before fallback | Completes IW08/global582 and established Stop/timeout ownership; zero new IDs |
| Pixel source groups | Share the component collector's immutable horizontal segments instead of scanning and allocating them twice | R3901/global845, one group |
| CPU palette preparation | Composite only the current 4,096-pixel scoring block when a full host composite is unnecessary | P3901/global846, one group |

## Required recovery images preserve current work on failure

The cache reader intentionally returns `None` for a missing or invalid image.
The controller previously published this as a successful recovery and applied
the checkpoint's settings and saved area while leaving the current, unrelated
source image in place. It could then display a successful recovery message.

The validated snapshot now exposes `image_required` separately from
`has_image`. The former preserves the checkpoint's strict Boolean declaration;
the latter retains its existing file-availability meaning. An accepted worker
checks Stop first and refuses to publish when the required image is absent.
Its existing error path reports that the local image could not be read or
verified and that current work was kept.

This also covers an image already missing before the dialog, both modern
digest references and legacy checkpoints. An invalid modern digest does not
fall through to an unrelated legacy file: the loader is still called only
when the validated reference is available. Intentional settings-only
checkpoints retain their previous behavior. Valid retry still restores the
exact pixels and settings with Manual preview and all input gates disarmed.
Recovery files are retained after these failures.

Ten new methods exercise the real controller, reader, Pillow decoder, worker,
queue and Tcl variables. They cover digest mismatch, matching-digest truncated
PNG, disappearance after the accepted dialog, the real reader byte limit,
missing modern and legacy files before the dialog, invalid modern identity
beside an unrelated legacy file, late Stop, valid retry and settings-only
compatibility. The first frozen product baseline fails eight of these methods;
all ten pass after the correction. These branches prove one existing recovery
contract, not eight new improvements.

## Preview results have an owner through publication

A real preview could finish planning just as its deadline expired. The
controller discarded its return value without explicitly retiring the images
before starting a fallback. Finalization or queue-publication failure likewise
left the completed result's images alive through a retained exception.

The controller now reuses the existing `_PlanImageOwner`. It captures a real
`make_plan` result immediately, retires an unsuccessful attempt before another
allocation, and retains a successfully published plan for the queue/UI owner.
Unpublished results close in the worker's finalizer. Borrowed input/options
and the previous UI plan remain open. A secondary close failure does not
replace the primary error; an otherwise unhandled cleanup failure remains
visible and prevents another fallback allocation.

The initial actual-worker reproduction retained eleven open result images
after a controlled publication `MemoryError`. Seven frozen regressions verify
normal and full-detail publication, actual UI adoption, deadline fallback,
full-detail timeout, Stop/closing and retry, publication failure, primary-error
preservation and borrowed inputs. Six methods fail on the baseline; all seven
pass after the patch. Five existing explicit-preview Stop cases also pass.
Planning policy, source pixels and successful preview contents are unchanged.

## R3901 — reuse exact horizontal source segments

Lines planning previously called `groups_from_pixel_map` before component
extraction. Both stages scanned the same rows and color transitions into
identical horizontal segments, with separate tuple objects for the two lists.

The builder now performs the same palette/PixelMap validation before creating
the cost model, allocates the empty color groups and supplies them to the
existing component collector. The collector appends each immutable segment
to its component and source-color group in the original row-major order.
The lists remain separate; no persistent cache or new raster is introduced.

Component labels, region statistics, orientations, path scheduling and the
later R2601 topology handoff are unchanged. Dot planning keeps its existing
builder. Standalone component consumers do not build extra source groups.
The actual public-plan cases include ordinary Lines, an active timer,
Subject first, Subject only and Dots. Independent scalar component labels,
read-only/unsigned inputs, Stop and retry preserve the existing contracts.

The focused observations remove respectively one, one, two and one duplicate
group scans from the four Lines-based public cases. Dots still performs its
original one group scan. Three real asset cases share all 420, 672 and 756
segment tuples between the source groups and component lists; previously
none were shared. All ten recorded semantic plan/component signatures agree
between the frozen before and after selections.

This differs from CP05/global680, which batches statistics inside component
extraction; PL36/global176, which reuses a Gartic vertical density raster;
R1401/global787, which improves later path attachment; and R2601/global838,
which hands labels and compact topology to later regional scoring. The
removed scan and duplicate tuples form one work/storage reduction.

The existing `planning_stage_seconds.source_runs` now measures validation and
empty-group setup, while the shared extraction belongs to `components`.
Individual stage times therefore are not equivalent before/after measures.
Only complete caller times are compared below.

## P3901 — bounded necessary CPU palette compositing

Normal CPU palette matching already tiled its distance/features work, but
first prepared a full float32 visible RGB image. This could force its public
Pixel Accurate caller into emergency mapping when that avoidable allocation
failed. The CPU scorer only consumes 4,096 source pixels at a time.

Large CPU inputs and OpenCL-to-CPU fallback now use the unchanged compositor
for the current scoring block and fill the required visibility output in
place. Alpha arithmetic, white filtering, candidate order, ties, fidelity and
custom-color preference are unchanged. Small inputs retain the previous
preparation path. CUDA-to-CPU fallback reuses the full composite already
prepared for CUDA.

CPU completion also releases private closure references. This resolves the
reproduced full-composite retention through a held native exception after
successful fallback. Returned arrays retain their own references; Stop and
host failures retain their original identity and backend health behavior.
Those lifetime completions add no separate ID.

Eight frozen methods compare full arrays against the dense historical cost
model, exercise real `exact_palette_map` and `make_plan` callers, observe
bounded preparation and test controlled native/host failures. Six methods
fail on the baseline; all eight pass after the patch. Seventeen adjacent
numeric/native-boundary controls also pass. Controlled allocation limits
are fault injection, not observations of physical OOM or GPU performance.

This differs from CG22/global122's bounded distance/features work,
GP10/global562's compositor arithmetic, P2504/global836's omission of unused
OpenCL host preparation, P3801/global844's Auto-count sampling, and
R1402/global788/PL19/global159's separate emergency matching path.

### Whole palette-mapper measurements

The actual `PixelAccuratePlanner.exact_palette_map` uses 18 standard colors
and Faithful matching. Four existing assets have six balanced before/after
pairs each. Only the complete historical/current `UniversalGpuAcceleration`
module changes; all other dependencies are held constant. Loading, warm-up,
allocation observations and parity checks are outside the timed calls.
All 48 outputs agree, including complete pixel arrays, masks and metadata.

| Existing asset | Median full call, before → after | Live RGB-composite ndarray payload, before → after |
| --- | ---: | ---: |
| Screenshot PNG, 1,920 × 1,048 | 943.153 → 947.639 ms | 24,145,920 → 49,152 bytes |
| Screenshot WebP, 720 × 393 | 133.901 → 135.907 ms | 3,395,520 → 49,152 bytes |
| Mixed-alpha icon, 512 × 512 | 123.351 → 126.100 ms | 3,145,728 → 49,152 bytes |
| Paint tools reference | 8.646 → 8.250 ms | 69,312 → 49,152 bytes |

The large-source medians are 0.48%, 1.50% and 2.23% slower locally; the Paint
case is 4.59% faster. The accepted change bounds temporary preparation memory;
it does not establish a general CPU speedup. The payload observation sums live
returned RGB composite arrays, not all compositor scratch, peak native memory
or process RSS. Required image-sized raw RGBA, index/mask outputs and the
PixelMap byte-RGB representation still exist. No physical GPU timing is claimed.

### Isolated whole Pixel-plan measurements

The exact historical/current `PixelStrokeEngine` module is selected before
application imports. Every other current dependency, including the concurrent
CPU palette change, is identical. Six workloads have six balanced process pairs.
Each process measures the first call after imports/source loading, then two
warm calls. Separate processes record Python-traced allocation.

| Existing asset/caller | Cold median, before → after | Warm median, before → after |
| --- | ---: | ---: |
| Paint reference, Lines | 596.2 → 606.9 ms | 556.0 → 595.3 ms |
| Screenshot, Lines | 859.5 → 898.7 ms | 869.3 → 835.9 ms |
| Icon, Lines | 320.8 → 336.3 ms | 312.7 → 308.6 ms |
| Screenshot, two workers | 387.6 → 369.9 ms | 353.9 → 338.1 ms |
| Unchanged Dots control | 470.2 → 480.6 ms | 427.3 → 455.4 ms |
| Standalone components control | 10.200 → 9.615 ms | 9.493 → 9.346 ms |

These mixed observations do not establish a general whole-plan speedup.
Whole-plan traced peaks remain nearly unchanged; these measurements neither
establish an overall memory reduction nor locate the peak. The standalone
control's traced peak and retained bytes are exactly unchanged.
The established reduction is the removed duplicate scan/segment storage at
this stage, with full output parity. All slower cases remain in the evidence.

There are 216 accepted timed calls: 180 complete public plans (60 cold,
120 warm) and 36 standalone component calls (12 cold, 24 warm). A separate
24 allocation calls comprise 20 public plans and four component calls. All
complete semantic outputs, images and metadata agree; only documented elapsed
time diagnostics are excluded. Every measurement process retains the stable
1,122-entry source manifest. These are local Linux observations, not physical
mouse execution, Windows throughput, all native memory or RSS measurements.

## Test-fixture and runner diagnostics

A larger recovery selection exposed a pre-existing fixture ownership gap:
`ScreenTaskWindow.root` still referenced its Tcl interpreter after workers were
joined and the fixture's other root aliases were released. The shared fixture
now clears that alias on its creator thread. A second reference probe identified
the dialog mock's retained `parent=root` argument in cyclic call history. Both
dialog sites now reset their mock history in `finally`, after their call-count
assertions. The before/after reference probes show that this borrowed alias is
released. The initial `Tcl_AsyncDelete` aborts are retained as failed diagnostics,
not completed regression runs.
No product GC policy, timeout, assertion or skip was weakened.

The first custom adjacent runner also lacked a `__main__` guard. An existing
multiprocessing regression reimported it under spawn and recursively executed
the selection. Its mixed logs and overwritten receipt are retained as invalid
diagnostic evidence. The runner was corrected; the final same 54-method
selection passes, including all ten new recovery methods. Earlier seven-method
recovery results are separately retained and are not added to the final count.

The 32 new methods use shipped raster assets, cropped/resized versions or
derived numeric representations. Existing regression suites run their
established fixtures unchanged, including older synthetic unit fixtures.
No AI images or new source motifs are introduced.

## Final local verification

The final source freeze contains the four product changes, four new test files
and the completed shared fixture cleanup. Linux Python 3.12.14, Pillow 13.0.0
and NumPy 2.3.5 executed the following checks:

| Actual selection | Result | Unittest time |
| --- | --- | ---: |
| All four new modules together | 32 passed; no failures, errors or skips | 4.298 s |
| Complete discovery | 4,768 total: 4,682 passed, 86 platform/display/hardware skips; no failures/errors | 263.504 s |
| Real Linux/Xorg UI selection | Four existing workspace/profile/error-action/shutdown methods passed; no skips | 20.254 s |
| Source gate | Passed all structural checks and 5,000 lifecycle/profile-isolation cycles | Separate gate |
| Source-package hygiene | 1,423 files; no forbidden paths, missing required files or warnings | Separate gate |

Integration, full discovery and native UI validation bind exactly the same
**958 unchanged source/configuration/fixture hashes**. The report builder checks
the actual commands, raw log bytes, counts, final source state, all four frozen
test modules and the independently reviewed file/method hashes. The complete
4,768-method verbose inventory is retained in `full.log` and bound by its
ordered inventory and raw-file hashes.

The accepted frozen before/after selections comprise 32 methods: 22 fail on the
old product, with 31 assertions across their subcases, and ten are unchanged
positive controls. All 32 pass after the patch. These are regression methods,
not additional improvement IDs. Focused adjacent selections overlap integration
and full discovery and are never summed as new tests.

An earlier complete 4,768-test run passed on the preceding fixture revision.
It remains a historical receipt; the final 263.504-second run above follows the
second explicit dialog-history cleanup. Failed Tcl attempts, alias probes,
the initial seven-method recovery selection and the invalid spawned runner
remain separately identifiable in the evidence.

[Validation and exact source bindings](v148-batch39-validation.json),
[lossless focused/measurement evidence](v148-batch39-evidence.json) and
[the preserved previous PR checkpoint](pr46-history-through-batch38.md) record
the results and their limits. The evidence archive preserves all 84 Pixel
measurement reports, every CPU pair and the earlier diagnostics. Repeated
source maps are represented losslessly by content-addressed base/delta records.

Local validation does not establish physical drawing in Microsoft Paint,
physical CUDA/OpenCL execution or every Windows DPI/target combination.
Exact published-head Windows/Linux, dependency, CodeQL and packaged-app results
are reported separately in [draft PR46](https://github.com/Vxiey/Image-Draw-Bot/pull/46).
The preceding commit's successful CI is not reused as verification of this
patch. No merge, tag or release is performed by this continuation.
