# Batch 31 — respect the actual Portrait contour budget during selection

## Status and counting scope

**R3101 is registered as global843 after the reviewed final evidence and explicit root decision.** The three focused
regressions and completed integrated evidence are recorded below. Registration
records reviewed local evidence; it does not certify a newly published GitHub
head or claim a general application speedup.

The published baseline is
`e49e2535c5f8edea80e47824fe56cae58781b971`, with 842 registered improvements.
Independent source and counting review distinguishes this contour-prefix
selection from GP14/global566, which changed tonal priority and coverage in
`_select_tone_candidates`, and PB08/global649, which changes later generic
execution-path capping. The common use of a heap does not make those different
ranking stages interchangeable. All budgets, quality modes, ties and controls
here belong to one contour-selection change. Portrait plan ownership and local
image-stream ownership complete older contracts and add zero IDs.

## Actual public before evidence

`DrawBot.make_plan` prepares the grayscale analysis image, generates Portrait
strokes, finishes the plan and, when needed, fits it again to the drawing-time
budget. `_portrait_strokes_impl` already knows its first contour budget, but
previously called `_edge_strokes` without that bound and sliced its full result.
The helper retained each cell's strongest candidate, fully sorted all cell
winners and built a complete stroke list before that suffix was discarded.

The read-only probe used the real public planner on the unchanged published
checkout, with actual private calibration and CPU processing. A profile return
observer read counts from the real helper and caller; it changed no numerical
code and made no timing measurement. All 893 root Python hashes stayed equal to
`0da8de7641efb47fea77c62ece22629b27f9425c137e9d8ccd8d7e9933ae5845`.
No repository writes or network access occurred.

The structured source is RGBA 320×240. Its High likeness analysis image is
**321×241**; **1200×900 is the target drawing area**, not the analysis size.
The 3 s and 30 s settings below are configured drawing budgets, not measured
software runtime or a claim that physical Paint execution was performed.

| Public case | Cell winners fully sorted and returned | First caller contour budget | Reported edge strokes after later time fitting |
| --- | ---: | ---: | ---: |
| High likeness, 3 s | 19,107 | 6 | 3 |
| High likeness, 30 s | 19,107 | 65 | 37 |
| High likeness, Unlimited | 19,107 | 3,690 | 3,690 |
| Flat white, High likeness, 3 s | 0 | 6 | 0 |
| Balanced, Unlimited, target 128×96 | 3,072 | 3,240 | 3,072 |

The complete observation is
`pending-batch31-portrait-edge-budget/before/summary.json`, SHA256
`b39b7b7566041fc1877dc2feaafeff670710e3b204d9c029dd0ccef39a5e101e`.
It includes complete public-plan fingerprints, original input preservation,
metadata, source maps and all five cases. The configured short budgets later
produce nine and 89 execution paths; these are distinct from the helper's first
selection and the plan's `edge_strokes` metadata.

The permanent actual-public-work assertion was also loaded against that frozen
checkout. It failed once for the reproduced full-result-then-discard behavior,
with zero errors or skips. No test of the newly added helper argument was used
to manufacture a before failure. Its log SHA256 is
`d1396e7d1d14cc8244b4c11a67f538f78973fc49099f3841346de227b6f2b1b8`.

## Narrow implementation

The caller now passes its existing `edge_budget` as the helper's keyword-only
`max_strokes`. When that prefix is smaller than one thirty-second of the actual
cell-winner pool, the helper selects it with `heapq.nlargest`. Otherwise it keeps
the original full stable sort and truncates the candidate list before building
the returned strokes. Calling the helper without the new bound still returns
the original complete ranking.

Both routes use the identical pre-existing scores and dictionary iteration
order. A stronger later candidate replaces a cell's value without changing
that cell's first insertion position; ties retain the same stable order.
Sobel processing, pixel scanning, cell selection, geometry, subject weighting,
GPU metadata and existing Stop/PixelAccess cleanup are unchanged.

This change does **not** eliminate the scan or the `occupied` dictionary's
linear storage. A bounded selection only avoids the unnecessary full sort for
small prefixes and avoids building a returned suffix that the actual caller
will discard. Allocation and timing claims require the separate measured
whole-helper and whole-public-call evidence.

## Focused regressions and remaining validation

`test_v148_rendering_batch31_portrait_edges.py` has three methods covering:

- the real public finite-budget caller, with an actual winner pool over 32 times
  the requested prefix and a returned list limited to that prefix;
- exact bounded prefixes of the unchanged full stable helper ranking across
  tied and varied scores, quality/focus settings, zero, small, near-full, full
  and oversized bounds, with unchanged borrowed pixels and acceleration metadata;
- complete public-plan comparison against the original full-result-then-slice
  boundary, including short budgets, a full-budget control, flat input and Dots.

