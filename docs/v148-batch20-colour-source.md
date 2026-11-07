# Batch 20 — shared color-source analysis

## Scope and status

The **C2001** group shares one operation's visible RGB pixels and
alpha between drawable filtering, quantized-region measurement and regional
color analysis. It changes the actual Dynamic Colors path used by public
Standard, High and Ultra plans, and the palette-only path used by Paint picture
palette preparation. It does not change color selection, grouping, stroke
geometry, calibration, fidelity policy or execution.

Historical baseline: **47777158e5b1daf759993190e638fe507e7691da** (published
batch 19). Changed production files are `ColorMatchingEngine.py`,
`DynamicColors.py`, `RegionAwareQuantization.py` and
`PictureCustomPaletteLegacy.py`. No DrawBot integration change is required.

The work/count and correctness gates below are complete, and independent source
review is closed without a blocker. Final coordinated six-pair timing/allocation
measurements are recorded below, including neutral or slower observations.

## Reproduced before changing production code

`test_v148_colour_batch20_source_analysis.py` initially ran three actual-flow
methods with **eight assertion failures and no fixture errors**. The failures
covered all three requested public resolutions, two real Dynamic planning
failure boundaries, and three picture-palette completion paths.

A real `DrawBot.make_plan` receives an RGBA image after source preparation. In
its Dynamic Colors call, the previous implementation prepared the same visible
source again for separate consumers:

1. `visible_rgb_image` produced the quantizer's RGB source.
2. `_drawable_source` converted/extracted alpha for skip decisions.
3. `measure_quantized_regions` produced another visible RGB image and another
   alpha plane for source statistics.
4. `build_region_context` converted the already-visible RGB image again.

The public fixture uses a 600×450 canvas, a deterministic 96×72 source with
opaque, partial-alpha and transparent pixels, four available planning workers,
8,192 MB available RAM and CPU compute policy. Actual planner resolutions are
200×150 (Standard), 480×360 (High) and 600×450 (Ultra); the resolution policy and
image preparation remain real.

| Actual full-size Pillow operation inside Dynamic Colors | Before | After |
| --- | ---: | ---: |
| RGBA → RGBA conversion | 4 | 0 |
| Conversion producing RGB | 3 | 1 |
| Alpha channel extraction | 2 | 1 |
| White RGBA composite image | 2 | 1 |

Every public resolution and both 640×480 direct workloads have these same
operation counts. Nested Pillow `copy` and `convert` observations are not added
together as separate allocations. On the already-RGB picture-palette input,
actual RGB copy operations fall from three to one.

The initial failure tests also retained real exception tracebacks. Stop directly
after the real quantizer, and an injected error after real region measurement,
left private source/quantizer images open. The picture palette's owned analysis
image remained open after successful refinement, Stop and a retained refinement
error. These are disposal completions, not separate counted improvements.

## Implementation and ownership

`ColorMatchingEngine._ColorSourceAnalysis` is an operation-local owner. It
borrows already-RGBA input through the existing read-only reader and owns one
independent visible RGB image, one read-only RGB byte export, and an alpha export
when the source needs alpha statistics. Non-RGBA modes retain the same Pillow
RGBA normalization and rounded white compositing as before.

The existing `DynamicColors.visible_rgb_image` hook remains in the real call
chain, including its established Stop regression. The same source data is passed
privately to the measurement and region consumers. The owner checks source
identity; it cannot be reused for a different image or a completed operation.
Nothing is cached globally, attached to the original image, or retained in a
returned plan.

Lifetimes follow actual consumers:

- The visible Pillow RGB image closes immediately after quantization.
- The alpha byte export is released after source-region statistics.
- The RGB byte export is released after regional analysis, before color merging.
- Palette-only labels close after regional analysis; stroke labels close after
  row/dot generation, before later color diagnostics.
- An outer owner closes all remaining private images on early return, Stop or a
  retained exception. Quantizer-count failure closes the newly created quantizer
  before propagating the error.

Direct `measure_quantized_regions` callers create and close their own source
owner, and close the visible Pillow image as soon as its independent exports
exist, before statistics run. Direct `build_region_context` callers retain the historical
`convert('RGB')` semantics, including its handling of transparent input; the
private prepared path receives already-composited pixels. Its temporary source
conversion and protected-mask resize/conversion now close explicitly.

