# Batch 27 — Sketch Fill presentation handoff

## Status and scope

**R2701/global839 is verified and registered as one distinct work-elimination
group.** The product, focused tests, historical comparisons, integrated gates
and final measurements are complete and independently reviewed. The ownership
completions described below add no groups. Release 1.0.148 remains unpublished;
this result makes no general performance claim.

The user-visible operation is Microsoft Paint's **Sketch + Auto Fill**, reached
through actual Studio options and public `make_plan`. Its color planner still
performs its original preprocessing, color selection, Pixel corrections, path
cap, optimizer, deadline admission, physical base simulation and PreviewSafety.
The composed sketch → color fill → re-outline plan still receives the complete
published preview, target, auxiliary layers, source accuracy, ETA and diagnostics.

The change removes the **unused late presentation of the private color plan**:
its quantized-target display, auxiliary layers, source-accuracy images and
measurements, final ETA attachment and diagnostic summary. Two geometric
`finish_plan` passes and two physical base-preview/PreviewSafety passes remain.
It would be incorrect to describe this as running all of `finish_plan` once.

The internal request is consumed by the finisher and cannot appear in the
returned options. The generic public `make_plan` signature is unchanged.
An active auto tuner retains the complete color presentation because real
acceptance and bounded rescue consume its accuracy and ETA. Nested Adaptive
Hybrid and standalone color plans also retain the full path.

## Published baseline and concrete before observation

The baseline is published commit
`8e0a0e4c61ca0742dfb7857649103477cd307516` (checkpoint 838).
The 13-case observation used its unmodified complete public callers, real
four-swatch calibration and actual Studio option construction. It made no
timing or `tracemalloc` measurements and sent no native input.

| Before behavior | Evidence |
| --- | --- |
| Balanced and Pixel Accurate | One complete inner presentation and one complete final presentation: two target, auxiliary and source-accuracy passes. |
| Pixel refinement | Exactly one original `refine_with_corrections` call; it is not a presentation pass. |
| Inner images still open at outer `finish_plan` | 11 for Balanced, 15 for Pixel Accurate. |
| Stop after real inner return, after real contours, or at real final finish | The same 11/15 inner images remain open with the actual exception traceback retained. |
| Valid 1601 × 16 Pixel source | The real Sketch 2.0 size bound raises `ValueError` after the color plan; 15 private inner images remain open in its retained traceback. The error policy itself is unchanged here. |

The compact before artifact is
[`v148-batch27-sketch-before.json`](v148-batch27-sketch-before.json). It binds all
13 complete per-case report hashes, source images, exact before outputs and the
873 before/after root-Python hashes. Their canonical map digest is
`e4057cf13bd9e97e52b07dbdba90f6962a9bbb012c0c78430d782418d8d0442d`.
The complete per-case raw files remain in the scratch checkpoint
`pending-batch27-sketch-finalization`; their hashes are in that artifact.
Image band × width × height totals are payload estimates, **not RSS**.

An earlier version of the scratch observer indexed weak image records only by
Python object ID. IDs could be reused after collection. That version and its
outputs are preserved separately in `initial-observer-id-reuse`. The final
observation verifies weak-reference identity, assigns unique record numbers and
was rerun against the same unchanged published source. Only this corrected
observation supplies the counts above.

## Ownership completion — zero additional groups

The short-lived Sketch Fill image owner is stored in an operation-local
`ContextVar`, never in options or a plan. It requires the creating Thread object
and resets the context on return, Stop and error. It knows the renderer's image
fields and normalized-source aliases, preserves borrowed input/option images,
and does not traverse arbitrary options to infer ownership.

The finisher separately owns its newly allocated presentation images and
`ImageDraw` handles. It releases `draw`, `im` and `_image` references before
closing unused images, including when a Pillow or worker traceback remains
alive. The real source, retained final-plan images and borrowed cache/target
images remain open.

The Sketch scope also encloses the **existing, unchanged** auto-tuner finalizer.
Its color diagnostics retire before composite acceptance. If the outer tuner
rescues the composite and that rescue is stopped, the unpublished first
composite is retired too. A concrete review regression initially retained 14
first-plan images after this real outer rescue was interrupted; the focused
test now requires their cores to be closed with the exception retained.