The initial focused run passed all three methods in 2.172 s. Its test file is
byte-identical to the one used for the public before failure, SHA256
`db1b90d50414690e46d72c5d4cb5ed673ccbaff6e3f069d998ac71857b60ad83`.
That initial console result is distinct from the later frozen-source full
suite and complete historical replay.

The completed experiment below compares the whole historical Portrait module
with the new implementation, retaining exact output and metadata comparisons,
balanced before/after sample ordering, separate work and Python allocation
observations, and unchanged-work controls. Full public planning and direct
contour selection remain separate scopes. No RSS, physical GPU, Windows
performance or physical drawing claim follows from portable CPU evidence.

## Complete historical comparison and measured work

The standalone driver loads the complete published `PortraitPlanner.py` from
e49. Before each call it binds both real `DrawBot` Portrait imports and the
`PortraitPlanner` module outside the measurement boundary. Current `DrawBot`,
including this batch's outer plan ownership, and all other recorded
dependencies are shared. This measures the contour change; it does not compare
every historical application module. The separate seven-pair ownership replay
links both complete old `DrawBot` and old `PortraitPlanner` together.

All **three complete preparations**, **39 helper/public parity cases** and
**nine measured workloads** passed. The 39 cases comprise 34 helper cases and
five public plans, including five quality levels, focus settings, genuine
score ties, zero/near-full bounds, flat input and Dots. Complete result values,
image bytes, metadata and borrowed input preservation match. Only the seven
pre-existing profiler-clock paths recorded in the raw report are excluded.

Preparation uses the actual UI-derived options, including `High throughput`
while computing on the CPU. The public calls independently observe their real
preparation arguments and returned grayscale/fitted/metadata and require an
exact match with the borrowed helper input. They reach the actual initial
contour budgets **6 / 65 / 3690** and final execution counts **9 / 89 / 7867**.
These two sets of counts describe different stages.

Separate profile observations of real function returns and native `list.sort`
calls show:

| Prepared-image workload | Occupied cell winners, both versions | Full-sort input before → after | Heap input / final sort after | Helper return before → after |
| --- | ---: | ---: | ---: | ---: |
| Budget 6 | 19,107 | 19,107 → 0 | 19,107 / 6 | 19,107 → 6 |
| Budget 65 | 19,107 | 19,107 → 0 | 19,107 / 65 | 19,107 → 65 |
| Budget 3690 | 19,107 | 19,107 → 19,107 | 0 / 0 | 19,107 → 3,690 |
| Near-full control | 19,107 | 19,107 → 19,107 | 0 / 0 | 19,107 → 19,106 |
| Unbounded helper control | 19,107 | 19,107 → 19,107 | 0 / 0 | 19,107 → 19,107 |
| Flat control | 0 | 0 → 0 | 0 / 0 | 0 → 0 |

The three full public calls reproduce the same corresponding work counts.
No numerical helper, sorter, heap implementation or clock is replaced by the
observer. Work observation, elapsed measurement and allocation observation are
separate executions.

## All elapsed and allocation results

Each workload has one warm before/after pair followed by **six balanced AB/BA
pairs**, with all 54 pairs retained and no sample removal or rerun. Inputs,
options, module binding, collection, output fingerprints and caller-owned
result cleanup are outside the clocks on both sides. The public scope includes
the real `make_plan` preparation, tones, contours, finish/time-fit, diagnostics
and internal cleanup. The helper scope includes all its scoring and scanning,
plus the old caller's discarded-suffix boundary on the before side.

| Workload | Before median, ms | After median, ms | Change | Faster pairs |
| --- | ---: | ---: | ---: | ---: |
| Helper, budget 6 | 191.684 | 186.523 | −2.693% | 5/6 |
| Helper, budget 65 | 187.247 | 184.347 | −1.549% | 5/6 |
| Helper, budget 3690 | 205.855 | 198.767 | −3.443% | 6/6 |
| Helper, near-full control | 192.534 | 190.467 | −1.073% | 4/6 |
| Helper, unbounded control | 189.885 | 191.295 | +0.743% | 1/6 |
| Helper, flat control | 50.238 | 50.818 | +1.155% | 3/6 |
| Whole public plan, 3 s setting | 1205.756 | 1205.331 | −0.035% | 2/6 |
| Whole public plan, 30 s setting | 983.612 | 958.481 | −2.555% | 6/6 |
| Whole public plan, Unlimited setting | 1510.872 | 1484.966 | −1.715% | 5/6 |

The full public 3 s workload is effectively unchanged in this sample and is
slower in four of six pairs. The unchanged-work controls vary in both
directions. Small median differences do not establish a universal speedup.
The 3 s and 30 s labels remain configured drawing budgets, separate from the
software elapsed times above and from any physical drawing session.

