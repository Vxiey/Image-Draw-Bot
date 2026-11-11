# PR #46 history through batch 36

The following is the exact previous PR description, archived before the batch37
continuation. Its latest verified head was
`e7c13861346129227c7696e348fecb396933cda7`; those results do not verify later code.

---

## Current checkpoint — profile, export, recovery and image fixes

**Head: `e7c13861346129227c7696e348fecb396933cda7`. Draft; not merged or released.**

**843/1,000 distinct improvements implemented; 157 remain.** This continuation corrects eight gaps in existing behavior and assigns **zero new IDs**. The machine registry is byte-identical to the preceding verified checkpoint.

### What this patch fixes

1. **Stop during PNG snapshot copying.** Preview and captured-image exports no longer clear a newly requested Stop when their worker starts. Existing destination bytes survive; a later explicit export still succeeds.
2. **Failed profile loads cannot overwrite saved preferences.** Read/validation/application errors protect the affected settings path. The UI retains actionable error feedback; selecting the same profile retries without saving fallback values first. Successful loading, confirmed removal or explicit Reset releases protection.
3. **Legacy profile sections are validated before fallback selection.** Schema-0 falsey nonobjects cannot silently become empty settings/calibration in a Replace import. Missing/null/object forms and alias priority remain compatible.
4. **Oversized JSON integers produce controlled import errors.** CPython's conversion limit is translated through the profile error boundary, without replacing syntax/Unicode/duplicate-key diagnostics.
5. **Export distinguishes absent calibration from unusable paths.** Existing directories, broken links, FIFO and device sources abort packaging instead of silently disappearing from the export. Regular-file symlinks and genuinely optional absent files remain supported.
6. **Recovery resumes after an accepted background edit or actual Undo.** Clearing old recovery no longer suppresses checkpointing of those new image states. No-op, stopped, rejected and pending-Clear results remain suppressed; Undo does not restart drawing.
7. **Rename/Remove follow their profile disclosure group.** Their existing row now collapses/reopens consistently, preserving widget ownership, ordering, padding, keyboard access and profile scope.
8. **Monochrome PNG with a GRAY ICC profile imports correctly.** Mode `1` is normalized to owned `L` data before the existing CMS transform. Both transparency keys, sRGB tagging, cancellation and borrowed-source ownership are preserved.

The runtime changes are confined to **DrawBot.py, ProfilePortability.py, UICompactLayout.py and ImageColorManagement.py**. Existing RecoveryImagePreparation/SessionRecovery implementations, rendering engines, dependencies and version remain unchanged.

**CI fixture follow-up:** the first full Linux run exposed two older worker adapters that did not accept `reset_stop`. Both now accept the established keyword and explicitly require `False`. All 14 existing test methods and earlier assertions are preserved. The product files and all 44 new tests are unchanged; the two fixture hashes are the complete source delta from the recorded local gate.

### Actual local verification

Linux x86_64, Python 3.12.14, Pillow 13.0.0:

| Selection | Result |
| --- | --- |
| All seven new regression modules together | **44/44 passed**, 0 errors/skips, **16.096 s** |
| Native UI within that combined run | **3/3 passed** on real Tcl/Tk/CustomTkinter, isolated child processes |
| Recorded source/fixture/registry files during combined run | **912/912 hashes unchanged** |
| Existing export/Stop/cleanup selection | **38/38 passed** after correcting one older fixture's worker keyword signature |
| Existing profile portability/integrity/export selection | **39/39 passed** |
| Validation plus prior export-lifecycle selection | **20/20 passed** |
| New UI plus adjacent settings/transaction/sidebar selection | **40/40 passed**, including the three native cases |
| Source-package hygiene | **1,395 files**, no missing/forbidden paths or warnings |
| Whitespace check | Passed |

These selections overlap; their counts are **not** added as unique tests. The 44-method run is the final combined local gate. Before/after evidence reproduces actual overwritten export bytes, preference preservation failures, malformed import acceptance, omitted export sources, missing recovery checkpoints, incorrect disclosure visibility and rejected valid ICC imports. Failed subtests and child/parent output are distinguished from unique methods.

