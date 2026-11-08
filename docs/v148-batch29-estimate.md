# Batch 29: one cold sequence calculation per preview worker

## Scope and status

The baseline is published `bfa43deb090c9ef858b04313fad9559ec4acfab1`, with 839
registered groups. **R2901 is registered as global 840, after the explicit root/peer count decision and integrated gates.** Tests, typed input variants, ownership guards and benchmark
maintenance are not additional groups. No timing or memory improvement is
claimed by the preliminary work-count evidence below.

Product changes are confined to `DrawTimeEstimate.py` and the actual preview
worker in `DrawBotApp.update_plan`. The worker owns a single local observation
across public planning and final estimate attachment. The main sequence's
immutable, full-precision `CostBreakdown` can be reused only by the same plan
with unchanged cost inputs. No plan, options, persisted settings or returned
metadata gains an internal cache/owner field.

## Actual repeated work before the change

The scratch observer ran against the clean published batch28 worktree, not an
edited historical module. All **883 root Python files** stayed unchanged; the
compact JSON source-map SHA-256 was
`74a659994b8f25037a6b233eb05efcafd2f60bffd3fa0de073d3623355c7929c`.
Its process audit rejected repository writes and network bind/connect, and
runtime/calibration paths were isolated in a private temporary directory.

The original U2001 controller fixture drove real `update_plan`, its real
worker, public `make_plan`, queued `planned`/`done`, `poll`, and visible
Tcl-bound readouts. It recorded the first estimate in `finish_plan` and the
second estimate after the worker sets final preview/target/full-detail fields.
Both calculations used the same returned plan and identical sequence geometry,
full-precision component breakdown and cold total. There was already no third
UI-thread calculation.

| Actual controller case | First worker path costs | Second worker path costs | UI path costs |
| --- | ---: | ---: | ---: |
| Native 84×64 preview | 98 | 98 | 0 |
| Projected 1100×600 target | 191 | 191 | 0 |
| Explicit full-detail 84×64 | 115 | 115 | 0 |

Evidence is retained outside the repository in
`pending-batch29-estimate/observe_before.py`, `before.json`, and `before.log`.
The report captures real effective delays, scale, full-precision dataclass
fields before display rounding, area/projection inputs, calibration scope,
throughput reads, final metadata and readouts. Product clocks were not mocked
and no elapsed comparison was made.

## Transfer boundary and late conditions

`preview_estimate_scope()` is entered only by the actual preview worker. It
remembers at most the latest plan's primary sequence calculation, together with
an immutable semantic input snapshot and the creating `Thread` object. A
copied context in another thread cannot consume or close that observation.
Nested/rescue producers replace the one observation; a different returned plan
takes the normal fresh path. The scope closes through success, Stop and errors.

The input snapshot covers ordered path coordinates, operation/phase/color/brush
values, effective source/fitted scaling, delivery policy and delays, precision,
model version, cold runtime/multiplier, color-selector evidence, color
verification and verified brush-reset behavior. In-place edits and replaced
values are compared by content, not only by top-level object identity. Types
are preserved for scalars and containers. The compact implementation validates
an exact builtin-type whitelist, then uses `pickle.dumps(..., protocol=5)` to
create local bytes. This preserves exact float bits, including signed zero.
There is no deserialization. Subclasses and custom objects are rejected before
the serializer can invoke a reducer. Unsupported values or an unavailable
input snapshot use the original fresh calculator.

Independent review found that an initial untyped snapshot could equate a
custom-selector dictionary with a list of equal pairs, and numeric phases with
different string forms. A real public plan followed by first pricing, mutation
and final attachment reproduced four failures: dict→list-of-pairs, phase
int→float, bool→int, and +0.0→−0.0. Each fixture also demonstrated a genuinely
different fresh estimate. The original typed-tuple snapshot fixed all four,
and the compact byte representation retains those controls; the original
failure log is `pending-batch29-estimate/seal-types-before.log`.

