# Batch 26 — share Pixel region topology within one plan

Integrated product baseline: `5b0c22ac5dc620a911fa2a1f6216e272f644f7db`,
with 837 registered improvements. The subsequent
`a3b7b929b1332772a089e1819143471ae5d58c68` changes one existing UI test and two
batch25 documents only; the four historical product modules are unchanged.
The original topology reproduction and local preintegration comparison used
`586e12db5ea5142951c844f60dc2364f07a01c37` (830 registered improvements).

**R2601 / global 838 is one registered behavior group.** Concurrent published batch25 already uses
R2501 for timed admission order; this topology work was renamed without
expanding its scope. The earlier private checkpoint is preserved below and
is not evidence that the newly integrated head has passed its final gates.
Product review, focused integration tests, new full-history verification,
coordinated elapsed/allocation measurements and the combined repository gate
are complete on the frozen integrated source. This adds one unique group;
no general speed or memory improvement is claimed.

## Reproduced work in the actual public planner

The Paint/Pixel `make_plan` route first calls `focused_stroke_plan` and
`build_stroke_plan`. Line planning extracts connected components, their scalar
statistics, runs and a pixel-to-component label map. Later,
`refine_with_corrections` calls `region_accuracy_scores`, which independently
extracts components from the same `PixelMap` to obtain labels, component IDs,
colors, areas and bounding boxes. This second consumer does not use the
builder's full run/path graph or vertical-run extraction.

The initial read-only probe ran nine complete public plans on the unchanged
batch24 source. It observed the real `connected_components` calls and checked
each result against an independent row-major four-neighbor flood. It did not
record elapsed time or allocation measurements. The raw before observation is
`pending-batch25-topology/before-work-counts.json` in the review scratch area,
SHA-256 `d88855188bb5956f84ea45fd7e366d0189106c1e9f28b61543fbe37ab1c510b9`.
Its 850-source map is the same frozen map as the published batch24 measurement
(`b8b2992bab94fadacd12d84f874dffc6987183b1dcc6f772e28b532ddc3ed1d8`,
canonical compact sorted JSON).

Examples from that public observation:

| Actual source/options | Component analyses before | Row-statistics calls before | Observation |
| --- | ---: | ---: | --- |
| 64×64 checkerboard, Lines, Subject Off | 2 | 112 | The same 1,568 regions and labels are found twice. |
| 96×72 blocks, Lines, Subject Off | 2 | 110 | Both stages find the same three regions. |
| 64×48 RGBA, Lines, Subject Off | 2 | 64 | Both stages see the same alpha-derived visibility. |
| Blocks with white included | 2 | 144 | Both stages find the same four regions. |
| Blocks with Balanced background-fill policy | 2 | 110 | Both stages still use the same effective target. |
| Checkerboard, dots | 1 | 56 | Only the regional scorer extracts components. |
| Blocks, Subject first | 3 | 154 | Two subset builders and a full-target scorer have distinct masks. |
| Blocks, Subject only | 2 | 88 | Subject construction and native subject scoring require separate targets. |
| Fully transparent 32×24 source | 2 | 0 | Both analyses are empty. |

Both eligible stages use `validated_pixel_indices` and the same drawable mask.
There is no separate ignored-color or background-fill argument in component
discovery. Identity alone is nevertheless insufficient: an array may be
mutated in place between stages, and subset/clone targets must stay separate.

## Bounded ownership and fresh fallback

`PixelRegionTopology` is an explicit private owner for one planning operation.
The public controller creates it only for Lines with Subject Off, passes it to
the builder and the regional scorer, and closes it before checkpoint/final
preview construction and `finish_plan`. The encompassing `finally` also
closes it when an intervening brush/budget/simulation step raises or stops.
The owner is never stored in options, a `PixelMap`, an exported/returned plan,
module state or a persistent cache.

The builder offers its already completed private `int32` label map and copies
only seven integer fields per region into a read-only `int64` matrix: ID,
palette index, area and four bounding-box coordinates. Full Components, run
lists and paths are not retained. The builder clears its local component and
label aliases on this late handoff, including the last loop/pool-result
aliases if the offer raises.

