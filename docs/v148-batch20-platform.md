# Batch 20 — explicit GPU cache maintenance and completed learning resets

Baseline: `47777158e5b1daf759993190e638fe507e7691da`, the published batch19
checkpoint. This ledger proposes **one new behavior group, P2001**, for the
existing **Clear GPU cache** action. The Real-Speed reset work completes
previously counted reset contracts and adds **zero** IDs.

## P2001 — maintain already used resources independently of compute policy

The actual controller previously called `GpuAcceleration.clear_gpu_cache`
synchronously on Tk. That function resolved the currently selected compute
backend before doing maintenance. Two initial actual-controller regressions
failed on the baseline:

1. After CUDA had been used, choosing CPU made Clear leave its unused pool
   blocks behind. The controlled allocator boundary held 3,584 total bytes,
   including a still-owned 128-byte array; all 3,584 bytes remained after Clear.
2. Clear before any GPU operation called `_load_cupy`, entering optional CUDA
   discovery merely to look for a cache that the application had never used.

These tests retain the real controller, legacy CUDA selection, numerical
callers and event handler. CuPy's native device/allocator boundary is represented
by a deterministic NumPy-backed facade. Those byte counts are **controlled
boundary observations, not measured native VRAM**.

### Resource ownership

`GpuResourceCache` keeps a weak registry of CuPy providers and device ordinals
that the application has already selected for work. Registration covers the
legacy CUDA path, every universal CUDA numeric branch, the hardware benchmark,
the CUDA smoke test and the existing importance-map operation. It retains no
array, image or computation result. Bookkeeping failure cannot turn successful
GPU work into a failure.

Clear visits only those recorded devices and restores the calling thread's
previous CUDA device. It invokes the default allocator's `free_all_blocks` and
clears the shared default pinned pool once per provider. It does not enumerate
devices or load a hardware profile. The selected compute policy, configured
pool limits and backend quarantine remain intact. Independent resource errors
are reported while other known pools can still be maintained.

