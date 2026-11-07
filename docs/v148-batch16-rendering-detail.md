# v1.0.148 batch 16 — detail-preview numeric scratch memory

Baseline: published batch15 commit
`d1a5e3a709745ee64263b5801cf1b9089cd6b707`.

This area implements **one distinct behavior group, R1602**: reduce scratch
allocation and retention within the existing detail-aware preview kernel.
The RGB gathering change and associated last-consumer lifetimes are one
allocation improvement. No output-quality, frame-rate or real-time
responsiveness improvement is claimed.

## Observed unnecessary work

`PreviewDetailEngine._cell_extreme` scores the luminance samples in each
oversampled cell and returns one representative RGB pixel per output pixel.
The original function also reshaped, transposed and reshaped the entire RGB
cube into cell order. For a two-dimensional output and an oversampling factor
above one, that last reshape materialized an independent float32 RGB copy.
Only one RGB triplet per cell was subsequently read from that copy.

Before changing the producer, a 960×720 RGBA source resized to 320×240 with
Micro detail produced a `(240, 320, 9, 3)` RGB cell array occupying
**8,294,400 bytes**. `numpy.shares_memory` confirmed that it did not share the
input RGB storage. The same inspection inside a real
`preview_safe_options` → `make_plan` call observed a 200×150 result, 438
paths and a **3,240,000-byte** independent RGB cell copy.

The outer resize also retained completed selection arrays into straight-alpha
output reconstruction: oversampled source bytes, alpha and visible RGB,
converted base pixels/alpha, selected RGB, contrast, the activity mask and blend
strength. These arrays had already reached their final consumers.

Two new allocation regressions failed on the unchanged producer. At the
smaller 96×72 → 32×24 fixture they observed an 82,944-byte RGB cell copy and
all four observed selection arrays still alive during straight-alpha output.
The numerical, public-planner and ownership tests passed before the change,
confirming that this is a redundant-allocation correction.

## Change and preserved arithmetic

The existing luminance scores and `argmax` decision are unchanged. The chosen
row-major cell index is converted to original-raster row and column indexes;
only the selected RGB pixels are gathered. This requires two output-sized
integer index arrays, in exchange for removing an RGB copy whose size scales
with the square of the oversampling factor.

Completed luminance/score arrays are released at their final consumers. The
outer resize similarly releases completed alpha, source, selection and blending
arrays before later reconstruction stages. Metadata keeps the same scalar
recovered-cell count and maximum contrast instead of retaining those full
arrays until publication.

Every float32 expression, arithmetic association, threshold, clipping,
rounding, alpha-compositing formula and sharpening parameter remains unchanged.
The first `argmax` tie still wins. No input array is modified, and no
oversampling cap, cancellation boundary, public signature or Pillow-image
ownership policy changes.

## Exact correctness and ownership evidence

`test_v148_rendering_batch16_detail_memory.py` contains **seven tests**:

- An independent per-cell oracle verifies selected RGB and contrast for
  factors 1, 2 and 3, thin axes, normal/noncontiguous read-only arrays, four
  dark-bias values and deliberate first-position ties.
- Seventy-two full resize cases compare exact pixels, alpha, image metadata,
  EXIF and recovery metadata across RGBA, RGB, L, LA, palette transparency and
  premultiplied RGBa inputs, including hidden transparent RGB and orientations
  1, 6 and 8.
- Explicit bounded-factor cases exercise factors 1, 2 and 3 for Micro detail;
  the grayscale caller retains complete image/metadata parity in every mode.
- The allocation tests verify absence of the independent oversampled RGB
  cell array and use weak references to prove that visible/base/selected RGB
  and contrast have been released before straight-alpha output.
- Stop at each of the four existing boundaries and an injected selection
  failure close private Pillow images while retaining live exception
  tracebacks. Success returns an independent open output. The caller's source
  remains usable and unchanged.
- Actual bounded-preview color and Paint-outline `make_plan` calls, with
  Detailed and Micro detail, compare every stable plan field, geometry,
  estimate, diagnostic image and recovery metadata against the independent
  reference pipeline. Only the explicit existing profiling-duration fields
  are excluded.

The seven tests passed in **0.605 s**. The following adjacent gate passed
**44 tests in 2.239 s**, with no failures or skips:

```text
.venv/bin/python -m unittest -q test_v148_rendering_batch16_detail_memory test_detail_aware_preview_v10113 test_v148_delivery_batch02_diagnostics test_v148_rendering_batch15_prepare test_v148_rendering_batch15_sketch_memory
```

## Complete historical module and initial allocation evidence

The benchmark loads the **entire** `PreviewDetailEngine.py` from the recorded
Git baseline. It does not substitute just a copied expression or a reduced
algorithm. The portable unit suite itself requires no Git history.

```text
.venv/bin/python benchmark_v148_rendering_batch16_detail.py --verify-only
```

This untimed verification passed **459 complete historical cases**: 432 RGBA
pipeline cases, 24 grayscale cases and three bounded-factor cases. Four real
public-planner comparisons also passed, with 96/32 paths for Detailed
color/outline and 97/45 for Micro detail color/outline. Both sides share all
current public planner dependencies, and a call observer verifies that the
actual detail-aware resize was reached once in each plan.