The owner can retain references to some intermediate image wrappers until its
scope closes. This is an explicit allocation/lifetime tradeoff measured below;
the active-tuner control has higher traced peak and retained allocations, and
the standalone control has a higher peak. There is no general memory-reduction
claim.

## Correctness and preserved consumers

The final focused module has **14 passing methods** (2.680 seconds in the local
gate; this is test duration, not a planner performance measurement). An earlier
33-method combined gate passed the then-current 12 methods, existing S1101,
selector/native-execution and legacy Sketch Fill regressions, plus the six
independently reviewed monochrome ownership tests. No existing native golden
was weakened.

The first eight new methods were run before product edits: nine expected
product assertion failures and no test errors. Their complete-output and
standalone controls passed. Later tests added real active budgets, nested
Hybrid, borrowed aliases, active tuner/rescue and an unreturned inner plan.

An independent frozen generic-finisher control also passed **8/8** complete
published-versus-current public plans: RGB, RGBA, L and P with explicit Balanced
current ink and Outline both off/on. Its artifact is
[`v148-batch27-current-ink-parity.json`](v148-batch27-current-ink-parity.json),
SHA-256 `3423a2b4625bc828e8432aa121860e168f48f05d8009b0d2b79c0b865d66e334`,
on the same 881-file source map. It covers the generic finisher outside Sketch
Fill; it does not replace the separate tuner and active-budget controls.

Specific controls include:

- Actual Balanced and Pixel Accurate options, RGB and partially transparent
  RGBA sources, and physical brush widths 1, 3 and 4.
- Complete final-plan output and original finalized color geometry against a
  full-inner control, with Pixel correction decisions and metadata preserved.
- An actual 30-second Balanced caller whose explicit 50-path target reduces
  **411 → 50** color paths, retaining all 361 skipped-path metadata entries.
- The actual Pixel progressive budget, retaining original occurrence order and
  admission priority: 105 total admitted paths, 92 base paths, 13 correction
  reserve and **64 omitted paths** in this fixture.
- Real source analysis and tuner quality gates. A 4-pixel source executes two
  color finishes (initial plus actual quality rescue), one final finish, and
  three real acceptance/rescue calls. Those full consumers are retained.
- A separate real outer quality rescue and Stop within its new inner finisher.
- Standalone and nested Adaptive Hybrid full-presentation controls.
- Real Stop boundaries, the real Sketch size `ValueError`, retained exception
  frames, drawing-core aliases, borrowed source/target/cache images and context
  retirement.

The S1101 regression file was adapted only where its fixture depended on the
unused inner UI output. Its inner coverage-image assertion now checks retained
Pixel coverage data and the intentional absence of an inner UI bundle. Its
failure fixture targets the actual final finisher rather than the ordinal
second source-accuracy call. Its inner-source-accuracy assertion now reflects
the omitted inner display measurement while retaining the Pixel measurement.
All existing final sequence, counts, physical cost, safety, UI, diagnostics and
executor assertions remain. The new active-tuner controls retain and verify the
full-presentation consumer.

## Complete historical linkage and causal measurement scope

The verifier links these **complete** published files, not copied formulas or
selected old helper bodies:

| Historical module | SHA-256 at 8e0 |
| --- | --- |
| DrawBot.py | `615b48142aeb6a07c826aa2aa0130176b8cde01162f12b1d6ffe6b359f1f81bc` |
| SketchFillRenderer.py | `dfffc8dc6a72475ff2f279e920eb06a30dbd88582127c48541a3fbe644bff265` |
| PixelData.py | `b56ac3cf09c8e603d0d373a685cf79535b89e370ae371b3aed6e97ca0e51fe31` |

It installs the matching public import names and also binds
`AutoSketchBudget.monochrome_strokes` and `FillOptimizer.closest_color` to the
selected PixelData module. Other dependencies are shared.

Every correctness case compares three graphs:

1. All three published baseline modules.
2. Published DrawBot and SketchFillRenderer with the same **current PixelData**
   used by the changed side.
3. The complete current graph.

