# v1.0.148 rendering — batch 18

Baseline: `d7721a36975a36137b583beda9ff3c47c05208fd` (the published
batch17 checkpoint). This ledger proposes two distinct work reductions,
**R1801** and **R1802**. It does not change the release version, completion
register or the meaning of existing quality/safety gates.

## R1801 — export palette-reader rows as the bounded scheduler requests them

The actual basic and advanced palette builders made a private fullsize RGBA
copy even for an already decoded RGBA input. The basic parallel helper made
another identical copy. Both helpers then exported the whole image to a
`bytes` object and built every chunk's independent byte slice before calling
the already bounded `ResourceAllocation.parallel_map` scheduler. The scheduler
could limit pending submissions, but these producer allocations already existed.

The baseline observation at real dispatch retained **401,408 bytes** of full
raw data plus eager task payloads for a 256×196 input, in each builder. Real
public High and Ultra plans retained **1,228,800** and **3,038,120 bytes** at
that same dispatch boundary. These are separate producer allocations, before
the executor consumes its first task. They exclude the PIL image itself,
future objects, returned geometry and worker-local allocation.

`PlanningRowTasks.RgbaRowTasks` is a repeatable sequence that exports one
requested row range into ordinary independent bytes. It closes the temporary
crop before submission. The existing scheduler alone chooses how many tasks
are outstanding, and worker arguments remain pickleable for ProcessPool.
Workers receive bytes and never read the producer's image. No persistent or
cross-plan cache is introduced.

`read_only_rgba` borrows an RGBA reader and owns conversions of other supported
input modes. The builder closes only its conversion, including worker failure,
serial fallback and cancellation with a retained exception traceback. Palette
choices, alpha arithmetic, Bayer coordinates, run formation, resource policy,
ordered chunk merging and metadata remain unchanged.

### Actual caller and cancellation evidence

The first six methods in `test_v148_rendering_batch18_row_payloads.py` produced
12 failing baseline subcases, with no fixture errors. Its existing positive
serial/real-ThreadPool/real-ProcessPool output control passed before the change.
The failures were the redundant RGBA copies, eager raw/task retention in both
direct and public High/Ultra callers, and unclosed owned conversions retained
by worker-failure/Stop tracebacks.

The completed eight-method module additionally blocks actual ThreadPool
workers. With two workers the producer exports four crops, matching the
existing `workers * 2` submission bound, while later image rows remain
unexported. Stop cancels that operation without returning partial groups. The
test checks that submitted crops are closed and that the borrowed input stays
open and byte-identical. An actual row-export failure also closes its crop
before the unchanged serial fallback returns matching groups.

Basic and advanced outputs agree exactly across serial, Threads and Processes;
advanced backend/chunk labels deliberately describe the chosen backend, while
all other metadata matches. The historical module comparison separately checks
complete old/new metadata without backend exclusions for matching backends.

### Deduplication

- CG07 fixed mode compatibility; RGB, grayscale, alpha and palette inputs still
  normalize to the same pixels here.
- SS24 bounded row dimensions. The same row-range calculation remains in use.
- SS25 bounded executor submissions. This change removes the separate eager
  producer materialization that happened before that scheduler was called.
- R1502 removed copies in `prepare_image`. These builders consume the prepared
  image later in the public planning pipeline and independently copied/exported
  it again.

There is one counted producer-work group for both builders. Conversion cleanup,
fallback, cancellation and the helper API are supporting parts of that group.

## R1802 — reuse the identical first-brush search inside one component

Every candidate ladder starts with the largest fitting verified brush and the
same empty painted mask. Both complete-packing policies therefore score the
same target and residual for that first brush. Their only local-selection
difference is the gain floor applied after layout scoring. The baseline
repeated erosion, safe-centre calculation, candidate rasterization, path
construction and local cost scoring eight times for that identical search in
both established R1101 public fixtures.

One private cache now retains a single useful-centre mask and immutable scalar
layout scores while that component's ladders/policies compete. It stores no
candidate trial rasters or path lists. Every policy still applies its original
gain floor and complete tie key and reconstructs its winning geometry. Later
brushes have changed residuals and perform their own searches. Every completed
pack still receives its original complete execution-cost comparison.

The cache is component-local, identity/context-qualified, limited to one entry
and cleared in `finally`, including Stop. The first residual can borrow the
unchanged target instead of allocating `target & ~empty`. This saves work at
the cost of retaining one Boolean useful-centre mask between candidate ladders;
the final measured allocation tradeoff is reported below.

