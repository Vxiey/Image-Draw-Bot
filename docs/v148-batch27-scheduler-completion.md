# Batch 27 — current RAM policy reaches UI scheduling (zero new IDs)

## Existing contract and observed gap

This completes P2502 / global 834 and SS29 / global 209. The scheduler already
rejects a saved recommendation for a different current CPU/RAM signature when
called directly. `DrawBotApp.options` instead loaded the recommendation using
the loader's default signature, which combines current CPU capacity with the
saved record's RAM bucket. Passing that record into the scheduler bypassed its
normal current-allocation lookup. The resulting UI schedule could then survive
unchanged into the actual public `make_plan` call.

The before probe ran against the complete published
`8e0a0e4c61ca0742dfb7857649103477cd307516` source. All 873 root Python hashes
remained unchanged, with canonical manifest SHA-256
`e4057cf13bd9e97e52b07dbdba90f6962a9bbb012c0c78430d782418d8d0442d`.
It saved a real v3 recommendation file, loaded a real temporary calibration,
called the controller's actual options method and generated both public plans:
one carrying the UI schedule and one allowing the existing planner to resolve
the same allocation itself. Only hardware observations were controlled.

| Scenario | UI schedule before | Planner resolving its own schedule |
| --- | ---: | ---: |
| Saved 4 GiB; selected 8 GiB; 16 CPUs; Auto | 1 base worker | 10 base workers |
| Saved 8 GiB; selected 4 GiB; 16 CPUs; Auto | 1 | 10 |
| The same two changes with Benchmark recommendations | 1 | 10 |
| Saved 4 GiB; 2 GiB currently available; effective budget 1,536 MiB | 1 | 8 |
| Same saved/current 4 GiB budget, either automatic mode | 1 | 1 |
| Current CPU capacity changed from 16 to 8 | 6 | 6 |
| Explicit four workers | 4 | 4 |
| Scheduler Off | 8 | 8 |

These are scheduler decisions, not measured throughput. The ten fixture pairs
have identical final drawing geometry; the defect changes resource policy.
Four regression methods produced five failing subcases and zero errors before
the correction. The unchanged RAM, manual, disabled and current-CPU cases are
positive controls.

## Resulting behavior

The controller now passes the signature of its already resolved allocation to
the existing loader: current usable CPUs and the effective RAM budget after
the allocator's existing headroom rule. An incompatible record is ignored in
both Auto and Benchmark recommendations. A compatible record keeps its saved
worker choice. Manual workers, Scheduler Off and the public standalone planner
retain their existing behavior.

This adds no RAM observation, global cache, worker policy or signature format.
The options path still probes available RAM exactly once. The loader's existing
standalone/default API remains unchanged, so benchmark inspection can continue
to load a record with its saved budget when no current allocation is supplied.

## Verification

`test_v148_platform_batch27_scheduler_options.py` preserves both complete public
plans and checks schedules, groups, stroke counts, estimates, preview bytes,
source pixels and the single RAM observation. Real recommendation and palette
files, logs and timing state are isolated in temporary directories. The original
global palette and environment hints are restored after every fixture.

The corrected four methods and the adjacent tuner, executor benchmark,
scheduler, planning and resource-cancellation regressions passed **49 tests in
5.209 s**, without skips. Final frozen-source integration evidence is recorded
in the batch validation report. This is a correctness completion with no new
improvement ID and no claimed speed or memory gain.

## Final integrated evidence

The preserved before observations, initial observer diagnostics and final
source-bound completion checks are published in
[completion evidence](v148-batch27-completion-evidence.json).
The common-source full regression suite, native UI cases, source/raster/package
gates and scope limits are recorded in
[batch27 validation](v148-batch27-validation.json).
The new published commit requires its own Windows/package checks in
[PR46](https://github.com/Vxiey/Image-Draw-Bot/pull/46); the preceding commit’s
CI results are not substituted for those checks.
