# v1.0.148 batch 42 — protected detail, affordable Fill and bounded rendering storage

## Scope and count

This ledger proposes **seven** independent rendering groups against public
checkpoint `e33fa67d17e3c33ccda8e736e7e16c2582d9fc06`. That commit has the same
`72e55f2a6d3dad971a13e9ab9141aa521cf15177` tree used locally as `b75ef8e`.
The checkpoint registry contains 869 implemented groups. This document assigns
no final global IDs and does not claim the 900 target has been reached.

All seven implementations have focused regression and historical evidence.
The final adjacent selection passed **135/135 methods in 61.989 seconds**,
with zero failures, errors or skips. Its complete log and source hashes are in
`v148-batch42-rendering-tests.json`. The two numeric historical reports are
`v148-batch42-rendering-validation.json` and
`v148-batch42-rendering-costs.json`; their reproducible drivers are
`verify_v148_rendering_batch42.py` and
`benchmark_v148_rendering_batch42_costs.py`.

| Local group | Independent failure | Implemented correction | Count boundary |
| --- | --- | --- | --- |
| R4201 | Pixel Accurate used only rounded luminance for edge evidence, so distinct equal-luminance colors did not protect their boundaries. | Combine the unchanged normalized luminance signal with bounded, halo-aware R−G/B−G opponent gradients. Actual Pixel priority, brush protection and corrections consume the result. | One Pixel feature-signal group, including all consumers. |
| R4202 | The standard public planner computed a protected-detail mask, then background simplification ignored it and erased the protected foreground. | Pass the existing mask into the background flood; protected pixels block traversal and writes, preserving enclosed interiors too. | One mask handoff and flood-policy group, not separate helper/caller IDs. |
| R4203 | Low-complexity Auto selected Balanced in Preview but Strong simplify in Draw, losing detail only in the actual drawing plan. | Use one conservative Auto policy: Balanced below the established high-complexity threshold, Preserve detail above it. Explicit Strong stays available. | One automatic policy group; diagnostics and an adjusted expectation add no IDs. |
| R4204 | Hybrid admitted Fill from per-region core prices without finally charging both actual tool transitions to the surviving color batch. Other Extra Fast callers used an unlearned UI-delay price. | Share calibrated batch-control cost, subtract the complete known embedded tool share, price the actual retained batches and reprove stateful safety after any cost removal. | One complete Fill admission/pricing group across public routes, with no per-route IDs. |
| R4205 | Late Detail Zoom appended up to its path-count cap after the real deadline planner had finished, without pricing the extra operations against remaining time. | Admit source-backed optional proposals through the existing stateful appended-delivery gate, including actual fitted geometry, fixed setup, preceding Fill and color selections. Keep base geometry/order and Unlimited unchanged. | One late optional-detail budget group; reuse of Pixel's gate is not another Pixel ID. |
| R4206 | Detail Zoom composited the full original source using several full-size float planes before its bounded analysis resize. | Keep the required RGB result and composite large sources in 256×256 tiles with the identical float32 formula; small images and panoramas use one dense bounded call. | One source-analysis staging group. Required output and global analysis arrays remain. |
| R4207 | GPU stroke preparation retained a Python tuple and Python integers per rectangle, then allocated a second complete NumPy catalogue. | Accumulate the unchanged ordered five-int records in one private native int32 buffer and return its NumPy view. | One host rectangle-storage group. CUDA kernels, clipping and raster order are unchanged. |

## Registry overlap review

R4201 is separate from **R4001/848**, which changed the Pillow local-range
signal inside `AdaptiveDetail`. Pixel Accurate bypasses that preprocessing
stage and uses a separate NumPy/GPU-routed edge API. Its two-color opaque
reproduction remained entirely unprotected after R4001. **CP03/678** fixes
boundaries against skipped white/transparent neighbors; both colors here are
drawable and opaque. **CP04/679** changes picture-palette sampling. **GP09**
preserves the finite-difference boundary formula, which remains unchanged.
**R4002/849** bounds the different micro-detail neighbor stage. Its cleanup
pattern is reused with no additional count.

R4202 is independent of **RC05/737**, which removed background-flood storage
while preserving its former membership, and of **R3001/841**, which corrects
the separate Remove BG operation. Its grayscale reproduction does not depend
on R4001's chromatic signal. Adaptive Off retains the unprotected legacy route.
R4203 reproduces with background simplification explicitly Off in a standard
planner, so it is independent of both preceding groups.

R4204 preserves **RP32/546** invalid cached-cost handling and **RP33/547**
one-model-per-evaluation behavior. Those earlier groups did not charge the
actual surviving batch's learned Fill/restore controls. The existing
**RD04/751** contour/seed conversion and **R2502/832** delivered Fill topology
remain in use. Revalidating safety after cost removal closes this new admission
operation; it is not another topology ID. Model reuse in the new optional
`cost_model` argument and the corrected aggregate headline are zero-count
implementation details of the same group.