The owner accepts at most **8 MiB of labels** and **65,536 records**. The
record payload is at most `65,536 × 7 × 8 = 3,670,016` bytes, approximately
3.5 MiB. Source-map and source-array references are weak. Thread identity,
array identity, declared dimensions, shape, integer dtype, boolean mask and
C-contiguity must still match at consumption. Replaced arrays, cloned views,
foreign maps/threads and unsupported representations use fresh extraction.

Before handing the labels to the scorer, bounded 65,536-pixel chunks verify
that `labels >= 0` still exactly equals the visible mask and that each visible
pixel still has its recorded palette index. In-place visibility or visible
color changes therefore cause a fresh fallback. Changes solely to ignored
pixels do not invalidate an unchanged effective topology. No second full
source copy or lossy content hash is used for this check.

Consumption is single-use. A capacity miss or optional record/validation
`MemoryError` takes the original fresh path; Stop retains priority. Other
malformed-data errors are not converted into a cache miss. Subject first,
Subject only, dots and standalone regional scoring retain fresh discovery.
Stop checks remain in component discovery and are also bounded through
record construction and validation.

The scorer uses the same accumulation, arithmetic, rounding, rank and
selection rules with either original Components or compact scalar records.
Its `finally` clears labels, records and all label-bearing views even when a
real NumPy error is held in a traceback. These ownership checks complete the
reuse contract; they do not add separately counted improvements.

### Memory tradeoff

Previously the builder's first label map could die before regional scoring.
The new successful path retains it, plus the compact records, between those
stages. This is up to 8 MiB + about 3.5 MiB of explicitly bounded additional
inter-stage retention. The full Component graph is avoided, but this does
**not** establish a lower complete-planner peak. Some plans can have a higher
peak while brush assignment or simulation runs. Validation also creates
bounded chunk scratch. The final tables below include both traced peak and
retained-with-result measurements for every workload, including higher or
slower controls. No total-RSS or all-Pillow-memory claim is made.

## Deduplication

- **RP14** replaces per-component full-canvas masks with chunked regional
  accumulation and omits unused vertical runs for that scorer. It still
  independently discovers the topology.
- **CP05** batches run statistics within one component extraction. R2601
  preserves that algorithm and avoids repeating the whole extraction.
- **R1201** shares desired-index and source-edge preparation across categorical
  score/checkpoint calls. It does not hand region labels from the builder to
  the regional scorer.
- **R1403** prepares path-cost inputs and **R2401** bounds the component
  scheduler's pending queue. Both precede this later scoring consumer and
  remain unchanged.
- **Published R2501 / global 831** preserves occurrence order after timed
  admission. That function and its three regression methods remain unchanged
  by R2601. It changes selected execution work, not the target's component
  topology. Both its admission and order metadata are included in the new
  complete-plan parity checks.

One group covers the bounded cross-stage reuse. Empty images, representation
checks, capacity controls, Stop, output parity and lifecycle regressions are
proofs of that group. The separately reviewed RC02 Shadow lifetime completion
adds no ID and is shared identically by both sides of the integrated topology
comparison; it is not charged as a topology saving.

## Focused regression and independent review

The initial topology suite contained 13 methods covering:

- An independent four-neighbor flood for exact labels and compact rows,
  including scalar IDs/order and immediate release of full Components.
- Same-object visible-color/mask mutations, harmless ignored-index changes,
  replaced/cloned arrays, shapes/dtypes, bounds and unsupported masks.
- Record/validation allocation fallback, Stop, foreign-thread access and
  single-use ownership with borrowed inputs unchanged.
- Actual public eligible plans with one component analysis, plus unchanged
  Subject/dot controls. Label maps are already dead at `finish_plan` and with
  the returned result; no owner enters the returned data.
- Actual public capacity, constructor, record-allocation and validation
  fallback, compared against complete normal outputs.