`attach_preview_draw_time_estimate` consumes the private observation once and
always retires it, including failed preparation. Only the primary immutable
`CostBreakdown` is reused. Sequence operation metadata is rebuilt. Region Fill
still reprices real contours/seals with `use_cached_cost=False`; background
Fill, custom prelude selections, fixed countdown/clear overhead, measured
throughput, projection, local calibration and uncertainty remain fresh.

This deliberately does **not** extend R2101's calibration scope. The first
estimate is inside public planning; the late estimate runs after that scope
has closed. Real timing samples and RealSpeed data written between those two
boundaries are read by the late estimator. After publication, U2001 still
consumes the exact prepared metadata reference once; later previews observe
later writes. The first estimate remains available to standalone planners,
AutoTuner acceptance, diagnostics and rescue decisions.

The signature has its own CPU/allocation cost and retains one plan until it is
replaced, consumed or the worker scope ends. These costs belong in the complete
pipeline measurements; a reduced `path_cost` count alone is not evidence of a
general speed or memory improvement. Executor delays, clocks, mouse delivery,
input authorization, preview watchdogs and controller Stop policy are unchanged.

## Correctness and historical linkage

The eleven new methods cover actual native/projected/full-detail worker adoption;
in-place path/order/phase/brush/color/selector and delay/speed/precision/delivery/
fitted/scale changes; foreign and legacy plans; fresh fixed/background and real
three-region Fill costs; real calibration/throughput writers between planning
and publication; copied-thread contexts; one-use retirement; actual Stop and a
subsequent explicit preview; retained error ownership; and all four typed-input
collisions. The additional public-plan method checks ordinary object and
`str`-subclass reducer traps and a real snapshot `MemoryError`: all use fresh
cost arithmetic, and neither custom reducer is called. Expected output is
compared with the ordinary fresh public estimator. No cost arithmetic oracle
is reimplemented by the tests.

The first Fill control selected a legacy grouped route without a final
execution sequence, so it did not exercise the intended sequence/Fill boundary.
The fixture now explicitly selects the supported **Progressive passes / On**
route, asserts a real final sequence and three retained Fill regions, and
requires a fresh Fill calculation. No production change was made for that
fixture correction. The initial 16-method log is retained separately.

The typed-tuple checkpoint passed **17 methods in 7.582 s**. After the compact
representation and reducer/allocation controls, the focused gate passed
**18 methods in 8.261 s**: all eleven new methods and all seven unchanged U2001
regressions. The latter retain failed late-preparation
fallback, metadata replacement, stale/Stopped disposal, later geometry changes
and next-preview calibration semantics. Independent source/test review closed
the typed-input blockers without removing an assertion or changing a skip.

`benchmark_v148_ui_batch29_estimate.py` loads the **complete** historical
`DrawBot.py` and `DrawTimeEstimate.py`, linked together for the actual
worker/join/poll lifetime. Other dependencies are the same current modules on
both sides. It must not be described as executing the entire old dependency
graph. Both sides use the same private calibration paths, resource boundary,
fixture controller bindings and logger/scheduler boundaries.

Historical source hashes:

- `DrawBot.py`: `d0bd7e013299eebb74ee502da5d07fb7012b48818561902c01b8be656abf4ec8`
- `DrawTimeEstimate.py`: `b6cb04e11cf2b95c55bd0afcf0748831192448fe2e6c7017514b9a5bcdbd5b44`

The final preliminary `--verify-only` run passed all seven workloads with
complete plan/readout and full-precision primary-breakdown/cold-total parity.
Its **887 root Python files** were unchanged. The source-map digest is
`a4e566ae461134bb7c033425af0c75c1e65a737792cb0c97e05ff119bf665529`, calculated
with `json.dumps(source_sha256, sort_keys=True)` using its default separators.
This differs in serialization from the compact digest used by the original
883-file before observer; the raw source maps are authoritative.

| Workload | Actual `path_cost` calls, before → after |
| --- | ---: |
| Complete native preview pipeline | 196 → 98 |
| Complete projected preview pipeline | 382 → 191 |
| Complete full-detail pipeline | 230 → 115 |
| Complete dense 96×72 pipeline | 2386 → 1193 |
| Pipeline with changed late delay | 196 → 196 |
| Standalone public-plan control | 115 → 115 |
| Separate late-estimator dense helper | 576 → 0 |

