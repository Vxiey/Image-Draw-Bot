# Batch 24 — bounded Pixel component scheduling

Baseline: `bb6dfa6a5e8a43bfcfc77c9e00f52dc2dfd7db9c` (828 registered
improvements). Historical `PixelStrokeEngine.py` SHA-256:
`8c6d94dc58a8bb7c25fcffd1dd9a0d8a8f9d88acf32bf5c92b4f5dfb349c4750`.

**R2401 is registered as global improvement 830.** Independent review, complete
historical/public parity, coordinated final measurements and the combined
repository gate are complete. This ledger records one bounded queue-work
improvement, with no general speed or memory-reduction claim. The batch24 registry records its
completed verification.

## Reproduced work in the public planner

The real Paint/Pixel `make_plan` path builds connected components and calls
`PixelStrokeEngine.schedule_components`. The scheduler already restricts each
choice to the first 72 pending components, but removed its chosen item from the
entire remaining Python list. Removing near the front shifts every later
reference, including components that cannot yet be candidates.

A read-only baseline observation of complete public plans used a calibrated
black/white palette, brush one, CPU/one worker, Unlimited time, and 64×64,
96×96 and 128×128 one-pixel checkerboards. It observed the actual list's `pop`
indices and retained full-plan digests, without recording elapsed time. The
planner source hashes were unchanged across the observation.

| Source | Actual components | Actual references shifted by pending-list removal |
| --- | ---: | ---: |
| 64×64 | 2,048 | 2,064,236 |
| 96×96 | 4,608 | 10,453,548 |
| 128×128 | 8,192 | 33,352,055 |

The candidate index never exceeded 71. The original repeated tail removal can
therefore do quadratic reference-moving work even though candidate comparison
work is bounded by 72 per selection. The initial observation's hypothetical
bounded-window counts are not treated as measurements of the implementation;
the final benchmark separately observes both actual queues.

## Change and retained semantics

The implementation creates the same stable sorted list with the same priority
and component-ID key, reverses that list once in place, and consumes its end
into an active window of at most 72 items. After selecting and removing a
candidate, it appends the next unseen item. Both operations move at most the
window's other 71 references; popping the unseen tail shifts none.

Reversing after the original stable sort preserves even the original order of
equal sort keys. The already allocated sorted list is reused. There is no
second full component list, persistent cache or forward iterator retaining
already consumed component references. The unseen list shrinks normally as
items are consumed. The small active list is local to the scheduling call.

All candidate cost formulas, arithmetic order, strict first-minimum tie rule,
stateful cursor and color updates, phase boundaries, path emission, metadata,
cost-model calls and cancellation checks remain in their original order.
Compatible models without `prepare_path_cost` retain their previous path-cost
interface. Interrupted final sequence pricing still propagates; other final
diagnostic failures still use the same original intrinsic-cost sum.

This changes queue maintenance, not the number of candidates priced, the
path/brush policy, palette, quality limit or native safety boundaries.

## Deduplication

- **R1403 / global 789** prepares immutable geometry and scalar costs for
  repeated first-path pricing. Its candidate queue still removed from the full
  pending list. R2401 does not change or claim those pricing savings again.
- **R1401 / global 787** indexes previous-row intervals during lossless path
  attachment. It does not maintain this subsequent component scheduler queue.
- **CP05 / global 680** batches component statistics and avoids a second
  statistics dictionary. It does not change pending candidate-list removal.
- **SS25 / global 205** bounds submitted executor tasks. This is a synchronous
  CPU component-selection queue, not that executor backlog.

One group is proposed for the shared queue algorithm. Boundary cases, Stop,
metadata, controls, public callers and their tests do not add groups.

## Regression evidence

`test_v148_rendering_batch24_component_queue.py` initially passed **8 methods
in 3.342 seconds**. The tests cover:

- An independent original full-list selection oracle, including empty queues,
  71/72/73 and replenishment boundaries, multiple phases, equal sort keys,
  unscored/empty components and first-candidate behavior for nonfinite costs.
- Exact ordered cost callbacks for legacy and prepared models, learned and
  default pricing, physical width and different native scales/precision.
- A real 2,048-component public Pixel plan: zero unseen-tail shifts, exactly
  2,048 actual active removals and no active window larger than 72. Its private
  pending-list owners are gone after return and the source pixels are intact.
- Actual `make_plan` → `execute_plan` calls with cost policy Off/Auto and one/two
  planning workers. A native mouse fixture paints solely from the clicked
  calibrated swatches; every delivered pixel matches both source and preview.
  Mouse release, unchanged sequence and the normal runtime guard counts are
  checked.
- Stop during preparation, selection and final cost, reusable unmodified
  borrowed components, and exact legacy fallback metadata on final-cost error.