Picture palette fingerprint strips and their visible images close after each
strip. The analysis thumbnail closes if preparation fails, and the complete
picture palette analysis closes after refinement on success or at any failure
boundary. Successfully returned palettes contain values, not image owners.
Borrowed caller images remain open and byte/metadata-identical.

Independent review identified a further retained-traceback boundary: clearing
the source owner alone did not remove local RGB-array aliases in drawable
filtering, quantization, regional setup and local contrast. Two focused methods
reproduced five live weak references after actual controlled allocation or
quantizer errors. Narrow `finally` blocks now release those aliases in callers
and consumers without changing arithmetic. Both methods pass, including the
straight-RGB direct-region control. A separate before-failing test also verifies
that standalone region measurement closes its visible image before statistics
read the still-valid independent byte exports.

The sharing retains the one-byte alpha export across quantization until
measurement, instead of extracting it twice. The final allocation measurements
report the complete operation's traced peak; reduced conversion counts are
not a claim that every workload's peak memory or time improves.

## Correctness and work evidence

The new test module contains **eleven methods**, covering:

- actual Standard/High/Ultra public plans and operation counts;
- independent visible-pixel, alpha and region-mask comparisons for RGBA, RGB,
  keyed RGB, L, keyed L, LA, P, indexed alpha and premultiplied RGBa;
- real last-consumer boundaries for source images, arrays and quantizer labels;
- separate concurrent source operations and source-identity rejection;
- Stop and retained errors through actual public planning;
- direct measurement/quantizer failure ownership;
- retained computation/allocation failures with weak references to shared RGB
  exports, and the standalone measurement's last Pillow-image consumer;
- picture fingerprint strip cleanup and failed thumbnail preparation; and
- picture analysis completion, Stop and retained refinement errors.

All eleven passed in **3.024 s**. The first combined gate also passed the three initial new
methods and 49 existing color/performance/region regressions. The final adjacent
color/picture gate before the last three ownership methods passed **98 tests in
4.180 s**; the source-alias changes then passed **37 related tests in 3.466 s**.
Independent source review is closed. A separate root run of all eleven final
methods passed in **3.033 s**, preserving the actual caller and retained-owner
assertions. Final whole-project integration remains a separate gate.

`benchmark_v148_colour_batch20.py --verify-only` passed:

| Whole historical comparison | Exact pairs |
| --- | ---: |
| Complete Dynamic Colors strokes/selectors/metadata | 108 |
| Complete palette-only output | 9 |
| Complete source-region measurements | 9 |
| Complete direct region contexts | 9 |
| Complete public/helper workload outputs | 8 |

Twelve of the stroke cases also pass the independent drawable-coverage raster
oracle. The four complete historical modules are loaded together, with historical
imports linked at module loading and call time; the stable picture frontend also
uses the selected historical/current legacy module. This includes the real
`make_plan` → Pixel Accurate → picture palette path. All unrelated public planner
dependencies are identical on both sides.

The eight workloads are small/large direct Dynamic strokes, a large Dynamic
palette, actual Standard/High/Ultra plans, the public picture palette builder,
and an actual Pixel Accurate plan that builds its image RGB palette. Complete
plan comparison excludes only the established wall-clock/profiler fields; no
color, geometry, selector, estimated-time or quality fields are excluded.

Pillow work observers deliberately retain returned image wrappers to distinguish
explicit closure from garbage collection. They show all private Dynamic image
results closed before return after this change. Their cumulative logical pixel
payload counts are not process RSS, Pillow native allocation sizes, or peak
memory measurements. These observers are disabled during timing and tracing.

## Deduplication

Only the cross-stage work reuse is counted as C2001. **CG29** already established
an owned opaque-RGB fast path and avoided copies in individual analysis helpers;
its behavior remains intact. Avoiding an already-RGBA copy inside the shared
visible helper completes that contract and is not counted separately.
**CG30** already replaced per-label full-image scans with stable grouping; that
source ordering and statistical arithmetic remain unchanged. **C1901** caches
cluster statistics after the source analysis and is also unchanged.