All new raster tests use existing repository PNG assets. No new test motif, mockup or AI image was introduced. Fault injection targets the specific I/O/application/startup/transform boundary while retaining actual storage, encoding, controller and CMS paths. The UI tests cover 100/150/200% widget scaling; they do not claim Windows monitor-DPI or physical Paint verification.

### Exact-head CI

<!-- batch36-ci-status -->
**All seven exact-head checks passed for `e7c13861346129227c7696e348fecb396933cda7`.**

- [Application CI run 43037666794](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43037666794): both complete regression jobs and both dependency audits passed.
- [CodeQL run 43037655881](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43037655881): Python/Actions analysis and the aggregate CodeQL check passed.

| Full discovery | Tests run | Passed | Skipped | Duration |
| --- | ---: | ---: | ---: | ---: |
| [Windows / Python 3.12.10](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43037666794/job/130580734824) | **4,647** | **4,643** | **4** | **494.374 s** |
| [Linux / Python 3.12](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43037666794/job/130580734175) | **4,647** | **4,566** | **81** | **302.243 s** |

Both suites completed with **zero failures and zero errors**. Each platform also passed the separate **56-case exact-raster/portable-planner selection**, Extra Fast smoke and source-package checks.

All **14 Windows job steps succeeded**, including `DrawBot.py --self-test`, the Windows bundle build/validation and the packaged executable's GUI/native drag-and-drop smoke test. All three new native UI cases passed on Windows. Among the 44 new cases, Windows passed 43 and skipped the one POSIX-only case; headless Linux passed 41 and skipped the three native cases. The recorded local Xorg run executed all 44 without skips.

The four Windows skips are **three unavailable GPU cases and one POSIX FIFO/device case**. Linux skips are Windows/native-display/hardware cases. These results do not claim physical Paint drawing or real GPU execution.

<details>
<summary>Initial failed run and fixture-only correction</summary>

The initial [Linux full-suite job](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43035849444/job/130574326842) on `5e95afd0b5f4767ef2423c03316587ddbd469c79` completed 4,647 tests in 314.809 s, with 16 errors across four methods and 81 skips. The initial [Windows job](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43035849444/job/130574326856) completed 4,647 tests in 598.763 s, with the same 16 errors across four methods and four skips.

Every error was an older worker adapter rejecting the existing `reset_stop` keyword before its export checks ran. Two adapter signatures were updated and now explicitly require `False`. All 14 existing test methods, their earlier assertions and raster fixtures remain unchanged. Product code and all 44 new regressions were unchanged. No timeout, skip, test selection or CI gate was weakened.

The complete reruns on `e7c13861346129227c7696e348fecb396933cda7` above verify the correction. The initial failed attempt and exact two-fixture source delta remain in the validation record; no failed run is presented as passing.

</details>
<!-- /batch36-ci-status -->

### Review and evidence

- [Eight corrections, compatibility decisions and regression details](https://github.com/Vxiey/Image-Draw-Bot/blob/e7c13861346129227c7696e348fecb396933cda7/docs/v148-batch36-profile-image-fixes.md)
- [Commands, results, source hashes, retained failures and combined verification](https://github.com/Vxiey/Image-Draw-Bot/blob/e7c13861346129227c7696e348fecb396933cda7/docs/v148-batch36-validation.json)
- [Improvement ledger — still 843/1,000](https://github.com/Vxiey/Image-Draw-Bot/blob/e7c13861346129227c7696e348fecb396933cda7/docs/IMPROVEMENTS-v1.0.148.md)
- [Previous live PR description preserved through batch35](https://github.com/Vxiey/Image-Draw-Bot/blob/e7c13861346129227c7696e348fecb396933cda7/docs/pr46-history-through-batch35.md)

Independent source/test reviews and a separate evidence audit found no blocker. Initial fixture/display/oracle diagnostics remain explicitly separated from accepted results. The regular-file check does not claim to eliminate a separate stat/open race. No new local physical Paint, system-clipboard or GPU result is claimed.

**Merge and release require the user's explicit approval after reviewing the changes.** The 1,000-improvement target and planned release verification remain incomplete.
