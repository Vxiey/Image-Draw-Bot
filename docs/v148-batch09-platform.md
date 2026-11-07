# v1.0.148 batch09 — cancellable diagnostics export

Baseline: `ab2a59bd1432aac7528d378cef2c4ebcf689a47b`, the published batch08
checkpoint plus its native test-fixture repair. This ledger currently contains
**one new behavior group, PX901**. Individual checks, tests, cleanup branches and
caller changes are not counted separately.

| ID | Reproduced public behavior | Implementation and evidence |
| --- | --- | --- |
| PX901 | The Diagnostics command entered a tracked worker and exposed Stop, but never passed the cancellation event into the collector. A public `collect_diagnostics` reproduction set Stop during collection and still produced a completed ZIP, queued `diagnostics_ready` and displayed its success dialog. The collector could continue reading up to 100 settings files, 100 calibration files and the remaining logs after Stop. | `create_diagnostics_package` accepts a cooperative cancellation callback. Summary/dump enumeration, bounded JSON/log reads, package metadata, section boundaries and the final publication check honor it. Staging is removed on cancellation; prior completed exports remain unchanged. Cleanup failures retain the primary interruption and record only the secondary exception class. The actual GUI worker forwards Stop and rejects late completion; the GUI result branch and standalone helper suppress success/folder presentation after cancellation or closing. |

## Validation

`test_v148_platform_batch09_diagnostics.py` exercises the actual public collector
and tracked GUI worker. Its ten regressions cover interruption before directory
creation, between real settings reads, during a large candidate inventory,
during log redaction, after ZIP closure but before rename, late result delivery,
standalone folder presentation, and JSON/unlink/ZIP-close failure handling.
Tests compare the exact bytes of an earlier completed ZIP and verify that a
cancelled collector leaves no newly published ZIP. A failed temporary-file
deletion is explicitly covered as an exceptional retained staging file, with
`InterruptedError` still primary.

The related existing privacy, WER, atomic-export and bounded-summary suites stay
in the validation selection. Collection keeps its existing allowed fields,
opaque summary labels, log redaction, image exclusions, file limits and GPU
probe avoidance. This change neither submits reports nor touches certificate
trust or installer authorization.

Final focused/related selection: **76 tests passed in 0.163 seconds, with one
native Windows skip**, including the four clipboard completion tests below.
`git diff --check` passed. Whole-project integration and native CI remain root's
separate gates for the eventual frozen checkpoint.

The separate `test_v148_application_batch09_clipboard_preview.py` file contains
four integration regressions written during independent review of root's new
clipboard-worker group. Automatic preview waits for matching loader completion,
Manual remains manual, Stop cannot restart it, and explicitly armed Drop-In
runs after idle and before an automatic preview. Those tests and the two fixes
they prompted belong to that single clipboard group; they add **no platform
count** here.

## Limits

- Cancellation is checked between bounded work units. It cannot interrupt an
  OS filesystem call, importlib metadata read, JSON parse, redaction operation or
  ZIP compression already executing. There is no hard wall-clock guarantee for
  a blocked filesystem or dependency provider.
- The final Stop check is immediately before the atomic rename. Stop after
  that commit may leave the already complete local ZIP, but the later worker/UI
  checks suppress success presentation. A completed artifact is not deleted
  merely because the user subsequently presses Stop.
- If the filesystem refuses temporary cleanup, the private `.diagnostics-*.tmp`
  may remain. The interrupted operation is not reported as a successful export,
  and earlier complete files are retained.
- Portable tests use temporary directories and controlled I/O failures. They do
  not open Explorer, initialize a GPU driver or execute native input.

No benchmark or speedup is claimed for this correctness change.

## Existing source-bootstrap contract completed — zero additional count

`Enable-Crash-Dumps.bat`, `Disable-Crash-Dumps.bat`,
`Collect-Diagnostics.bat`, `Install-GPU-NVIDIA.bat` and
`Install-GPU-Universal.bat` still started their source Python helpers without
the startup isolation already used by `Start.bat` and `Build-Release.bat`.
A harmless actual `CrashDumpConfig.py --help` invocation executed a temporary
`sitecustomize.py` supplied through inherited `PYTHONPATH`. The same public
helper with `-E -s` retained its working help/import behavior and did not execute
that unrelated startup hook.

All five source launchers now pass `-E -s` before the helper script. Their
frozen-executable branches, arguments, local virtual-environment selection and
existing application behavior are retained. No package, proxy, credential or
index policy is added here. This also matters for the explicit administrator
LocalDumps workflow, but these tests never request elevation or alter registry
values. It is a completion of original022/GP01/BP02's source-startup boundary,
not a sixth launcher-specific security count.

`test_v148_platform_batch09_launchers.py` runs the real harmless help command
using the flags extracted from every Python launch branch, demonstrates the
unisolated control case, and checks that explicit proxy/index environment is
preserved. Its Windows-only test executes all five actual BAT files from a path
containing spaces and an ampersand, using a temporary no-pip venv and harmless
helper stubs. It verifies unchanged arguments and Python's actual isolation
flags with invalid inherited `PYTHONHOME`, `PYTHONPATH` and `PYTHONINSPECT`.
No application, package installer, GPU driver or registry configuration is run.

The launcher/source-startup/GPU regression selection passed **27 tests in
4.372 seconds, two native Windows skips**. Actual CMD execution remains a native
CI gate; the portable checks do not claim to have executed BAT files on Linux.

## Frozen checkpoint validation

Batch 09: final frozen-source discovery passed 3,514 tests in 190.952 seconds (42 platform/hardware skips), with unchanged Python and batch-script hashes. All four area source reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. This checkpoint still requires its own Windows/Linux, dependency, CodeQL and packaged Windows checks. No 1.0.148 release is published.
