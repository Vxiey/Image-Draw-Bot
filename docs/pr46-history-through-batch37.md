# PR #46 — verified history through batch 37

The following is the exact PR body captured before batch 38, for commit
`b8fb914b020f879a6c1c72434abb6f9f0f6725dd`. Its results belong to that commit.
The original body follows the separator without rewriting its CI history.

---

## Development status

**843 distinct behavior improvements implemented / 1,000 requested. 157 remain. Version 1.0.148 is unreleased.**

This remains a **draft**. No merge, tag or release without Felix's explicit approval after reviewing the changes. Tests, assertions, documentation and corrections within existing contracts do not add improvement IDs.

## Current continuation: batch37

Current head: `b8fb914b020f879a6c1c72434abb6f9f0f6725dd`.

Four reproduced lifecycle defects are corrected:

1. **Generic profile Reset:** include `positions.txt` and `palette.json` in the existing atomic reset transaction for Other drawing app only. Its real palette reader can no longer reimport old calibration immediately after Reset. Other profiles and shared data remain intact, with full rollback on failure.
2. **Profile reload feedback:** Import, Reset, Rename and Remove retain a failed settings-load error after the saved change completes. A warning identifies the completed operation and the failed reload. Same-profile retry loads the committed files without a second import, a new UUID or saving fallback values.
3. **Recovery decision ownership:** recheck the offered checkpoint and current image after the modal dialog. Reject stale Yes/No without cancelling the newer source's encoder. A valid Yes retires the previous autosave timer/encoder. No compares and deletes under the existing publisher lock, including after waiting for a cancelled encoder; newer checkpoints survive.
4. **Cancelled canvas adoption:** preserve the previous geometry, target/browser region, saved settings and plan through Stop, shutdown or failed analysis. Commit setup changes after analysis and cancellation checks. Successful selection still invalidates the old plan and input authorization.

**Zero new IDs.** These complete existing reset/migration, protected-load, recovery and cancellation contracts. The machine registry is byte-for-byte unchanged at 843/1,000.

