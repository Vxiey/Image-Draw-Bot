# Detail Zoom physical quality admission

This fix does not mark the missing batch 43 or the 900-item scope complete.

Previously, a high-frequency source sample with a different palette color could
be appended even when the smallest physical brush would overwrite nearby detail.
Detail Zoom now checks proposed strokes against the original, alpha-composited
source at the fitted target resolution, after replaying CanvasGuard/EdgeBehavior
for the complete base sequence and each proposal.

The existing discrete square-brush model is used, not a claim that every target
application produces identical antialiased ink. Each modeled touched pixel must
have no larger squared RGB error than before, and at least one must improve.
Admission is incremental in execution order. The per-pixel rule ensures that a
later delivery-budget selection can omit any subset of approved proposals without
invalidating the modeled quality proof.

The gate intentionally declines optional details when the baseline is unproven:
- native Fill/background Fill plans;
- more than 4,000,000 physical canvas pixels;
- fractional fitted dimensions, fractional centered offsets, or fractional screen origins;
- base geometry stopped by CanvasGuard.

These cases keep the existing base plan unchanged. They are not falsely marked as
quality-verified. Source analysis can still find candidates while physical admission
adds no strokes; ROI diagnostics show only actually admitted and affordable work.

Tests in `test_v148_detail_zoom_quality.py` cover beneficial and harmful footprints,
wide/even brushes, palette-independent white canvas, actual ordered base coverage,
overlap and duplicate strokes, anisotropic scaling, connectors, guarded skipped
base strokes, integer centering, fractional placement rejection, memory bounds,
cooperative cancellation, and source-level integration. Existing time-budget tests
now use source details that are physically drawable at their native target size;
a golden-image regression preserves the previously harmful subpixel case.

Windows CI and packaged-installation verification must run on the final pushed
commit before release. Neither local tests nor this note establish release readiness.