The separate, untimed allocation probe for Micro detail 960×720 → 320×240
recorded:

| Observation | Historical module | Updated module |
| --- | ---: | ---: |
| Independent float32 RGB cell copy | 8,294,400 B | 0 B |
| Observed selection arrays still alive at straight-alpha output | 4 | 0 |
| Complete resize traced peak | 40,868,131 B | 24,918,890 B |

The preliminary traced-peak reduction is approximately **39.0%**. These are
Python/NumPy allocations measured by `tracemalloc`, not process RSS or most
native Pillow pixel storage. Array-lifetime observation and peak measurement
run separately, with exact complete output comparisons. This initial result
is not a whole-planner memory or timing claim.

Raw initial evidence: `docs/v148-batch16-detail-validation.json`, SHA-256
`db263c71b252d189f08a3896848191f0b266b8a6d4aa6aa1b0f1b6278375c298`.
Only this area's source files were held stable for that validation; it is
explicitly marked as not being a frozen whole-repository benchmark.

## Final coordinated measurement

The final six-pair run passed all 459 complete historical resize cases and four public-plan parity cases. All 780 root Python files stayed unchanged and match the final full-suite source manifest. Each of eight complete workloads uses a warm pair, six balanced AB/BA timing pairs and separate traced allocation probes. Every measured result preserves the complete output signature.

| Complete workload | Before median (ms) | After median (ms) | Before traced peak (B) | After traced peak (B) |
| --- | ---: | ---: | ---: | ---: |
| resize_320x240_Detailed | 51.785 | 52.321 | 20,900,059 | 11,094,962 |
| resize_320x240_Micro_detail | 50.165 | 46.056 | 40,868,131 | 24,918,890 |
| resize_512x384_Detailed | 125.074 | 118.442 | 53,490,587 | 28,347,314 |
| resize_512x384_Micro_detail | 121.881 | 117.216 | 104,608,739 | 63,736,682 |
| make_plan_color_Detailed | 164.752 | 163.531 | 16,518,892 | 16,518,724 |
| make_plan_color_Micro_detail | 181.099 | 179.395 | 16,523,248 | 16,523,200 |
| make_plan_outline_Detailed | 308.236 | 295.331 | 53,503,334 | 28,360,181 |
| make_plan_outline_Micro_detail | 408.908 | 401.743 | 104,621,414 | 63,749,621 |

Timing includes output signatures and owned-image cleanup on both sides. These are CPU resize/planning measurements, not native input, GPU or real-time UI responsiveness tests. Traced allocation is not RSS or all native Pillow storage. Whole-planner results can differ from the isolated resize because unchanged work dominates their duration and peak.

Raw final data: `docs/v148-batch16-detail-benchmarks.json`, SHA-256 `07d5b8298608429ab6878f4dfc177242cd05058735aeda231ec436080813cdf5`. Root-Python manifest SHA-256: `1174910496c869777f22eee93e9328c22558704fac7de74b4f0c13d8345e0569`.

## Deduplication and review

- **DP42** avoids full-resolution orientation/RGBA conversions before a small
  resize. R1602 removes a later float32 RGB cell copy inside micro-feature
  selection; it does not change those source conversions.
- **DP44** owns cancellation boundaries and private Pillow-image cleanup.
  Those contracts are preserved and retested, not counted again. R1602's
  lifetime changes concern completed numeric scratch arrays.
- **R1501** reduces gradient-array lifetime in Sketch 2.0. This work concerns
  a separate preview-resampling kernel, also reached by ordinary color
  previews and the grayscale preview path.
- **R1502** avoids two full-source copies in `PixelData.prepare_image`.
  That caller remains unchanged; both historical benchmark sides use it.

Baseline module SHA-256:
`4a9375df0134f46fc35aade59f6e01ab313960eb529af4dae7c96761e12805e1`.

Current implementation snapshot:

| File | SHA-256 |
| --- | --- |
| `PreviewDetailEngine.py` | `34974b75645e5d63ded5aa132510fde31472a3cc48871bbbee2bfe13d42b0db7` |
| `test_v148_rendering_batch16_detail_memory.py` | `d1d78a3a6ae09ffc91af18e97313af63503bede07721316e55af7661681c5034` |
| `benchmark_v148_rendering_batch16_detail.py` | `b416cf3b1cd108b1e328899a979ebdaa43bcea1098cb5ac5ebc0779f017c6aa3` |

Independent source review is closed. Root reviewed the direct indexes,
unchanged float32 expressions, scalar metadata before buffer release and the
existing ownership/cancellation boundaries, then independently passed 20
detail-preview and R1502 tests in 0.907 seconds. Final raw-data review also
verified all eight measurement rows, balanced orders, source hashes and exact
outputs. The coordinated measurements and combined batch16 gates passed; see
[final local validation](v148-batch16-validation.json). Exact published-commit
Windows/CI results are recorded separately in PR46.