- [Batch37 change ledger](docs/v148-batch37-lifecycle-fixes.md)
- [Commands, frozen comparisons, source hashes and validation](docs/v148-batch37-validation.json)
- [Review this continuation against its verified parent](https://github.com/Vxiey/Image-Draw-Bot/compare/e7c13861346129227c7696e348fecb396933cda7...b8fb914b020f879a6c1c72434abb6f9f0f6725dd)

## Local executed evidence

All accepted before runs use exact parent `e7c13861346129227c7696e348fecb396933cda7` in a separate worktree. Each before/after pair has identical frozen test bytes.

| Selection | Before | After |
| --- | --- | --- |
| Legacy palette Reset — 5 methods | 3 passed; 2 methods failed, with 4 failing subtests | 5/5 passed |
| Native profile feedback — 5 methods | 1 passed; 4 methods failed | 5/5 passed |
| Recovery dialog — 10 methods | 3 passed; 7 methods failed | 10/10 passed |
| Canvas adoption — 6 methods | 2 passed; 4 methods failed | 6/6 passed |
| **All four modules together** | — | **26/26 passed, zero errors/skips, 23.993 seconds** |

The combined run used Python 3.12.14/Pillow 13.0.0 and real Linux Xorg/Tcl/Tk/CustomTkinter. **919 source/asset/registry hashes remained unchanged.** The five native profile cases use the actual application, registry, saved files and selector retry in isolated children. The 21 other cases use real controller/storage/detector paths without native windows.

Adjacent executed selections passed **11/11 profile/palette**, **8/8 recovery/Clear** and **11/11 picker/profile-transaction** cases. These runs overlap existing coverage and are not new improvements. Independent source/test reviews found no blockers; static inventory confirmed 26 unique new methods without imported TestCase duplication.

Source-package hygiene: **1,402 files, no warnings, forbidden paths or missing required files**. Staged whitespace validation passed.

New raster tests read only existing repository PNG/WebP assets. No new synthetic image motifs, mockups or AI-generated images were introduced. Local runs do not claim physical Paint, actual Win32 target capture, Windows DPI, system clipboard or GPU verification. Conditional recovery deletion is atomic; no whole-dialog/whole-decode external-publication lock is claimed.

Initial rollback-fixture diagnostics, a repeated recovery baseline and an unfrozen canvas draft are explicitly separated from accepted evidence. Native child failures are not counted again as additional parent methods.

<!-- batch37-ci:start -->
## Exact-head CI — complete

**All seven checks passed for `b8fb914b020f879a6c1c72434abb6f9f0f6725dd`.** [Application CI, attempt 2](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43044246005/attempts/2) is successful. Both dependency audits and the three CodeQL checks passed.

| Executed selection | Total methods | Passed | Skipped | Time |
| --- | ---: | ---: | ---: | ---: |
| [Windows full suite — successful rerun](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43044246005/job/130611686010) | 4,673 | **4,669** | 4 | 565.959 s |
| [Linux full suite — original successful job](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43044246005/job/130603854378) | 4,673 | **4,587** | 86 | 233.738 s |
| Separate Windows raster/planner selection | 56 | **56** | 0 | 7.643 s |
| Separate Linux raster/planner selection | 56 | **56** | 0 | 5.958 s |

All **26 new cases passed on Windows**, including the five native profile-feedback cases. Linux passed the 21 portable new cases and skipped those five display-dependent cases; all 26 had also passed together locally with a real display. These selections overlap and are not additive unique-test counts.

Windows' four skips are three unavailable CUDA/OpenCL hardware/dependency cases and one POSIX FIFO/device fixture. All **14 Windows job steps succeeded**, including source-package hygiene, Extra Fast smoke, complete regressions, Windows self-test, bundle build/validation and the **packaged GUI/native drag-and-drop smoke**.

### Retained first-attempt failure

The [first Windows job](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43044246005/job/130603854934) completed **4,673 tests in 580.003 seconds with one error and four skips**. All 26 new cases passed. The sole error was `TimeoutExpired` in the unchanged `MobileBrowserTests.test_available_view_is_accessible_and_loads_its_own_image`: its first Node process exceeded the existing five-second timeout. The four following Node mode processes passed quickly. That attempt did not reach self-test/build/packaged-app verification.

The four existing text-only `MobileBrowserTests` then passed locally in **0.423 seconds** with unchanged source hashes and the original timeout, skips and assertions. Read-only reviews found no deterministic timer/socket/thread leak or batch37 import-side effect; the mobile product/test code and CI workflow are byte-identical to the parent. **The cause of the single timeout remains unproven.**

Only the failed Windows job was requested for rerun, on the **same commit**. The unchanged full rerun and all subsequent Windows steps passed. No product code, fixture, assertion, timeout, skip or CI gate was changed between attempts. The first failed attempt remains negative evidence; it is not reported as a passing run.
<!-- batch37-ci:end -->

## Retained work and history

The preceding verified head, `e7c13861346129227c7696e348fecb396933cda7`, passed all seven checks. Its Windows run executed 4,647 tests: 4,643 passed and four skipped (three GPU, one POSIX file-type case); Linux executed 4,647: 4,566 passed and 81 skipped. Both separately passed 56 raster/planner tests. All fourteen Windows job steps, including self-test, bundle build and packaged GUI/native drag-and-drop smoke, succeeded.

The exact previous PR description, prior CI failure/fix history and earlier continuation links are preserved in [batch36 history](docs/pr46-history-through-batch36.md). Batch36's [eight corrections](docs/v148-batch36-profile-image-fixes.md), batch33's [UI readability work](docs/v148-batch33-ui-readability.md), original [improvement ledger](docs/IMPROVEMENTS-v1.0.148.md), [registry](docs/v148-improvements.json) and [working progress](docs/v148-improvement-progress.md) remain available.

**The 1,000-improvement target and planned final release verification remain incomplete. This PR stays draft.**