- Retained exceptions during the late offer, scorer consumption, after real
  adaptive-brush assignment and after native simulation but before scoring.
  Full component and label weak references are dead while the error remains
  reachable.
- Standalone scoring after a real target edit and a genuine NumPy
  boolean-index shape error with held traceback frames.

The implementation's 13-method gate passed. Independent source/runtime
review is closed without blockers; the independent gate passed **13/13 in
1.080 seconds**. Root separately reviewed the owner, four integration paths,
bounded retention and finalizer placement.

The first combined discovery ran **4,344 cases** and reported one failure:
the older `test_drawbot_forwards_full_options_to_subject_planner` required the
literal source suffix `options=options,cancelled=cancelled)`, which the new
private keyword necessarily changes. Its log, report and unchanged
906-source/config manifest are preserved; that run is not reported as a pass.
Only this test method was repaired, replacing the string match with actual
public planning and real Subject delegation for cost policies Auto/Off,
checking options, cancellation identity and resulting cost metadata. The
temporary drawing handle is released before planning. Independent source
review is closed and the complete ten-method legacy module passed **10/10 in
0.242 seconds**. No product change followed the first full gate. Root then
froze the new snapshot and started a complete rerun; its 856-root-Python
manifest is `d74a54b3b20b5cdddf623fe634c94f1f82ba4ba77f6d78cd74012355008a7ba2`.
That preintegration rerun subsequently passed **4,344 cases: 4,278 passed and
66 skipped, in 202.054 seconds**, with all 906 source/config hashes unchanged.
It used the same 856-root-Python manifest above. The resulting local paired
report is preserved in the previous, now frozen integration tree at
`Image-Draw-Bot-integration/docs/v148-batch25-topology-benchmarks.json`, SHA-256
`88e9f7be5ce9420442ec489a9b899a5de992298d1f11a49dc25c39a9aed5ac60`.
The full-gate record is preserved as `v148-batch25-local-regressions.json` in
review scratch. This checkpoint was never published. It remains historical
evidence against 586 and is not substituted for the new 837-baseline gate or
final batch26 measurements.

### Integrated active-timer coverage

The renamed `test_v148_rendering_batch26_topology.py` now has **14 methods**.
Its added public test uses the existing eye crop `(155,102,174,121)` from
`golden-regression/small-detail-preservation.png`, a 100×100 area, physical
3 px brush and the ordinary 30-second mode. The 18 shipped `DEFAULT_COLORS`
are loaded through a real temporary calibration file, and missing saved speed
history is the same explicit control for both calls. The real budget must
be active and omit paths; the test does not substitute a budget result.

The first attempt with the older four-swatch queue fixture collapsed this crop
to seven paths and therefore failed the required omission assertion. The
fixture was corrected to the actual shipped palette; the assertion and
product rules were preserved. A real capacity-fallback call then performs two
component analyses and the normal call performs one. Complete returned plans,
all budget metadata and admitted occurrences are identical. Selected work
remains an occurrence-aware subsequence of the real original builder, with
both `phase_order` and `admission_priority` checked. Labels and the private
owner are absent at finalization and return.

The **14 topology methods plus the three untouched incoming order methods
passed 17/17 in 1.660 seconds**. The incoming order-test file remains
byte-identical to 5b0, SHA-256
`b9756397d5bc5f62952ff00b85aca2cbc526f3b733ea946ea3bee3ed155a1fb7`.
The owner, builder and Subject files remain byte-identical to their reviewed
preintegration implementations; `progressive_time_budget` remains
byte-identical to the incoming product. Root independently reviewed the new
timer case and historical benchmark linkage without blockers.

## Historical verification and preserved preintegration evidence

`benchmark_v148_rendering_batch26_topology.py` compiles the four **complete**
historical modules from the selected baseline: `DrawBot`, `SubjectFocus`,
`PixelStrokeEngine` and `PixelAccuracyEngine`. They are linked together under
their public import names while each historical call executes. The after
side uses all four current modules. Shared dependencies, the temporary real
palette calibration file, CPU policy and the explicit available-RAM input are
identical on both sides.

