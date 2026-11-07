# Batch 27: include direct GPU installers in source-environment ownership

Published parent: `8e0a0e4c61ca0742dfb7857649103477cd307516` (838 groups).
This is **P1403 / global 795 completion, zero new IDs**. The original
[batch14 ledger](v148-batch14-platform.md) explicitly limited its cooperative
lock to participating source launchers. That lock already protected Start and
Update correctly. This completion makes the two shipped direct GPU batch
entrypoints participate as well.

## Before evidence

The actual `Install-GPU-NVIDIA.bat` command dispatched directly to
`AutoGpuSetup.py --ensure --force --require-nvidia`. The Universal command
dispatched directly to `AutoUniversalGpuSetup.py --ensure --force`. Neither
went through the source launcher's checkout lock.

The regression reads these exact commands from the batch files, preserving
their `-E -s` interpreter flags, and executes the selected real public helper
CLI, setup policy and pip-policy code. A separate real Python process holds
`start_source` at its application boundary with the real OS file lock. Only
external Python processes and GPU detection/readiness are replaced; no pip
process, package download or GPU driver installation runs.

While that independent owner was active, NVIDIA reached **three external
package-mutating commands**, and Universal reached **one**. Both returned
success. Two focused before methods produced four failing assertions and no
errors in 0.228 seconds: the two ownership cases and the two missing
private-startup-dispatch cases.

The first scratch run incorrectly supplied package-list JSON to the distinct
`pip config list` query. Its log is retained as
`batch27-gpu-installers-before-fixture.log`; it is not evidence of package
mutation. The corrected actual-policy before evidence is in
`batch27-gpu-installers-before.log`.

The three product files were unchanged from the published parent at that
before checkpoint:

| File | Before SHA-256 |
|---|---|
| `SourceStartup.py` | `0fc9107ed2fcdfec85cc4cdd2977cbbdced6cb2510491a110be9b65334602662` |
| `Install-GPU-NVIDIA.bat` | `4997868748c6b22b6abf72e6494345befd56d9babca0e0b8c0a403ddac9d14bd` |
| `Install-GPU-Universal.bat` | `c90ec59c9d96b3db54391258a01238a01711d92dbc045d3fdf5a36ec8a432f14` |

## Behavior after the change

`SourceStartup --setup-gpu nvidia` and `--setup-gpu universal` acquire the
existing nonblocking `build/.source-startup.lock`. They verify that the
existing `.venv` is a regular, isolated private Python 3.11+ environment, then
run only the chosen optional helper. They do not create an environment,
refresh `requirements.txt`, rewrite the installed-requirements stamp or open
the application. The optional helper retains its existing package policy,
including its own tooling/bootstrap operations.

The NVIDIA batch retains force and require-NVIDIA behavior. Universal retains
force and now captures the helper exit code before printing or pausing, so a
failure reaches the caller. NVIDIA retains its established zero/one batch
result and only removes its failure marker after successful setup; missing
environment codes remain unchanged. The new setup-only Python entrypoint
returns the selected helper's exact result.

Normal `Start --gpu` and `Start --update` still call the two public helpers
directly while their parent owns the lock. Neither helper gains a second lock
attempt, so the child does not wait for a lock held by its own parent. Invalid
combinations of setup-only and application-start flags are rejected explicitly.
The helper modules themselves are unchanged.

The cooperative limit remains: unrelated commands that invoke a lower-level
helper directly do not automatically participate, and this does not supervise
an orphan child after forcibly killing its owning launcher. It extends the
documented entrypoint coverage rather than claiming universal process control.

## Verification and scope

The new `test_v148_platform_batch27_gpu_installers.py` covers actual helper
CLI policy, a separate running source owner, a separate setup owner,
Start/Update/setup contenders, lock release and retry, invalid or absent
private environments, helper failure codes, no-NVIDIA semantics and unchanged
normal `--gpu`/`--update` dispatch. Its Windows-only method runs the actual batch
files with a real temporary private Python and a harmless entry stub, checking
flags, failure/success exit codes and marker handling.

* Focused gate: **7 methods, 6 passed, 1 Windows-only skip**, 0.379 seconds.
* Related gate: **45 tests, 42 passed, 3 Windows-only skips**, 3.576 seconds.
  This includes batch14 process ownership, batch08 private interpreter/pip
  isolation, batch09 native-entrypoint contracts and the existing CUDA/OpenCL
  setup regressions.
* `git diff --check` passed.

Three old dispatch expectations were updated, with their original assertions
retained: the two GPU rows in
`test_v148_platform_batch09_launchers.py` and the one NVIDIA command check in
`test_auto_gpu_setup_v1085.py`. Proxy/index preservation and inherited Python
startup-hook controls remain in place.

After logs are `batch27-gpu-installers-after.log` and
`batch27-gpu-installers-related.log` in task scratch. These are Linux results;
the new native Windows batch method awaits the batch27 Windows gate. No GPU
hardware performance, successful real package installation or elapsed-time
optimization is claimed.

Root independently reviewed the full product diff and the actual process-lock
tests, then ran the seven new methods: **6 passed, 1 Windows-only skip**,
0.390 seconds. Review closed without a blocker, including acquisition versus
in-body `TimeoutError`, private-environment verification order and unchanged
parent-to-helper lock ownership.

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