The separate late-estimator fixture prepares its plan/possible observation
before the measured call and uses ordinary public-plan options. Its 576 paths
are distinct from the dense controller's 1193 preview-policy paths. It is not a
complete preview pipeline or a native UI benchmark.

## Measurement method

After a shared source/CPU freeze, the script uses six balanced AB/BA pairs
per workload and separate `tracemalloc` observations with the raw result alive.
Only the actual operation is timed/traced; fixture setup, source generation,
private-path routing, output normalization/hashing and cleanup are outside.
Observed correctness, verify-only and warm runs do not read the elapsed timer.
An already active external trace is rejected without stopping it.

To distinguish total ETA cost from whole-pipeline variation, the final timed
pipeline samples also delegate through identical wrappers around each real
`estimate_from_plan` call. The raw report retains both pass durations and their
actual sum for every paired sample. The first interval includes constructing
the input snapshot; it is not a late-only measurement. Wrapper installation
and summation are outside the whole-pipeline timer, and pass/thread structure
must match the separate correctness observation. The whole operation still
includes the wrapper's small bookkeeping overhead on both sides. Allocation,
observed, warm, verify-only and standalone calls have no extra ETA timers.

Raw output is reserved exclusively before the run. Completed side observations
and timing samples are retained as they accumulate; any failed parity, timing,
allocation or source check is published as a failed partial report with its
active stage and exception. Existing artifacts cannot be overwritten.

Final timings, all regressions or higher allocations and the final raw hash
appear below. Integrated test counts remain pending until that gate completes. No
physical target application, Windows runtime, GPU throughput or RSS claim is
made by these CPU/Tcl fixtures.

## First frozen measurement: performance implementation not accepted

The first coordinated measurement completed with all correctness, full-precision
and source checks passing. Its raw artifact is now retained byte-for-byte as
[v148-batch29-estimate-tuple-diagnostic.json](v148-batch29-estimate-tuple-diagnostic.json),
SHA-256 `8dcb9709a6b7c97d986fb456b008ca64455bd7c8d94d64a08f17fbeb50d099e1`.
Its original filename was `docs/v148-batch29-estimate-benchmarks.json`; only the
name changed, so the next final run can reserve that original destination
exclusively. No raw field or sample was edited.
All 887 root Python files remained unchanged. The raw report's default-JSON
manifest is `a4e566ae461134bb7c033425af0c75c1e65a737792cb0c97e05ff119bf665529`;
the same map's compact canonical digest is
`fda7b811a726083ed1881fdc810a0ddd6c354bec7b4215c1cf516e81dbe3edeb`.

This run **does not justify accepting the typed-tuple implementation as a
performance improvement**. The typed nested-tuple input snapshot removes the
repeated path calculator, but its own work/allocation outweighs that saving in
the dense complete pipeline. The precise cause has not yet been separately
profiled; Python snapshot-object allocation is the concrete implementation
hypothesis. No slow sample was removed and no artifact is overwritten.

| Workload | Before median, ms | After median, ms | Change | After faster, pairs |
| --- | ---: | ---: | ---: | ---: |
| Native pipeline | 163.7025 | 168.8502 | +3.145% | 3/6 |
| Projected pipeline | 1237.0254 | 1262.2667 | +2.040% | 2/6 |
| Full-detail pipeline | 154.5814 | 155.0951 | +0.332% | 3/6 |
| Dense pipeline | 691.8944 | 746.4159 | +7.880% | 0/6 |
| Changed late-delay control | 183.7868 | 185.8849 | +1.142% | 2/6 |
| Standalone public-plan control | 157.1261 | 151.6559 | −3.481% | 4/6 |
| Separate late-estimator helper | 11.0339 | 10.6824 | −3.186% | 4/6 |

