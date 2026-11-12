# v1.0.148 application batch41

## Scope and counting

The implementation base is local checkpoint `fc3f927`. This ledger proposes
**two independent groups**, A4101 and A4102. The aggregate registry owns their
final integrated IDs and total. The earlier boundary-fixture correction is a
**zero-ID** completion, documented separately in
[its ownership ledger](v148-batch40-boundary-fixture.md).

All new raster regressions use the repository's existing Paint reference or
application icon. No new image motifs or AI-generated images were introduced.

## A4101 — compare typed timing history with its own cold path cost

The final-sequence ETA previously assigned the same global path average to
dots, short strokes, long strokes and outlines. Runtime timing history is
recorded separately for those operation types. A profile with only some types
measured therefore compared different workloads: even a measured dot average
equal to the model's exact dot cost could incorrectly reduce the estimate.

The real planner on `assets/paint-tools-reference.png` produces 271 dots,
27 short strokes, 16 long strokes and three outlines in the regression fixture.
Their independently accumulated cold means are approximately 0.02910,
0.02345, 0.66826 and 0.03554 seconds respectively. The previous estimator used
approximately 0.06094 seconds for each type. A matching dot-only history
therefore produced an applied ratio of about 0.81365 instead of 1. These are
deterministic model values, not measured physical Paint timings.

`ExecutionCostModel.sequence_cost` now optionally fills a caller-owned mapping
of `(count, seconds)` by declared path operation type during its existing
geometry pass. The returned cost breakdown and default callers are unchanged.
ETA uses those complete, matching totals for its existing typed calibration
comparison. The ordinary partial-history coverage and blending rules remain.

The existing preview-local cost handoff transfers immutable typed evidence
together with the exact breakdown. It does not price the geometry again or
publish a private accumulator in plans/options. Signature inspection preserves
older injected models without retrying a genuine failed model call. Models
without the optional keyword, ones which ignore it, variadic positional collectors,
and incomplete or malformed optional totals retain the previous aggregate
fallback. Stop still interrupts the same sequence loop; callers discard any
partial accumulator after cancellation.

This fixes the per-type baseline used by final ETA. It is distinct from
RP10/global524, which distinguishes absent UI-switch measurements from an
explicit measured default, and from the earlier preview cost-reuse group, which
avoids a second identical sequence calculation. Root's delivery-history key
change is also separately owned; this group does not change profile-history
identity or persistence.

Files: `DrawTimeEstimate.py`, `ExecutionCostModel.py`,
`test_v148_application_batch41_typed_eta.py`.

Five new methods exercise real plans, independent public per-path costs,
partial history, displayed ETA metadata, the actual preview reuse scope,
legacy models and cancellation. Two core methods run with the historical ETA
function bodies produce **five failed assertion/subtest records and zero
fixture errors**. Those records demonstrate one defect, not five extra fixes.

## A4102 — avoid duplicating an already oriented Upscale source

File/clipboard import already normalizes orientation. Upscale nevertheless
called Pillow's no-op EXIF transpose, which copied the complete input raster
before either Pixel art or Smooth resampling. The worker already retained the
original source for matching-result adoption and Undo.

`ImageUpscale.upscale_image` now borrows the source when its loaded EXIF
orientation is already 1. It keeps the previous owned orientation transform
for actual rotations and other orientation values. Loading occurs before the
decision, matching Pillow's prior decoding semantics. Required RGBA conversion,
premultiplied-alpha Smooth processing, result metadata and output ownership
remain unchanged.

The actual `_start_upscale` worker, event queue, adoption and Undo flow using
the existing 512 × 512 RGBA icon now make **zero input copies instead of one**
for each method: **1,048,576 bytes of avoided source-copy payload per call**.
This is a deterministic work/allocation observation, not an overall peak RSS
or speed claim. The existing controller/worker continue to retain the original
source through adoption, and Undo continues to reference that original source.

Complete output pixels, dimensions, mode and metadata match the previous
pipeline for RGBA, RGB, L, LA and P inputs, 2×/4× factors, both methods and all
actual EXIF rotations 2–8. Source pixels, metadata and EXIF remain unchanged.
Late Stop and native resize failures close private images while leaving the
borrowed input usable. Rotated metadata remains normalized.

This is a separate public edit operation from R1502/global800's standard
planner-preparation copies. It does not change planner preparation, background
Undo transfer or palette sampling. The two older Upscale ownership fixtures
now distinguish borrowed input from owned orientation/resampling temporaries;
their cancellation, error and pixel assertions are retained.

Files: `ImageUpscale.py`,
`test_v148_application_batch41_upscale_source.py`,
`test_v148_image_batch03.py`.

Three new methods cover the real worker workflow and complete pipeline parity.
The worker-copy regression fails for both methods when only the historical
Upscale function is substituted, then passes with the current implementation.

## Verification and limitations

The final combined selection passes **58/58 methods**, with **zero failures,
errors or skips**. All six recorded owned implementation/regression files have
identical before/after hashes. The relevant Upscale-only selection also passed
23/23. These overlapping runs are not added together as independent coverage.

The earlier ETA selection passed 35/35 before a compatibility tightening. A
later recorded attempt encountered one existing 10-second worker-join fixture
bound while the full batch40 suite was also running. That exact unchanged
method then passed alone (1/1 in 4.000 seconds). The failed attempt remains in
[its original evidence](v148-batch41-eta-concurrent-attempt.json); no timeout or
skip setting was relaxed. The final 58-method run was green while the rendering
agent's first benchmark run overlapped. Its 32.004-second duration is only a
verification log, and no timing-performance claim is based on it.

The separate corrected boundary-fixture selection passes 21/21, including
real retained tracebacks and later worker collection with automatic GC enabled.
The earlier whole batch40 run aborted because of that fixture ownership issue;
it is not a passing full gate. Root will run the combined whole-suite gate
alone after integration. Native Tk/Windows, physical Paint input, CUDA devices,
packaging and remote CI remain separate checks.

Evidence:

- [Final selection and source hashes](v148-batch41-application-validation.json)
- [Historical ETA component proof](v148-batch41-eta-historical.json)
- [Upscale validation and avoided copy payload](v148-batch41-upscale-validation.json)
- [Historical Upscale component proof](v148-batch41-upscale-historical.json)

Historical substitutions keep current fixtures/dependencies and replace only
the named baseline functions. They are component red proofs, not complete
historical-checkout gates. `git diff --check` passed. No commits, shared registry
edits or publication actions were performed by this agent.
