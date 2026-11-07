# Batch 19 — observe the current hardware profile once per scoring operation

Baseline: `7f41c7ee8c4b69f750008bd2d83349d186396fd1`, the published batch18
checkpoint. This ledger records **one operation-scoped work reduction,
P1901 / global 818**, accepted after the final measurement and registry review. It does not add
separate IDs for selectors, comparisons, cleanup or callers.

## Actual repeated work

The public `AccuracyEvaluator.evaluate_preview` performs four numerical route
selections: channel error, paired perceptual conversion, source edges and final
edges. Each selection independently loaded the same saved hardware profile,
parsed and validated its JSON, then checked the current machine signature.
That signature check includes the existing CPU/RAM/GPU/runtime observations.

`SafeCanvasSnapshotScoring.score_final_canvas_snapshot` evaluates the source,
simulated drawing and quantized target in one completed observation. It could
therefore repeat the same file and current-hardware validation twelve times.
These are actual work calls, including when the measured preference selects
CPU for the numerical work.

The initial three tests used a real temporary profile file, the normal writer,
strict JSON loader and current-signature validator. The baseline failed the two
new operation-count assertions and passed its explicit CPU control:

| Complete operation | Profile loads | JSON reads | Current hardware observations |
| --- | ---: | ---: | ---: |
| One evaluator, Auto | 4 | 4 | 4 |
| Final snapshot with all three comparisons, Auto | 12 | 12 | 12 |
| Both operations with explicit CPU | 0 | 0 | 0 |

The baseline run completed in 0.030 seconds. This is regression-run duration,
not a performance claim. Native device creation was not needed to reproduce
the repeated validation.

## Lifetime and policy

`UniversalGpuAcceleration.HardwareProfileObservation` owns one lazy validation
for one synchronous scoring operation. It reads nothing until a non-CPU route
needs the profile. It stores either the validated profile or the existing
fallback reason. A failed read retains text, without keeping an exception or
its traceback. Missing, malformed and stale profiles remain ordinary CPU
fallbacks.

A standalone public evaluator creates and closes its observation in `finally`.
The final-canvas scorer owns one observation for its three comparisons and
passes a borrowed reference through the private `_profile_observation` keyword.
Those nested evaluators do not close their caller's observation. The owner
releases the profile on success, Stop and scoring failure, including when the
exception traceback remains live. Existing explicitly supplied lower-level
profile dictionaries retain their previous behavior.

No profile is stored globally or on a plan. The next explicit operation reads
and validates the file again. Replacing the file partway through an operation
does not mix old and new preferences within that single result; the following
operation observes the replacement. A changed hardware/runtime signature is
likewise revalidated on the next operation. Two real concurrent operations
keep independent observations.

The observation caches profile data, not route decisions. Each route still
applies its actual workload, pixel count, selected CPU/Auto/forced-CUDA policy,
measured crossover and current backend-health state. For example, a failed
source-edge kernel is quarantined before the destination-edge route is chosen.
The subsequent comparisons consult that updated quarantine. Native kernel
fallback, numerical arithmetic and returned route provenance are unchanged.
Explicit CPU still performs no profile or native-device access.

The existing cooperative cancellation checks remain in place. A native/file
probe already executing is not made preemptible by this change. There are
fewer repeated validations before an operation completes or reaches its next
Stop boundary.

## Deduplication

- **Original 020** owns the backend status panel's measured crossover and live
  health behavior. That status path already passes one loaded profile to its
  selectors. This change applies a bounded observation to the actual numerical
  evaluator and complete final-canvas scorer, which previously repeated their
  own validated reads. The status panel is not changed or counted again.
- **Original 014/015** own recoverable damaged profiles and respect for
  explicitly empty preferences. Both remain tested controls here.
- **RD01**, completed for final scoring in batch18, owns propagation of the
  user's selected hardware policy. This work preserves that contract; it
  introduces no new acceleration option or GPU availability claim.
- **GP21** owns atomic publication of hardware/scheduler recommendations. The
  writer and its publication behavior are unchanged.