| Workload | Traced peak before → after, B | Retained with result before → after, B |
| --- | ---: | ---: |
| Native pipeline | 4,613,802 → 4,824,906 | 1,769,989 → 1,863,333 |
| Projected pipeline | 45,553,639 → 45,555,098 | 5,539,252 → 5,643,503 |
| Full-detail pipeline | 4,683,134 → 4,908,915 | 1,820,696 → 1,914,087 |
| Dense pipeline | 8,677,640 → 11,093,699 | 4,622,137 → 4,260,731 |
| Changed late-delay control | 4,613,934 → 4,825,121 | 1,770,102 → 1,867,752 |
| Standalone public-plan control | 4,584,855 → 4,585,705 | 1,686,376 → 1,687,285 |
| Separate late-estimator helper | 120,376 → 1,782,564 | 103,968 → 289,376 |

Dense pipeline pairs were all slower, from +6.671% to +13.973%. The isolated
late-estimator helper ranged from −14.601% to +5.870%, so its small median
decrease does not excuse the complete-pipeline regression or higher traced
peak. These are Python/NumPy trace values, not RSS or most native Pillow memory.
The implementation and any new-group registration remain pending a better
bounded input representation and fresh verification, or withdrawal of the
candidate. All type/mutation, late-correction and Stop requirements still apply.

## Compact representation diagnostic, before any final claim

The bounded follow-up changes only the internal input representation. It uses
one presence bitfield and the five raw semantic values per sequence row,
validates exact builtin types recursively, and serializes the validated data
to bytes without ever loading pickle data. Alias/memo differences can produce
a conservative cache miss; they do not relax input equality. The existing
typed/shape/signed-zero controls and fresh fallback remain mandatory.

The scratch-only `pending-batch29-estimate/compact_diagnostic.py` reuses the
reviewed permanent benchmark with only the actual dense pipeline and late
estimator workloads. Its four balanced AB/BA pairs are diagnostic, not the
final seven-workload gate. Complete plan/readout and unrounded cost parity
passed. All 887 root Python files were unchanged; compact map SHA-256:
`44aeead671ab7aaf48a59e12ffcd430609607b2f470e57d8419ae00bd9612394`.

The byte-identical report is retained as
[v148-batch29-estimate-byte-diagnostic.json](v148-batch29-estimate-byte-diagnostic.json),
SHA-256 `fdf8f8090618d4aa42d35b72ff9cc4e424caf6d63db0c5416357d77f62649555`.
The original scratch report and log remain separately available.

| Published bfa → compact bytes | Before median, ms | After median, ms | Change | Faster pairs |
| --- | ---: | ---: | ---: | ---: |
| Complete dense pipeline | 716.1235 | 711.9223 | −0.587% | 2/4 |
| Separate late estimator | 10.1104 | 2.7286 | −73.012% | 4/4 |

The complete pipeline includes creation of the first snapshot, not only its
late consumption. Its paired changes were −12.638%, +4.651%, −4.962% and
+7.651%; this run **does not establish a reliable whole-pipeline speedup**.
The late-only helper improved in all four pairs (−74.154% to −68.907%) but
deliberately prepares the first observation before its measured interval.

| Published bfa → compact bytes | Traced peak before → after, B | Retained with result before → after, B |
| --- | ---: | ---: |
| Complete dense pipeline | 8,678,618 → 8,679,297 | 4,622,785 → 4,600,835 |
| Separate late estimator | 120,376 → 243,119 | 103,968 → 58,520 |

The same diagnostic captures the actual 1193-path model/sequence from the dense
controller and compares only the two signature builders. Four balanced pairs
of 20 calls per side gave **19.9055 → 2.9497 ms per seal**. Separate single-call
traces gave peak **3,019,340 → 818,127 B** and retained seal **2,784,372 →
150,332 B**. The saved tuple module SHA-256
`0ae751d302b446e3f07ee7cdb8ce36fcc4a40e83d25651916cc491a54a8cfb4e` matches the
first raw report's source map exactly. These numbers explain the reduced
snapshot overhead; they are not a comparison with a published whole product.

The remaining cost of safe mutation detection and the higher late-estimator
peak are explicit. No final performance acceptance, new-group count or broad
speed/memory guarantee follows from this diagnostic alone.