Independent source/test/benchmark-method review is closed without blockers.
The independent eight-method gate also passed in **3.129 seconds**. The final
combined discovery completed **4,308 cases: 4,242 passed and 66 skipped**. The
5,000-cycle source soak, eight exact raster fixtures and 1,263-file source
package hygiene gate passed. The final timing/allocation evidence follows.

The exploratory `--verify-only` run passed all 72 complete historical
scheduler pairs, 24 complete public-plan pairs, 24 independent public raster
pairs and all nine workload comparisons. Every instrumented pricing-call count
also matched. Actual list-pop reference shifts were:

| Workload | Before | After |
| --- | ---: | ---: |
| 72-component calibrated scheduler | 1,933 | 1,933 |
| 8,192-component calibrated scheduler | 33,261,430 | 290,170 |
| 32,768-component geometry-only scheduler | 535,599,125 | 1,068,569 |
| Public Pixel 64×64, 1,568 components | 1,205,698 | 85,942 |
| Public Pixel 128×128, 7,200 components | 25,748,149 | 340,393 |
| Public Pixel 192×192 geometry-only, 16,928 components | 142,822,158 | 751,362 |
| Public RGBA 96×72, 216 components | 18,398 | 7,958 |
| Public flat 192×128, one component | 0 | 0 |
| Public dots 128×128, no component scheduler | 0 | 0 |

These counters measure list-pop shifts, not every reference operation. The
new implementation also performs one linear in-place reverse per phase and
one bounded-window append per replenishment, which the final elapsed
measurements must include. Queue comparisons and model-call counts are not
reduced. The exploratory run intentionally made no elapsed/allocation claims;
other batch24 capture source/tests changed concurrently, so its global
`sources_unchanged` flag is correctly false. Final measurements must use a
coordinated unchanged snapshot.

## Historical comparison and measurement method

`benchmark_v148_rendering_batch24_component_queue.py` installs the **complete
historical PixelStrokeEngine module**, including its builder and connected
component implementation, under its public module name. Real nested imports
from `DrawBot` and `PixelAccuracyEngine` therefore use the matching historical
module. Other dependencies are shared between the two sides. No isolated old
function is linked to changed queue helpers.

The historical verification includes 72 complete scheduler pairs and 24
complete public-plan pairs over queue boundaries, seeds, geometry/learned
pricing, RGBA, line/dot mode, one/two workers and cost policy Off/Auto. Public
fixtures leave an interior white margin; independent Pillow native centerlines
must match every preview pixel without calling a production geometry helper.
The regression suite separately checks the actual executor boundary.

Complete outputs are compared except the pre-existing, explicitly listed
planning-clock telemetry paths. No geometry, score, estimate, budget, safety,
component-statistics or quality fields are excluded.

The nine measured workloads cover small and fragmented calibrated
schedulers, a large geometry-only scheduler, three fragmented public Pixel
plans, RGBA, a flat component control and public dot mode. The public benchmark
checkerboards have a four-pixel white border for their independent native
raster checks; they are distinct from the initial edge-to-edge before-probe
workloads above.

The final run used six balanced AB/BA pairs, with one warm pair and a separate
traced-allocation probe per side.
Source/image construction happens outside the timer. The whole public
`make_plan` or whole scheduler call is timed, with no cached plan. Full-output
comparison, independent raster checks, work-counter instrumentation and owned
image cleanup are outside the timer and tracer. Both worker estimates and all
ordinary planning stages remain included in public-call timing.

Traced allocations include the returned result but exclude already prepared
borrowed input images/components. They are Python/NumPy allocation evidence,
not total process RSS or all Pillow/native memory. External active allocation
tracing is rejected instead of being taken over. The final run requires the
same before/after hashes for all root Python files.

## Final measurements on the frozen batch24 source

Raw evidence: `v148-batch24-component-queue-benchmarks.json`, SHA-256
`ea40ba06ae9b68d924bdb9d9015ac3a41219001b84dfb18d8ae121e07fc62ef5`.
All **850 root Python source hashes** match before, after and independent
result review. The canonical source-map digest is
`b8b2992bab94fadacd12d84f874dffc6987183b1dcc6f772e28b532ddc3ed1d8`,
using UTF-8 `json.dumps(map, sort_keys=True, separators=(',', ':'))` bytes.

The final run passed **72 complete historical scheduler pairs, 24 complete
public-plan pairs and 24 independent public raster pairs**, plus all warm,
counted, timed and traced comparisons in the nine workloads. The complete
historical-output digest is
`83aa270f67bcde0bcad41bdc8a01e9f904645bd02a593ba8bbcc31b976cfcf36`;
the independent raster digest is
`31a8a6ce70184c23a9e045a91d8bfaa17df2b7c73921bdc8f9d354567ac24cb1`.
Every recorded cost-call count and the actual queue-work counts in the earlier
table match the final run. The source/image inputs remain unchanged.

