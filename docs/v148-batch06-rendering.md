# Batch06 — rendering, color names and planning policy

Baseline: `f59a57c6fc1eef1ace07e872ba50ed834e1bb924` (published batch05,
699 improvements). This ledger currently records **seven distinct new behavior
groups**. Root's independent source review of RB01–RB07 is closed and the
product/test sources are frozen. Whole-program discovery passed **3,201 tests
in 71.794 seconds**, with 31 platform/hardware skips and unchanged source hashes.

Related call sites, tests, reports, documentation and completion of earlier
contracts do not add separate improvement counts.

## New improvements

| ID | Reproduced problem | Change | Production and independent evidence |
|---|---|---|---|
| RB01 | Canvas verification accepted RGB band contrast as an edge but located it using luminance only. A real rectangle with outside `(100,100,20)` and inside `(101,69,177)` has equal luminance; all sides were spuriously placed at search offset −24, stopping a correctly selected canvas. | Locate adjacent boundaries with weighted RGB contrast, prefer the nearest expected position on exact strength ties and require nonzero local evidence. Existing weak/no-margin fallback and conservative-inset semantics remain. | `test_v148_rendering_batch06_edges`: independent integer luminance equality and geometric side offsets; exact, oversized and conservative selections. Actual `execute_plan` with fake input accepts the real chromatic boundary and stops a shifted boundary before any click/press. |
| RB02 | Custom Auto reserves jumped at policy thresholds. Increasing the timer 30→31,80→81 or150→151 seconds reduced usable drawing time. | Interpolate established generic timer anchors continuously, with reserve slope below1 and the existing30-second maximum. Fixed game presets and explicit Off/manual reserves retain their values. | `test_v148_rendering_batch06_budget`: every quarter second from5 to3600, adjacent floating-point values around each anchor, all fixed presets and legacy anchors. Actual application budget resolution, time-aware color planning and adaptive execution planning consume the same increasing usable budget. |
| RB03 | Extra Fast evaluated the same complete final plan twice when every local candidate kept the original paths. The second pass repeated target capping, stroke ordering and stateful costing. | Reuse the first complete evaluation only when every source group remains unchanged, including portrait semantics. Changed proposals still receive the complete downstream regression guard; Stop remains observable after the first evaluation. | `test_v148_rendering_batch06_extra_fast`: source-pixel oracle, protected portrait prefix under a real cap, changed geometry, cancellation and actual Paint Line Art `make_plan`. Paired measurements compare full paths, semantic metadata and costs against the published baseline. |
| RB04 | X11 Gray, Maroon and Purple were displayed using names that parse as different CSS RGB values. Reports could say `Purple → Purple` for a visible color change, and an exact X11 match was labeled CSS. | Preserve ordinary CSS input precedence, provide explicit `X11` names for collisions, publish only aliases that parse to the same RGB, and report the vocabulary of exact extended matches. Rendering colors and candidate scoring are unchanged. | `test_v148_rendering_batch06_names`: every unique RGB in both independent static tables round-trips through its displayed name and every published alias. All CSS names keep their values. Real `DynamicColors` mapping reports distinguish the three collisions while preserving source runs and selected palette colors. |
| RB05 | Explicit Portrait style injected the full-color `Subject first` policy into Paint's supported current-color shaded renderer. Both Manual and Auto `make_plan` then failed with a subject-focus compatibility error. | Do not inject that full-color policy into a compatible single-color portrait. Preserve any explicit user subject selection so the real planner still rejects an invalid combination. Full-color Portrait and Extra Fast's contour policy keep their behavior. | `test_v148_rendering_batch06_profiles`: actual Manual/Auto plans contain shaded portrait strokes in one current-color group; the explicit invalid subject combination still fails. Full-color and Extra Fast compatibility cases are retained. |
| RB06 | Preview safety treated the fitted image rectangle as the entire canvas. A 1×24 source centered in a 200×48 canvas raised `CanvasSafetyStop` because its fitted width was only 2 pixels, although the actual centered stroke was safe. Ordinary letterboxing also clipped legal image edges and projected saved polygons/anchors against the wrong rectangle. | Keep full-canvas guard geometry and centered image placement separate. Project normalized/relative/screen evidence through the complete target canvas; render guarded paths and safety/debug/stroke layers back into the fitted image crop. Root forwards the current planning canvas through ordinary, recursive and test plans. | `test_v148_rendering_batch06_canvas`: both letterbox axes, negative screen origins, reduced-canvas evidence, independent screen-space native-guard comparisons and explicit output pixels. Actual `make_plan` and `execute_plan` succeed for thin sources; Subject only selection remains source-relative; a verified 5→1 px brush switch agrees with the same whole-canvas preview guard. |
| RB07 | Both Fill detectors retained every pixel index of a component after it touched the canvas border, although border-connected components are unconditionally ineligible for bucket Fill. A large background therefore retained unusable candidate geometry for its entire flood traversal. | Release that list on the first border contact and omit later coordinate retention. Continue the complete traversal, component accounting and bounded cancellation checks. Interior candidate point order and every subsequent safety/contour decision remain unchanged. | `test_v148_rendering_batch06_fill`: independent breadth-first component sets, later border contact, exact interior region/row spans/seed membership, sparse components, cancellation in both detectors and the actual application Fill route. Paired image/group detectors compare every region field and complete metadata; border fixtures reduce peak traced allocation by about 42–43%. |

