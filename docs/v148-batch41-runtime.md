# v1.0.148 batch 41 — bind runtime evidence to its execution context

## Scope and count

Baseline: `fc3f927966d79c3f5d8cd04ea071c0670faa6ad0`, with 861 registered
improvements. This ledger proposes **two distinct behavior groups**. Parent
integration owns global IDs and the cumulative total; this document does not
claim that the 900-improvement target has been reached.

Product changes are confined to `UniversalGpuAcceleration.py`,
`UniversalHardwareBenchmark.py` and `ResourceScheduler.py`. The new regression
modules use the committed Paint reference and its pixel-preserving transforms
or nearest-neighbor resized derivatives. No image artifact or new motif is
created.

| Local group | Reproduced problem | Implemented behavior | Count boundary |
| --- | --- | --- | --- |
| P4101 | A newly loaded, currently valid hardware profile at the same backend ordinal reused an old OpenCL context and inherited the old hardware's workload quarantine. A successful new measurement also could not revalidate the adapter, and a late error from an old operation could poison new work. | Bind the route's failure evidence and OpenCL context to the hardware signature and completed measurement identity. Each completed hardware benchmark supplies a fresh `measurement_id`, including two completions in the same timestamp second. Old active contexts remain owned until their operations finish; obsolete idle generations are detached and their references dropped outside the cache lock. Late failures retain the route's original generation. | This is one runtime evidence identity defect, counted once across the cache, quarantine and profile producer. P1901 rereads and validates the profile per operation; the defect reproduces even after that fresh validated read. P2001 safely clears idle resources but does not distinguish two hardware/measurement generations at the same ordinal. GP03 addresses the separate legacy CUDA status probe cache. |
| P4102 | A valid saved Threads benchmark recommending one worker was used after selecting Processes, silently reducing process planning to serial work. The reverse direction affected Threads and Auto as well. Machine/RAM compatibility alone did not identify the executor measured. | Use saved worker recommendations only when their effective measured executor matches the requested executor. Auto and Threads retain their existing shared Threads policy. Incompatible or unidentified executor evidence takes the existing safe cap; manual workers, disabled scheduling, memory pressure and preview caps retain their authority. | This is selection of evidence from the wrong executor. SS28 validates persisted values/schema and SS29 validates current CPU capacity. P2502 binds the RAM policy; P2503 measures real executor work and invalidates old serial proxy scores. None prevented a valid current-format Threads record from being applied to Processes. |

The new private generation field is omitted from `RouteInfo.as_dict()`, so
public route metadata retains its previous shape. Generation-qualified health
diagnostic keys identify the evidence they describe. Anonymous direct legacy
profiles retain their established process-local quarantine. Existing saved
profiles without `measurement_id` use their hardware signature and finite
record timestamp; no timestamp can distinguish two otherwise identical legacy
records written in the same second. Newly completed measurements avoid that
ambiguity with the explicit ID. Existing files are not rewritten on reads.

Failure records are bounded to 256 entries. Each backend retains at most one
idle context in addition to contexts still borrowed by live operations. The
cache does not force-release native objects still owned by active work, and a
new measurement does not clear unrelated generations' failure records.

## Evidence

`test_v148_runtime_batch41_gpu_identity.py` exercises real route selection,
actual profile save/load and validation, context cache ownership, fallback and
concurrent operation lifetimes. Its native OpenCL ABI boundary reuses the
existing batch-20 resource facade. It does not replace routing, profile
storage, cache management or fallback with a test implementation. Exact CPU
channel-error output is checked against each accelerated-boundary/fallback
result using the committed Paint pixels.

Coverage includes hardware replacement, same-second remeasurement, same
generation reuse, old active work completing with a late native error,
12 successive idle-context replacements, legacy timestamp identity, anonymous
legacy callers and cache maintenance preserving workload quarantine. The real
benchmark producer is run with optional native providers unavailable and
committed asset-derived source data; two completed publications at one fixed
wall-clock second must have distinct IDs. These functional benchmark calls are
not performance measurements or a report of physical GPU execution.

