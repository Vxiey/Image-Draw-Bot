# Batch05 — colour correctness and planning memory

Baseline: `5f3fcfb5c4519e5ed1b9b770ba951918819d725d` (published batch04,668 improvements).
This ledger contains **six distinct new behavior groups**. Backend implementations,
call sites, tests, documentation, cache invalidation and completion of earlier
contracts do not add separate improvement counts.

## New improvements

| ID | Reproduced problem | Change | Production and independent evidence |
|---|---|---|---|
| CP01 | Near-neutral source colors received hue-family penalties in vector/GPU mapping that the canonical scalar matcher explicitly disables below OKLab chroma5. For source `(222,200,194)` and the recorded four-swatch fixture, Faithful scalar matching chose index3 while CPU/vector mapping chose2. | Gate the family penalties consistently in universal NumPy/OpenCL, fused CUDA, legacy CUDA array expressions and the Pixel Accurate emergency CPU fallback. | `test_v148_colour_batch05_matching`: independent scalar costs, actual `exact_palette_map` and its forced fallback, actual CUDA array branch using host arithmetic. Existing `test_gpu_pipeline_optimization.ScalarKernelTests` compiles and executes the actual fused CUDA formula as C++ and compares decisions across modes. A real-device OpenCL fixture runs when available. |
| CP02 | A palette without white used its nearest color as the supposedly untouched white canvas. An empty black-only plan reported100% target/plan accuracy, zero coverage and one missing pixel; black spill also disappeared from the error classification. | Use signed `-1` only as internal unpainted-white simulation state when no exact white swatch exists. CPU/CUDA scoring retain missing/spill errors. Corrections repair drawable colors but never emit the sentinel or pretend an unavailable white swatch can erase spill. Preserve explicit valid background indices. | Real `DrawBot.make_plan` with a black-only prepared Paint palette; missing-dot correction, wide-brush spill, near-white/exact-white palettes and explicit backgrounds. Actual tiled CUDA scoring code is exercised with host-backed arithmetic. Metadata exposes `background_repaint_available` and `unrepairable_background_pixels` for report integration. |
| CP03 | Excluding unpainted white removed isolated colored pixels' boundary evidence. A black dot changed from protected cleanup with micro score.66 to unprotected mid-detail with score.18 solely because Skip white was enabled. | Count skipped white/transparent neighbors as boundaries of drawable features, while keeping nondrawable pixels outside contour/protected maps. A singleton target also retains micro-detail evidence. | Actual source→PixelMap→component-plan tests for black/red/blue dots, transparency, image borders and flat fills. The actual protected entry survives the reserved cleanup quota of a tight progressive budget. |
| CP04 | The picture-palette edge sampler used a clipped Laplacian, which selected only the bright background around a dark accent. Its unchanged filter border also supplied “edge colors” for uniform images. | Use symmetric four-neighbor RGB contrast, retaining both sides of real transitions and no artificial outer-border response. Preserve row-major bounded sampling and palette deduplication. Increment the picture-cache schema so previously cached edge choices are rebuilt. | Dark/bright and equal-luminance chromatic accents, uniform singleton/thin/ordinary images, invisible RGB, real `build_picture_palette` call and old-schema rejection. The previous bounded-sampling test now uses an independent scalar neighbor oracle for the corrected edge definition. |
| CP05 | Component extraction issued five NumPy sums plus max/count work separately for every run, including every one-pixel checkerboard component, and kept a second statistics dictionary per component. | Reduce busy rows together with bounded start/end reduction arrays. Preserve small slice reductions for rows with fewer than eight runs. Accumulate final component fields directly, retaining exact IDs, runs, order and statistics. | Independent pixel flood-fill/statistics oracle with gaps, optional maps, thin images and worker settings; independent reconstruction of complete production planner paths. Paired checkerboard, solid and sparse component measurements compare every field and label pixel. |
| CP06 | Preview accuracy retained multiple normalized RGB copies and materialized full-frame linear/LMS scratch arrays, alongside already finished metric intermediates. | Borrow already valid normalized inputs in read-only numeric consumers, bound CPU OKLab transform scratch to65,536pixels, and release evaluator intermediates when their scalar results are complete. Whole-workload GPU routing and formulas remain unchanged. | Independent scalar OKLab/source-accuracy oracle, chunk-boundary/reversed/transposed inputs, read-only source preservation, full evaluator baseline parity including optional heatmap bytes. Paired CPU measurements show lower traced peaks. |

## Earlier contracts completed, zero additional count

