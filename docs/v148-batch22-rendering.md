# v1.0.148 batch22 — preserve correct detail during Pixel corrections

Initial reproduction: published commit
`ec22fd8739573adc2df1b3e33dbe1a98a09b9c99`.
Final paired baseline: `be30fa54a0c58a8d2b6535d31cb6672727f4e6cc`.
This ledger records **one** behavior group, **R2201**. The interval solver,
acceptance gate, bounded retry, diagnostics and regression evidence belong to
the same correction-quality contract. Tests, measurements and documentation
do not add improvement IDs. The version and release status are unchanged.

## Reproduced defect

`PixelAccuracyEngine.refine_with_corrections` previously accepted a correction
pass when its aggregate pixel accuracy improved, or when accuracy did not
decrease and the error count fell. That can erase a small correct feature:
repainting several surrounding pixels compensates numerically for losing the
feature. A second pass may then refuse to restore it because the available
brush also repaints its surroundings.

The smallest reproduction runs the actual numeric
`PixelMap → build_pixel_stroke_plan → assign_adaptive_brushes → refine_with_corrections`
flow. A 7×7 colored region has a single protected dark center and an available
3 px brush. The initial component plan scores **83.6735%** overall with the
center correct. The old accepted correction scores **97.9592%** overall but
erases the center, reducing protected accuracy from **100% to 0%**. The next
pass cannot improve the global score by restoring it.

The public-caller reproduction reads the existing tracked
`golden-regression/small-detail-preservation.png`, crops its existing eye at
`(155, 102, 174, 121)`, and lets ordinary `make_plan` prepare a 100×100 Pixel
Accurate plan. No new image asset is generated. Both the source simulation and
the real executor's recorded native mouse actions reproduce the loss:

| Available brush | Initial overall accuracy | Old final overall accuracy | Old final protected accuracy | Previously correct protected pixels erased |
| --- | ---: | ---: | ---: | ---: |
| 3 px | 83.72% | 86.20% | 51.3238% | 784 |
| 4 px | 75.43% | 85.67% | 50.2546% | 667 |

Initial protected accuracy is 56.2118% and 43.5845%, respectively. The 4 px
case shows why comparing only aggregate protected accuracy is insufficient:
that metric rises while 667 previously correct protected pixels are lost.

The first three new regression methods were run before the implementation.
All reproduced the intended defect: the numeric component and missing-region
cases each lost the center, and the public native-action cases lost exactly
784 and 667 protected pixels. There were four failing assertions across three
test methods, with no test setup errors.

## R2201 implementation

The original correction proposal and its original simulation remain the first
candidate. A tiled comparison then counts **individual previously correct
drawable protected pixels that would become wrong**. Proposals with no such
loss retain the existing path order, score arithmetic, efficiency decision and
simulation route. Initially incorrect protected pixels remain eligible for
repair. Unprotected pixels do not introduce an additional quality category.

When a proposal loses protected pixels, one conservative alternative is tried:

1. Keep the original correction priority and the actual available brush width.
2. For each horizontal correction run, find the source centers whose complete
   square brush footprint avoids already correct protected pixels of another
   color. Same-color overpainting remains allowed.
3. Remove unsafe centers and split a run only where the forbidden interval
   requires it. Adjacent safe intervals across tile boundaries rejoin.
4. Apply the remaining path budget to those complete safe paths.
5. Release the rejected candidate raster, simulate the safe alternative from
   the unchanged accepted state, and check individual protected pixels again.
6. Accept only when both the original global-improvement rule and the new
   protected-pixel rule pass. Otherwise retain the previous accepted sequence
   and simulation.

For a brush with `before = (width−1)//2` and `after = width//2`, a protected
pixel at horizontal coordinate `p` forbids correction centers
`p−after .. p+before` when its correct color differs from the correction.
Difference arrays combine those intervals. This preserves the existing odd
and even brush convention, including the asymmetric footprint of even widths.
Clipping uses the actual canvas dimensions.

The comparison and source-footprint checks use tiles of at most **64×4,096
pixels**. A center block has at most **4,096 centers** and a **4,097-element
int64 difference array**. No full-canvas erosion mask per color, unverified
smaller brush, diagonal connector, persistent cache or executable background
sentinel is introduced. The retry may require a second simulation for a pass;
that is a deliberate quality cost, not a speed optimization.

