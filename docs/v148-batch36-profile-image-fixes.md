# v1.0.148 — profile, export, recovery and monochrome fixes

## Scope and counting

Baseline: `b22df12d9e17807edc43de7dabf29a113c81edc5` on the draft
`improve/v1.0.148` branch. This batch contains eight specific corrections to
existing behavior. The recovery review also checked `RecoveryImagePreparation`
and `SessionRecovery`; their established preparation/storage implementations
remain unchanged in this batch.

**Zero new improvement IDs: 843/1,000 implemented; 157 remain.** The corrections
complete existing cancellation, settings, profile, recovery and color-management
contracts. The machine registry remains byte-for-byte unchanged. Tests,
assertions, error messages and documentation are not additional improvements.

## Reproduced defects and changes

| Area | Reproduced behavior before the fix | Implemented correction |
| --- | --- | --- |
| PNG export cancellation | Stop arriving while the actual preview/capture snapshot was copied was cleared when the worker began. Both export paths then replaced an existing PNG despite Stop. | Clear a previous Stop only after the save chooser and context checks, before copying. Start the worker with `reset_stop=False`; refuse a newly stopped request, close its private snapshot and retain the existing destination. A later explicit export still works. Completes IW16/global590, IW08/global582 and the established Stop-handoff contract. |
| Profile settings protection and retry | A transient read failure, invalid document or setting-application failure left fallback UI values writable. A later save could replace the original preferences. Profile-change feedback also reported success after failed loading. | Protect the affected settings path, retain a useful error with a retry/reset action, and block dependent saves. Explicitly selecting the same protected profile retries loading without first saving fallback values. Successful loading, confirmed file removal or explicit Reset releases protection. Ordinary same-profile selection remains a no-op. Completes AW08/global622, AW10/global624 and AW13/global627. |
| Legacy profile sections | Schema-0 `False`, `0`, empty string and list sections were discarded by `or {}` before validation. Replace import could publish defaults and delete existing calibration. | Validate every supplied legacy settings/resource/calibration/canvas section before alias/default selection. Missing sections, `null`, empty objects and the existing alias priority remain supported. Completes AW07/global621, AW11/global625 and AW14/global628. |
| Oversized JSON integers | CPython's integer conversion limit raised a plain `ValueError` outside the profile-error boundary. | Report the rejected number through `ProfilePortabilityError`, preserving syntax, Unicode, duplicate-key and nesting diagnostics. The import dialog reports a controlled error before publication. Completes the existing validated-import boundary. |
| Export source file types | Existing directories, dangling symlinks and nonregular calibration paths were treated like absent optional files and silently omitted from an otherwise successful export. | Distinguish actual absence with `stat`/`lstat`, require a regular file before opening, and retain the existing bounded read. Broken links, directories, FIFOs and devices abort packaging before chooser/publication. Regular-file symlinks and genuinely absent optional calibration remain supported. Completes existing profile-export validation and storage contracts. |
| Recovery after a new background edit | After Clear recovery/cache, a successfully accepted background removal or actual Undo scheduled a timer but retained recovery suppression. The new image was not checkpointed. | Release suppression after those two real image adoptions, as other successful image-edit paths already do. No-op, cancelled, rejected and pending-Clear results remain suppressed. Undo does not clear Stop or start drawing. Completes AW17/global631 and A1001/global766. |
| Profile control grouping | Rename/Remove remained visible when the surrounding custom-profile section was collapsed. | Include their existing shared row in the existing disclosure members. Widget ownership, order, logical padding, keyboard operation and builtin/custom-profile scope remain intact. Completes UW805/global756 and existing compact-layout behavior. |
| Monochrome ICC import | A valid mode-`1` PNG with a GRAY ICC profile failed in both file and bitmap-clipboard import because the transform received an incompatible raster mode. | Normalize only that case to an owned `L` image before the existing CMS transform, with an immediate cancellation check. Keep existing alpha/tRNS, sRGB tagging, borrowed-source and cleanup behavior. Completes AX06/global705. |

The UI changes apply consistent grouping and actionable error feedback to the
existing desktop controls. They do not introduce another visual system or
rebuild the sidebar. The native tests exercise 100%, 150% and 200% **widget
scaling**; these Linux observations are not a Windows monitor-DPI claim.

## Executed local verification

Linux x86_64, Python 3.12.14, Pillow 13.0.0. The final combined selection ran
**44 tests: 44 passed, zero failures/errors/skips, in 16.096 seconds**. All
**912 recorded source/fixture/registry hashes** were unchanged during that run.
Three cases used actual Tcl/Tk/CustomTkinter controls on an authenticated Xorg
dummy display, each in an owned child process. Recovery cases additionally
exercise real Tcl timers, workers, PNG preparation, checkpoint publication and
reload.

The accepted before/after comparisons retain the same final test files. A
failure count can exceed the number of affected methods because `unittest`
reports each failed subtest separately; neither count represents new product IDs.

| New regression selection | Methods | Baseline result | Patched result |
| --- | ---: | --- | --- |
| Export snapshot Stop | 8 | 5 passed; 3 affected methods, 4 failed assertions | 8 passed |
| Legacy sections and integer guard | 8 | 4 passed; 4 affected methods, 24 failed assertions | 8 passed |
| Export source paths | 7 | 4 passed; 3 affected methods, 6 failed assertions | 7 passed |
| Recovery after background edit/Undo | 6 | 4 passed; 2 failed methods | 6 passed |
| Profile persistence, without native widgets | 6 | 1 passed; 5 affected methods, 8 failed assertions | 6 passed in UI and combined selections |
| Native profile error/retry/reset | 2 | 2 failed methods | 2 passed in UI and combined selections |
| Native Rename/Remove disclosure | 1 | 1 failed method | 1 passed in UI and combined selections |
| Monochrome GRAY ICC | 6 | 1 passed; 5 affected methods, 8 failed assertions | 6 passed |

