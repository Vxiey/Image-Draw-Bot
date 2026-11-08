# Batch 29 — complete borrowed accuracy-input handling

## Classification and status

**Focused product regressions, paired historical plan replay and independent
review and integrated validation pass. This adds zero IDs.**

CP06/global681 already promises to borrow valid normalized inputs in read-only
numeric consumers. CG29/global129 covers unnecessary opaque-RGB conversion, and
IW08/global582 covers private-image cleanup while preserving borrowed inputs.
This change completes those existing guarantees in the actual final-preview
accuracy caller. Tests, observers and cleanup are not additional improvements.

## Actual before behavior

The frozen published parent is
`bfa43deb090c9ef858b04313fad9559ec4acfab1`. Its 883 root Python files were
unchanged throughout the read-only probe; their canonical map SHA-256 is
`74a659994b8f25037a6b233eb05efcafd2f60bffd3fa0de073d3623355c7929c`.

`finish_plan` already produces an owned normalized source and final opaque RGB
preview. `_evaluate_preview` nevertheless passed both through public
`normalize_source`, whose documented ownership behavior requires returning a
separate image even for an already normalized RGB input. This made two identity
copies immediately before NumPy copied their pixels into numeric arrays.

The observer counts `Image.copy` only on the actual selected source and preview
operands during the real evaluator call. Four actual UI-options → public Sketch
planner cases reproduce the redundant work:

| Quality | Original source / final RGB operands | Before identity copies | Nominal copied RGB pixel bytes | After copies |
| --- | --- | ---: | ---: | ---: |
| Balanced | RGB, 40 × 32 | 2 | 7,680 | 0 |
| Balanced | RGBA, 96 × 72 | 2 | 41,472 | 0 |
| Pixel Accurate | RGB, 40 × 32 | 2 | 7,680 | 0 |
| Pixel Accurate | RGBA, 96 × 72 | 2 | 41,472 | 0 |

The nominal payload is width × height × three RGB channels for each observed
copy. It is neither peak memory, process RSS nor an elapsed-time measurement.
All four evaluations return identical full metric dictionaries and both
heatmaps; the selected source, preview and caller image remain open and
unchanged. Each case invokes the actual final evaluator exactly once.

## Narrow change and ownership

Only the private read-only evaluator borrows an operand when it is RGB, has no
`transparency` metadata key and already has exactly the required size. The
numeric conversion creates independent float arrays before metric processing.
RGBA, palette, grayscale, color-key transparency and resizing retain the real
normalizer and its `ExitStack` ownership. A wrong-size normalized cache is still
ignored. Neither borrowed operand is closed on success, Stop or partial error.

Public `normalize_source` is unchanged. Its result remains separately owned
and mutable, including the RGB identity case. GPU routing, metric formulas,
source-relative accuracy, heatmap values and returned metadata are unchanged.

The existing CP06 resource fixture now uses RGBA for its owned-normalization
case. Its two created-image close-before-metric assertions, second-normalizer
failure, metric-call assertions and source-preservation assertion remain intact.
The new module separately covers the borrowed opaque-RGB path. This fixture
change retains the ownership contract while exercising a case that still needs
normalization.

## Regressions and evidence provenance

`test_v148_colour_batch29_accuracy_inputs.py` has five methods covering the four
actual public callers; direct, valid-cache and invalid-cache evaluation; RGBA,
RGB color keys, P/LA/L and alpha-bearing previews; public normalizer ownership
and resize; and retained real Pillow errors and cancellation during CPU metrics.
Transparency expectations use an independent integer alpha-over-white oracle,
and source snapshots include metadata and exact pixels.

Explicitly loading the permanent fixture against the frozen parent gives
**seven expected copy-count failures across two methods, zero errors and zero
skips**. Functional assertions run before the copy-count assertion. The other
three methods already pass. The before raw report is
`pending-batch29-accuracy/before/observations.json`, SHA-256
`c194c66eafeed9b957783824e5678c6bf9b1ab3012b7f279a3f60e34527cd582`.

Two initial observer-isolation diagnostics are preserved separately. The first
probe installed private paths too late for import-time crash/session logging;
the read-only audit blocked two attempted log opens under the frozen checkout.
A diagnostic repeat retained their full details. Redirecting real RuntimePaths
before importing DrawBot fixes the observer: final before and after probes have
zero audit violations and unchanged source maps. No product code or regression
assertion was changed to resolve this harness issue.