The earlier preintegration verify-only run passed **36 complete regional-score pairs, 36 complete
public-plan pairs and 24 independent native raster pairs**, plus all ten
warm/counted workload comparisons. The public cases vary color/alpha data,
physical widths 1/4, one/two workers, white inclusion, Subject modes and dots.
Independent Pillow centerlines check brush-one/source-sized delivery without
production geometry helpers. Borrowed source pixels remain unchanged.

The comparison traverses the complete returned plan. It excludes only the
previously enumerated real planning-clock paths plus the same
`planning_stage_seconds` telemetry nested in Subject first's subject and
background sections. Geometry, ordering, colors, image bytes, component
statistics, scores, quality decisions, costs, budgets and estimates are not
excluded. Fingerprinting, native raster checks and image cleanup are outside
the eventual timer/tracer.

Exploratory verify-only raw: `batch25-topology-parity.json` in review scratch,
SHA-256 `9ca4dec510f6974a88f5f5a18c96681864bd27c6c269f943169381cfe512baa7`.
All **856 root Python hashes** were unchanged within that run. Complete public
output digest:
`de8c733aa9111772c1cb53d8a8840fec0f9ef0ea549b0f949e9671d99a41cb8f`;
independent raster digest:
`dd2e4568cdba13f84eb18bd292c1c30af6bbdb9ca0ba2de6f3084468a6709b9b`.
This is correctness/work evidence, not final elapsed/allocation evidence.

| Complete public workload | Analyses before → after | Row-statistics calls before → after | Final paths |
| --- | ---: | ---: | ---: |
| Checkerboard 64×64 | 2 → 1 | 112 → 56 | 1,568 |
| Checkerboard 128×128 | 2 → 1 | 240 → 120 | 7,200 |
| Checkerboard 256×192, geometry-only pricing | 2 → 1 | 368 → 184 | 22,816 |
| Blocks 384×256 | 2 → 1 | 390 → 195 | 5 |
| RGBA 128×96 | 2 → 1 | 128 → 64 | 2 |
| Flat 384×256 | 2 → 1 | 480 → 240 | 3 |
| Empty 128×96 | 2 → 1 | 0 → 0 | 0 |
| Dots 128×128 control | 1 → 1 | 120 → 120 | 7,200 |
| Subject first 96×72 control | 3 → 3 | 154 → 154 | 5 |
| Subject only 96×72 control | 2 → 2 | 88 → 88 | 2 |

## Historical benchmark compatibility

The new private handoff means old single-module replacement harnesses cannot
be plugged into today's caller as if their APIs were unchanged. The batch12
and batch24 replay scripts therefore pin their own published **after**
checkpoint's complete four-module caller graph for both sides, then change
only the module originally measured: accuracy for batch12, scheduling for
batch24. Their original output assertions and work counters remain. The
batch12 bridge still drops only its original `score_context` keyword and uses
the original no-op score-context factory on its before side.

This preserves each old experiment's causal scope without disabling the new
handoff in today's product or charging topology reuse to an old result.
Historical module hashes are recorded. Replays require an explicit previously
unused output path, with exclusive creation; published raw reports are never
overwritten. The batch24 compatibility replay passed all **72 scheduler,
24 public-plan and 24 independent raster pairs**, plus all **nine** warm and
counted workload comparisons. Its scratch report
`batch25-replay24-compatibility.json` has SHA-256
`c53be29379eb9afb6cdb6aae430ce8a6fc4648d5f48ad175ed4bfc88183a90ab`.
The global source-stability flag is correctly false because the separate
batch12 replay harness was updated concurrently; no elapsed/allocation probes
ran. The published batch12 and batch24 raw files remain byte-identical to
HEAD, with SHA-256 `1d18c9268cebacfa34817d5a0c9d8cb7c37cda3d6533fa52258b0eef9e5cd03d`
and `ea40ba06ae9b68d924bdb9d9015ac3a41219001b84dfb18d8ae121e07fc62ef5`.
The batch12 source review and independent compatibility call are also closed:
both complete public fixtures are exact, both preserve six score calls, and
the original target-build count changes **8 → 1** while source-edge percentile
calls change **6 → 1**. All four pinned after-module hashes match the original
batch12 raw report, as does the original before-accuracy hash. The first replay
attempt stopped because the shallow checkout lacked the historical Git
object; fetching that object enabled the unchanged harness to complete. No
product code or assertion was altered for that environment issue.