The timed/allocation comparison is **graph 2 versus graph 3**. Holding PixelData
constant prevents the separate CPU source-white correction and monochrome
ownership completion from being credited to this work. This comparison still
includes the new **DrawBot/Sketch image-ownership completion** as well as
R2701's omitted presentation. Therefore an observed elapsed or memory delta
cannot be attributed exclusively to the newly counted group. Its distinct work
reduction is proved separately by the call counters.

Source creation, actual UI option construction, complete settings deepcopy,
module linkage and real temporary calibration occur before the timer/tracer.
Only actual public `make_plan` is timed, including geometry, safety, Pixel
corrections, active consumers and internal cleanup. Fingerprinting, independent
executor replay and caller-owned result disposal occur afterwards. The prepared
sources remain byte- and metadata-identical. The tracer refuses to replace an
already active external trace.

Only the existing explicit planning-clock/profile fields listed in the raw
report are excluded from output equality. Budget, estimate, correction,
admission, geometry, image bytes/info, calibration and file-backed history-path
fields are compared. One real temporary calibration context surrounds each
three-graph comparison and all rounds of a workload.

## Frozen verify-only result

`benchmark_v148_rendering_batch27_sketch_finalization.py --verify-only` passed:

- **22 complete public cases**, each equal across all three graphs.
- **8 native-executor raster cases**, equal across all three graphs for the
  actual delivered bitmap, sent/skipped counts and ordered color actions.
- **8 full workload controls**, with exact complete outputs and separate work
  observations. No elapsed or traced-allocation probes were run in verify-only.

The initial successful raw result is in scratch
`pending-batch27-sketch-finalization/historical-verify.json`, SHA-256
`f6bf428422e7fc4f78bda235fc61ecb774caef81e03c3a2b49553b14c9b0f7ea`.
It binds **881 unchanged root Python files**, canonical digest
`59de95e5201bf591c7c7118aee9c20e40aa0dbfc020fd5e8714c65ba5903853f`.
The complete public-output digest is
`bbcafd0ba276d9f66f373e7bb2fd4260a4b7300e0a0d63dec27ca4d26beeeb57`;
the independent native-ink digest is
`f3bf153c394fae0c669cb40a6388f24e2b1a669b88388c5b25c48bc9be07a5a8`.

| Workload | Inner source-accuracy calls before → after | Inner PreviewSafety calls before → after |
| --- | ---: | ---: |
| Balanced RGB 320 × 256 | 1 → 0 | 1 → 1 |
| Balanced RGBA 384 × 288 | 1 → 0 | 1 → 1 |
| Pixel RGB 192 × 160 | 1 → 0 | 1 → 1 |
| Pixel RGBA 192 × 144 | 1 → 0 | 1 → 1 |
| Balanced full preview 256 × 192 | 1 → 0 | 1 → 1 |
| Actual active target cap, 96 × 72 | 1 → 0 | 1 → 1 |
| Active tuner/rescue control, 40 × 32 | 2 → 2 | 2 → 2 |
| Standalone control, 192 × 144 | 1 → 1 | 1 → 1 |

The ordinary changed workloads still make one complete final source-accuracy
call. Their target/auxiliary/diagnostics counters show the same omitted-inner
pattern. No first-pass Pixel correction or geometry/safety pass is eliminated.

### Pre-existing native-oracle difference retained transparently

The expanded verification found a difference already present in the complete
published baseline: Balanced RGBA 96 × 72 differs from its emulated native ink
by **2,587 RGB values at 1 px** and **1,581 at 4 px**. All three graphs produce
exactly the same delivered raster and the same preview delta. All 37 paths are
sent, with zero guard-skipped paths. The six other native fixtures have no
preview/raster difference.

The oracle runs real `execute_plan` into `PaletteInkMouse`: clicked calibrated
swatches determine RGB, and each delivered cursor segment is a Pillow centerline
expanded by the physical square brush. It is **not a physical Paint capture**.
The difference remains a separate audit candidate; it must first be determined
whether the preview or the emulator's line/coordinate model explains it. This
batch changes neither behavior and makes no new correctness claim about that
difference.