Stop is checked before and within the tiled work and before result return.
The span generator is explicitly closed even when the path budget ends its
iteration early. Borrowed PixelMap arrays and the caller's sequence are not
modified; the returned accepted sequence changes only after the simulation
and acceptance gates complete. Errors and cancellation propagate through the
ordinary planning contract.

If the additional protected-pixel comparison, safe-span filtering or safe
retry simulation raises `MemoryError`, this optional correction stops and
returns the **same accepted simulation and complete sequence**. It cannot
publish an unchecked proposal or discard a usable plan. The failed candidate
and temporary retry data are released; diagnostics record the allocation
stage and `MemoryError` stop reason. Cancellation and unrelated failures still
propagate. This is part of R2201's stability contract, not another improvement
ID or a change to the pre-existing first-candidate simulation/error contract.

Each attempted pass additionally reports:

- the original proposal's path count;
- the original proposal's lost protected-pixel count;
- the final candidate's lost protected-pixel count;
- the safe retry path count, or `null` when no retry was necessary;
- a specific rejection reason when no safe correction is available;
- the resource-stop stage when a new optional allocation fails, with an
  unknown original loss count represented as `null` if comparison could not
  finish.

The pixel score still describes planned source-coordinate strokes before
CanvasGuard/runtime delivery. This patch does not broaden that score's scope.
The public regression separately verifies preserved details after the actual
native-boundary executor and its existing guard decisions.

## Verified quality outcomes

The existing public asset crop produces these final results:

| Available brush | Old → new overall accuracy | Old → new protected accuracy | Old → new lost protected pixels | Old → new accepted correction paths |
| --- | ---: | ---: | ---: | ---: |
| 1 px control | 100 → 100% | 100 → 100% | 0 → 0 | 0 → 0 |
| 3 px | 86.20 → **86.56%** | 51.3238 → **57.0265%** | 784 → **0** | 858 → 312 |
| 4 px | 85.67 → **90.19%** | 50.2546 → **72.9124%** | 667 → **0** | 870 → 524 |

The 7×7 unavailable-width case keeps the original 83.6735% plan and its correct
center because none of the proposed neighboring repairs can preserve it with
the 3 px brush. The separate incomplete 13×9 case accepts safe remote repairs
while retaining that center. Therefore the implementation does not simply
reject every correction that encounters a protected feature.

These results do not promise perfect fidelity or a better global score than
every unconstrained correction on every image. The new requirement preserves
already correct protected details; a safe alternative can legitimately retain
more ordinary errors than a proposal that erases such a detail.

## Regression and independent review

`test_v148_rendering_batch22_detail_corrections.py` contains ten methods:

- actual component-planner behavior with a fixed physical brush;
- useful safe repairs, read-only PixelMap arrays and caller-sequence ownership;
- unprotected and initially incorrect protected pixels, with both 1 px and
  wider valid repair brushes;
- remaining path budgets of 1, 3, 8 and 20;
- a literal square-stamp oracle across six widths (1, 2, 3, 4, 17 and 20,000),
  thin/ordinary canvases, numeric protected masks, skipped pixels and edges;
- an 8,207-column run crossing the 4,096-center boundaries, exact even-brush
  forbidden intervals and cancellation;
- Stop during the real retry, unchanged caller data, and successful later work;
- actual `make_plan → execute_plan` native-action preservation on the existing
  tracked asset for 3 px and 4 px brushes;
- a protected-comparison allocation failure returning the exact prior
  meaningful component plan, unchanged metrics and ink, with the rejected
  candidate released; `InterruptedError` and unrelated `ValueError` still
  propagate;
- actual safe-span workspace and retry-score allocation failures preserving
  the same incomplete accepted plan, score, sequence and hit counts, with
  stage diagnostics and no retained rejected/partial raster.

Before integrating the concurrent checkpoint, the focused rendering and
adjacent suite passed **42 tests in 2.727 seconds**, without skips. Its command
with the now-renamed test module is:

```text
.venv/bin/python -m unittest test_v148_rendering_batch22_detail_corrections \
  test_pixel_accuracy_engine_v1088 test_rc10_pixel_accuracy_2 \
  test_v148_colour_batch05_accuracy test_v148_accuracy_batch12_context -q
```

After integrating `92d5a867`, the ten new methods were rerun and passed in
**1.238 seconds**, without skips:

```text
.venv/bin/python -m unittest test_v148_rendering_batch22_detail_corrections -q
```