## Earlier contracts completed, zero additional count

- **IW08:** canvas edge verification borrows RGB screenshots and explicitly
  closes an owned conversion on success or failure. A retained real Pillow
  reference verifies closure without closing the caller's capture.
- **RP02:** Extra Fast's report reads the current execution-model version
  instead of retaining the old literal `stateful v3`. This accompanies the
  existing estimate correction and has no separate improvement ID.
- The saved-plan, source-safety and input authorization boundaries are
  unchanged. Root owns the runtime processed/sent counter and learning work.

## Focused validation

The first three groups and their adjacent canvas, Extra Fast, semantic-barrier
and deadline suites passed **70 tests in5.513s**. The name-table/real-mapping
suite and prior color suite passed **34 tests in0.216s**. Portrait style plus
existing image and hybrid policy suites passed **43 tests in0.550s**. These are
overlapping focused runs, not independent improvement counts or a whole-project
gate. No native desktop input was sent.

The six canvas-placement regressions and adjacent safety, subject, detail-pass
verification and preview suites passed **68 tests in 0.480 s**. This run also
exercises the real execution function with fake input and real guard decisions.

The four Fill regressions and adjacent region, application, Quick Sketch,
geometry and Extra Fast suites passed **57 tests in 2.115 s**.

## Paired performance evidence

Run `../security-venv/bin/python benchmark_v148_rendering.py --repeats 5`.
Raw samples, source hashes, environment and compared-output fingerprints are
recorded in [v148-batch06-rendering-benchmarks.json](v148-batch06-rendering-benchmarks.json).
Each case warms/verifies a before/after pair, then takes five alternating elapsed
pairs and separate traced-memory peaks. The changed ExtraFast2 and FillOptimizer
modules are loaded separately from the baseline; each comparison uses the same
current downstream dependencies and application caller, whose hashes are
recorded. The sole excluded metadata field is Extra Fast's corrected
execution-model version label. Every other compared value must match. Every
recorded source/dependency hash was checked again after this measurement and
still matched the working tree.

| Workload | Baseline median | Current median | Final cost evaluations before→after | Compared output |
|---|---:|---:|---:|---|
|240 unchanged disconnected source points|26.40 ms|18.43 ms|2→1|Exact|
|480 unchanged portrait points,16 protected, cap120|28.86 ms|26.55 ms|2→1|Exact|
|160 changed vertical runs|21.87 ms|22.73 ms|2→2|Exact|
|Actual Paint Line Art `make_plan`,35 contours|136.17 ms|121.27 ms|2→1|Exact|

| Fill workload | Baseline median | Current median | Baseline peak bytes | Current peak bytes | Compared output |
|---|---:|---:|---:|---:|---|
| Image detector, 384² border-connected background | 120.19 ms | 116.49 ms | 7,677,085 | 4,416,797 | Exact |
| Group detector, same background | 108.87 ms | 103.37 ms | 7,572,897 | 4,312,609 | Exact |
| Image detector, 256×192 interior rectangle plus later border-connected region | 56.18 ms | 52.79 ms | 2,220,917 | 2,220,949 | Exact |
| Group detector, same mixed regions | 50.82 ms | 48.13 ms | 2,218,533 | 2,218,565 | Exact |

The complete Line Art plan is about 15 ms faster in this run; earlier paired
runs showed smaller differences. This is not a claim of a large application-wide
speedup. The changed-candidate fixture remains slightly slower. Peak traced allocation is effectively
unchanged for Extra Fast. In the mixed Fill fixture, accepted interior geometry
still determines the peak, so no peak-memory improvement is claimed there.
The synthetic CPU cases do not establish GPU throughput, Windows
input speed or total real drawing time. Measurements must be refreshed if their
recorded source/dependency hashes change before the batch is frozen.