The independent read-only follow-up identified a specific next probe: this
Balanced case has a 67 × 50 planning raster fitted to 96 × 72. Sketch's final
renderer currently expands source-grid brush coverage, while the executor maps
centerlines and retains the physical brush width. A single horizontal path at
that ratio can distinguish this width-model difference without diagonal-line
ambiguity. That next probe and any correction remain outside this frozen batch.

Exact source, preview and delivered PNGs, full pre-execution plans/options,
ordered swatch selections/ink colors, verification samples and raw SHA values
are preserved under scratch
`pending-batch27-sketch-finalization/native-preview-evidence/` for both brushes
and all three graphs. The old strict R1601 native goldens remain unchanged.

One initial verifier attempt also revealed shallow fixture state sharing:
`execute_plan` correctly updates its own `color_session_cache`, which was shared
between runs by the initial harness. Settings are now deep-copied before the
measurement boundary. The failed initial log is preserved; no product change or
output-field exclusion was made to pass that comparison.

## Deduplication

An independent review of all 838 registered groups supports at most one new
group for the omitted unused inner presentation:

- **S1101/global777** established ownership of the composed geometry, counts,
  safety and diagnostics. Its record explicitly makes no allocation/lifetime
  claim and still built the inner presentation.
- **U1401/global790** removed one auxiliary color raster that the same
  `finish_plan` replaced. It did not eliminate this separate inner target,
  auxiliary, source-accuracy, ETA and diagnostic pass.
- **R1501/global799** and **R1502/global800** concern early Sketch gradients and
  image preparation/conversion/resize lifetimes, not this late consumer split.
- **U2001** removed a further UI estimate pass; **R2101** shared calibration DB
  observation. Neither removed this color-plan presentation.
- Image ownership, Stop, traceback and rescue cleanup remain **zero-count
  completions** under IW08/global582, UI34/global255, RP38/global552 and
  A1101/global774.

## Final gates and measurements

The frozen integrated suite completed **4,481 cases in 218.814 seconds: 4,408
passed and 73 skipped**, with all **931 source/configuration hashes unchanged**.
The 14-case native gate, 5,000-cycle source gate and eight exact raster fixtures
also passed. Final source/package hygiene passed over **1,325 files** after the
raw report and publication metadata were added; the validation artifact retains
the earlier 1,323-file observation separately. All 73 older benchmark reports
remain byte-identical.

The final raw artifact is
[`v148-batch27-sketch-finalization-benchmarks.json`](v148-batch27-sketch-finalization-benchmarks.json),
SHA-256 `b906d364edbbcfc4a36fa0d9da1877e15c418350325b482f4b8f8fcc3141e689`.
Its before/after maps bind the same **881 root Python files** used by the frozen
gates, with canonical digest
`59de95e5201bf591c7c7118aee9c20e40aa0dbfc020fd5e8714c65ba5903853f`.
The final run repeated all **22 complete three-graph public cases**, **eight
three-graph native-executor cases** and **eight workload comparisons**, with
complete historical and isolated output equality throughout. The 22 historical
and 22 isolated comparisons describe the same 22 cases, not 44 distinct cases.

The final complete-output digest is
`6a6598ededdc648097dee9588262be6f0b5143c37a17cb198189ba553698b662`.
It differs from the initial verify-only digest because each invocation creates
a fresh real temporary calibration directory and those path fields remain in
the complete comparison. The three graphs share that context within each
comparison; no path field is excluded to obtain parity. The native-ink digest
remains
`f3bf153c394fae0c669cb40a6388f24e2b1a669b88388c5b25c48bc9be07a5a8`.

### Elapsed measurements

Each workload has one warm pair followed by **six balanced pairs**, alternating
before/after and after/before. The table reports each side's median in
milliseconds and the percentage change between those medians. Faster/slower
counts compare the two observations within each pair. All observations are kept,
including the slower pairs below. These are CPU planner measurements on this
environment, with calibrated fixture inputs; they do not measure physical Paint
delivery or a GPU.