## Final compact measurement and its limits

The final coordinated seven-workload run passed all complete-output,
full-precision, timed-result, allocation-result and source checks. Each workload
has six balanced AB/BA pairs; no sample or negative control was removed. The
raw artifact is
[v148-batch29-estimate-benchmarks.json](v148-batch29-estimate-benchmarks.json),
SHA-256 `0a55a290f801f9ece2c96481b0a23f777b3f09304ee713002d8d7c0ae8f77a12`.
All **887 root Python files** remained unchanged. The report's default-JSON map
digest is `8a0472c5a2fdd5824ff6e0ef4bfa4b67fce238d886e5107f31678981cb0afb68`;
the same map's compact canonical digest is
`48245acbd0a159956f998b1009f022a5d7b0245f977f741eef84016c9ffbb4bc`.
The final Accuracy four-case and Portrait 47-helper/five-public replays also
passed on that exact map before the timing window. No product or test source
changed during or after these measurements.

### Actual total ETA cost, including the first snapshot

These medians are computed from each actual sample's **sum of both ETA pass
durations**, not from the sum of independent pass medians. The first pass
includes constructing the mutation-protected input snapshot.

| Pipeline | Before ETA sum, ms | After ETA sum, ms | Change | After faster, pairs |
| --- | ---: | ---: | ---: | ---: |
| Native 84×64 | 4.7054 | 3.6092 | −23.297% | 5/6 |
| Projected 1100×600 | 47.6682 | 36.8351 | −22.726% | 6/6 |
| Full-detail 84×64 | 4.6106 | 3.6987 | −19.779% | 6/6 |
| Dense 96×72 | 30.0203 | 23.8240 | −20.640% | 6/6 |
| Changed late-delay control | 4.7669 | 5.8271 | +22.242% | 0/6 |

The unchanged dense pipeline's total ETA reductions ranged from 16.948% to
23.257% across its six pairs. The native ETA control has one slower pair
(+28.518%); its other five were faster. The changed-delay control deliberately
cannot reuse the first result. Both estimators therefore run, with input
validation added: all six ETA sums are slower, from +6.299% to +83.630%, and
the median difference is about **1.060 ms**. Its fresh estimate and complete
output still match exactly. This is a real conservative-fallback cost.

The separate pass medians make the first snapshot's cost visible:

| Pipeline | Pass 1 before → after, ms | Pass 2 before → after, ms |
| --- | ---: | ---: |
| Native | 2.2803 → 2.8295 | 2.3784 → 0.7933 |
| Projected | 24.3167 → 30.1481 | 23.2694 → 5.8480 |
| Full-detail | 2.2383 → 2.9694 | 2.2912 → 0.7099 |
| Dense | 14.9811 → 19.9120 | 14.6679 → 4.0703 |
| Changed late-delay | 2.3039 → 2.9473 | 2.3846 → 2.7300 |

Thus the measured benefit is smaller total **estimator work inside an
unchanged actual preview worker**, not a free first pass or a universally
faster estimate after a plan mutation. The work counter still shows one main
sequence calculation instead of two in the four unchanged cases; the mutated
and standalone controls retain their original calculation counts.

### Complete operation and allocation controls

| Operation | Before median, ms | After median, ms | Change | After faster, pairs |
| --- | ---: | ---: | ---: | ---: |
| Native pipeline | 184.5082 | 176.5611 | −4.307% | 4/6 |
| Projected pipeline | 1250.5893 | 1226.6821 | −1.912% | 4/6 |
| Full-detail pipeline | 179.2711 | 180.2425 | +0.542% | 4/6 |
| Dense pipeline | 698.8328 | 690.9475 | −1.128% | 2/6 |
| Changed late-delay pipeline | 177.2221 | 177.5175 | +0.167% | 1/6 |
| Standalone public-plan control | 148.9312 | 154.9643 | +4.051% | 3/6 |
| Separate late-estimator helper | 10.0243 | 2.7043 | −73.023% | 6/6 |