Explicit disposal, Stop and retained-exception coverage complete **IW08** and the
existing palette cancellation contract (**CQ07**), with **zero additional IDs**.
There is no count for each format, each resolution, each consumer or each cleanup
branch. The new group records verified cross-stage work reuse, not a claim that
all complete planning calls become faster or have lower peak memory.

## Final measurement protocol

Run only after coordinated source/CPU freeze:

```sh
.venv/bin/python benchmark_v148_colour_batch20.py --repeats 6
```

The script performs one warm parity pair, six balanced AB/BA timing pairs for
each of eight workloads, then separate `tracemalloc` probes after garbage
collection. Every timed/traced output must match the complete historical result.
All root Python source hashes are checked before and after. Final raw output is
`docs/v148-batch20-colour-benchmarks.json`.

Timing covers CPU planning, complete result fingerprinting and owned-plan
cleanup. It excludes actual target-app drawing, native GPU computation, network
and GUI throughput. Traced peaks cover Python/NumPy allocations and exclude most
native Pillow cores and process RSS. The final table discloses neutral or
slower workloads alongside improvements; no whole-application speed claim is
made.

## Final frozen-source measurements

The final report compares `47777158e5b1daf759993190e638fe507e7691da` with the final batch20 source using six balanced AB/BA pairs per workload. All complete timed and separately traced outputs match. All **819 root Python files** remained unchanged. Values below are observed medians, with the allocation probe measured separately from elapsed time. A negative time change means less elapsed time in this fixture.

| Workload | Before median, ms | After median, ms | Time change | Traced peak before → after, KiB |
| --- | ---: | ---: | ---: | ---: |
| `dynamic_strokes_small` | 74.322 | 76.213 | +2.5% | 793.9 → 794.0 |
| `dynamic_strokes_large` | 267.310 | 260.857 | -2.4% | 15080.6 → 15081.7 |
| `dynamic_palette_large` | 145.812 | 140.602 | -3.6% | 15080.8 → 15082.0 |
| `make_plan_standard` | 379.491 | 390.915 | +3.0% | 23555.2 → 23557.0 |
| `make_plan_high` | 912.752 | 904.023 | -1.0% | 26054.8 → 26055.1 |
| `make_plan_ultra` | 1320.515 | 1377.325 | +4.3% | 28490.1 → 28490.3 |
| `picture_palette` | 78.328 | 77.632 | -0.9% | 1920.0 → 1920.2 |
| `make_plan_pixel_picture` | 383.545 | 355.910 | -7.2% | 4451.6 → 4451.2 |

These observations retain the measurement boundaries described above. They do not establish native drawing speed, physical GPU performance, process RSS, or a universal application speedup. Python/NumPy tracing excludes most native Pillow image storage.

Raw result: [v148-batch20-colour-benchmarks.json](v148-batch20-colour-benchmarks.json); SHA-256 `fd99453a0e329b206f98c21db9fed35c0a308b9ed3c7dc3ac4e0655ef6caa028`. Canonical compact source-manifest SHA-256: `32d88cc73bf427735e361550fcaaa2942063a62de5ae8fefee3baf79dfb122f5`.

### Interpretation and observed regressions

The final timings establish no general whole-planning elapsed-time improvement.
Ultra was **4.3% slower** in the median and slower in five of six pairs; small
Dynamic was **2.5% slower**, also in five of six pairs. These observed
regressions are retained, not dismissed as proven noise. The large direct
Dynamic and palette workloads were faster in five of six pairs. The lower
Pixel+picture median is not a robust 7.2% speedup claim: three pairs were faster
and three slower, with after samples spanning approximately 329–442 ms.
Standard, High and picture-palette pairs were also mixed.

Every measured traced-peak change is below 0.01% (−452 to +1,863 bytes), so
these observed peaks are effectively unchanged. The stable improvement is the
verified reduction in repeated conversions/composites and logical image payload
work described above; native Pillow allocation and process RSS were not measured.
Independent review of the raw alternating pairs and output digests found no
measurement blocker and required no selective rerun.