Separate `tracemalloc` probes record the following exact byte values. Retained
means the result is still alive, before caller cleanup. Prepared borrowed
images and setup are excluded; native Pillow buffers are not necessarily
traced. These measurements are not process RSS.

| Workload | Peak bytes before → after | Retained bytes before → after |
| --- | ---: | ---: |
| Helper, budget 6 | 5,264,592 → 4,807,300 | 259,784 → 260,184 |
| Helper, budget 65 | 5,264,592 → 4,814,052 | 264,504 → 268,752 |
| Helper, budget 3690 | 5,264,592 → 5,264,592 | 598,344 → 601,816 |
| Helper, near-full control | 5,264,592 → 5,264,592 | 1,883,264 → 1,884,112 |
| Helper, unbounded control | 5,264,592 → 5,264,592 | 1,884,112 → 1,884,112 |
| Helper, flat control | 3,456 → 3,456 | 1,128 → 1,128 |
| Whole public plan, 3 s setting | 87,591,679 → 87,598,150 | 1,219,700 → 1,226,223 |
| Whole public plan, 30 s setting | 87,804,198 → 87,804,065 | 1,333,436 → 1,333,162 |
| Whole public plan, Unlimited setting | 92,149,259 → 92,149,521 | 5,970,284 → 5,970,615 |

The small-prefix helper peaks decrease by **457,292** and **450,540 bytes**;
their retained values increase by 400 and 4,248 bytes. There is no demonstrated
whole-public-call peak-memory reduction: its values are effectively unchanged,
including the 3 s case's 6,471-byte peak and 6,523-byte retained increases.
The full scan and cell-winner dictionary still account for work and storage.

Both the initial verify-only pass and the final measurement keep all **897
root Python files** unchanged, compact SHA256
`325d536b457d8b384a0738efab531ae0f6d773db5fb30fa569e56dbc0d7e329f`.
The verify-only report contains no timing or allocation samples. The complete
output digests legitimately differ between these two invocations because real
private temporary calibration paths are part of the complete comparisons;
every before/after result within each invocation is exact.

The final standalone report is
[v148-batch31-portrait-edge-benchmarks.json](v148-batch31-portrait-edge-benchmarks.json),
512,747 bytes, SHA256
`f0d36d2fd7c3ebbf431cf9f8d23fdba5b1b7a93876dca3a738d22c71d0045a07`.
Its full log has SHA256
`231fdf6780c23431b8ab465d3ef28764e79097d0c28a2ffe0c613ebc55826f46`.
The verify-only report, exit receipts, all preliminary observations and complete
logs are preserved in the common evidence. Integrated full discovery, native
widgets and source/raster/package checks remain separate final gates.


## Integrated frozen-source result

Batch 31 records **843 distinct improvements, 157 remaining**. One contour-prefix work-reduction group is registered as R3101/global843. Local import-stream and outer Portrait-plan ownership complete existing contracts with zero IDs. All 842 preceding registry entries and 80 prior benchmark JSON reports are preserved. Completed frozen discovery ran **4,569 tests in 244.002 seconds: 4,496 passed and 73 skipped**, with all 947 source/configuration hashes unchanged. Fourteen Linux/Xorg native cases, the 5,000-cycle source gate, eight exact existing-raster fixtures and initial package hygiene (1,370 files) passed. The package check after final metadata passed with 1,372 files and no warnings. Seven complete historical Portrait public-plan pairs retain finite time-fitting, actual rescue and borrowed inputs. The contour experiment compares the whole published Portrait module within shared current dependencies: 3 complete preparations, 39 exact helper/public comparisons and 9 workloads with six balanced pairs and separate traced allocations. Scanning and the cell-winner dictionary remain; whole-helper and whole-public-plan observations, slower controls and allocation costs are kept separate. Early source maps, expected red proofs and initial harness diagnostics remain explicit. No universal application speed, RSS, physical drawing or GPU improvement is claimed. Published parent e49 passed seven exact-head checks and all fourteen Windows steps on attempt one; the new head requires its own CI. Version 1.0.148 remains unreleased.

Final gates bind **897 root Python files**, compact SHA256 `325d536b457d8b384a0738efab531ae0f6d773db5fb30fa569e56dbc0d7e329f`, and **947 source/configuration files**, compact SHA256 `1ae580174ddabeb86dc289c6fdfbc17eddcea9085b9c4671ce71ae6b3182501e`. Earlier red and focused checkpoints retain their original maps and labels; no failed harness or expected before failure is presented as a passing integrated gate. The parent Windows run is separate from the new head. Independent metadata review and post-metadata package hygiene are recorded separately in [final validation](v148-batch31-validation.json).
