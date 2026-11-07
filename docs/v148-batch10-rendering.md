# 1.0.148 batch 10 — renderer ownership and region planning

Baseline: `3c5fe8fc27ec3b503e2affa6f3ed00cb7856f973` (765 recorded improvements).

This working ledger contains **four implemented behavior groups**, R1001–R1004.
The corresponding callers, tests, cancellation checks, reports and measurements
support those groups and are not counted separately.

## R1001 — dispatch the resolved Pixel/Subject renderer directly

Extra Fast's Pixel Art policy already selects `pixel-components` and Pixel
Accurate. The early `make_plan` dispatch nevertheless wrapped that planner in
Adaptive Region Hybrid. The wrapper created a second sequence and replaced the
coverage diagnostics, while `finish_plan` continued executing the original
`_pixel_execution_sequence`. Subject focus reached the same conflicting route
because its Pixel Accurate promotion happened after dispatch.

Resolve the Subject policy first and let a resolved Pixel Accurate plan bypass
the regional wrapper. The existing Pixel engine remains the sequence owner;
ordinary regional Extra Fast and contour policies retain their dispatch. This
removes the discarded alternative computation and its misleading metadata.

The independent baseline reproduction uses the public Extra Fast + Pixel Art
policy on a 96×72 image of 48 colored tiles. Under Custom 10 s, the executable
Pixel sequence paints 1,040 pixels, while the discarded regional sequence paints
1,664. The public Coverage map described the latter and differed from the
actual-sequence map at 1,648 pixels. The main simulated drawing already used the
executed sequence; the later source-error heatmap has its own source comparison.
Neither is claimed to have this Coverage provenance defect.

`test_v148_rendering_batch10_dispatch.py` exercises the actual policy and public
planner under both 5 s and 10 s budgets. Independent Pillow footprints produce
the expected public Coverage colors and missing-pixel count. The summary's
palette cost follows the actual retained color/phase transitions. Separate
Subject-only and Subject-first cases preserve R901's physical footprint and
subject ordering. A non-Pixel Logo case still executes the regional sequence.
The four new tests plus adjacent policy/hybrid/subject tests pass together:
30 tests in 1.310 s. C independently reviewed the complete source/test delta
and ran 22 dispatch/subject/regional tests in 1.317 s with no blocker.

This differs from RB03: that group avoided repeating an identical final cost
evaluation within ExtraFast2. R1001 corrects dispatch and published ownership
between two different planners after an explicit policy decision.

## R1002 — retain scores instead of all alternative brush rasters

`_candidate_paths_for_brush` evaluates native and half-stride layouts in both
orientations. It formerly retained every candidate's ROI-sized trial mask and
path lists until the final 90%-gain and cost comparison. The 96×128, width-16
fixture retained 48 Boolean planes at once: 589,824 bytes of mask payload alone.

Keep only each candidate's gain, cost, path count, stride, orientation and
offset. The existing 90% threshold and complete tie key choose the same layout.
Reconstruct its paths and painted mask once for return. All temporary trial
buffers can then be released as candidates are scored, independent of the
number of offsets. The actual target/residual masks remain borrowed and
unchanged. Stop is checked before and during reconstruction and before return.

`test_v148_rendering_batch10_candidates.py` compares against literal pixel
footprints and independent Pillow sweeps, including holes, residual subsets,
readonly inputs, odd/even brushes, final-size policy, translated coordinates
and a brush too large to fit. It verifies exact winning geometry, mask and
cost. Weak-reference instrumentation bounds simultaneously live alternative
planes to two instead of 48. A Stop injected while rebuilding the winner
cannot publish partial geometry. A real public multibrush plan uses a 47×31
region and matches the independent scalar alternative oracle for complete
sequence, groups, choices, candidate diagnostics, quality and preview pixels.
Its independently painted footprint covers exactly the source region.

The four new tests with dispatch, existing brush-packing/ROI and morphology
tests pass together: 28 tests in 3.480 s. A independently ran the four new tests
in 2.891 s and closed the source and measurement review without a blocker. It
verified all 25 recorded source hashes, recomputed the medians, and checked
the helper substitution, parity scope and memory/time tradeoff.

RD03 reduced scratch arrays *inside each morphology calculation*. R1002 fixes
the separate lifetime of fully generated alternatives after those calculations.
Rebuilding the winner adds work; the elapsed-time tradeoff is reported below,
without a universal speed claim.

## R1003 — admit an exact pack that needs only one verified brush size

After proving that a brush pack painted exactly its component, the planner
discarded it when fewer than two distinct sizes had been used. A 48×32 blue
rectangle needed only the already-verified 16 px control, so every successful
wide candidate was rejected with a contradictory zero-residual failure reason.
The connected 2 px fallback then painted 81 outside pixels.

An exact pack using one verified size now competes in the existing calibrated
cost comparison. The available control evidence, ROI fit, complete footprint
and exact-coverage gates are unchanged. No new brush size is invented. The
chosen fixture becomes three actual 16 px strokes, covering all 1,536 source
pixels with zero spill. A high measured brush-switch cost still makes the
existing narrower candidate win; wide-brush admission does not force selection.

