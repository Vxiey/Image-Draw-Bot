# v1.0.148 batch 41 — costed Pixel admission and brush-center runs

## Scope and count

This batch proposes **two** independent implementation groups against the
unchanged batch 40 checkpoint `fc3f927`. Its registry contains 861 implemented
groups. This ledger neither assigns global IDs nor claims the final target of
900 has been reached.

All tests and comparisons use existing repository source images, crops, resized
versions, or their real palette/component plans. No source motif or rendered
image artifact is generated. Product changes are confined to the Pixel timed
admission/correction path, its existing public integration, and the Boolean
center-run extractor used by regional brush packing.

| Local group | Demonstrated problem | Implementation and count boundary |
| --- | --- | --- |
| R4101 | Public Pixel Accurate planning cut paths using a fallback five-paths-per-second estimate before examining real delivery cost. A 30-second plan lost substantial detail even when the entire exact plan cost much less than the available time. Its correction reserve was also expressed as a path count, which cannot account for custom colors, native brush transitions or verification. | Pass the existing `ExecutionCostModel` into public timed Pixel planning. Subtract resolved fixed work from the canonical render budget; retain a complete affordable sequence, otherwise remove complete low-priority paths with stateful neighbor deltas and a bounded refill. Freeze inherited brush widths and preserve original occurrence order. Price correction proposals and their protected-detail retry against the same remaining sequence budget. A full stateful cost pass is the final admission gate. Base admission, correction admission, public wiring and the matching budget log form one root-cause fix. |
| R4102 | Regional brush packing repeatedly walked each Boolean center mask in Python for every row/offset/orientation candidate. | Find transitions in bounded Boolean blocks. Group short rows into a single native search; carry runs across blocks for exceptionally wide rows. Preserve exact path order, numeric truth semantics, stride/offset behavior, orientation and seam joining. This is the center-mask extraction inside brush candidate search, separate from component-label vertical extraction and packing-score reuse. |

## Registry overlap review

R4101 does not recount R2501 (831), which fixed the original paint order after
the old phase quotas had already selected paths. This batch preserves that
ordered-subsequence contract and changes **which work is affordable**. RP28
(542) prices the separate `AdaptiveDeadlineRenderer`; RC03 (735) fixes its
initial charging of unused color setup. Neither connects the Pixel engine's
old throughput admission to its actual delivery model. R2201 (824) remains the
owner of protected-pixel correction safety; this batch only adds the timer gate
before accepting its resulting paths. Existing cost-model, calibration and
prepared-path formulas are reused without additional counts.

R4102 is distinct from R4003 (850), which batches vertical transitions through
integer connected-component labels. This function extracts horizontal or
vertical paths from already proven Boolean brush-center ROIs. R1802 (813)
reuses first-brush layout scores; it does not remove this repeated Python
pixel scan. Cancellation forwarding, private scratch release, inherited-brush
preservation and historical-test adjustments add **zero** independent IDs.

## Public Pixel quality evidence

`benchmark_v148_rendering_batch41.py` loads the historical `DrawBot` and
`PixelAccuracyEngine` modules from the checkpoint, then calls their actual
public planners with the same CPU settings, palette, source pixels, calibration
override and 30-second timer. Both sources are existing 96×64 resized fixtures.
The resolved render budget is 26.55 seconds, including 3.35 seconds of fixed
work; 23.2 seconds remain for sequence delivery.

| Existing source | Old paths | New paths | Old planned accuracy | New planned accuracy | Old error pixels | New error pixels | New estimated draw time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `small-detail-preservation.png` | 105 | 221 | 85.7259% | 100% | 2,778 | 0 | 11.755 s |
| `red-bananas-texture.png` | 105 | 134 | 89.6647% | 100% | 635 | 0 | 8.566 s |

Protected-detail accuracy changes from 78.8986% and 54.6046%, respectively, to
100%. The new model prices sequence delivery at 8.530961 and 5.710730 seconds;
both fit completely. This is an intentional quality improvement, not a claim
of unchanged timed output. Untimed behavior and legacy direct callers without
a cost model retain their existing admission behavior.