The proposed group concerns the one complete operation's repeated validated
observation. File freshness, failure cleanup, threading and policy tests are
necessary supporting parts of that group, not separate improvements.

## Correctness evidence

The final focused module currently has **12 passing methods in 0.108 seconds**.
It exercises the actual scorer and selector with real profile-file validation:

- one real read/validation for four evaluator routes and all twelve final
  comparison routes, while explicit CPU retains zero;
- exact complete score metadata and diagnostic image bytes against an
  explicit, independently validated profile;
- real atomic profile replacement during an operation, fresh state on the
  next call and runtime-signature invalidation;
- missing/invalid files, original fallback reasons and a failed read retried
  only by the next operation;
- actual Auto, forced CUDA and measured crossover decisions with controlled
  unavailable native devices and live per-workload quarantine;
- Stop before work, Stop during a load, failure after loading and deterministic
  profile release while a real exception traceback remains retained;
- two real ThreadPool operations with separately validated profiles.

The related gate passed **119 tests in 2.728 seconds, with no skips**:

```sh
.venv/bin/python -m unittest \
  test_v148_platform_batch19_profile_observation \
  test_v148_application_batch18_snapshot_policy \
  test_v148_application_batch18_result_recheck \
  test_step13_safe_canvas_snapshot_scoring_v10137 \
  test_step23_universal_gpu_acceleration_v10146 \
  test_step22_universal_hardware_auto_benchmark_v10145 \
  test_gpu_route_regressions test_gpu_benchmark_regressions \
  test_v148_rendering_batch08_gpu_policy test_v148_color_correctness \
  test_v148_colour_batch05_resources test_v148_accuracy_batch12_context \
  test_source_relative_accuracy_v10125 test_gpu_scoring_regressions -q
```

`benchmark_v148_platform_batch19_profiles.py --verify-only` additionally passed
**36 historical complete-output pairs** and all **six workload pairs**. It
installs all three complete baseline modules together, including the old
scorer's binding to its old evaluator; no historical function receives a new
private keyword. All unrelated dependencies are current on both sides.

The parity matrix includes thin and ordinary RGB/RGBA inputs, CPU/Auto/forced
CUDA, current and absent profiles, crossover thresholds, unavailable native
devices, quarantine, every returned score/route field and exact diagnostic
image bytes. No output fields are excluded. Borrowed image bytes remain
unchanged. The complete historical-pair digest is
`0a495074de5aa43ef3ef781f030a9468ac3e54cbebc9606a0b0cd4909f6e921a`.

The workload observations independently confirm **4 → 1** and **12 → 1** real
profile/JSON/current-hardware calls, **0 → 0** in CPU mode, and **12 → 1** file
attempts for an absent profile without inventing a hardware observation.
Source hashes were unchanged during the successful verify-only run.

## Measurement protocol and allocation tradeoff

The root coordinator ran the final command in the coordinated source/CPU freeze:

```sh
.venv/bin/python benchmark_v148_platform_batch19_profiles.py --repeats 6
```

Its raw output is `docs/v148-batch19-platform-profile-benchmarks.json`, SHA-256
`04e3a0638ec591f1e685cc5b76b49c6a544991af5cdb303d25f54d564e295836`.
This final run followed the test-fixture lifetime repair and supersedes the
earlier measurement on the pre-repair test snapshot. All tables and final
claims below use this final raw output; the scoring product code did not
change for that repair.
After full-output verification, it ran six balanced AB/BA timing pairs for
complete evaluators and final snapshot scorers at 96×72 and 640×480, plus
explicit CPU and absent-profile controls. The temporary saved profile has the
actual current machine signature and controlled CPU workload preferences;
normal file/schema/runtime/hardware probes execute during scoring. No physical
GPU kernel, screen capture, drawing input, GUI or network is timed.

Separate tracemalloc probes report peak allocation, retained bytes with the
complete returned result and retained bytes after releasing that result.
Tracemalloc covers Python/NumPy allocations, not whole-process RSS, most native
Pillow cores or other processes. Reusing one profile retains that dictionary
until the whole operation finishes instead of releasing it between numerical
stages. The observed allocation effects are reported alongside time below.

