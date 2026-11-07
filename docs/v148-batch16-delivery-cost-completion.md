# Batch 16 — native delivery cost completion

Baseline: `d1a5e3a709745ee64263b5801cf1b9089cd6b707`.
This work completes **RP02 (global 516)** and **RP28 (global 542)** and adds
**zero new improvement IDs**. RP02 already requires the cost model to count the
same rounded native samples as delivery. RP28 and its existing caller
completions price retained execution controls in the accepted plan and ETA.

## Reproduced differences

A real Microsoft Paint Pixel Accurate `make_plan` for a 96×32 RGBA source with
one black horizontal line from `(8,16)` to `(87,16)` produces one native path.
The actual executor sends **53 drag moves** with the selected 1 px brush. The
baseline model prices **40**, and final planning publishes **0.098 seconds** of
motion waits. The real executor's canvas waits total **0.1266 seconds**.
The preview-failure fallback has the same discrepancy. A Paint current-color
plan without Pixel geometry is a positive control: it correctly retains 40
moves even when the requested quality text says Pixel Accurate.

The difference comes from the native Pixel brush limit
`min(delivery_step, max(1, physical_brush * 1.5))`. Native drawing applied that
limit; `ExecutionCostModel.path_cost` and the final preview/motion summary did
not. The Pixel component model was also constructed before the caller attached
the final `pixel_accurate` flag, so repairing only the final model still left
earlier component prices inconsistent. The existing prepared-palette regression
detected this remaining discrepancy during integration.

A separate real public Extra Fast plan uses one verified switch from a 2 px
brush to 16 px. Recording the executor's waits at its actual external brush
control shows **0.13825 seconds**. The baseline model charges **0.06375 seconds**,
and `finish_plan` omits the returned `brush_seconds` entirely from its published
operation overhead. These observations replace only native mouse, visual
inspection, waiting and report-persistence boundaries; planner, finalizer and
executor are the production functions.

## Correction

`StrokeDelivery.interpolation_step` now expresses the existing native brush
limit for both delivery and pricing. The cost model applies it to the actual
path brush and to its default per-pixel rate. Final planning uses each guarded
sequence entry's physical width, including inherited widths; the ordinary
group path and preview-failure fallback use the same limit. The actual selected
Pixel branch attaches its flag before constructing the component cost model.
Other quality labels are not promoted to Pixel execution.

`brush_switch_delays` shares the existing native move/click settle constants
with the model. Default brush-change pricing includes both waits, while learned
operation averages retain their existing precedence. Final operation metadata
now exposes `brush_seconds` and includes it in overhead and the final estimate.
The model identifier advances to 7 as part of this correction; that version
change is not another improvement. Initial brush verification, retries,
CanvasGuard, physical brush selection and native waits are unchanged.

## Evidence and limits

Five regressions in `test_v148_rendering_batch16_delivery_cost.py` exercise the
actual public planner/finalizer and executor. Besides the two original failures
and the non-Pixel control, a three-path final sequence selects widths 5→1 and
then inherits 1. Native move counts are **40, 53, 53**. Both normal guarded
preview and its failure fallback price those exact moves and observed motion
waits. Independent review also reproduced a remaining fallback-only inheritance
error: an empty row with a different width changed the next preview stroke and
its motion estimate. The fallback now ignores empty rows before updating brush
state, matching normal preview, the model and actual execution. The same
per-entry regression includes that empty row and requires identical preview
bytes on both routes. This completes the existing P1402 inheritance contract
and adds no ID. The verified brush-control fixture requires its original native
0.13825-second waits, so the executor cannot be shortened to satisfy an
optimistic model. Independently rounded summary components are compared within
their declared four-decimal rounding bound.

The adjacent model, prepared-cost, palette-summary, actual-control, Pixel,
verified-brush and delivery gate passed **50 tests** before the final additional
per-entry regression; the final five-test file also passed. Independent review is closed: a separate reviewer checked the shared sampling
and brush-delay rules, reproduced the empty-row inheritance issue, and passed
37 adjacent tests plus 17 UI/cost integration cases. The batch-wide final
frozen-source gate is recorded separately by the coordinator.
No elapsed CPU, native drawing speed, GPU or memory improvement is claimed.

The broader Sketch ownership gate exposed one old motion-cost oracle that still
used the uncapped delivery step while the same test explicitly required Pixel
native spacing to survive composition. Its independent formula now applies
`min(step, max(1, brush * 1.5))` to each actual/inherited entry width. All existing
plan, ownership, phase and native-executor assertions remain. The focused
Sketch/delivery/Studio integration passed 29 tests in 0.468 seconds.

The first batch-wide run completed 3,923 cases with three expectation failures:
one historical source-text assertion still required the now-shared native
spacing formula inline in DrawBot, and two exact pack-choice fixtures retained
the old brush-change price. The source assertion now verifies the shared call
and both Pixel/non-Pixel numeric behavior. The four recorded pack costs remain
explicit and add only the independently derived native wait difference: three
versus one switch for the scaled fixture, four versus three for its opposite
counterexample. Actual executor switch counts must match those transitions.
All geometry, selected-policy, inequality, tie, Stop and pixel assertions remain.
The pack/delivery gate passed 11 tests; the motor/delivery gate passed 15.
These expectation updates add no behavior IDs.