- **CG05:** the legacy CUDA array branch also bypasses fidelity penalties for
  `RGB nearest`. Its public production call is included in the scalar-oracle test.
- **RP18:** absent edge/protected categories in CPU and CUDA pixel accuracy use
  target color accuracy, as the hybrid/regional scorers already do. Perfect flat
  artwork therefore does not receive zero for nonexistent feature categories.
- **PL31:** CPU simulation, CUDA rectangle compilation and incremental phase
  checkpoints retain brush state across implicit entries. Empty paths do not
  change it. The used-size report and default correction brush follow the same
  sequence state. Root coordinates the corresponding preview integration.
- **IW08:** owned normalization/resizing images use `contextlib.closing` to
  release their pixel buffers explicitly; Pillow's ordinary image context
  manager alone does not close these in-memory buffers. A failed/cancelled
  second diagnostic output closes an already created first output. These are
  lifetime completions included with CP06, not additional features.

## Focused validation

The final combined production/regression run passed **110 tests in 2.161s, with three
environment-dependent skips**. It covers the four new batch05 test modules,
pixel accuracy/component/performance tests, detail fidelity, CUDA scoring,
compiled fused-kernel arithmetic, picture-palette integration and prior color
analysis allocation/Stop contracts. Independent review also verifies numeric
protected masks retain `count_nonzero` semantics on either side of the batched
reduction threshold, and retained Pillow references prove owned images are
closed on success and partial failure, before metric calculation. A separate
50-test run covering color/GPU
numeric correctness and picture-cache validation also passed before the final
PL31/RP18 additions. Full-project validation and independent review belong to the
parent batch gate.

The earlier tile-memory golden test now derives every expected palette choice
from the independent scalar `ColorFidelity` matcher and checks every pixel at
row chunks 1, 4 and 96. CP01 intentionally changes the Balanced and Faithful
hashes; RGB-nearest and unweighted OKLab retain their previous hashes. Golden
updates therefore follow an independent decision oracle, not the vectorized
implementation under test.

```sh
../security-venv/bin/python -m unittest -q \
  test_v148_colour_batch05_matching test_v148_colour_batch05_accuracy \
  test_v148_colour_batch05_picture test_v148_colour_batch05_resources \
  test_pixel_accuracy_engine_v1088 test_pixel_stroke_engine_v1087 \
  test_pixel_performance_v1089 test_step26_detail_fidelity_v10149 \
  test_gpu_scoring_regressions test_gpu_pipeline_optimization \
  test_picture_palette_pipeline test_v148_colour_batch03_analysis \
  test_v148_planning_resources
```

No Windows desktop input was sent. CUDA array/scoring fixtures run production
code against host arithmetic; the C++ formula fixture is not a CUDA device test.
OpenCL device execution was unavailable here. Hardware runs remain conditional
and must not be described as observed GPU execution.

## Paired measurements

Run `../security-venv/bin/python benchmark_v148_colour_planning.py`.
Raw samples, exact-output hashes, dependency scope, source hashes and fixture
parameters are in [v148-batch05-colour-planning-benchmarks.json](v148-batch05-colour-planning-benchmarks.json).
Each comparison warms/verifies one pair, takes five alternating elapsed pairs,
and measures separate Python/NumPy-traced peaks after garbage collection. The
baseline evaluator loads its baseline numeric backend too. Other shared
dependencies use the current checkout. Component PixelMaps are built once
outside both timings. Most native Pillow allocation is not traced.

| Workload | Before median | After median | Before traced peak | After traced peak | Exact output |
|---|---:|---:|---:|---:|---|
|160×160 checkerboard components|929.919ms|399.889ms|40,702,476B|31,630,048B|Yes|
|1024×768 solid components|41.057ms|42.471ms|3,647,840B|3,648,136B|Yes|
|1024×768 sparse components|20.588ms|19.935ms|3,272,656B|3,262,508B|Yes|
|768×512 RGB preview metrics|66.735ms|62.830ms|51,600,920B|31,475,584B|Yes|
|1536×1024 RGB preview metrics|321.256ms|276.652ms|206,134,564B|125,847,216B|Yes|
|640×384 RGBA preview with both heatmaps|63.357ms|62.398ms|41,071,805B|19,679,152B|Yes|

These are CPU helper/evaluator workloads, not complete drawing or native-input
speed measurements. The solid component case was slightly slower in this
sample; the optimization does not establish a universal runtime
speedup. Preview traced peaks fell approximately39% for RGB metrics and52% for
the RGBA heatmap case while retaining all returned metrics, routes and image
bytes. Component extraction's largest measured benefit is on highly fragmented
images.