### Final observed times

All 36 historical comparison pairs and all six measured workload pairs retained
exact complete-output parity. The run recorded **807 unchanged root Python
source hashes**, with shared source-manifest SHA-256
`a0d152b40c9a48c43492f51a6ac54aa655a7df99aabeae90b03d1db2e6e0b551`.
It used Python 3.12.14, NumPy 2.3.5 and Pillow 13.0.0 on Linux
x86-64. The temporary current-machine profile was 2,213 bytes. These are six-pair
medians for the stated fixtures, not Windows or live-GPU measurements.

| Complete operation | Policy/profile | Before median | After median | Observed time change |
| --- | --- | ---: | ---: | ---: |
| Evaluator, 96×72 | Auto/current | 3.854 ms | 2.156 ms | −44.1% |
| Snapshot scorer, 96×72 | Auto/current | 11.623 ms | 5.615 ms | −51.7% |
| Evaluator, 640×480 | Auto/current | 50.309 ms | 45.168 ms | −10.2% |
| Snapshot scorer, 640×480 | Auto/current | 173.283 ms | 162.572 ms | −6.2% |
| Snapshot scorer, 640×480 | Explicit CPU/current | 157.469 ms | 159.755 ms | **+1.5% slower, control** |
| Snapshot scorer, 96×72 | Auto/missing | 5.658 ms | 5.230 ms | −7.6% |

The deterministic work reduction is **4 or 12 validated reads to one** for
Auto with a current profile. It yields a clear reduction in the small complete
operations here. Both larger Auto fixtures also had lower medians in this final
run. Explicit CPU already makes zero profile reads and its control median was
2.286 ms slower; that difference cannot be attributed to fewer profile reads. This
does not establish a universal full-score performance improvement or a
drawing-quality change.

### Final observed allocation

Values below are traced bytes from the separate allocation probes. Retained
bytes cover the whole measured call and its returned metadata, including
runtime/library allocations; they are not a count of retained profile objects.
The weak-reference lifetime regression separately establishes that the owned
profile is released even with a retained scoring-error traceback.

| Operation/policy | Peak, before → after | Retained with result, before → after | Retained after result release, before → after |
| --- | ---: | ---: | ---: |
| Evaluator 96×72, Auto/current | 4,536,397 → 4,409,158 | 85,941 → 51,476 | 17,103 → 16,202 |
| Snapshot 96×72, Auto/current | 4,590,133 → 4,426,222 | 115,651 → 58,042 | 19,117 → 17,242 |
| Evaluator 640×480, Auto/current | 24,651,317 → 24,645,135 | 85,687 → 51,676 | 16,849 → 16,402 |
| Snapshot 640×480, Auto/current | 25,310,156 → 25,272,889 | 116,306 → 58,100 | 19,580 → 17,108 |
| Snapshot 640×480, CPU/current | 25,248,553 → 25,248,669 | 39,205 → 39,301 | 14,831 → 15,117 |
| Snapshot 96×72, Auto/missing | 675,849 → 675,893 | 40,953 → 40,933 | 15,171 → 15,325 |

The explicit-CPU peak is effectively unchanged, and its post-release retained
value increases by 286 bytes in this probe. The missing-profile control has
44 more peak bytes and 154 more post-release retained bytes. Larger comparisons remain dominated
by their numerical buffers. No whole-process memory or persistent-leak
reduction is inferred from these small residual differences.

Independent source review is closed without blockers. The reviewer read the
three product diffs, actual profile/route implementations and complete test
module, then separately ran all 12 methods successfully. These tests do not claim improved
drawing quality or prove live CUDA/OpenCL availability.

The root coordinator's final integrated gate passed **4,083 tests in 117.859
seconds, including 58 platform skips**, after correcting the headless Tcl
fixture ownership that had aborted the first attempt. Its **857 source hashes
remained unchanged**, with manifest SHA-256
`3743e476eb8596030a5884bd05e8657e6cf5e75ba9b901a46fde2ec1edd68a4f`.
The aborted attempt is superseded by this completed gate; it is not counted as
a successful verification run.