| Public workload | Before median, ms | After median, ms | Median change | Faster / slower pairs |
| --- | ---: | ---: | ---: | ---: |
| Balanced RGB 320 × 256 | 117.676 | 93.980 | −20.136% | 6 / 0 |
| Balanced RGBA 384 × 288 | 146.757 | 121.255 | −17.377% | 6 / 0 |
| Pixel RGB 192 × 160 | 273.921 | 245.939 | −10.215% | 5 / 1 |
| Pixel RGBA 192 × 144 | 257.710 | 253.419 | −1.665% | 5 / 1 |
| Balanced full preview 256 × 192 | 104.880 | 88.036 | −16.060% | 6 / 0 |
| Actual active target cap, 96 × 72 | 144.727 | 135.581 | −6.320% | 5 / 1 |
| Active tuner/rescue control, 40 × 32 | 150.510 | 132.780 | −11.780% | 4 / 2 |
| Standalone control, 192 × 144 | 42.070 | 40.753 | −3.129% | 4 / 2 |

| Slower observation | Pair | Before → after, ms |
| --- | ---: | ---: |
| Pixel RGB 192 × 160 | 1 | 266.163 → 278.328 |
| Pixel RGBA 192 × 144 | 4 | 249.781 → 285.896 |
| Actual active target cap, 96 × 72 | 6 | 154.378 → 163.545 |
| Active tuner/rescue control, 40 × 32 | 2 | 126.184 → 138.667 |
| Active tuner/rescue control, 40 × 32 | 6 | 119.352 → 124.507 |
| Standalone control, 192 × 144 | 1 | 41.161 → 41.202 |
| Standalone control, 192 × 144 | 6 | 40.737 → 40.782 |

The six ordinary Sketch Fill workloads remove the unused inner presentation;
their observed median reductions range from 1.665% to 20.136%. The small Pixel
RGBA median difference and its slower fourth pair are retained as measured, not
treated as a uniform speedup. The active tuner and standalone controls remove
no presentation passes, so their median changes cannot establish an R2701
work-elimination benefit. They also demonstrate the variation in this run.

### Separate traced allocations

After timing, one independent before probe and one after probe measure Python
traced peak allocations and bytes still retained with the result. These are
single allocation observations, not six-pair medians, and do not represent
process RSS or all native Pillow storage. Result fingerprinting and caller-owned
result disposal remain outside the traced call.

| Public workload | Peak bytes, before → after | Peak change, bytes | Retained with result, before → after | Retained change, bytes |
| --- | ---: | ---: | ---: | ---: |
| Balanced RGB 320 × 256 | 8,408,561 → 8,036,368 | −372,193 | 1,336,227 → 1,302,663 | −33,564 |
| Balanced RGBA 384 × 288 | 10,294,022 → 10,018,596 | −275,426 | 1,386,475 → 1,350,647 | −35,828 |
| Pixel RGB 192 × 160 | 9,755,022 → 9,475,378 | −279,644 | 1,993,452 → 1,959,840 | −33,612 |
| Pixel RGBA 192 × 144 | 9,025,967 → 8,757,331 | −268,636 | 1,683,178 → 1,663,933 | −19,245 |
| Balanced full preview 256 × 192 | 8,386,072 → 8,014,053 | −372,019 | 1,318,622 → 1,284,719 | −33,903 |
| Actual active target cap, 96 × 72 | 9,061,618 → 8,744,783 | −316,835 | 1,932,066 → 1,894,182 | −37,884 |
| Active tuner/rescue control, 40 × 32 | 8,556,608 → 8,562,373 | +5,765 | 1,258,129 → 1,266,322 | +8,193 |
| Standalone control, 192 × 144 | 2,964,284 → 2,965,622 | +1,338 | 784,192 → 782,077 | −2,115 |

The active tuner still performs its two complete color presentations and the
complete final presentation; its peak rises by **5,765 bytes** and retained
allocations by **8,193 bytes**. The standalone control still performs its one
complete presentation and has a **1,338-byte peak increase**, despite lower
retained allocations. Both costs are included rather than omitted as controls.

These elapsed and allocation results include the DrawBot/Sketch ownership
completions as well as the omitted presentation; only the separate PixelData
changes are held constant. The work counters establish R2701's distinct saved
work, while the measurements characterize the combined implementation on these
eight callers. They support no universal elapsed-time, peak-memory, RSS or
physical-GPU claim. Active tuner, standalone, nested Hybrid, geometry, safety,
correction and active-budget consumers retain their documented behavior.