After the subsequent `be30fa54` integration, a targeted review reran the
public detail method with a private `ProfileStorage.data_dir` observation
boundary. All four actual executor calls retained the existing generic
profile and palette selectors; real `ColorCache.load_cache` and
`ColorCache.put_verified` were called **zero times**. The method passed, the
private directory stayed empty, and the real Paint cache remained absent
before and after. The new detail test was therefore not the runtime-cache
writer and needed no additional storage patch. The concurrent checkpoint's
isolation of two existing Paint recovery tests is retained separately.

The root review found no blocker and independently checked 72 numerical cases
with protected/skipped pixels, source widths of 4,105 and 8,201, and six brush
widths. The platform agent independently checked another 120 seeded numerical
cases with omitted/inherited/explicit brush settings, correction widths 1–5
and path limits. Those preserve initially correct protected pixels and give
identical complete sequences, simulated indices and hit counts between CPU
incremental evaluation and Auto dispatch falling back to CPU. No physical CUDA
test is claimed. The combined full-suite/Windows gates are recorded separately
by the batch coordinator.

## Planning-cost measurements

The final command for this source snapshot was:

```text
.venv/bin/python benchmark_v148_rendering_batch22.py --repeats 6
```

The script loads the **complete historical `PixelAccuracyEngine` module** from
`be30fa54a0c58a8d2b6535d31cb6672727f4e6cc` into the same current public caller. Other current
dependencies are shared. It uses one warm call per variant, six balanced
AB/BA pairs per workload, and separate tracemalloc observations after garbage
collection. Every invocation checks its variant's complete selected-output
fingerprint. The harmed cases intentionally change output; the one-pixel
control retains full cross-version output parity.

The compared fields include source/fitted geometry, colors, source/execution
groups, sequence, every UI preview, counts, path statistics, estimate, Pixel
Accuracy metadata and operation-cost metadata. Only volatile profiler
durations are excluded. Timing includes public planning, fingerprinting and
owned-image cleanup. Quality observations run outside the timers.

| Public workload | Before median ms | After median ms | Elapsed change | Before traced peak bytes | After traced peak bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixed 1 px, unchanged control | 208.347 | 213.779 | **+2.607%** | 4,592,452 | 4,592,472 |
| Fixed 3 px, detail-preserving retry | 284.787 | 303.394 | **+6.534%** | 4,592,234 | 4,592,253 |
| Fixed 4 px, detail-preserving retry | 285.820 | 316.021 | **+10.566%** | 4,615,269 | 4,592,324 |

There is **no speedup claim**. The 3 px and 4 px quality repairs cost about
18.6 ms and 30.2 ms at the observed medians. The unchanged 1 px control also
has a 5.4 ms higher observed median despite requiring no correction pass;
these complete-call measurements include ordinary timing variation and do not
isolate the new filter's cost. Traced peaks are effectively unchanged at this
scale. They cover Python/NumPy allocations, not process RSS or most native
Pillow memory. These are CPU planning measurements, not native mouse execution
or physical GPU timings.

Raw report: `v148-batch22-rendering-quality.json`, SHA-256
`7638352c26455ba4c5b8086a6d2469ef1add5ecfcd6166915d04919b209933f7`.
All **836 root Python files** remained unchanged during the accepted run. The
sorted-key JSON source-manifest SHA-256 is
`d6573202a7602865784e94f495a0931c1280f9a270bd3e9317eb1d72245cd2e2`.
The report binds the combined final source snapshot, including the platform
ownership/allocation completions and concurrent checkpoint integration. Both
variants use those same current dependencies. Their separate behavior checks
are recorded in the platform ledger and coordinator's integration evidence.

## Deduplication

Earlier Pixel changes established accurate brush simulation, shared scoring
inputs, valid background sentinels, cancellation and physical-width retention.
R2201 changes the **acceptance contract**: an aggregate improvement may no
longer erase previously correct protected pixels. Its safe alternative keeps
the established brush, simulator, score arithmetic and budget constraints.
The change is counted once, including all associated paths and diagnostics.

Integration note: this batch was rebased onto concurrent checkpoint
`92d5a86709a61802821780f5866409da6cd8cf2e` (823 improvements).
The later `be30fa54a0c58a8d2b6535d31cb6672727f4e6cc` checkpoint added the
fixture-byte policy and existing Paint-test storage isolation without changing
product code or the improvement count. The initial reproductions above used
`ec22fd8`; the final paired measurements use the fully integrated source as
recorded above. Earlier local timing runs were superseded by this final
frozen-source measurement.