Tight-budget controls use actual source geometry with verified brush states and
calibrated palette/brush/verification costs. They require the complete retained
sequence to fit its risk-adjusted budget, retain protected work, preserve source
input, and keep original occurrence order. A budget smaller than fixed work
admits no path rather than forcing one. Correction tests retain a real accuracy
gain while admitting fewer paths than the unlimited correction plan.

## Validation

The new focused files are `test_v148_rendering_batch41_pixel_budget.py` and
`test_v148_rendering_batch41_mask_runs.py`. Their eleven tests cover public
quality, exact stateful cost, inherited brush widths, affordable corrections,
fixed-work exhaustion, retained-Stop cleanup, exact independent scalar runs,
noncontiguous/read-only masks, numeric truth values, empty shapes, wide seams,
bounded allocation, actual Python-read reduction, cancellation and complete
regional-plan/diagnostic equality.

The batch 25 and batch 26 public timer regressions now use a real per-move delay
of 0.05 seconds so their fixtures still require trimming under the actual cost
model. Their ordered-subsequence, protected-cleanup, topology-ownership and
complete-plan parity checks remain. The legacy direct-throughput assertions
are unchanged. No timeout or skip was added.

The parent integration owns the full application gate.

The final focused selection completed **113 tests in 22.014 seconds, with zero
failures, errors or skips**. It includes all eleven new tests and existing
Pixel mapping/simulation/performance, Subject Focus, hybrid/native brush
packing, ROI, cost-model, protected-correction, timed-order, shared-topology and
batch 40 region regressions. The exact fifteen-module unittest command and
final implementation/test hashes are retained in the validation JSON.
`git diff --check` passes.

An earlier targeted command used an incorrect unittest class name; the actual
class was then selected correctly and passed. That harness-selection error is
not reported as a product regression or hidden by a skip. Independent read-only
runtime-agent review found no blocker in the transition accounting, removal and
refill state, correction gate or either run-extraction branch.

## Isolated historical CPU comparison

Run `python benchmark_v148_rendering_batch41.py` with the repository interpreter.
The script loads the checkpoint's actual modules, warms both routes, alternates
A/B order, and records exact complete-plan hashes and diagnostic-image hashes.
It does not write images. Full raw observations are retained in
`v148-batch41-rendering-validation.json`.

| Stage and existing source | Old median | New median | Equality and work evidence |
| --- | ---: | ---: | --- |
| Boolean center runs, small-detail 360×240 | 5.886 ms | 0.8595 ms | Exact runs; 87,215 Python mask reads become six bounded block reads. Six alternating pairs. |
| Complete hybrid builder, small-detail 192×128 | 1.096804 s | 1.035048 s | Exact groups, sequence, quality, non-timing metadata and both diagnostics. Three alternating pairs. |
| Complete hybrid builder, icon 192×192 | 2.233762 s | 2.641109 s | The same complete equality checks pass. Three alternating pairs; the observed median is slower and is retained. |

Complete-planner timings are noisy: the icon's old calls range from 1.977208 to
4.146428 seconds and new calls from 2.515285 to 4.541886 seconds. They do not
establish a whole-planner speedup. The deterministic reduction is in the mask
extractor's Python work, whose separate stage measurements also improve.

The Boolean stage's traced peak increases from **112,616 to 156,723 bytes**
because batching uses bounded transition scratch. This is an explicit
CPU-versus-scratch tradeoff; required path output is unchanged. The scratch is
bounded independently of full canvas dimensions and does not retain a numeric
copy of the entire mask.

## Limits

The model predicts input delivery time; native Windows execution was not
measured here. Runtime cancellation and hard deadline enforcement remain
necessary. Geometry, source resolution, palette fidelity and physical brush
simulation are not simplified to obtain the budget result.

Boolean transition scratch remains bounded, but the required output path list
still grows with the number of actual runs. The new native transition search
uses extra bounded scratch compared with the scalar implementation. CPU stage
measurements and complete-planner measurements must be read separately; neither
establishes a general application, Windows, GPU or total-process-RSS claim.

An early timing pass overlapped another agent's final regression run and was
discarded. A small-ROI probe also identified that one NumPy search per short row
could regress small component work; grouping those rows in a bounded block is
part of the same R4102 change. Only the isolated final comparison is retained
as performance evidence.