`test_v148_rendering_batch10_single_brush.py` exercises the public planner and
independent square-footprint oracle, the calibrated-cost counterexample, and
the real `execute_plan` loop with a fake native mouse. Replaying its recorded
actions changes physical width only when the verified 16 px control is clicked,
then reproduces the rectangle exactly and leaves the mouse released. These
three tests, R1002 and the existing brush/ROI suites pass together: 14 tests in
0.774 s. Root independently reviewed the source and ran all three actual-plan
tests; the R1003 review is closed without a blocker.

R1003 repairs candidate admission after a successful proof. It is separate from
R1002's alternative-buffer lifetime, RD03's morphology and R901's interior
Subject-only mask constraint.

## R1004 — model fixed native brush widths in the physical drawing raster

A regional plan can analyze a 200×150 image and draw it at 400×300. The old
packing proof treated a verified 16 px brush as 16 *source* pixels, although
the executor selects a physical 16 px control. Scaling the path coordinates
then separates strokes without increasing their real width. A published
baseline 95×63 region used 27 paths and verified widths 2/4/8/16, and reported
100% coverage. Replaying the actual executor's native mouse actions covers
47.6023%: 12,544 target pixels are missing, with zero guard skips and zero
spill. This reproduction uses the baseline regional builder and admission
function, so it is independent of R1003's newly admitted single-size pack.

`NativeBrushProjection` retains the original source-integer path contract and
uses `CanvasTransform` for exact reachable screen centers. The nearest-source
target cells, native brush erosion, candidate gain and exact final footprint
proof use physical pixels. The verified width is never rounded or scaled into
a fabricated source brush. Candidate spacing is only a proposal; every layout
still has to pass the actual native-footprint and complete-coverage checks.
The unchanged 90%-gain rule may retain a wide partial layout plus narrower
verified cleanup strokes. If the reachable grid cannot fill the region exactly,
the packing candidate is rejected instead of claiming exact coverage.

Each projected ROI is checked against the existing `planner_max_pixels` before
allocation. An oversized ROI rejects that optional pack with a concrete reason.
Final quality is streamed through tiles within the same allowance, so it can
still measure the fallback over the entire physical canvas, including spill
into a letterbox outside the fitted source. Conservative fallback metadata
does not label a source-centerline proof as an exact physical footprint.
The bounded main preview samples native brush rectangles into the fitted crop;
the Coverage diagnostic explicitly describes the full physical canvas.
Neither score claims to include later CanvasGuard clipping, real target ink
verification or native application behavior beyond the existing square-brush
model. The tests compare actual delivered actions where guard clipping is absent.

Unit scale with a coincident source/canvas grid retains the existing path and
source-preview behavior. Every letterbox uses full-canvas accounting, including
integral placement: the independent review's actual 4 px unit-scale run spilled
561 pixels, while a fitted-source-only simulation saw just 438. Fractional
letterbox placement also needs the physical model: signed half-pixel rounding
can leave a screen coordinate unreachable even at unit scale.
The current executor's gap is preserved and reported, rather than normalized
away inside the simulation. Native input and its coordinate transform are unchanged.

The inverse cell map floors an exact rational expression of the supplied fitted
geometry and stored offset. It does not divide by a pre-rounded scale or move
boundaries with an epsilon. With fitted/source 216/200 and half-pixel vertical
placement, the previous division assigned native row 135 to source row 124
instead of 125. That lost a complete 152-pixel target row. The actual public
fixture now retains 8,208 target pixels and reports the executor's 605 missing
pixels; adjacent floating values on both sides of the exact boundary are also
checked. Safe coefficient ranges use vectorized integer quotients; other cases
use bounded axis chunks and Python integers.

`test_v148_rendering_batch10_physical.py` has nine regressions. They cover real
public planning and actual executor replay at 2× scaling, unequal noninteger
axis scales, negative screen origins, fixed 4 px letterbox spill both at unit
scale and enlargement, a native ROI
above the Standard 75,000-pixel allowance, and unit-scale signed half ties.
The exact 216/200 cell boundary and its adjacent representable fitted values
cover the numerical distinction between a true tie and a nearby cell.
Independent inverse cell mapping and Pillow brush sweeps match the complete
public Coverage diagnostic and missing/spill/wrong-color counts. An independent
Pillow EXTENT/NEAREST sample of every recorded native raster also matches the
main preview's fractional fitted crop. The 96×64-source
rectangle at 2× now covers all 24,576 physical target pixels with zero spill,
using only its real verified controls, and its main preview matches that raster.
A literal footprint oracle checks reachable centers around a hole, and Stop
during streamed simulation closes the owned diagnostic image. The initial
eight-case module and adjacent ROI, morphology and hybrid preview tests passed:
38 tests in 15.191 s.
The final nine-case module, including the integral-letterbox and exact-boundary
review corrections, passes in 2.081 s.
A independently reviewed the final caller/projection/simulation/preview changes
and ran all nine tests in 2.692 s. It also checked 80 complete-axis cases against
an independent Fraction oracle, including integer, fractional and adjacent
representable fitted values and letterbox margins. Both reported integration
and numerical findings were corrected and verified. The R1004 review is closed
without a remaining blocker.