R4205 is not **R4101/864**, which fits the Pixel Accurate progressive and
correction sequence. This independent late pass runs for ordinary color
planning and already intentionally stays off for Pixel Accurate. It reuses the
existing stateful gate. **PL28/168** caps analysis dimensions, **PL29/169**
bounds nonmaximum-suppression search and **PL33/173** chooses a verified detail
brush. None prices the optional pass against the finished plan's remaining
execution budget. The prior path-count cap remains a preliminary bound.

R4206 changes Detail Zoom's original-source analysis, which does not call the
visible-color helpers previously improved in **GP10/562**, **C2001/819** or
**P3901/846**. It preserves compositing before LANCZOS; postponing alpha
composition until after resize would not preserve the contract. All of its
source modes and callers belong to this one group. R4207 is separate from
**RP11/525**, which bounds off-canvas lattice traversal, and **R1901/817**,
which shares native CPU footprints across physical simulation tiles. The GPU
compiler already visits each visible rectangle once; this group changes the
live host representation of that required catalogue. Existing Stop/traceback
ownership completions add zero IDs in both resource groups.

## R4201–R4203: measured image-quality decisions

Every new source is an existing repository raster, a crop/resize, or a
palette-only derivative of its labels. No new motif or image file is generated.
Asset checksums and exact derivative palettes are in the JSON reports.

For the original 360×240 geometry of
`golden-regression/small-detail-preservation.png`, the palette colors
`(160,100,10)` and `(116,103,110)` both round to luminance 108. The actual old
PixelMap has zero edge and protected pixels. The new map has **4,704 edge
pixels and 9,120 protected pixels** without changing its palette labels.
The real component planner changes from 19 fill/four mid-detail paths with no
protected paths to nine fill/four mid-detail/ten cleanup paths, all 23 protected.

With actual verified browser brush controls, the old public Pixel plan starts
at **89.8565% accuracy with 8,764 wrong pixels** and needs **1,044 correction
paths**, producing 1,067 paths in total. The new plan starts and finishes at
**100% with zero error pixels and zero corrections**, using 23 paths. Both
versions finish at 100%; the gain is that correct feature protection avoids the
initial destructive brush choice and its repair work. The complete displayed
model estimate changes **46.8728→43.12505 seconds**. This is modeled delivery,
not a physical browser timing measurement. A grayscale control retains exact
complete geometry, pixels, preview, accuracy and estimated time.

The background/Auto tests use the same existing source resized to 96×64 with
grayscale colors `(220,220,220)` and `(190,190,190)`. Explicit Preserve detail
identifies 3,144 protected pixels. Old Strong background simplification still
overwrites all **351 foreground pixels** and removes their 148 source runs.
The protected flood preserves the exact source while continuing to simplify
eligible background. Its estimated work increases **4.8085→5.6361 seconds**;
that extra cost is retained because it preserves real detail.

With background simplification Off, old Auto uses Balanced for Preview but
Strong for Draw. Only Draw loses the foreground. Both new public calls use
Balanced, identify 2,532 protected pixels and return identical geometry with
all source pixels preserved. Explicit Strong and high-complexity behavior
remain covered by regressions.

## R4204: actual retained Fill batches

The public reproduction uses
`golden-regression/dominant-hue-four-color.png`, resized to 192×128 with NEAREST,
Balanced delivery and a valid learned tool-change observation of one second.
Four small same-color regions have areas 161/160/159/160 pixels. Their scanline
comparison costs **5.74958 seconds**; actual contour/click/verification core
plus both tool transitions costs **5.903 seconds**. Old Hybrid admits them
without the final batch check. The corrected plan restores their stroke
fallback and retains the four profitable regions of the other color.

| Complete public-plan observation | Before | After |
| --- | ---: | ---: |
| Fill regions | 8 | 4 |
| Main sequence paths | 32 | 36 |
| Modeled complete work, including fixed/Fill/color costs | 204.575421 s | 204.320172 s |
| Source-grid coverage / color accuracy | 100% / 100% | 100% / 100% |
| Missing / wrong-color pixels before CanvasGuard | 0 / 0 | 0 / 0 |

Complete preview bytes remain identical. The increased path count is
intentional: the learned tool transitions cost more than the restored strokes.
The test runs the real executor against an independent numeric mouse/flood
boundary. Every physical pixel matches the expected canvas, including the
existing **1,884 empty pixels in CanvasGuard's 3 px safety inset**. All four
retained Fill clicks execute, the mouse is released and the borrowed source
is unchanged. Source-grid quality is explicitly before CanvasGuard; the batch
does not claim to eliminate its intentional inset.

Removing a region can change the painted state seen by later bucket fills.
The implementation therefore repeats the existing stateful safety proof after
cost removal, preserves the accepted paint order and terminates as candidates
are only removed. Cancellation after the first 8→4 decision is verified to
abort before publishing an unproven subset. Aggregate savings use the final
batch total, not a sum of individually clamped positive shares.

## R4205: late Detail Zoom stays within the existing deadline

The actual Maximum likeness planner uses the existing small-detail source,
a 96×64 target, a 15-second timer with an **11.82-second render allowance**, and
a valid learned dot cost of 0.4 seconds. With Detail Zoom Off, its 13-path base
costs **10.299887 seconds** including the active risk allowance and fixed setup.
Old manual 4x appends 16 extra detail paths and raises complete modeled work
to **17.258132 seconds**. The new pass admits three of the same proposals,
retains the byte-identical 13-path base and costs **11.811276 seconds**.

