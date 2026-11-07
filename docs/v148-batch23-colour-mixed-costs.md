# Batch 23 — bounded mixed-colour scoring

## C2301 — one distance for each identical mixture in a colour search

Status: verified and registered single behaviour group, **C2301 / global 827**.
Independent source and raw-result reviews are closed. The final historical baseline is
`5c32b6883c454268e06e199a8f15264ca9ec26e9`, which includes the concurrently
published batch22. Its complete `AdvancedColor.py` is byte-identical to the
original `92d5a86709a61802821780f5866409da6cd8cf2e` baseline. The original
local work and its focused evidence were prepared on `be30fa5`, then preserved
in a separate worktree and transferred without changing product/test bytes.
The benchmark was renamed to batch23 and now loads its old module from `5c32`.
All final integration and measurement results below must use the combined tree.

### Actual repeated work

The real layered-colour builder and public `DrawBot.make_plan` repeatedly score
the same final mixed RGB when different ordered palette pairs or ratios produce
identical rounded channel values. The selected primary, secondary and Bayer
ratio must still come from the original ordered search: swapping their roles
would change the actual emitted pixels even when the average RGB is identical.

An actual 48 × 32 source with eight colour blocks and 18 calibrated palette
swatches provides the following work-count evidence. Both the direct builder
and the complete public plan have these counts:

| Layer policy | Distance calls before | After | Mixtures enumerated, both sides | Final paths, both sides | Layered pixels, both sides |
| --- | ---: | ---: | ---: | ---: | ---: |
| Light shading | 1,352 | 1,352 | 1,056 | 832 | 384 |
| Dual-colour mix | 5,192 | 3,952 | 4,896 | 1,184 | 576 |
| Full colour mix | 10,088 | 6,392 | 9,792 | 1,168 | 564 |

The new work-count regression, routed through the complete historical module,
fails in all four Dual/Full builder/public-plan subcases. Light shading remains
an unchanged-work control; a local table can add overhead in that case.

### Implementation and bounds

`AdvancedColor._best_layer_cached` retains one local dictionary from the
**actually calculated mixed RGB tuple** to its unchanged distance. Source RGB,
metric and fidelity are constant throughout that individual search. No
algebraic equivalence is assumed for reverse `.35`/`.65` pairs: only the exact
rounded tuple can share a score.

Every ordered pair and ratio is still visited, and the strict `<` winner rule,
candidate ranking, improvement thresholds, returned colour identities and
Bayer placement remain unchanged. The existing 26-candidate and four-ratio
limits bound the local table to at most 2,600 entries. `finally` clears it on
normal return and exceptions, including retained Stop/error tracebacks.
Concurrent public requests use separate local tables. The existing scalar
winner LRUs retain their original keys, capacity and freshness behaviour.
Off, RGB-nearest and one-swatch paths return before allocating a score table.

This is one new search-work group. Earlier CG34 concerns adaptive colour-count
trials; PB02 owns single-colour raster assignment; R1701 owns diagnostic
sampling of emitted Bayer pixels; R1801 owns worker payload lifetime. None of
those changes removed this duplicate mixture scoring. Test, benchmark and
documentation additions do not receive separate improvement IDs. Concurrent
N2201 concerns native Paint spectrum coordinates; this group concerns the
layered source-colour builder and is independent of that search.

### Correctness and independent review

The six new regression methods cover actual builder/public-call work counts,
duplicate swatches and exact midpoint ties, independently rasterized Bayer
ownership and complete colour diagnostics, real thread/process workers,
retained failures, concurrent table ownership, nonlayered controls and fresh
palette changes. On the original local snapshot, the root run passed **6/6 in 1.252 seconds**;
the independent reviewer's run passed **6/6 in 1.187 seconds**, with no blocker.
The product and six-method test file are byte-identical after integration; the
combined discovery and final benchmark are separate gates.

The historical parity matrix loads the **complete old AdvancedColor module**
from the recorded revision, not a reconstructed scoring loop. It checks 552
public colour queries across calibrated/default/custom palettes, duplicates,
30-swatch ranking, all fidelity/workflow/layer choices and controls, plus 30
complete builder/public-plan pairs. The latter cover dots/lines, opaque and
partial/zero-alpha pixels, layer choices, nonlayered output and full preview.
The exploratory **582/582 exact** result has digest
`80015232903bb95334c911aafc1aa7f4a3f304be4d3395bb0f92989ee6aee8fb`.

An initial exploratory fixture tried to load an empty calibration; the actual
loader correctly rejected it. The accepted-calibration matrix uses one-swatch
and ordinary palettes. A separate exploratory public-plan comparison rejected
changing live free-RAM metadata. The final fixture supplies the same explicit
resolved resource allocation that the controller normally passes: one worker,
Threads, 512 MiB planning budget, four logical CPUs and 8,192 MiB available RAM.
All resulting resource/scheduler fields remain in the comparisons. No budget,
estimate or colour evidence was excluded to force parity.

### Final timing and allocation evidence