The allocator decides which blocks are unused. CuPy documents that
[`MemoryPool.free_all_blocks`](https://docs.cupy.dev/en/stable/reference/generated/cupy.cuda.MemoryPool.html)
releases free blocks; split allocations can retain free portions until the
whole allocation can be merged. Its
[memory-management guide](https://docs.cupy.dev/en/stable/user_guide/memory.html)
distinguishes device and pinned pools from live arrays. The result therefore
reports observed pool totals and unused bytes before/after cleanup, without
promising zero VRAM or resetting a CUDA context. Existing OOM-retry cleanup is
unchanged.

Every universal OpenCL numeric branch now borrows its cached context for the
duration of its operation. Clear skips active entries and a native context build
whose cache lock is busy. For idle entries it drops only the module's cache
reference, outside the cache lock; it never calls native `release` on a context,
queue, program or buffer. An independent owner, including a retained error
traceback, keeps its objects alive. Stop releases already removed cache
references even when the cancellation traceback itself is retained.

The controller uses the existing tracked worker and readiness guard. A new
explicit action clears an old Stop before handoff; `reset_stop=False` preserves
an Esc received during construction or execution. Stop is checked between native
resource operations and before status publication. The standard queued-event
filter keeps a late completion message from replacing `Stopped.`. Native
allocator calls themselves are not made asynchronously interruptible; Tk remains
available while the worker performs them.

### Deduplication

This is one complete explicit maintenance action, not one ID per backend,
device, worker, error path or registration site. It is separate from:

- **020** and **GP03 / 555**: measured backend selection and status/probe
  freshness. Clear does not choose a route or perform a status probe.
- **CG10 / 110** and **CG23–CG28 / 123–128**: color/palette lookup and persisted
  picture-palette caches. No color-cache policy changes here.
- **CG21 / 121**: backend-health synchronization. Clear preserves that state.
- **GP04–GP06 / 556–558**: capacity accounting, transient OOM quarantine policy
  and failure-frame release during a numeric retry. Those existing contracts
  remain the controls for live allocation and numeric fallback.

## Existing reset contracts completed — zero new IDs

Both **Reset profile** and **Reset learned draw timing** left the selected
browser profile in the shared `real-speed-profiles.json` database. Consequently,
the next real `DrawTimeEstimate.estimate_from_plan` still applied measured path
throughput, and browser time-budget recommendations still reported learning.
The two baseline regressions used actual `make_plan`, normal timing/speed
writers, both reset callers and the real estimator against temporary files.
Both retained the selected 20-path / 100-second sample (0.2 paths/second).

`RealSpeedBudget.profile_reset_changes` now prepares removal of exactly that
profile while holding the same file transaction used by runtime learning.
`ProfilePortability.reset_profile` publishes this change together with its
existing profile-file reset. `DrawTimeCalibration.reset_profile` publishes it
together with removal of the effective timing context. Real-Speed history is
profile-wide, so its one shared profile entry is retired; other tool/brush
timing contexts and every other profile's speed entries are preserved.

Both paths use the existing staged `replace_text_files` publisher. A caught
publication error restores existing file bytes and leaves the visible plan and
estimate untouched. This is **staged publication with rollback, not a
crash-atomic transaction across multiple files**. The shared speed writer lock
remains held through publication, so another profile's concurrent completed
sample is applied to the resulting database rather than overwritten. Unreadable,
unsupported or invalid shared speed data fails the reset instead of discarding
other profiles or claiming that unknown history was erased.

A further actual-writer reproduction found that whole-profile Reset could
return while a timing writer still held the selected timing file's transaction:
Reset published an empty model, then the older writer restored three previous
samples together with its fourth sample. Whole-profile Reset now takes the
selected timing transaction before the shared speed transaction and the
publisher, matching the existing timing-reset order. The writer finishes first;
Reset then retires its completed model. The new concurrency regression verifies
this order and preserves the other profile's timing file byte for byte. The
verified concurrency boundary is the selected timing file and the shared
Real-Speed database.

Timing reset reads eligible legacy records without first writing a migrated
file. A failed combined reset therefore leaves an originally absent current
timing file absent; a successful reset still establishes the existing migration
barrier. The controller also uses the normal readiness guard before reading UI
options during a pending profile change or Clear operation.

This work completes **068** (rollback and no reload after failure),
**SS04 / 184** (learning writer/reset transactions), **SR08 / 412** (final reset
and legacy migration) and **AX05 / 704** (the effective timing context, plan
invalidation and failure preservation). It receives **zero** additional IDs.

## Verification

| Gate | Result | Evidence covered |
| --- | --- | --- |
| Initial GPU controller reproduction | 2 failures | CPU after used CUDA left free blocks; unused Clear called the backend loader |
| `test_v148_platform_batch20_gpu_cache.py` | 13 passed | Actual legacy/universal numerical callers and controller worker; two devices, live device/pinned arrays, limits/current device, quarantine, partial errors, active/idle OpenCL, native build on another thread, retained cancellation, Stop and readiness |
| Initial speed reset reproduction | 2 failures | Both real reset callers retained the speed floor used by the next estimator |
| `test_v148_platform_batch20_speed_reset.py` | 9 passed | Real planner/estimate/budget behavior, profile/context isolation, late publication rollback, missing-file migration, unreadable shared store, two concurrent speed-writer paths, an older timing writer and controller handoff guards |
| Combined new and adjacent platform/learning gate, before the final timing-writer extension | 217 tests: 215 passed, 2 skipped; 2.606 s | Numeric output/routing, GPU capacity/retry behavior, hardware benchmark/smoke boundaries, storage transactions, profile isolation and calibrated estimates |
| Final timing-writer extension plus adjacent reset/storage/estimate gate | 101 passed; 0.886 s | The ninth regression and all affected rollback, shared speed-writer, legacy migration, profile isolation and calibrated-estimate controls |
| Final reset fixture isolation and focused integrity gate | 21 passed; 0.302 s | The older rollback fixture directs the real timing transaction into its temporary directory and checks only the expected files and retained coordination sidecar |

The earlier combined command was (the final source has one additional reset
test):

```sh
.venv/bin/python -m unittest \
  test_v148_platform_batch20_gpu_cache test_v148_platform_batch20_speed_reset \
  test_gpu_execution_regressions test_gpu_route_regressions \
  test_gpu_scoring_regressions test_gpu_pipeline_optimization \
  test_gpu_memory_fill_v106 test_gpu_v106 \
  test_step23_universal_gpu_acceleration_v10146 test_v148_gpu_numeric \
  test_v148_platform_batch03_benchmark test_v148_platform_batch03_cuda \
  test_v148_color_performance test_v148_application_batch06_timing \
  test_v148_storage_batch02_profiles test_rc4_profile_integrity \
  test_draw_time_calibration_v10117 test_real_speed_budget_v1077 \
  test_v148_platform_batch06_speed_storage \
  test_step9_profile_calibration_isolation_v10133 test_v148_storage_security \
  test_v148_storage_batch02_learning test_rc12_eta_calibration -q
```

The final 101-test gate used the same command's modules from
`test_v148_application_batch06_timing` through `test_rc12_eta_calibration`, plus
`test_v148_platform_batch20_speed_reset`.

GPU-cache source review and an independent 13-method run closed without a
blocker. Independent learning-reset source/rollback/locking review also closed
without a blocker; its initial eight methods passed independently in 0.259
seconds. The final timing-writer extension also passed independent source review
and a separate nine-method run in 0.386 seconds, with no blocker.
The older rollback fixture originally redirected the reset files but not the new
timing transaction. Its file boundary now uses the same temporary timing path;
the real lock, injected publication failure, exact rollback bytes and absence of
reload are still exercised. This fixture completion adds no product behavior or
improvement ID.
`git diff --check` passed. These are Linux regression results with controlled
native CuPy/OpenCL boundaries; no native Windows GPU or VRAM performance claim
is made. Test durations are verification timings, not optimization benchmarks.
The root-owned final full suite, source gate and exact-commit CI determine the
publication status.

The final shared frozen-source gate completed **4,162 tests in 200.541
seconds: 4,104 passed and 58 platform/hardware cases were skipped**, with all
869 source/configuration hashes unchanged. The 5,000-cycle source gate,
package hygiene and eight exact-raster engine fixtures passed. See
[final batch validation](v148-batch20-validation.json); exact new published-commit
CI and native Windows results remain separate gates recorded in PR46.
