# v1.0.148 application — batch 11

Baseline: published batch10 commit
`a8fabbc811029a8bfcbe8a5af2a848b034e5cd89`, tree
`d8941d4c99747e38bb39dea13667e4f6f6b19fd2`.
This area contains **one distinct behavior group, A1101**. The automatic
quality-rescue caller, replacement ownership and final acceptance belong to
one complete replanning workflow. Independent source review is closed; the combined gates remain pending.
No release is implied.

## A1101 — rebuild an automatic rescue from policy, then assess its final plan

An actual Auto / Microsoft Paint texture fixture uses a 48×32 input, a 96×64
canvas and a Custom 60-second budget. Its first regional plan has a 67×45
analysis image and 301 executable entries. Actual acceptance reports
`BELOW_QUALITY_GATE`, a projected 30.591 seconds against 53 usable seconds,
and 22.409 seconds of headroom. The public planner nevertheless returned
that plan with attempt zero and no top-level acceptance result. Its inner
color planner had been assessed before the regional wrapper changed geometry
and cost; the completed wrapper did not enter the finalizer again.

The same first plan also exposed a second part of the broken rescue flow.
Calling the real finalizer on that finished result chose a valid, bounded
`quality-rescue`, but `propose_rescue_options` copied compiled groups, execution
sequences and private renderer flags from the first plan. `finish_plan`
then reused those 301 coordinates against a new 96×64 analysis image. A
reference generated from real resolved policy before any plan outputs existed
had 387 entries instead. Independent native-coordinate Pillow rasters differed
at 5,746 of the 6,144 canvas pixels. This reproduction did not invent acceptance
metrics or change the quality thresholds.

The Sketch Fill and regional wrapper callers now assess their completed result
through the existing finalizer. The private color-planner checks remain in
place; this is not a claim that metadata is evaluated exactly once. The
existing attempt/history limit still permits at most one rescue.

Rescue options explicitly discard known derived results: compiled renderer
groups/sequences and recursion/active flags, the old plan palette/selectors,
source-grid scale and fill data, preview geometry, diagnostic images/caches
and profiler state. The replacement planner produces those values for its own
image, palette and renderer. This is an explicit list of generated outputs,
not a blanket deletion of private options or a deep copy of the first plan.

Prepared `picture_palette_rgb`, actual calibration and tool actions, canvas
safety inputs, cost-calibration overrides, preview configuration and the
tuner's resolved policy/attempt/history remain available. Removing dictionary
references does not mutate the first plan's lists or close its images. A failed
replacement can still return that usable plan; interruption still propagates.

With the complete caller and ownership corrections, the unpatched public
`make_plan` entry returns the fixture's fresh 96×64, 387-entry plan. Its actual
acceptance is `PASS`, attempt one, with a projected 45.992 seconds. Both the
top-level result and option metadata equal an independent evaluation of that
exact returned plan. These are modeled drawing times under the fixture's
calibration, not measured target-application drawing speed.

## Evidence and limits

`test_v148_application_batch11_rescue.py` is written by an independent reviewer.
Its clean reference starts with actual `resolve_drawing` output before any
renderer adds plan data, then uses the same actual acceptance, proposal and
planner. It does not mirror the production deletion list. Comparisons include
complete sequences/groups, physical raster, visible Coverage and main preview,
and raw operation cost. Separate cases exercise ownership, a real planning
failure and Stop at replacement entry.

On the unchanged published source, the first four tests produced two failures
and two passes in 3.286 seconds. The geometry comparison was the 5,746-pixel
failure above. The first ownership correction passed its geometry comparisons
but exposed missing final-wrapper acceptance. Root then reproduced the separate
unpatched public-entry omission and completed the caller correction. The final
reviewer suite now contains seven actual-flow cases, all passing in 11.459
seconds. It includes the fully unpatched public entry, which observes exactly
one real rescue proposal, preservation of prepared RGB/calibration/tool/canvas
and strict safety inputs through actual replanning, and a real browser
regional-to-Pixel rescue with no obsolete regional owner. First-plan images
remain readable and unchanged even after successful replacement.

The independent reviewer closed the source review for the explicit output
cleanup and both completed-wrapper callers. Twenty related Step11, Sketch Fill
and Pixel-dispatch cases also passed in 0.947 seconds. That selection is a
running integration check, not a frozen final gate: the separate S1101 Sketch
producer work was in progress. The final combined checkpoint will bind all
reviewed source files together.

AW24 removed a previous Quick Sketch policy when a rescue selected another
renderer. R1001 corrected initial dispatch and sequence ownership for explicit
Pixel/Subject policy. A1101 concerns the distinct transition from a completed
plan to a fresh, bounded automatic replacement, including its actual wrapper
caller and final acceptance. All renderer families and failure-path tests in
this transition count once; tests and documentation add no further IDs.

No universal quality, timing, memory or antivirus guarantee is made. Existing
source/canvas safety and native input authorization remain independent of the
planner's acceptance metadata.

## Frozen checkpoint validation

Batch 11: final frozen-source discovery passed 3,602 tests in 128.751 seconds (43 platform/hardware skips), with unchanged Python and batch-script hashes. Independent source reviews are closed for all four behavior groups. The 5,000-cycle source gate, source-package hygiene and eight exact-raster fixtures passed. Paired pack-selection measurements bind the final source and disclose planning overhead separately from modeled drawing cost. The published batch11 checkpoint `b0eedca7d8d63fde5c9da6a1cffb394613ff95bf` passed complete Windows/Linux regressions, both dependency audits, CodeQL, Windows self-test, bundle build and packaged GUI/native drag-and-drop in [run 42330134079](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42330134079). All four jobs and all seven commit checks succeeded. No 1.0.148 release is published.