The whole pipeline is dominated by other work and has mixed paired outcomes.
In particular, the dense median is lower even though four of six individual
pairs are slower; its paired changes span −2.676% to +7.168%. Conversely,
full-detail has a higher median even though four pairs are faster. The
standalone control has no active transfer or snapshot and is nevertheless
slower by median. These observations do **not** support a general
whole-planning speedup claim. The late-only helper excludes initial plan and
snapshot preparation and is reported separately from the actual two-pass
ETA totals above.

| Operation | Traced peak before → after, B | Retained with result before → after, B |
| --- | ---: | ---: |
| Native pipeline | 4,614,293 → 4,614,806 | 1,770,234 → 1,766,548 |
| Projected pipeline | 45,553,712 → 45,555,151 | 5,539,517 → 5,537,778 |
| Full-detail pipeline | 4,682,877 → 4,683,630 | 1,820,397 → 1,816,385 |
| Dense pipeline | 8,677,864 → 8,678,841 | 4,622,212 → 4,600,933 |
| Changed late-delay pipeline | 4,613,744 → 4,614,731 | 1,770,055 → 1,777,450 |
| Standalone public plan | 4,585,114 → 4,584,787 | 1,686,449 → 1,686,331 |
| Separate late estimator | 120,376 → 243,119 | 103,968 → 58,520 |

Every pipeline's traced peak is slightly higher in this observation, by
513–1439 B. The late-only estimator's peak is **122,743 B higher**, despite its
lower elapsed and retained-result figures. The mutated control retains
**7395 B more**. These traces include Python-tracked allocations with the raw
result still alive; they are not RSS, native Pillow, GPU or target-app memory
measurements. There is no general memory reduction claim.

Independent source/test review closed the compact whitelist, typed equality,
fallback and lifetime boundaries. Independent method review closed the actual
two-pass timing, historical linkage and unchanged trace intervals before this
run. Independent final raw review verified all 42 pairs, both worker passes,
the medians of actual sums, full-output/full-precision parity and the stated
negative controls without rerunning timing. Root independently recalculated
the same results and source map. Both reviews closed without a blocker and
support exactly one bounded estimator group after the integrated gates pass.
The completed integrated gates and the explicit root count decision are recorded below. No additional timing run is implied by metadata publication.

## Deduplication

U2001/global821 removed the third **UI-adoption** calculation and explicitly
left both worker estimates. R2101/global822 shared one bounded timing database
inside public planning while preserving every context correction and geometry
calculation. This candidate removes the second primary sequence calculation
inside the actual worker while deliberately keeping the late correction and
projection boundary. It is the single registered R2901 group; the typed-input and lifecycle controls complete that
same behavior.


## Integrated frozen-source result

Frozen batch29 discovery completed **4,522 tests: 4,449 passed and 73 skipped**, in **240.202 seconds**. All source/configuration hashes remained unchanged. Fourteen real Linux/Xorg native cases, the 5,000-cycle source gate, eight existing-raster fixtures and package hygiene passed. The registry contains **840 distinct groups, 160 remaining**. One independently assessed preview-worker cost-handoff group is registered as R2901. The two image completions add zero IDs.

The completed gates bind **887 root Python files**, canonical SHA-256 `48245acbd0a159956f998b1009f022a5d7b0245f977f741eef84016c9ffbb4bc`, and **937 source/configuration files**, canonical SHA-256 `5c1ad8d0ae71e2223216257fac60478ac054283a8eb05482fd884cb8bd9c331c`. The final image replays use the same 887-file root Python map. [Final validation](v148-batch29-validation.json) records actual test/native/source/raster/package counts, the separate timing scopes, controls and review status. [Raw image completion evidence](v148-batch29-completion-evidence.json) preserves all original checkpoints and diagnostic artifacts without adding IDs. [Final ETA raw data](v148-batch29-estimate-benchmarks.json), [rejected tuple data](v148-batch29-estimate-tuple-diagnostic.json) and [intermediate byte data](v148-batch29-estimate-byte-diagnostic.json) remain separate. Validation separately records the final metadata review and package check after metadata generation. No general whole-pipeline speed or memory reduction is claimed; version 1.0.148 remains unreleased.