The incoming `benchmark_v148_rendering_batch25.py` had the same concrete
compatibility boundary: its actual before invocation raised
`TypeError: refine_with_corrections() got an unexpected keyword argument
'_region_topology'`. The failure log is preserved as
`batch26-replay25-before.log` in review scratch. Its replay now pins the
complete published 5b0 caller/builder/Subject graph on both sides and switches
only the original complete Accuracy/AdaptiveRegionHybrid pair between 586 and
5b0. The actual direct component observation also uses the pinned builder.
All original quality, quota, Fill-count, geometry and output assertions are
retained, as are its original timing boundaries. The replay does not strip a
keyword from today's product or attribute new topology work to the old
experiment. It records all historical hashes and requires an unused output
path opened exclusively. The incoming published quality report remains
byte-identical, SHA-256
`3f1f9e88c97f73bda47271d47c91dd97243992ed2918aed6bc29e56dfb945568`.
The untimed compatibility replay passed all three original public workloads
and quality controls. Every before **and** after result is exactly equal to
its corresponding entry in the published original raw report. All five
pinned after-module hashes and both original before-module hashes also match
that report. The component counterexample retains the same 30 occurrences and
3 px brush while reproducing 80% → 100% protected accuracy; the accepted-Fill
case retains two Fills and the 666-pixel diagnostic correction, while the
complete no-Fill control remains identical. No new timing was performed.

Replay raw: `batch26-replay25-compatibility.json` in review scratch, SHA-256
`f3804d0fbdd231215344a992dcc32bc51c15c6edaa8c025e1cc04fa292a2b98c`.
All 873 root Python hashes remained unchanged, with the same canonical map
as the integrated topology verification below. Independent source review of
the linkage, original assertions and exclusive-output protection is closed.

## Integrated historical comparison — verification complete

The batch26 verifier keeps all previous 36 score pairs, 36 complete public
pairs and 24 independent brush-one raster pairs, and adds **two complete
active-timer public pairs**, with one and two workers. They use the tracked
eye crop and actual shipped palette described above. Both complete historical
5b0 and current four-module graphs must retain identical full output and
budget metadata, while actual component discovery changes 2 → 1. No new
semantic field is excluded. The 3 px scaled timer case is explicitly outside
the source-sized brush-one raster oracle; its full preview/geometry/metadata
remain compared. The 24 existing independent raster comparisons are retained.

The first integration-verifier attempt correctly rejected two different
`correction_review.history.storage_path` values: the new timer fixture had
created its temporary calibration directory separately for each side. The
field was retained in complete equality. The fixture scope was moved outside
the whole pair/workload, so before, after, warm, counted, timed and traced
calls share the same real directory. No product or comparison exclusion was
changed for this fixture repair.

The corrected verify-only run passed **36 complete regional-score pairs,
38 complete public-plan pairs, 24 independent brush-one raster pairs and all
11 workload comparisons**. The two new timed pairs each preserve 119 target
regions, 92 final paths, 71 omitted paths and a correction reserve of 13.
Their actual component-analysis count changes **2 → 1** and row-statistics
calls **200 → 100**. The requested 30-second mode resolves to the unchanged
27-second planning budget on both sides; no timer rule was replaced. Label
maps and compact records are gone at finalization and returned-plan
boundaries. The ten earlier work-count rows above also reproduce unchanged.