Elapsed values below are medians of six pairs in milliseconds. Positive
change means longer elapsed time. “Faster pairs” compares each after sample
with its corresponding before sample; it is not a significance test.

| Complete measured operation | Before ms | After ms | Median change | Faster pairs |
| --- | ---: | ---: | ---: | ---: |
| Scheduler, 72 components, calibrated | 9.379 | 8.752 | −6.681% | 5/6 |
| Scheduler, 8,192 components, calibrated | 1,686.172 | 1,681.703 | −0.265% | 4/6 |
| Scheduler, 32,768 components, geometry only | 1,955.209 | 1,923.385 | −1.628% | 4/6 |
| Public Pixel checkerboard 64×64, 1,568 components | 371.807 | 395.884 | +6.476% | 1/6 |
| Public Pixel checkerboard 128×128, 7,200 components | 1,856.979 | 1,874.302 | +0.933% | 2/6 |
| Public Pixel checkerboard 192×192, geometry only, 16,928 components | 2,609.261 | 2,640.414 | +1.194% | 1/6 |
| Public RGBA 96×72, 216 components | 89.277 | 91.548 | +2.544% | 1/6 |
| Public flat 192×128, one component | 68.847 | 66.992 | −2.694% | 4/6 |
| Public dots 128×128, no component scheduler | 441.003 | 443.137 | +0.484% | 3/6 |

Separate traced allocations are bytes, with one complete-build probe per
side. “Retained” is the live traced allocation while the returned result is
still owned. Inputs were prepared before tracing; cleanup and output
verification remain outside it.

| Complete measured operation | Before peak B | After peak B | Before retained B | After retained B |
| --- | ---: | ---: | ---: | ---: |
| Scheduler, 72 components, calibrated | 132,064 | 132,120 | 89,887 | 89,943 |
| Scheduler, 8,192 components, calibrated | 11,168,795 | 11,168,851 | 5,710,627 | 5,710,683 |
| Scheduler, 32,768 components, geometry only | 22,370,164 | 22,370,220 | 22,092,384 | 22,092,440 |
| Public Pixel checkerboard 64×64 | 5,974,001 | 5,971,962 | 3,860,923 | 3,858,812 |
| Public Pixel checkerboard 128×128 | 25,267,612 | 25,266,925 | 12,460,047 | 12,459,714 |
| Public Pixel checkerboard 192×192, geometry only | 58,427,404 | 58,427,418 | 27,557,037 | 27,557,273 |
| Public RGBA 96×72 | 2,408,266 | 2,407,649 | 1,619,375 | 1,618,934 |
| Public flat 192×128 | 3,952,748 | 3,952,287 | 1,058,397 | 1,051,915 |
| Public dots 128×128 | 20,013,712 | 20,013,910 | 8,709,691 | 8,709,858 |

### Interpretation and limits

The demonstrated gain is bounded queue maintenance: the large geometry
scheduler removes **535,599,125 → 1,068,569** actual list-pop reference shifts,
and the 192×192 public caller removes **142,822,158 → 751,362**. This counter
excludes the new linear in-place reverse and window append operations; elapsed
measurements include both. Candidate comparisons, cost-model calls and emitted
paths are unchanged.

There is **no general complete-planner speedup** in these measurements. All
three fragmented public checkerboards and the RGBA workload have longer
medians; checkerboard 64×64 is slower in five of six pairs. For that case the
ranges are 363.757–379.494 ms before and 372.437–462.114 ms after. The 32,768-item
helper has a 1.628% shorter median, but its ranges also overlap:
1,909.185–1,971.938 ms before and 1,837.242–2,078.813 ms after. Even the 72-item
control, whose list-pop shift count is unchanged, has a lower median, so that
timing difference cannot be attributed to eliminating future-tail shifts.
The unchanged dot path shows +0.484% and three faster pairs out of six.

Python candidate pricing and the other complete planning stages remain, while
maintaining the extra bounded window adds work. The observed slower public
results are retained rather than discarded or remeasured for a positive
headline. Six pairs are a limited sample and do not establish a universal
latency effect.

There is **no meaningful traced peak-memory reduction** established here. The
helpers are 56 bytes higher in both peak and retained counts; public peak
changes range from −2,039 to +198 bytes at multi-megabyte scales. Retained
public counts also vary, including −6,482 bytes for the flat control, which is
not evidence of a general allocation benefit. These are Python/NumPy traced
observations, not total RSS, native Pillow allocation or real mouse/GPU drawing
measurements.