The focused selection passes **36/36 tests**, no skips, in **0.479 seconds**.
It includes the new five tests, all CP06 resources, accuracy correctness,
source-relative accuracy and profile-observation controls. An independent
reviewer closes source/test review without blockers and passes a combined
**18/18** selection: five new Accuracy tests, eight new Portrait tests and five
existing CP06 working-set controls. Its raw log SHA-256 is
`ec4f8c06826cd118e5f1ccf95ad1a1fa4d409e576bc58e006e5cf2d8615fb971`.
These durations describe regression runs, not performance comparisons.

The first complete after observer passes **5/5**, with 886 root Python files
unchanged and canonical map
`85d9effac91ba6448bdfe5bda592f01899abcc501b8edab3e1e94f8b31e486eb`.
Every metric and heatmap matches its before counterpart. Separate processes
produce six different absolute temporary-state paths in each otherwise equal
public plan. Those raw differences are preserved separately from the paired
whole-module replay below. The common final source gate binds the completed ETA
work separately from this earlier focused checkpoint.

## Complete historical plan comparison

The paired replay installs the entire published `AccuracyEvaluator` module and
its six explicitly imported aliases for one side, then restores the current
module for the other. DrawBot, renderers, GPU routes and the other current
dependencies are shared and source-bound. Each pair uses the same real private
runtime/calibration directory. All four complete plans, including the six
storage-path fields, metadata, EXIF, accuracy values and both heatmaps, compare
exactly. Only the seven pre-existing profiler-clock paths are excluded.

The observed before/after copy counts remain two and zero in all four cases,
and every borrowed input remains open and unchanged. No runtime, traced-memory
or RSS measurement is part of this replay. It reports zero audit violations
and unchanged 887-file source maps with canonical digest
`00eff844ebd213643fe583cdeb32bf37081a6e768b5a2b7e421a9eba26b97469`.
Its complete raw summary is
`pending-batch29-accuracy/historical/summary.json`, SHA-256
`c5cdcec81bcb58eaea6099c25c32d3b453a3006ecc2b80cd1b0913344abab429`.
This checkpoint predates final maintenance of the separate ETA benchmark
reporter. Final evidence records the exact manifest relationship; it does not
rewrite this original observation to claim a later hash.

## Limits

This is an observed reduction of redundant image copying in the supported
preview evaluator and completion of existing ownership guarantees. It makes no
general planner speed, native peak-memory, physical drawing or GPU-performance
claim. The version remains development work until the original release target
and all required final gates are satisfied.


## Integrated frozen-source result

Frozen batch29 discovery completed **4,522 tests: 4,449 passed and 73 skipped**, in **240.202 seconds**. All source/configuration hashes remained unchanged. Fourteen real Linux/Xorg native cases, the 5,000-cycle source gate, eight existing-raster fixtures and package hygiene passed. The registry contains **840 distinct groups, 160 remaining**. One independently assessed preview-worker cost-handoff group is registered as R2901. The two image completions add zero IDs.

The completed gates bind **887 root Python files**, canonical SHA-256 `48245acbd0a159956f998b1009f022a5d7b0245f977f741eef84016c9ffbb4bc`, and **937 source/configuration files**, canonical SHA-256 `5c1ad8d0ae71e2223216257fac60478ac054283a8eb05482fd884cb8bd9c331c`. The final image replays use the same 887-file root Python map. [Final validation](v148-batch29-validation.json) records actual test/native/source/raster/package counts, the separate timing scopes, controls and review status. [Raw image completion evidence](v148-batch29-completion-evidence.json) preserves all original checkpoints and diagnostic artifacts without adding IDs. [Final ETA raw data](v148-batch29-estimate-benchmarks.json), [rejected tuple data](v148-batch29-estimate-tuple-diagnostic.json) and [intermediate byte data](v148-batch29-estimate-byte-diagnostic.json) remain separate. Validation separately records the final metadata review and package check after metadata generation. No general whole-pipeline speed or memory reduction is claimed; version 1.0.148 remains unreleased.
