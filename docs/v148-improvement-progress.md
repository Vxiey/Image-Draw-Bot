# Image Draw Bot 1.0.148 improvement progress

## Requested result

Continue application-wide correctness, performance and security improvements, with a target of **1,000 distinct improvements**, then release **1.0.148**. The 100 already reviewed and merged improvements form the starting point; formatting, tests, documentation and version bumps do not count as additional product improvements.

## Current state

Batch 16 implements **807 total distinct improvements, with 193 remaining**.
All four new groups and existing-contract completions have closed independent
source reviews. Final frozen-source integration completed **3,923 tests**:
**3,872 passed and 51 platform/hardware cases skipped**, with all
830 source/configuration hashes unchanged. The 5,000-cycle source
gate, source-package hygiene, eight exact-raster fixtures and all eight paired
preview workloads passed. [Final local evidence](v148-batch16-validation.json)
is separate from the published-commit Windows/CI gate recorded in PR46.
The preceding 803-group checkpoint `86fa125306b9c2db8e8125fec6a38270b09c8ff9`
passed all seven checks, including Windows self-test, bundle validation and
packaged GUI/native drag-and-drop in [run 42377334258](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42377334258).
The release condition remains 1,000 independently verified behavior changes.

- The first 100 improvements are merged on `main` at `eb9804560c8648a92aabe2688e362a6b4a1d28b5`; Windows and Linux CI passed for their reviewed source head.
- Version 1.0.147's promotion PR was closed unmerged after the target changed. The RC4 release run was cancelled before publication.
- Development continues on `improve/v1.0.148`, based on `94a748ec7690eebb542c70311c594aa835434a98`. No 1.0.148 release has been published.
- Batch 01 adds 162 distinct changes: colour/GPU 40, planning/geometry 40, storage/resources 41 and UI/input 41. All four areas received independent source review; whole-program local integration passed 2,202 tests with 19 platform/hardware skips. Draft [PR46](https://github.com/Vxiey/Image-Draw-Bot/pull/46) publishes checkpoint `1c09774ad22088c5c30a8f8220b6b451fdee9659`.
- The checkpoint's Linux, dependency and CodeQL checks passed. Its Windows test job exposed a concurrent atomic-publication sharing failure. Batch 02 serializes publication and retries the bounded Windows sharing errors; Windows CI verified the correction. It is not counted again as a new improvement.
- Batch 02 adds 236 independently reviewed changes: calibration 69, delivery/planning 73, storage/resources 38 and UI/input 56. Whole-program local integration passed 2,557 tests (22 platform/hardware skips), the 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures. Published head `2fb7abf470a4ef498df9c53f42cddda62d8b652b` passed the Windows/Linux regression, dependency, CodeQL and packaged Windows GUI/native drag-and-drop checks in [run 42260646614](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42260646614). Windows first hit three subprocess startup timeouts; one rerun passed with unchanged source and unchanged test timeouts. At that checkpoint the combined implemented count was 498, with 502 remaining before the requested release target.
- The requested count of 1,000 has **not** been reached. No release claims, antivirus verdicts or signing status should be inferred from source improvements or old binary scans.

Batch 03 adds 116 distinct changes: colour quality 16, rendering/planning 38,
GPU/platform 22 and image workflow/UI 40. That checkpoint brought the implemented total to **614**. Final frozen-source integration passed 2,800 tests in 70.634 seconds
with 22 platform/hardware skips and unchanged source hashes. All four independent
area reviews are closed. The 5,000-cycle source gate, source-package hygiene for
860 files and eight exact-raster fixtures also passed. Checkpoint `2aca72acb36b547d75e12a0a59d78325552c21a8` passed Windows/Linux, dependency, CodeQL and packaged Windows GUI/native drag-and-drop CI in [run 42273234504](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42273234504). The initial Ubuntu Node-startup timeout passed on rerun with unchanged source and test timeout.

Batch 04 adds 54 distinct changes: application workflow 27, planning 9,
UI/profiles 13 and native input/helper lifecycle/privacy 5. That checkpoint brought the implemented total
to **668**, with **332 remaining**. Frozen-source integration passed **2,934 tests
in 75.509 seconds**, with 23 platform/hardware skips and unchanged source hashes.
Independent source and cross-area reviews are closed. The 5,000-cycle source gate,
source-package hygiene and eight exact-raster engine fixtures passed. This new
checkpoint `5f3fcfb5c4519e5ed1b9b770ba951918819d725d` passed Windows/Linux,
dependencies, CodeQL and packaged Windows GUI/native drag-and-drop checks in
[run 42280910774](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42280910774).

Batch 05 adds 31 independently reviewed groups: application execution/recovery 7,
colour/planning 6, UI/workflow 13 and source/release publication 5. The implemented
total is **699**, with **301 remaining**. Frozen-source integration passed **3,059 tests in 73.421 seconds**, with 26
platform/hardware skips and unchanged source hashes. All area and final
adaptive-probe/correction reviews are closed. The 5,000-cycle source gate,
source-package hygiene for 918 files and eight exact-raster fixtures passed.
Checkpoint `4c8aa247f852df7225b5e7d10ce4ac151e612226` passed Windows/Linux
regressions, both dependency audits, CodeQL, the Windows self-test/bundle build
and packaged GUI/native drag-and-drop checks in
[run 42289019482](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42289019482).
Its preceding Windows attempt exposed fixture assumptions about temporary 8.3
path aliases and blank Tcl binding-script lines. Only the two test files changed
in the correction; callback identities and native event delivery are verified.
No 1.0.148 release is published.

Batch 06 adds 30 independently reviewed groups: application 7, rendering/planning 7, UI/calibration 11 and platform/diagnostics 5. The total is **729**, with **271 remaining**. Batch 06: final frozen-source discovery passed 3,201 tests in 71.794 seconds (31 platform/hardware skips), with unchanged source hashes. All four area reviews and the separate ICC/alpha and delivered-probe reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. The existing Windows scaling and compact-height repairs through `ace8fd741b363ab9f7a01ccd1fad94231a70a1f4` passed complete Windows/Linux regressions, both dependency audits, CodeQL, Windows self-test, bundle build and packaged GUI/native drag-and-drop in [run 42300520218](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42300520218). These repairs add no duplicate improvement IDs. No 1.0.148 release is published.

Batch 07 adds 16 independently reviewed groups: application 3, rendering/planning 6, UI/workflow 4 and platform/import 3. The total is **745**, with **255 remaining**. Batch 07: final frozen-source discovery passed 3,355 tests in 71.096 seconds (35 platform/hardware skips), with unchanged source hashes. All four area reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. Checkpoint `73788a51c1a3502f03f007e4d2ffe0152f56b7e6` passed complete Windows/Linux regressions, both dependency audits, CodeQL, Windows self-test, bundle build and packaged GUI/native drag-and-drop checks in [run 42302890291](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42302890291). No 1.0.148 release is published.

Batch 08 adds 14 independently reviewed groups: application 2, rendering/planning 4, UI/workflow 6 and platform/build 2. The total is **759**, with **241 remaining**. Batch 08: final frozen-source discovery passed 3,462 tests in 81.280 seconds (39 platform/hardware skips), with unchanged source hashes. All four counted-area source reviews are closed; review findings were corrected with regressions. The 5,000-cycle source gate, source-package hygiene and eight exact-raster fixtures passed. The earlier full-suite failure was an outdated fake cost-model interface; its swap-selection assertions are preserved. The batch08 checkpoint plus its native keyboard-test fixture repair at `ab2a59bd1432aac7528d378cef2c4ebcf689a47b` passed complete Windows/Linux regressions, both dependency audits, CodeQL, Windows self-test, bundle build and packaged GUI/native drag-and-drop in [run 42309898941](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42309898941). The repair starts Tab traversal from the actually focused native entry and adds no improvement ID. No 1.0.148 release is published.

Batch 09 adds **6 distinct groups**: application 1, rendering 1, UI/workflow 3 and platform 1. The implemented total is **765**, with **235 remaining**. Batch 09: final frozen-source discovery passed 3,514 tests in 190.952 seconds (42 platform/hardware skips), with unchanged Python and batch-script hashes. All four area source reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. The published batch09 checkpoint `3c5fe8fc27ec3b503e2affa6f3ed00cb7856f973` passed complete Windows/Linux regressions, both dependency audits, CodeQL, Windows self-test, bundle build and packaged GUI/native drag-and-drop in [run 42320087469](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42320087469). All four jobs and all seven commit checks succeeded. No 1.0.148 release is published.

Batch 10 adds **8 distinct groups**: application 1, rendering 4, UI/workflow 2 and platform 1. The implemented total is **773**, with **227 remaining**. Batch 10: final frozen-source discovery passed 3,579 tests in 125.869 seconds (43 platform/hardware skips), with unchanged Python and batch-script hashes. All four area source reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. Paired rendering and recovery measurements bind the final source snapshot and disclose unchanged or slower total-work results. The published batch10 checkpoint `a8fabbc811029a8bfcbe8a5af2a848b034e5cd89` passed complete Windows/Linux regressions, both dependency audits, CodeQL, Windows self-test, bundle build and packaged GUI/native drag-and-drop in [run 42325709249](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42325709249). All four jobs and all seven commit checks succeeded. No 1.0.148 release is published.

Batch 11 adds **4 distinct groups**: automatic rescue, complete brush-pack selection, native canvas rounding and composed Sketch Fill ownership. The implemented total is **777**, with **223 remaining**. Batch 11: final frozen-source discovery passed 3,602 tests in 128.751 seconds (43 platform/hardware skips), with unchanged Python and batch-script hashes. Independent source reviews are closed for all four behavior groups. The 5,000-cycle source gate, source-package hygiene and eight exact-raster fixtures passed. Paired pack-selection measurements bind the final source and disclose planning overhead separately from modeled drawing cost. The published batch11 checkpoint `b0eedca7d8d63fde5c9da6a1cffb394613ff95bf` passed complete Windows/Linux regressions, both dependency audits, CodeQL, Windows self-test, bundle build and packaged GUI/native drag-and-drop in [run 42330134079](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42330134079). All four jobs and all seven commit checks succeeded. No 1.0.148 release is published.

Batch 12 adds **2 distinct groups**: keyboard operation of existing boolean settings and operation-local Pixel score preparation. The implemented total is **779**, with **221 remaining**. The physical-brush policy correction completes the existing R901 contract and adds zero IDs. Batch 12: final frozen-source discovery passed 3,626 tests in 150.380 seconds (45 platform/hardware skips), with unchanged Python and batch-script hashes. Independent source reviews are closed for both new behavior groups and the uncounted physical-brush completion. The 5,000-cycle source gate, source-package hygiene and eight exact-raster fixtures passed. Paired full public-planner measurements bind the final source and retain identical results while reducing repeated score preparation. Timing and traced allocations are reported separately; these are not native drawing or GPU benchmarks. The published batch12 checkpoint `4704a94df364df9ceeefb113f5273f26ec4ee988` passed all four Windows/Linux and dependency jobs in [CI run 42331930641](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42331930641). All seven checks on that commit succeeded, including [CodeQL analysis run 42331925857](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42331925857). Windows self-test, bundle validation and packaged GUI/native drag-and-drop also passed. These results apply to that saved checkpoint; subsequent source changes require their own verification. No 1.0.148 release is published.

## Resume audit — 7 November 2026

The remote starting point was `4704a94df364df9ceeefb113f5273f26ec4ee988`,
with commit timestamp 04:00:13 Europe/Stockholm time. The later preview investigation from
the previous work session was not included in a subsequent branch commit.

| Deliverable | Verified status at resume |
| --- | --- |
| Original 100 improvements | Merged in [PR44](https://github.com/Vxiey/Image-Draw-Bot/pull/44), on `main` at `eb9804560c8648a92aabe2688e362a6b4a1d28b5`. |
| Additional 679 recorded improvements | Saved on `improve/v1.0.148` in draft [PR46](https://github.com/Vxiey/Image-Draw-Bot/pull/46); not merged. |
| Requested 1,000 improvements | 779 registry entries, 221 remaining. IDs 1–779 are unique and contiguous; all referenced ledgers exist. This bookkeeping check does not independently re-audit every historical behavior claim. |
| Version 1.0.147 | [PR45](https://github.com/Vxiey/Image-Draw-Bot/pull/45) was closed unmerged when work moved to 1.0.148; no release was published. |
| Version 1.0.148 | Development only; no published installer or portable ZIP. |
| Available download | [1.0.146-rc3](https://github.com/Vxiey/Image-Draw-Bot/releases/tag/v1.0.146-rc3), published 5 November as a prerelease. |
| Saved-checkpoint checks | All four CI jobs and all seven commit checks passed for `4704a94d`, including Windows package/self-test/native drag-and-drop and CodeQL. The batch12 “pending” documentation has been corrected with the exact commit and run links. |

The latest U1201 keyboard-switch and R1201 operation-local accuracy-preparation
implementations are present in their actual callers. The previously saved R901
correction covers Auto rescue and Masterpiece/Unlimited, but the resume audit
also reproduced a missing physical-width path in explicit Pixel Art and Line Art.
The separate preview-order defect affects the displayed result even when the
executor already uses the correct order. The follow-up corrections complete
these existing behavior contracts without adding improvement IDs.

The README now links to the actual published rc3 assets and clearly identifies
1.0.148 as development work. Future download URLs and stale CI text do not count
as product improvements. Final follow-up validation is recorded separately from
the historical batch12 measurements.

## Resumed correctness completions

These changes add **zero** improvement IDs: they finish the existing preview
execution-order and R901 physical-brush contracts.

### Final preview follows actual execution order

A public 64 × 48 Manual/Balanced plan with a blue rectangle and a thin black
line correctly executes blue before black. The old guarded preview instead
used palette order and displayed blue over the black line. `finish_plan` also
passed its final sequence into PreviewSafety only when Detail Zoom was enabled,
so ordinary progressive and Pixel correction passes could be regrouped.

The final nonempty sequence now reaches PreviewSafety regardless of Detail
Zoom. Grouped fallback plans preserve the executor's explicit color order,
including omitted and repeated colors. Each ordered entry retains its inherited
physical brush and corresponding CanvasGuard. A diagnostic-render failure clears
partial ink, restores the fill prelude and renders the same schedule; Stop still
propagates. The final simulated image also feeds source-relative accuracy, so
corrected pixels can legitimately change quality acceptance or Auto rescue.
The runtime executor and input/guard authorization are unchanged.

`test_v148_preview_execution_order.py` contains ten meaningful regressions:
actual public planner/executor pixel comparisons, progressive and Pixel
correction order, batch omissions/repeats, inherited verified brush widths,
edge guards, scaled previews, cancellation and diagnostic fallback restoration.
The 71-test related selection passed; independent review ran all ten new tests
without a blocker. Final whole-program evidence is recorded below separately.

### Explicit Pixel Art and Line Art preserve physical brush width

The earlier R901 completion fixed Auto rescue and Masterpiece/Unlimited but
left explicit style policies able to overwrite a preflight-resolved 4 px brush
with 1 px. Actual UI → planner → native-boundary executor regressions reproduced
**3,478** mismatched pixels for Pixel Art and **375** for Line Art. Both now retain
the supplied physical width and produce zero native/model differences in those
fixtures. The legacy default remains available to API callers that omit a width;
verified adaptive brush selection remains unchanged.

The existing brush-contract module now includes both explicit styles and a
verified Gartic Pixel Art case. Eleven focused tests passed independently, and
the 59-test related Auto, brush, CanvasGuard, subject and rescue selection passed.
These are correctness observations from controlled native boundaries, not timing
measurements of a real target application or new feature counts.

## Resumed maintenance: R1301 and P1301

That maintenance checkpoint recorded **781**, with **219 remaining**. Two new behavior
groups are counted; the correctness completions and maintenance do not add IDs.

### R1301 — reuse adjacent-link costs in the existing 2-opt search

`StrokeOptimizer._bounded_two_opt` now prices existing adjacent links once per
search pass and rebuilds those costs after each accepted reversal. Candidate
order, floating-point addition order, ties, direction restrictions, phases and
the final full-route guard remain unchanged. Stop is checked during preparation
at most 256 links apart. No cache survives an operation.

The work-count regression failed on the old code with 89,998 distance calls
against a 46,974 bound. The new code passes that test and 258 complete benchmark
parity cases. Independent review also checked 972 tied/large-coordinate cases
and reproduced both public-plan fingerprints. Six balanced AB/BA pairs yielded:

| Public workload, Smart merge + 2-opt | Before median | After median | Reduction |
| --- | ---: | ---: | ---: |
| Optimizer, 750 paths | 309.340 ms | 207.283 ms | 32.99% |
| Optimizer, 2,250 paths | 781.077 ms | 519.287 ms | 33.52% |
| Full `make_plan`, 128 × 96 fixture | 90.800 ms | 73.842 ms | 18.68% |
| Full `make_plan`, 192 × 144 fixture | 247.354 ms | 180.285 ms | 27.11% |

Every warm, counted, timed and traced invocation checks complete results;
public-plan comparisons exclude only four elapsed-profiler fields. The smaller
image has one noisy pair about 0.6% slower. Traced peaks increase by 552–2,064
bytes: these CPU fixture medians establish no RAM-saving, native drawing or GPU
claim. [Raw measurements](v148-maintenance-stroke-benchmarks.json) bind the old
optimizer to `4704a94d` and record 248 unchanged files during measurement.
Later verifier/package edits were outside that timed snapshot; review confirmed
all 107 recorded modules imported by public planning still match. Reproduce with
`benchmark_v148_stroke_optimizer.py`.

### P1301 — let complete Windows verification finish

`verify_windows.py` stopped full discovery after 60 seconds, although the saved
suite took 150.380 seconds. Full discovery now has the CI core-check ceiling of
1,800 seconds. The self-test, GUI smoke and diagnostics-only mouse commands each
retain a 60-second limit. Imports are inert; interpreter, cwd, command order,
first-failure handling, report location and exit status are preserved.

Six subprocess-boundary tests cover a suite longer than a minute, both timeout
limits, failed child exits, suppression of later checks, report placement and
inert imports. They simulate child processes; native Windows validation is a
separate CI gate.

### Uncounted older-file and dependency maintenance

- Source archives omit 43 known completed v1.0.145 integration workflows,
  triggers, patchers and repair helpers. Exact root-relative filtering preserves
  current tools, future names, compatibility modules and documentation examples.
  All historical files remain tracked. This completes the one-shot package policy.
- Root `verification.txt` diagnostics, including lock/case variants, are omitted
  from archives; `docs/examples/verification.txt` remains eligible.
- Thirty-five references across sixteen workflows move to official checkout,
  setup-python and upload-artifact v7. Two existing tests check those intended
  versions; permissions, events and build/publish commands remain unchanged.
- TkinterDnD2 moves to `>=0.7.0,<0.8`. Its upstream PyInstaller hook selects the
  matching CPU/Tcl library. Existing native-only build flags remain appropriate;
  the current Windows bundle/native drag-and-drop gate validates the new package.
- NumPy stays `>=2.0,<3`: a 2.5.4 floor would drop Python 3.11. Existing ranges
  already tested/built NumPy 2.5.4, Hypothesis 6.170.15, PyInstaller 6.22.3 and
  PyOpenCL 2026.1.4 on the saved Windows checkpoint.
- Current development history, available-download links, guide anchors and
  saved-checkpoint CI status now agree. Historical release notes are retained.

The reference audit covered 244 production modules and their conditional imports,
module literals and build/CLI paths. This does not establish that every behavior
in every module was revalidated. Used compatibility modules remain present.

### Combined local validation

Whole-program discovery passed **3,649 tests in 100.304 seconds**, with **45
platform/hardware skips** and unchanged hashes for 787 Python, batch, workflow
and requirements files. Independent reviews closed for all product changes.
The source gate passed 5,000 cycles. [Validation details](v148-maintenance-validation.json)
record exact-raster and package checks. The new commit's Windows, dependency and
CodeQL results belong to its GitHub checks and PR46, separately from batch12.

## Review method

1. Reproduce a concrete incorrect behavior, avoidable allocation, measured hotspot or unsafe failure mode.
2. Apply one focused correction and verify valid existing behavior remains compatible.
3. Add meaningful regression coverage for the failure or an independent correctness oracle for an optimization.
4. Count the product change once, grouping repeated call sites and related validation branches.
5. Compare performance to the unchanged source reference with identical inputs; disclose unchanged or slower results.
6. Integrate full tests, source gates, dependency review and Windows package checks before release.

## Baselines and ledgers

- [Original 100 improvements](100-IMPROVEMENTS-v1.0.148.md).
- [Batch 01 UI/input](v148-batch01-ui-input.md).
- [Batch 01 planning/geometry](v148-batch01-planning.md).
- [Batch 01 colour/GPU](v148-batch01-colour-gpu.md).
- [Batch 01 storage/resources](v148-batch01-storage-security.md).
- [Batch 02 calibration](v148-batch02-calibration.md), [delivery/planning](v148-batch02-delivery-planning.md), [storage/resources](v148-batch02-storage-runtime.md), and [UI/input](v148-batch02-ui-input.md).
- Batch 03: [colour quality](v148-batch03-colour-quality.md), [rendering/planning](v148-batch03-rendering-planning.md), [GPU/platform](v148-batch03-gpu-platform.md), and [image workflow/UI](v148-batch03-image-workflow.md).
- Batch 04: [application workflow](v148-batch04-application.md), [planning](v148-batch04-planning.md), [UI/profiles](v148-batch04-ui-profiles.md), and [native input/helpers/privacy](v148-batch04-platform-release.md).
- Batch 05: [recovery/execution](v148-batch05-application.md), [colour/planning](v148-batch05-colour-planning.md), [UI/workflow](v148-batch05-ui-workflow.md), and [source/release publication](v148-batch05-platform-release.md).
- Batch 06: [application](v148-batch06-application.md), [rendering/planning](v148-batch06-rendering.md), [UI/calibration](v148-batch06-ui-calibration.md), and [platform/diagnostics](v148-batch06-platform.md).
- Batch 07: [application](v148-batch07-application.md), [rendering/planning](v148-batch07-rendering.md), [UI/workflow](v148-batch07-ui-workflow.md), and [platform/import](v148-batch07-platform.md).
- Batch 08: [application](v148-batch08-application.md), [rendering/planning](v148-batch08-rendering.md), [UI/workflow](v148-batch08-ui-workflow.md), and [platform/build](v148-batch08-platform.md).
- [Combined numbered index](IMPROVEMENTS-v1.0.148.md) and [machine-readable registry](v148-improvements.json).
- `benchmark_engine.py` validates eight deterministic planning fixtures against quantized target geometry. The saved reference has zero mismatched pixels in all eight fixtures.
- `benchmark_v148_ui.py` reproduces UI helper workload comparisons. It does not exercise real Windows input or physical GPU hardware.

- Batch 09: [application](v148-batch09-application.md), [rendering](v148-batch09-rendering.md), [UI/workflow](v148-batch09-ui-workflow.md) and [platform](v148-batch09-platform.md).

- Batch 10: [application](v148-batch10-application.md), [rendering](v148-batch10-rendering.md), [UI/workflow](v148-batch10-ui-workflow.md) and [platform](v148-batch10-platform.md).

- Batch 11: [application](v148-batch11-application.md), [rendering](v148-batch11-rendering.md), [native input](v148-batch11-native-input.md) and [Sketch Fill](v148-batch11-sketch-fill.md).

- Batch 12: [UI workflow](v148-batch12-ui-workflow.md), [rendering](v148-batch12-rendering.md) and [uncounted physical-brush completion](v148-batch12-brush-contract.md).

## Release condition

Keep publication paused while the requested work and integration verification are incomplete. Do not manufacture a count of 1,000 by counting assertions, affected lines, repeated options, documentation or metadata edits as independent improvements.

## Repository security observations — 2026-11-06 UTC

The signed-in GitHub security pages showed:

- [Dependabot vulnerabilities](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot): **0 open**, 26 closed; dependency files last checked 2026-11-05.
- [Dependency malware alerts](https://github.com/Vxiey/Image-Draw-Bot/security/malware): **0 open**, 0 closed.
- [Code scanning](https://github.com/Vxiey/Image-Draw-Bot/security/code-scanning): **0 open**, 2 closed; all listed alerts resolved.

These are observations of the repository dashboards, not antivirus results for
a new installer and not proof that every possible vulnerability is absent.
The new source checkpoint must still pass its own dependency and CodeQL checks.

## Batch 15 — verified local checkpoint

Seven groups cover synchronous Start/Stop handoff, shorter private source
retention, Sketch gradient memory, avoidable preparation copies, clipboard text
sources, numeric Contrast control and per-execution sequence checkpoints.

- [Application](v148-batch15-application.md): A1501–A1502; capture/edit/export
  ownership, final draw-plan UI/executor ownership and existing manual-Paint
  guidance are uncounted completions.
- [Rendering](v148-batch15-rendering.md): R1501–R1502; exact masks, metadata,
  EXIF, preview pixels and complete public plans are preserved.
- [UI workflow](v148-batch15-ui-workflow.md): U1501–U1502; native Windows focus
  and event delivery remain part of the published-commit CI gate.
- [Platform](v148-batch15-platform.md): P1501; cached recovery proof retains
  more memory during execution, separately disclosed from its reduced CPU work.

These complete the three reproduced next-work candidates from batch 14 and
four further independently reproduced behavior groups. Final validation and
measurements are bound to the frozen source in the checkpoint report. The target
remains 1,000 and no 1.0.148 release is published.