Raw verify-only evidence: `batch26-topology-parity.json` in review scratch,
SHA-256 `d3fe5e5107f36800c7c2687b94bc767ca6e4548f1261c1234404132562cf1a87`.
All **873 root Python hashes** match before and after. The canonical compact
sorted JSON source-map digest is
`e4057cf13bd9e97e52b07dbdba90f6962a9bbb012c0c78430d782418d8d0442d`.
Complete public-output digest:
`c9e6472f7b9ac74f3ba94af3640df75698b7c5f8ef4ddacd2f176d700a7c6b38`;
independent native-raster digest:
`dd2e4568cdba13f84eb18bd292c1c30af6bbdb9ca0ba2de6f3084468a6709b9b`.
The unchanged regional-score digest remains
`b4db34b82564fba1898e919d9cdae9f3c6061709a12f9a2839d43014c79154eb`.

The final verifier source SHA-256 is
`41366ac9e54a8eb354a1819d707272415677fa3cc942ddbb222c3633b480c883`;
the repaired historical batch25 replay is
`ee4913ee6124bbfe9bf7fc21d96a4aed62ae10f547d361e44796abc187c8ddd6`.
Root independently reviewed the complete timer/trace boundaries and shared
fixture lifetime, with no remaining blocker. The integrated full suite and
final measurements use the subsequent shared source freeze.

The same active-timer public caller is an **eleventh workload** in the final
paired run. Palette-file and missing-speed-profile fixture preparation happen
outside the timer/tracer; real admission, compact export, semantic validation,
simulation, scoring and estimates remain inside the public call. Final raw
evidence belongs in `docs/v148-batch26-topology-benchmarks.json`. Earlier local
raw files and their provenance remain preserved separately above.

## Coordinated final measurement — complete

Root ran the final measurement alone after the integrated regression gates.
The accepted raw report is
`docs/v148-batch26-topology-benchmarks.json`, SHA-256
`22694492a512805267a3b01e54c14c102d95296a9092b1dc94868aa558440018`.
It records six balanced AB/BA pairs across all eleven workloads, followed by
separate before/after `tracemalloc` calls. Every timed and traced result passes
the same complete comparison. Only the real complete `make_plan` call is
timed: copied settings, source size, input construction, module linkage and
calibration preparation are outside. Compact record construction, semantic
target validation, both normal estimates and the rest of planning remain
inside.

The final run repeats all **36 complete regional-score pairs, 38 complete
public-plan pairs and 24 independent brush-one raster pairs**. The active
timer still retains 92 final paths, omits 71 and reserves 13, with both its
admission-priority and original-order metadata unchanged. Eligible work still
changes from two component analyses to one; dots and the two Subject controls
retain their original counts. The final complete public-output digest is
`79319c68e621f6010815e2520a55683ef31d2ca23d7d22c1a475f6aa67582e79`.
Unlike the independent raster and region-score digests, this digest need not
equal a separate invocation's digest: the full output includes the real
temporary history path. That field remains compared within every pair.

### Complete public-call elapsed time

Negative change means a shorter median. A faster pair compares the before and
after observations from the same balanced round; it is not inferred from the
two aggregate medians.

| Complete public workload | Before median, ms | After median, ms | Median change | Faster pairs |
| --- | ---: | ---: | ---: | ---: |
| Checkerboard 64×64 | 388.435 | 374.543 | −3.576% | 3/6 |
| Checkerboard 128×128 | 1,784.750 | 1,778.826 | −0.332% | 2/6 |
| Checkerboard 256×192, geometry-only pricing | 3,293.444 | 2,983.639 | −9.407% | 6/6 |
| Blocks 384×256 | 153.614 | 141.672 | −7.774% | 6/6 |
| RGBA 128×96 | 47.766 | 44.990 | −5.811% | 6/6 |
| Flat 384×256 | 142.209 | 135.358 | −4.817% | 6/6 |
| Empty 128×96 | 25.228 | 24.464 | −3.028% | 5/6 |
| Dots 128×128 control | 431.720 | 460.401 | +6.643% | 2/6 |
| Subject first 96×72 control | 55.633 | 55.881 | +0.447% | 2/6 |
| Subject only 96×72 control | 44.467 | 46.161 | +3.809% | 1/6 |
| Existing-asset active timer, 100×100 canvas | 176.122 | 170.123 | −3.406% | 6/6 |