The public unlimited control remains exactly equal: 354 paths, including all
120 proposed detail paths, identical ordered geometry, preview pixels,
metadata and **168.067891 modeled seconds**. Additional focused controls cover
zero remaining budget, preceding Fill controls and color selections, unchanged
borrowed proposal/base objects and the previously tolerated shorter legacy
diagnostic-group list. No timeout, path-cap or test skip is raised to make the
budget test pass.

## R4206–R4207: exact output with lower host allocation

The benchmark warms each real historical/current function, alternates call
order over seven pairs and checks exact output after every call. Tracemalloc
runs are separate from wall-clock timing. All raw samples and hashes remain in
`v148-batch42-rendering-costs.json`.

| Actual existing-source operation | Traced peak before → after | Median CPU time before → after |
| --- | ---: | ---: |
| Detail Zoom visible RGB, original 512×512 RGBA icon | 11,536,117 → 3,673,864 B | 9.3386 → 9.5628 ms |
| Same conversion, 128×128 crop | 722,677 → 723,543 B | 0.3299 → 0.3303 ms |
| Same conversion, 512×2 panorama crop | 66,890 → 67,519 B | 0.0588 → 0.0468 ms |
| Same conversion, 2×512 panorama crop | 66,890 → 67,519 B | 0.0650 → 0.0695 ms |
| GPU host catalogue from actual 258-path Pixel plan, 2,566 rectangles | 487,876 → 192,572 B | 9.8520 → 10.9134 ms |

The large conversion reduces traced peak **68.15%**; compact rectangle staging
reduces it **60.53%**. Both large cases are slower in this run, by approximately
2.4% and 10.8% respectively. Small controls retain slight memory overhead;
the vertical panorama also takes longer. These are resource improvements,
not universal speed claims. Complete process RSS, native Pillow allocations
and GPU VRAM are not measured by these figures.

The alpha tests use the real icon's RGB/RGBA/L/P derivatives and EXIF rotation,
an independent integer composite oracle, dense/tiled seams and thin panoramas.
Retained Stop and failure tracebacks release owned images and unpublished
output. Rectangle tests compare real component paths against the actual CPU
simulator's paint and coverage counts, including clipped translated geometry,
brush inheritance, repeated output independence and retained late errors.
The returned int32 catalogue has a private owner; caller mutations cannot
alter the input sequence or another compilation. No CUDA hardware is required
or claimed by this host-boundary proof.

## Verification and zero-count follow-ups

The new files contain **28 methods**: 11 fidelity, eight cost/admission and
nine staging methods. The initial cost/staging run was **16/17 passing**: its
only failed assertion incorrectly expected the intentional CanvasGuard border
to be painted. The repaired test compares the entire physical canvas exactly,
including that empty border. The subsequent focused run was **17/17 passing**.
The final adjacent selection passed **135/135 methods**, including all new
methods, the three repaired old fixtures and existing Fill/Zoom/CPU-to-GPU
boundary suites, with zero failures, errors or skips. Its log and source hashes
are preserved in `v148-batch42-rendering-tests.json`.

Three earlier full-batch41 fixture failures are repaired without IDs:

- The wide-brush spy accepts and forwards the new existing `cancelled` keyword.
- The five-second Pixel case permits an empty plan when fixed overhead alone
  exhausts the allowance. Its ten-second case still requires nonempty painting,
  real omission, exact coverage and a complete sequence-cost bound.
- The sketch-finalization Pixel case uses a real slower delivery configuration
  so its complete sequence exceeds the 30-second allowance. It still checks
  actual trimming, active timer behavior, explicit target cap, full/deferred
  parity and source ownership.

The old low-complexity Auto expectation changes from Strong to Balanced; all
manual and high-complexity controls remain. Late retained-output cleanup,
shorter legacy groups, exact aggregate savings and the small-panorama dense
cutoff complete their existing/new owner contracts with no additional IDs.
Two initial benchmark field typos and an Unlimited risk-policy mismatch were
harness failures, corrected before the final observed A/B report; they did not
change product code or weaken a deadline assertion. All earlier full-gate
failures remain in `v148-batch41-initial-full-validation.json`.

## Limits

These results concern actual CPU planning, ordered categorical simulation and
an isolated native input boundary on Linux. They do not establish physical
Paint/browser raster fidelity, calibrated Windows brush behavior or GPU
hardware performance. Fill admission compares complete retained color batches
against the existing scanline cost model; it does not claim a globally optimal
reordering of all rendering work. Detail Zoom reserves the same modeled
execution costs as the existing planner, not a hard real-time guarantee.

The chromatic edge result retains the normal global percentile workspace;
only its opponent and merge scratch is bounded. Detail Zoom still needs its
required full RGB output and bounded resized analysis planes. Rectangle staging
still grows with the number of visible output rectangles. These remaining
allocations are explicit rather than presented as a zero-memory path.