The public component chooser already knows the drawable-pixel total. It now
passes that scalar into brush packing instead of re-creating and scanning the
whole canvas's `component_map >= 0` for each component. Direct callers that do
not provide the scalar retain the original count calculation.

### Geometry, complete policy and resource evidence

`test_v148_rendering_batch18_pack_scores.py` initially produced four failing
subcases in three methods, with no fixture errors: the repeated initial search
in the direct caller and both actual public plans, plus the unnecessary full
canvas count. Independent native-action raster assertions passed before the
optimization and remain unchanged.

The completed five-method module also covers an empty first-brush search that
must still permit narrower exact repair, and verifies that the cache retains
only one mask plus scalar rows and releases them on success and Stop with a
retained exception traceback. The read-only input labels remain unchanged.

The previous batch10 scalar footprint oracle accepts the new private cache
keyword but intentionally ignores it, recomputing every candidate independently.
All its geometry, bitmap, cost, memory-bound and Stop assertions remain intact.
The previous batch11 complete-policy tests retain all cost/selection/inequality/
tie/native-raster assertions. The two R1101 counterexamples still choose their
respective cheaper original/maximum-gain complete policies.

### Deduplication and historical benchmark compatibility

R1002 bounded the lifetime of alternatives within one search. R1101 compared
two complete-packing policies. R1403 prepared immutable first-path costs for a
different component-ordering scheduler. This group removes identical repeated
geometry searches across regional brush ladders/policies; it preserves all
three existing contracts. The scalar drawable-count handoff belongs to this
same component-packing optimization and receives no separate ID.

The older `benchmark_v148_rendering_batch11.py` substitutes only a historical
packing function into current globals. Its old function cannot accept the new
scalar handoff, and comparing that hybrid would change its documented isolation
contract. It now stops before timing/output with a clear compatibility message,
matching the established batch10 benchmark policy. The original raw evidence
and published checkpoints are unchanged. Batch18 loads whole historical
modules instead.

## Verification and independent review

The combined focused command passed **23 tests in 5.266 seconds**:

```text
.venv/bin/python -m unittest test_v148_rendering_batch18_row_payloads \
  test_v148_rendering_batch18_pack_scores \
  test_v148_rendering_batch10_candidates \
  test_v148_rendering_batch11_pack_choice -q
```

`benchmark_v148_rendering_batch18.py --verify-only` subsequently passed:

- 288 complete serial reader pairs across independent seeds, thin/ordinary
  sizes, RGBA/RGB/L/LA/P/premultiplied modes, lines/points and white skipping;
- nine larger serial/real-ThreadPool pairs, including layered and nonlayered
  color modes;
- 24 complete brush-pack pairs with rectangles, holes, ragged boundaries,
  calibrated delays and unit/scaled native projection;
- all eight workload pairs, including six complete public plans. Both regional
  plans also pass the unchanged independent literal-rectangle native-action
  replay oracle.

All complete return fields are compared. Only the explicitly listed profiling
durations and profiling phase label are omitted from public plan comparison;
quality, palette, raster images, paths, costs, choices and other metadata remain
in the fingerprints. The 321 historical helper-pair digest is
`555926c1571fe9c6ebb0156e41194584fc73aaa91cc257307d9a4384f6493757`.

The root coordinator independently reviewed the three product diffs and
`PlanningRowTasks.py`, including borrowed/owned image boundaries, bounded task
submission, first-residual cache scope and unchanged independent policy oracles.
Source review is closed without a blocker. The repository-wide integration
gate is coordinated separately after the final measurement window.

## Final measurement protocol

The final command is:

```text
.venv/bin/python benchmark_v148_rendering_batch18.py --repeats 6
```

The script records complete historical module hashes and every root Python
source hash before/after. Each workload has one warm pair, six balanced AB/BA
timing pairs and separate tracemalloc probes after collection. Complete-output
fingerprinting and owned-image cleanup are included identically on both sides.
Work observations and native-action replay are separate untimed calls.

This measures CPU planning. Tracemalloc covers Python/NumPy allocation, not
process RSS, most Pillow pixel-core memory or child-process heaps. Nominal
fullsize copies and resident producer payloads are reported as separate
observations. It is not a physical drawing, UI, GPU or universal speed claim.

### Final frozen-source measurements

The final run completed all eight workloads after the RD01 GPU-policy and
Mobile Preview completions, in the coordinated quiet CPU window. All six AB/BA pairs, warm calls, allocation
calls and separate work observations preserve the complete compared outputs.
The native-action oracles pass on both historical and current regional plans.
All **799 root Python files** were unchanged during the run.