Final integrated measurements are recorded in
[v148-batch23-colour-mixed-benchmarks.json](v148-batch23-colour-mixed-benchmarks.json).
Earlier pre-integration timings are not used for these results. Reproduce with
`benchmark_v148_colour_batch23_mixed_costs.py --output <report.json>`.

Both sides bind the complete selected module through `sys.modules` and
DrawBot's imported builder alias. They share the same current dependencies.
After a complete warm/counting call, cold workloads clear the layer/nearest
LRUs before each of six balanced AB/BA pairs. The explicitly warm-layer-cache
control retains those LRUs. Shared colour-space caches are warmed for both.

Timing includes the actual builder or public-planner invocation and construction
of its small fixed fixture settings. Module binding, cache preparation, garbage
collection, complete result comparison and image cleanup are outside the timer.
Only the already documented seven elapsed-profiler/derived-clock fields are
excluded from public-plan comparisons. Separate owned `tracemalloc` calls
include the retained result and existing scalar winner caches; they do not
measure process RSS, most native Pillow memory, GPU or physical drawing speed.
The bounded new score table can raise peak Python allocation, so a reduction in
distance evaluations does not establish a memory-saving claim.

### Integrated results and tradeoffs

The six paired samples retain the complete actual outputs; no samples were
removed. Three pairs use before/after order and three after/before order.
Negative elapsed changes mean a shorter median in these fixtures.

| Actual workload | Before median, ms | After median, ms | Change | Shorter pairs |
| --- | ---: | ---: | ---: | ---: |
| Builder, Light | 23.787 | 23.881 | +0.395% | 3/6 |
| Builder, Dual | 54.350 | 48.145 | -11.417% | 5/6 |
| Builder, Full | 95.661 | 72.771 | -23.928% | 6/6 |
| Builder, RGBA Full | 135.964 | 103.651 | -23.766% | 6/6 |
| Public plan, Light | 67.929 | 68.084 | +0.227% | 2/6 |
| Public plan, Dual | 97.668 | 91.674 | -6.138% | 5/6 |
| Public plan, Full | 153.595 | 128.456 | -16.367% | 6/6 |
| Public plan, RGBA Full | 258.702 | 235.901 | -8.813% | 5/6 |
| Public plan, warm Full cache | 56.265 | 57.104 | +1.492% | 2/6 |
| Public plan, layers Off | 37.681 | 37.328 | -0.937% | 3/6 |

Python traced allocation is measured in separate calls, with the returned
result still retained. These exact byte observations include existing caches
and do not establish total-process memory or native Pillow allocation.

| Actual workload | Peak before → after, B | Retained with result before → after, B |
| --- | ---: | ---: |
| Builder, Light | 222,800 → 224,232 | 211,535 → 212,967 |
| Builder, Dual | 252,904 → 253,992 | 239,815 → 240,903 |
| Builder, Full | 251,144 → 307,912 | 238,151 → 239,399 |
| Builder, RGBA Full | 504,432 → 505,680 | 479,367 → 480,615 |
| Public plan, Light | 1,343,566 → 1,337,052 | 1,212,622 → 1,206,043 |
| Public plan, Dual | 1,414,721 → 1,415,891 | 1,283,497 → 1,284,593 |
| Public plan, Full | 1,419,353 → 1,419,346 | 1,288,129 → 1,288,122 |
| Public plan, RGBA Full | 2,169,820 → 2,170,087 | 1,932,780 → 1,932,835 |
| Public plan, warm Full cache | 1,414,968 → 1,414,595 | 1,283,744 → 1,283,230 |
| Public plan, layers Off | 1,155,356 → 1,155,429 | 1,034,188 → 1,034,217 |

The intended cold Dual/Full work reduction is visible in both actual APIs.
The Light control has no fewer distance evaluations and is slightly slower in
both median observations. The already warm layer-cache control is also slower;
its existing cache avoids the changed search in timed calls. Its published
`cold_work_counts` are from the separate cold counting preflight, not a count of
that warm timed passage. Layers Off performs no mixture searches; its small
median difference and three shorter pairs are an unchanged-work control.

The Full builder's traced peak **increases by 56,768 B**. The bounded table is
cleared before return, but its transient peak and dictionary work remain real
costs. The direct builder and complete plan have different dominant allocations;
one workload's near-unchanged peak does not invalidate the builder's measured
increase. There is no general memory-saving or uniformly faster-application
claim. All individual paired samples, including slower pairs, remain in the
raw report.

The independently checked final matrix retains **582 exact cases**, including
30 complete builder/public plans, and all ten measured outputs are exact.
Both sides share **841 unchanged root Python hashes**, also matching the full
integration's source manifest. The complete source suite finished **4,270 tests
in 206.108 seconds: 4,211 passed and 59 platform/hardware cases skipped**, with
all 891 selected source/configuration hashes unchanged. The 5,000-cycle source
gate, package hygiene and eight existing-raster geometry fixtures passed.
The new published commit still requires its own Windows/package gate.

Final historical-parity digest: `e3a2be0a4bad02b2c6bd829454dbe843f553c7aa97202aa2c8b84f46b8233b91`.

Raw report SHA-256: `070e810ac5462a2b71bccb97b918f097ee5a1ceba3cfa77e73d27cbfe8650dab`.
