# v1.0.148 batch10 — workspace build ownership

Baseline: `3c5fe8fc27ec3b503e2affa6f3ed00cb7856f973`.

This ledger currently contains **one distinct improvement, P1001**. The two
public entry points, helper checks, failure cases and tests are parts of the
same behavior. No runtime rendering, dependency policy, version or release
trigger changes are included.

## P1001 — a build owns its shared workspace until publication finishes

The public release builder and direct executable builder both used the same
`.build-venv`, PyInstaller working directory and `dist/ImageDrawBot` without
reserving those resources. BP01 protected the final release-file transaction,
but a second build could replace the first build's executable before that
transaction began.

The baseline reproduction runs the actual `build_release.main --skip-tests`
for a standard release. While its packaged executable self-test is in progress,
it interleaves the actual `build_exe.main(['--gpu'])`. Only external processes
are replaced with harmless synthetic output producers. The standard release
then finishes with the **second CUDA build's executable bytes inside the
standard-named ZIP**. The real ZIP/checksum/manifest gate passes, since it
consistently hashes the wrong producer's bytes. No installer or application
binary is downloaded or executed by this reproduction.

`BuildEnvironment.build_workspace` now reserves the canonical checkout before
environment preparation and retains ownership through source tests, packaging,
packaged self-test, optional signing, installer generation, archive validation
and completed asset publication. Direct `build_exe.main` uses the same session.
A contender receives a clear busy error before it can install packages or run
PyInstaller. Lock acquisition is nonblocking; a long-running compiler does not
make the second invocation wait indefinitely.

The process-level lock uses `fcntl.flock` on Unix and nonblocking
`msvcrt.locking` on Windows. A small registry checks the current process,
thread and canonical workspace for the common preparation/packaging APIs.
`build_release` calls `build_application` directly inside its existing session;
there is no child bypass argument, environment token or unrestricted skip-lock
flag. A nested second CLI invocation is rejected as well. The prepared builder
must also belong to the currently owned checkout.

The stable sidecar is `build/.workspace-build.lock`. It is deliberately kept
after release to avoid replacing the inode underneath another waiter. This
directory is already excluded from source archives. PyInstaller's inspected
6.22.2 implementation appends the spec name to its working directory before
performing `--clean`, so its normal `build/ImageDrawBot` cleanup does not delete
this parent-level sidecar. The new owner registry is separate from the existing
striped local-state transaction locks, avoiding holding one of those stripes
through a long build while release publication acquires another transaction.

### Deduplication

- SR23 protects one archive from partial replacement.
- BP01 stages, validates and publishes a coherent set of finished release
  assets, with exception rollback. Its documented scope explicitly excluded
  two full builds sharing mutable build/work/dist directories.
- BP02 provides a verified private environment shared by tests and packaging.
- Batch05 release-workflow concurrency serializes GitHub Actions publishers.

P1001 handles the earlier **local builder ownership** race. It neither repeats
those guarantees nor replaces their checks.

## Validation

`test_v148_platform_batch10_build_session.py` exercises six meaningful cases:

1. A real spawned Python process holds each public build entry in turn. The
   other public entry rejects the same workspace, including spaces and a
   canonical `build/..` alias, before invoking any external process. The first
   release retains its own CPU bytes and still passes the real artifact gate.
2. The exact baseline interleaving cannot replace CPU output with CUDA output;
   only the first PyInstaller invocation runs.
3. An injected failure in a public build releases ownership, and a subsequent
   complete release succeeds.
4. Terminating a holder process releases the OS lock despite the retained
   sidecar; a subsequent complete release succeeds.
5. Internal preparation/packaging calls reject an absent owner, a different
   thread and a builder belonging to another checkout. Separate workspaces can
   own independent sessions in the same process.
6. The actual release flow retains its owner during tests, signing, archive
   creation, final validation and publication, and releases it afterward.

The final combined run passed **31 tests in 1.595 seconds** on Linux: the six
new cases plus the existing private-builder, coherent-release, standard/CUDA-
variant and packaged-documentation suites. Windows executes the same
spawned-process tests against the real
`msvcrt.locking` branch; actual PyInstaller/Inno and packaged application checks
remain the Windows CI gate.

## Boundaries

This is cooperative ownership between the application's public builders. It
does not stop a user or unrelated tool from deleting the sidecar or modifying
the checkout directly. The existing asset publication remains exception-safe,
not a power-loss transaction across multiple filenames.

The terminated-owner regression stops a process inside a mocked external-tool
boundary. It proves OS-lock lifetime, **not cleanup of an orphaned real tool**.
Forcibly killing the Python build parent while pip, PyInstaller or a compiler
is still running can leave that external process alive; it must finish or be
stopped before rebuilding that workspace. This change does not introduce
Windows job-object/process-tree supervision or claim that arbitrary external
build processes cooperate with its lock.

No speed or memory improvement is claimed. No package installation, signing,
real executable launch, remote publication or repository staging/commit occurs
in these regression tests.

## Primary references

- [Python `fcntl` locking](https://docs.python.org/3/library/fcntl.html#fcntl.flock)
  documents exclusive and nonblocking file locks on Unix.
- [Python `msvcrt.locking`](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking)
  documents byte-region locking and the immediate-failure `LK_NBLCK` operation
  used for the Windows busy result.
- [PyInstaller usage](https://pyinstaller.org/en/stable/usage.html)
  documents the shared default work/dist paths, `--noconfirm` replacement and
  `--clean` behavior.
- [PyInstaller 6.22.2 build implementation](https://github.com/pyinstaller/pyinstaller/blob/v6.22.2/PyInstaller/building/build_main.py)
  was inspected at `build()`: the spec-name suffix is applied before the
  temporary-directory cleanup loop.
- [Python subprocess behavior](https://docs.python.org/3/library/subprocess.html)
  describes waiting for child processes and descriptor inheritance. This patch
  adds no process-tree supervision beyond the existing subprocess calls.

## Frozen checkpoint validation

Batch 10: final frozen-source discovery passed 3,579 tests in 125.869 seconds (43 platform/hardware skips), with unchanged Python and batch-script hashes. All four area source reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. Paired rendering and recovery measurements bind the final source snapshot and disclose unchanged or slower total-work results. The published batch10 checkpoint `a8fabbc811029a8bfcbe8a5af2a848b034e5cd89` passed complete Windows/Linux regressions, both dependency audits, CodeQL, Windows self-test, bundle build and packaged GUI/native drag-and-drop in [run 42325709249](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42325709249). All four jobs and all seven commit checks succeeded. No 1.0.148 release is published.