Raw data: `docs/v148-batch18-rendering-benchmarks.json`.
SHA-256: `5f41ce551b7dd29168e66ed94523a876b0867728543c8e8c3ed55f6e493e4e00`.
The recorded root-source map's SHA-256, using sorted-key JSON, is
`fc8f94513956845287182452c91a59282917830b6ec7e8bb03836d563db799d4`.

| Workload | Before median, ms | After median, ms | After versus before |
|---|---:|---:|---:|
| Basic reader, 768×512, four Threads workers | 331.248 | 337.517 | +1.9% |
| Basic full `make_plan`, High | 313.109 | 304.332 | −2.8% |
| Basic full `make_plan`, Ultra | 745.029 | 718.715 | −3.5% |
| Advanced layered reader, 768×512, four Threads workers | 1,058.196 | 1,045.003 | −1.2% |
| Advanced full `make_plan`, High | 578.743 | 517.347 | −10.6% |
| Advanced full `make_plan`, Ultra | 1,054.006 | 1,045.288 | −0.8% |
| Regional full `make_plan`, cheaper complete alternative | 210.153 | 158.567 | −24.5% |
| Regional full `make_plan`, cheaper original policy | 198.175 | 138.246 | −30.2% |

These are fixture medians, not a statistical claim about every input. R1801
is justified by the removed image copies and eager producer payloads, with
mixed timing results. In particular the basic reader was 1.9% slower in
this run; the change makes no general color-planning speed promise. R1802
reduces total public planning time in both existing policy counterexamples,
while retaining their exact geometry and policy decisions.

| Workload | Before traced peak, bytes | After traced peak, bytes |
|---|---:|---:|
| Basic reader, 768×512, four Threads workers | 4,146,495 | 2,081,234 |
| Basic full `make_plan`, High | 32,180,942 | 32,180,282 |
| Basic full `make_plan`, Ultra | 33,864,278 | 33,863,410 |
| Advanced layered reader, 768×512, four Threads workers | 41,944,480 | 41,944,844 |
| Advanced full `make_plan`, High | 33,853,350 | 33,853,246 |
| Advanced full `make_plan`, Ultra | 35,663,142 | 35,663,878 |
| Regional full `make_plan`, cheaper complete alternative | 10,663,292 | 10,661,307 |
| Regional full `make_plan`, cheaper original policy | 1,926,470 | 1,930,824 |

The basic reader's traced peak falls **49.8%**. The advanced reader and complete
color plans have later geometry/fingerprinting/diagnostic allocation peaks
that dominate the removed producer buffers; their total measured peaks are
effectively unchanged. This does not imply that the removed buffers still
exist: the separate lifetime observation directly observes their disappearance
at real worker dispatch.

The regional useful-centre cache is a speed/memory tradeoff. The cheaper-original
fixture's total traced peak rises **4,354 bytes (0.23%)**; the other regional
peak is effectively unchanged. No overall memory reduction is claimed for
regional planning.

### Work eliminated at the real boundaries

Both 768×512 readers previously retained **3,145,728 eager payload bytes**
(full raw data plus all task slices) at dispatch; both now retain zero eager
payload bytes at that boundary. The basic reader's two private fullsize RGBA
images and the advanced reader's one are eliminated. Their nominal pixel-core
payloads were respectively **3,145,728** and **1,572,864 bytes**, reported
separately from tracemalloc rather than added to its peaks.

The actual High plans prepare **480×320** pixels and eliminate **1,228,800**
eager payload bytes each. Ultra prepares **755×503** and eliminates
**3,038,120** bytes each. All four retain the same eight chunks and real Threads
backend. Consuming the provider still creates the bounded in-flight row bytes;
zero eager bytes does not mean zero worker memory.

In each regional public plan the initial 16px erosion/search falls from **eight
to one**. Calls for all later 8px/4px/2px brushes remain unchanged. The repeated
whole-canvas drawable scan falls from **one to zero** for the single component
in each fixture. Complete policy counts, costs and output fingerprints remain
identical to the historical module.

The original module hashes are recorded in the JSON. The final raw-data review
recomputed every median from its samples and checked all six balanced orders,
all parity flags, the work counters and the unchanged source manifest. Both
rendering source reviews and this final measurement review are closed. The
coordinator owns the subsequent full-suite and release/checkpoint decisions.
