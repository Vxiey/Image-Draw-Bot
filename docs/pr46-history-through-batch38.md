# PR #46 history through batch 38

Archived before batch39 from the open draft at `74c3a510416b56bff84e70353622e3a91884f09e`.
This records earlier implementation and exact-head CI; those checks do not verify later commits.

## Current checkpoint: 844/1,000; 156 remain

**Draft; v1.0.148 remains unreleased. Merge, tagging and release require explicit user approval.**

Current head: `74c3a510416b56bff84e70353622e3a91884f09e`. Batch38 follows `b8fb914b020f879a6c1c72434abb6f9f0f6725dd` and implements eight profile/image/planner corrections. **Only P3801/global844 is new.** The other seven groups complete existing contracts. All 843 preceding registry objects and 132 earlier JSON reports, including 84 benchmark reports, remain unchanged.

[Review this batch](https://github.com/Vxiey/Image-Draw-Bot/compare/b8fb914b020f879a6c1c72434abb6f9f0f6725dd...74c3a510416b56bff84e70353622e3a91884f09e) · [Implementation ledger](https://github.com/Vxiey/Image-Draw-Bot/blob/74c3a510416b56bff84e70353622e3a91884f09e/docs/v148-batch38-lifecycle-and-planning.md) · [Validation](https://github.com/Vxiey/Image-Draw-Bot/blob/74c3a510416b56bff84e70353622e3a91884f09e/docs/v148-batch38-validation.json) · [Raw evidence](https://github.com/Vxiey/Image-Draw-Bot/blob/74c3a510416b56bff84e70353622e3a91884f09e/docs/v148-batch38-evidence.json)

### What changed and why

1. **Replace-import retires destination-owned legacy calibration.** Generic positions/palette and Paint legacy tools join the existing staged file-set publisher. Copy import and other owners retain their sources. Handled failures roll back before reload; a failed rollback retains recovery backups. Individual renames are atomic; no crash-atomic file-set guarantee is added.
2. **Published profiles fit their actual readers.** Validate final UTF-8 output after owner rewrite/conversion: 256 KiB settings, 128 KiB tools/exact colors and 2,000 Paint-tool JSON values. Rejection precedes publication.
3. **Export includes active legacy calibration.** Pure capture follows normal fallback semantics without mutating color globals, caches or migration files. Canonical priority and source validation are preserved.
4. **Resume identity includes active legacy sources.** Changed generic click positions/colors invalidate the actual old checkpoint; shadowed files and unrelated profiles do not affect identity.
5. **Saved-area target probes honor Stop.** The controller forwards cancellation to the existing helper process, checks late results, restores the browser region with other geometry and suppresses shutdown feedback. Actual child-process tests verify termination/reaping/pipe closure.
6. **P3801: smaller opaque Auto-count preparation.** RGB/L reduce before full RGB preparation; opaque RGBA reduces one source channel at a time through public Pillow BOX calls. Exact pixels, recommendation metadata and tuner behavior are retained. Mixed alpha/color-key inputs retain full composition.
7. **Resize work has explicit ownership.** Failed native frames and private images are released before CPU fallback; borrowed input stays open. Cleanup preserves the primary failure/Stop. This completes GP06/IW08, not a new GPU feature.
8. **Extra Fast reuses exact costs within one bounded operation.** Original candidate selection is unchanged. Existing PreparedPathCost descriptors are limited to 4,096 entries/65,536 points, with ordinary-model fallback, Stop, OOM recovery and final cleanup. This completes R1403/global789 with zero new IDs.

### Executed local verification

| Run | Actual result |
| --- | --- |
| Final new-test integration | **63/63 passed**, 0 failures/errors/skips, **3.785 s** |
| Complete Linux headless discovery | **4,736 tests: 4,650 passed, 86 skipped**, 0 failures/errors, **250.327 s** |
| Real Linux/Xorg profile windows | **7/7 existing native cases**, 0 skips, **29.465 s** |
| Source gate | **5,000 cycles passed** |
| Source-package hygiene | **1,415 files**, no forbidden/missing paths or warnings |
| Independent source/test reviews | All eight groups approved; no blocking findings |
| Patch whitespace | `git diff --check` passed |

The three final test runs share **954 unchanged source/configuration/fixture hashes**. The seven native cases are existing methods skipped by headless discovery; they are not additional new tests. Local Python was 3.12.14, Pillow 13.0.0.

The exact b8 before/after comparisons use identical frozen test bytes: **63 unique methods, 14 baseline passes and 49 failing methods with 80 assertion failures; final 63 pass, zero errors/skips**. Five renderer baseline failures simply assert the new owner exists; one further method contains two real repeated-work failures. They are not seven old user bugs. Overlapping adjacent selections are not added to the new-test count.

### Measurements and rejected work

Whole-recommendation Auto-count measurements retain full pixel/metadata parity. Observed live private PIL channel samples fall from 6,087,168 to 2,062,848 for the opaque screenshot and 14,085,120 to 67,584 for its L version. These are **channel samples, not bytes or RSS**. Timings include unchanged/slower controls; no universal CPU speedup is claimed.

Accepted Extra Fast measurements compare exact b8 with the combined working branch: six balanced pairs, **144 timed whole public plans in 48 fresh processes**, plus 16 separate tracemalloc calls. Warm medians (before → after):

- Line Art reference: **98.512 → 96.054 ms**.
- Smaller Line Art control: **67.806 → 59.183 ms**.
- Current-color icon: **167.255 → 146.060 ms**.
- Fractional screenshot control: **96.795 → 92.046 ms**.

All compared plans, estimates, metadata, source/preview/palette pixels and final safety-plan ink match. Direct repeated-work controls reduce full `path_cost` calls **141 → 68** and **432 → 94**. The screenshot's traced peak rises by 14,944 bytes cold/12,502 bytes warm. These are Linux planning observations, not physical Paint/GPU or general memory claims. The timing manifest covers 19 files plus a derived DrawBot AST, not every transitive dependency.

**The broader regional-axis search was rejected and removed:** complete planning time outweighed modeled input savings. Its source snapshots, negative timings and three-way exploration are retained separately. Initial fixture/oracle diagnostics and earlier test selections also remain explicit. New image tests use existing repository assets and derived modes/sizes; no AI image or new source motif was introduced.

### Exact-head CI

**All seven checks succeeded for `74c3a510416b56bff84e70353622e3a91884f09e` on workflow attempt 1.** No rerun was needed.

| Executed job | Actual complete-suite result | New batch38 methods | Separate exact-raster/planner selection |
| --- | --- | --- | --- |
| [Windows Python 3.12](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43070181047/job/130695626234) | **4,736 total; 4,731 passed, five skipped**, 0 failures/errors, **705.712 s** | **62 passed, one POSIX-only FIFO case skipped** | **56/56**, 10.444 s |
| [Linux Python 3.12](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43070181047/job/130695626140) | **4,736 total; 4,650 passed, 86 skipped**, 0 failures/errors, **240.654 s** | **63/63 passed** | **56/56**, 5.388 s |

Windows' five skips are **three unavailable GPU/device cases and two POSIX-only FIFO/device cases**. The new FIFO export test passed on local Linux and Linux CI. No platform/hardware skip is described as an executed pass.

All **14 Windows job steps** passed, including source self-test, bundle build/validation and packaged GUI/native drag-and-drop. Both runners also passed source-package hygiene and Extra Fast benchmark smoke. [Full CI workflow](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43070181047).

[Windows dependency audit](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43070181047/job/130695626322), [Linux dependency audit](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43070181047/job/130695625961), [CodeQL Python](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43070168868/job/130695588776), [CodeQL Actions](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/43070168868/job/130695588923) and the [aggregate CodeQL check](https://github.com/Vxiey/Image-Draw-Bot/runs/130695909710) all succeeded.

Raw Linux job-log SHA-256: `8f646c723a1e569038581291061388c119a847fe197637f542204c3226c47400`.
Raw Windows job-log SHA-256: `213260bc642210380224f2c11c4af44c1e81fa21a3b91497540973e9904a91e5`.

### Preserved previous checkpoint

[Previous PR description through batch37](https://github.com/Vxiey/Image-Draw-Bot/blob/74c3a510416b56bff84e70353622e3a91884f09e/docs/pr46-history-through-batch37.md) preserves b8's seven green checks, Windows 4,673 total/4,669 passed/four skipped, Linux 4,673 total/4,587 passed/86 skipped, and the initial old Node timeout followed by one successful unchanged Windows-job rerun. No failure history has been removed.

The target remains 1,000 distinct behavior improvements. Version 1.0.148 is not ready for release merely because this batch passes its checks.