All accepted baseline runs completed with zero unexpected errors and zero skips.
The export-source baseline already includes the earlier schema/integer fixes;
it isolates the regular-file correction rather than claiming a whole-tree
baseline. Recovery's baseline preserves the original relevant controller
methods while independent export work was already present elsewhere. ICC uses
the exact original color-management file. UI baselines use a separate worktree
at the recorded baseline commit with only the frozen new tests copied in.

Adjacent executed selections also passed:

- **38/38:** batch15 image-worker cleanup, batch30 Stop/copy and batch03 UI tests.
- **39/39:** existing profile portability, integrity and batch32 export tests.
- **20/20:** the eight new profile-validation cases plus the twelve batch32
  export-lifecycle cases, after the export-source correction.
- **40/40:** nine new UI cases plus 31 existing settings, profile-transaction and
  sidebar cases; includes all three native cases, in 16.222 seconds.

These selections overlap and must not be added as unique tests. The final
44-case run integrates all eight corrections together. Full Windows and Linux
discovery and packaged-app results require the new published commit's CI;
their exact-head results are recorded in
[PR #46](https://github.com/Vxiey/Image-Draw-Bot/pull/46).

```bash
python -m unittest -v \
  test_v148_application_batch36_export_stop \
  test_v148_application_batch36_profile_validation \
  test_v148_application_batch36_profile_export_sources \
  test_v148_application_batch36_recovery_resume \
  test_v148_ui_batch36_profile_load \
  test_v148_ui_batch36_profile_group \
  test_v148_image_batch36_monochrome_icc
```

Native UI tests require a display. The FIFO/device case is POSIX-specific;
symlink cases skip only explicit platform/privilege limitations. This local
combined run supported all of them, so none were skipped.

## Regression boundaries and evidence

The new raster tests derive their pixels from the repository's existing
`paint-tools-reference.png` and `image-draw-bot-icon.png`. No new test motif,
mockup or AI image is introduced. Tests use real PNG encoding, existing atomic
writers, actual CMS, settings files, registries and worker/controller paths.
Fault injection is limited to the boundary being tested, such as denied reads,
thread construction, setting application and CMS failure. The export startup
failure is at **thread construction**, not `Thread.start`.

Controls verify explicit export after a previous Stop, chooser cancellation,
Stop after actual encoding, preserved destination bytes, successful legacy
imports, both profile import modes, optional calibration, regular symlinks,
successful settings retry/reset, rejected recovery results, source ownership,
both monochrome transparency keys and untagged/L/LA/unsigned-16 image paths.

An initial adjacent export run reported one fixture error: its older fake worker
did not accept the existing `reset_stop` keyword. The fixture now accepts that
argument and explicitly asserts `False`; all earlier assertions remain. The
38-case rerun passed. Early native harness issues (a helper import, reserved
`load_tests` name, child-test identity and Reset label) were corrected before
the accepted frozen comparisons. Failed display setup probes are environment
diagnostics. The first ICC oracle pair used a deprecated Pillow read helper;
the final frozen pair uses `getpixel` without that warning. These attempts are
retained separately in the [validation record](v148-batch36-validation.json),
not counted as product-defect proof or accepted passing runs.

Independent source/test reviews found no blocker. The validation record binds
actual commands, per-run results, source hashes, retained failure evidence and
the combined source snapshot. Source-package hygiene passed for **1,395 files**, without warnings or
forbidden/missing paths. `git diff --check` passed. Both checks are recorded
there after the final documentation was assembled.

## Full-suite CI follow-up

The first published commit, `5e95afd0b5f4767ef2423c03316587ddbd469c79`,
completed Linux discovery with **4,647 tests in 314.809 seconds** but reported
**16 errors across four methods**, with 81 skips. Every error was the same
worker-adapter signature mismatch in the two older preview/capture modules;
the 41 new portable cases passed and the three new native cases were skipped
on that headless runner. The failed
[CI job](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43035849444/job/130574326842)
and representative tracebacks are retained in the validation record.

A separate fixture-only correction makes both adapters accept the existing
`reset_stop` keyword and explicitly require `False` before queuing the job.
All **14 existing test methods**, their earlier assertions and raster fixtures
remain unchanged. No product file, new regression, timeout, skip or CI gate was
changed. No additional local runtime test is claimed for this follow-up; its
verification is the subsequent complete Windows/Linux CI on the new commit.
The original 912-file local map remains bound to its original run, with the
exact two changed fixture hashes recorded separately. PR46 records the final
commit's results without presenting this failed attempt as a passing run.

## Limits and review history

The file-type check does not claim to eliminate a separate `stat`/`open` race.
The new local tests do not operate physical Paint, the system clipboard,
Windows monitors or GPU hardware. Existing rendering engines, dependencies,
PNG storage formats and version number remain unchanged.

The previous live PR description is preserved exactly after an archive header
in [the batch35 history](pr46-history-through-batch35.md), including its earlier
CI evidence and links to older history. Those earlier green checks are not
verification of this patch. The PR remains draft; merge and release require
the user's explicit approval.