`test_v148_runtime_batch41_scheduler_identity.py` saves and reloads actual
recommendations, resolves the real schedule and checks complete phase worker
choices. Both automatic modes, both mismatched directions, Auto/Threads
equivalence, explicit missing/unknown executor evidence, manual selection,
disabled scheduling, preview caps and legacy schema invalidation are covered.
Rejected recommendations leave their persisted files byte-identical.

The machine-readable report `v148-batch41-runtime-validation.json` retains the
final source/test hashes, focused and integration commands, complete raw
results, unchanged-source checks and exact-baseline negative evidence. It also
retains the earlier 15-method pre-edit reproduction with its original hashes;
later methods are not attributed to that earlier run. Failed subtests are
reported separately from test-method counts and never counted as improvements.

## Validation and review boundary

The product changes are frozen for parent integration. All **17 new tests
passed in 0.318 seconds**, without skips. Loading the exact three baseline Git
objects and running the same final tests produced **15 failed assertions or
subtests and one error across 17 methods**. The error is the baseline producer's
missing `measurement_id`; the failures exercise context/quarantine reuse and
executor mismatch. Both runs retained unchanged product and test hashes.

An independent read-only review of the three product files and all 17 new
tests found no blocker. The final targeted integration completed **145 tests
in 10.046 seconds: 143 passed and two existing physical-device checks skipped**
because CuPy and an OpenCL GPU were unavailable. There were no failures or
errors, and all recorded product/test sources stayed unchanged throughout the
run. No skip condition or timeout was changed. This run began after the
renderer's benchmark and functional selection had finished.

```text
.venv/bin/python -m unittest -v \
  test_v148_runtime_batch41_scheduler_identity \
  test_v148_runtime_batch41_gpu_identity \
  test_resource_scheduler_v1044 \
  test_v148_storage_batch02_resources \
  test_v148_platform_batch25_scheduler \
  test_v148_platform_batch27_scheduler_options \
  test_v148_platform_batch19_profile_observation \
  test_v148_platform_batch20_gpu_cache \
  test_v148_gpu_numeric \
  test_step23_universal_gpu_acceleration_v10146 \
  test_step22_universal_hardware_auto_benchmark_v10145 \
  test_v148_platform_batch03_benchmark \
  test_v148_platform_batch22_numeric_ownership \
  test_v148_platform_batch26_opencl_host \
  test_gpu_route_regressions \
  test_gpu_pipeline_optimization
```

The recorded harness dispatches this same selection, captures the raw unittest
output and hashes sources before and after it. Its source and exact invocation
are retained in the JSON, alongside the equivalent direct unittest command.
Adjacent checks include actual spawned process workers, complete verified
benchmark work, cancellation/publication boundaries, current RAM compatibility,
CPU/anonymous-profile behavior, context maintenance during active operations,
OpenCL host/native ownership and complete numeric/fallback parity.

| Frozen product | SHA-256 |
| --- | --- |
| ResourceScheduler.py | `111e14e18cbeb5133f5f7f16937624e494ac751afc4752405cf739b9aadf6f37` |
| UniversalGpuAcceleration.py | `e6a71cfb3d01c3cf69d03d4b4ee1b29bc97ebf41636ef1e0f78c7e27ea5940ef` |
| UniversalHardwareBenchmark.py | `44a9e7fd3e5dd1382f7e3362ab56c73329086f5304696f50d7a18087696c179d` |

All new runtime tests run on Linux with real Python threads, NumPy and
filesystem persistence. Native OpenCL behavior is isolated at its resource
and kernel boundary. These tests establish route isolation, ownership and
fallback semantics; they do not establish physical driver behavior, VRAM
usage, end-to-end Windows drawing time or live Paint compatibility.

No performance benefit is claimed for these two correctness groups. The
completed CPU benchmark calls validate ID publication only. No timing
experiment is run alongside the renderer's benchmark window or the parent's
full-project gate. Parent integration owns full discovery, native Windows
checks, packaging and exact-commit remote CI.

Additional related review found a malformed-row brush-state regression in the
parent's initial dry-sample change. The parent fixed it by using the canonical
execution-sequence iterator; an independent 25-test check, including the then
16 runtime tests and nine native delivery/sample tests, passed in 0.687 seconds.
That review, the zero-count completion and the tests add no runtime group.