The large geometry-priced checkerboard, blocks, RGBA, flat and active-timer
cases are shorter in all six paired observations. This supports a benefit for
those measured calls. The two smaller checkerboards have overlapping sample
ranges and only three or two faster pairs despite lower medians. All three
fresh-analysis controls have higher medians; their observations are retained
as measured, without attributing them to a reuse benefit. In particular, the
dots control is 28.681 ms slower at the median. The evidence does not establish
a general planner or drawing speed improvement, and a six-pair sample does not
characterize every target, source or machine.

### Separate traced allocations

These are bytes sampled while the original returned result is still alive.
Prepared input images, normalization, equality checks and cleanup are outside
the trace. Values cover the traced Python/NumPy allocations of the actual
call; they are not total process RSS, GPU memory or all native Pillow memory.
Retained-with-result values can include remaining traced allocator/cache
state as well as result data. They do not imply that the topology owner is
retained: the dedicated boundary/weak-reference tests require it and its
labels/records to be gone before finalization and return.

| Complete public workload | Before peak, B | After peak, B | Before retained with result, B | After retained with result, B |
| --- | ---: | ---: | ---: | ---: |
| Checkerboard 64×64 | 5,862,998 | 5,862,537 | 3,750,190 | 3,749,597 |
| Checkerboard 128×128 | 24,997,809 | 22,169,338 | 12,471,605 | 12,213,984 |
| Checkerboard 256×192, geometry-only pricing | 78,641,684 | 68,732,767 | 36,570,090 | 36,569,847 |
| Blocks 384×256 | 13,359,584 | 13,359,409 | 1,141,908 | 1,141,709 |
| RGBA 128×96 | 2,166,624 | 2,166,352 | 875,135 | 874,786 |
| Flat 384×256 | 13,317,858 | 13,317,405 | 1,102,878 | 1,102,401 |
| Empty 128×96 | 2,051,205 | 2,050,679 | 781,346 | 780,574 |
| Dots 128×128 control | 19,955,240 | 19,955,484 | 8,600,007 | 8,600,356 |
| Subject first 96×72 control | 1,507,790 | 1,507,349 | 936,372 | 936,019 |
| Subject only 96×72 control | 1,684,631 | 1,684,494 | 1,117,585 | 1,117,426 |
| Existing-asset active timer, 100×100 canvas | 4,530,255 | 4,530,232 | 1,606,634 | 1,606,379 |

The 128×128 and 256×192 checkerboards have peaks lower by 2,828,471 B and
9,908,917 B respectively. Most other peak changes are only tens or hundreds of
bytes; dots increases by 244 B, and its retained result increases by 349 B.
These observations do not remove the explicit additional inter-stage
retention allowance described above. There is no general memory reduction
claim, and no measurement of total RSS or physical-device resources.

### Final integrated gates and source binding

The complete final discovery passed **4,431 cases: 4,361 passed and 70 skipped,
in 215.945 seconds**. All 923 source/config hashes remained unchanged. The
canonical compact-sorted-JSON digest of that complete source/config map is
`f84e92559d7bcc3a5f56fc605e1a203fdb7dafd369127ab85001da6f89e599fa`.
The subsequent native Linux/Xorg gate passed ten actual widget/lifetime cases
with no skips or diagnostics, in 5.238 seconds. This is local native evidence;
the new commit's Windows CI remains a separate validation boundary. The
5,000-cycle source gate and eight existing exact-raster fixtures also passed.

All **873 root Python files** are identical across the full-suite root subset,
native gate, engine report, both topology snapshots and both OpenCL snapshots,
and remain unchanged after measurement. Their canonical compact sorted JSON
source-map digest is
`e4057cf13bd9e97e52b07dbdba90f6962a9bbb012c0c78430d782418d8d0442d`.
The final report uses Python 3.12.14, NumPy 2.3.5 and Pillow 13.0.0 on Linux.
The elapsed and allocation evidence is complete. The batch finalizer registers
R2601/global 838 while preserving all 837 preceding entries.