R1004 concerns the dimensional mismatch between native brush width and scaled
source coordinates. RP38's source-raster pixel-interval projection remains
correct for its direct callers; R1004 adds the physical-coordinate contract at
the actual scaled regional caller. RB06 established full-canvas placement,
which is reused here. R1001 dispatch, R1002 candidate retention and R1003
admission each retain their separate earlier behavior contract. No timing or
memory reduction is claimed for this additional physical simulation work.

## Paired measurements

`benchmark_v148_rendering_batch10.py` records function and current dependency
fingerprints in `v148-batch10-rendering-benchmarks.json`, checks output parity,
runs five interleaved before/after pairs, then measures traced peaks separately
after garbage collection. The table and JSON now contain the **final shared
source-freeze run**, replacing the preliminary measurements. All 26 dependency
fingerprints remained unchanged during the run and matched the current files
again afterwards. Exact output parity passed for all three comparisons.

| Workload | Before median | After median | Before traced peak | After traced peak |
|---|---:|---:|---:|---:|
| R1001 public Extra Fast Pixel Art `make_plan`, 64×48 | 63.879 ms | 36.375 ms | 2,928,875 B | 898,467 B |
| R1002 alternative selection, 128×96 ROI, 16 px brush | 10.315 ms | 11.723 ms | 753,228 B | 152,680 B |
| R1002 public multibrush `make_plan`, 128×96 | 139.563 ms | 140.601 ms | 1,847,944 B | 1,847,464 B |

R1001 substitutes only the baseline `make_plan` function. Its interior fixture
compares the complete executable sequence/groups, image, palette, fitted size,
main preview, executable count, estimate and operation timing. The obsolete
wrapper's reconstructed source-run representation/count and the corrected
Coverage/alternative metadata intentionally change and are not claimed equal.
The budget-limited diagnostics correction is separately covered by the public
pixel oracle tests above.

R1002 substitutes only `_candidate_paths_for_brush` inside the same current
planner, including the same R1003 admission and R1004 integration on both sides.
The R1002 public fixture has a coincident source/canvas grid, so it isolates
alternative retention without adding the separate native-projection workload.
The helper comparison
includes every path coordinate, painted pixel and calibrated cost. The full
planner comparison also includes source/main/Coverage preview pixels, both
source and execution groups, sequence, counts, estimate, path statistics,
operation timing, quality, region choices, all candidate diagnostics and the
complete schedule. Volatile timing/profiling fields are excluded explicitly.

Weak-reference instrumentation records 48 live candidate Boolean planes before
and one after in the helper fixture: 589,824→12,288 bytes of trial-mask payload.
The new implementation allocates one additional final mask while reconstructing
the winner, so the improvement concerns simultaneous retention, not eliminating
every allocation. The helper is slower in this final run. The whole planner is
also slightly slower and its peak allocation is essentially unchanged. These
are Python/NumPy traced bytes,
not process RSS or most native Pillow pixel storage; the measurements do not
cover physical drawing, UI interaction or hardware GPU execution.

The JSON records all 26 source SHA-256 values. Key final fingerprints are:

| Source | SHA-256 |
|---|---|
| `DrawBot.py` | `0ae9a90f823d06d24aa4ac2c67ebc32789235592dd8bbc5390dfb6efb04d4cef` |
| `AdaptiveRegionHybrid.py` | `5055fdba5fc45d27a542724f6a6b200047533e9c8bf93d0cb5bae71b320706d3` |
| `NativeBrushProjection.py` | `8b7f0dd1e53892d03adff620145c6265fa4675020770ab123effca4a271fe0c5` |
| `benchmark_v148_rendering_batch10.py` | `dffa4ae67820dcbf3eb7656a39d4f5808c58320dfdd6ec855874b4418e804938` |

## Validation status

Focused tests, paired timing/allocation measurements and `git diff --check`
pass. All four source reviews are closed. Shared frozen whole-program validation
remains pending and is owned by root.

## Frozen checkpoint validation

Batch 10: final frozen-source discovery passed 3,579 tests in 125.869 seconds (43 platform/hardware skips), with unchanged Python and batch-script hashes. All four area source reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. Paired rendering and recovery measurements bind the final source snapshot and disclose unchanged or slower total-work results. The published batch10 checkpoint `a8fabbc811029a8bfcbe8a5af2a848b034e5cd89` passed complete Windows/Linux regressions, both dependency audits, CodeQL, Windows self-test, bundle build and packaged GUI/native drag-and-drop in [run 42325709249](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42325709249). All four jobs and all seven commit checks succeeded. No 1.0.148 release is published.
