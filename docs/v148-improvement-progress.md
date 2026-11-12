# Image Draw Bot 1.0.148 improvement progress

## Requested result

Continue application-wide correctness, performance and security improvements, with a target of **900 distinct improvements**, then release **1.0.148**. The user reduced the earlier 1,000 target on 12 November 2026. The 100 already reviewed and merged improvements form the starting point; formatting, tests, documentation and version bumps do not count as additional product improvements. Earlier checkpoint counts below retain their historical targets.

## Current state

The current reviewed source checkpoint contains **886/900 distinct implemented
improvements, with 14 remaining**. Batch 42 adds 17 groups: four application,
seven rendering, two runtime and four native-input/resource groups. All 869
preceding registry entries are preserved exactly. Delivery-context follow-ups,
test-fixture repairs, tests, documentation and review completions add no IDs.

The [application](v148-batch42-application.md),
[rendering](v148-batch42-rendering.md), [runtime](v148-batch42-runtime.md) and
[native](v148-batch42-native.md) ledgers retain historical reproductions,
exact controls, raw paired measurements and limitations. Focused selections
pass 22 application, 28 rendering and 14 runtime methods; the 19 native methods
have 18 passes and one unavailable real-Windows skip. Adjacent selections pass
85 application, 135 rendering, 168 runtime and 144 of 145 native methods (the
same Windows skip). These selections overlap; their counts are not added into
a fabricated full-suite result.

The [initial complete batch41 discovery](v148-batch41-initial-full-validation.json)
finished 4,884 methods with **4,788 passes, nine failures, one error and 86
skips**. All 1,014 source/configuration/fixture hashes remained unchanged and
there was no Tcl abort. This is a failed gate. Six worker/helper timeout methods
subsequently [passed unchanged in isolation](v148-batch42-timeout-followup.json)
in 41.847 seconds with the original limits. Four other old fixtures are adapted
to their implemented cancellation, timing-budget or delivery-identity contracts
without weakening those contracts. Final isolated complete discovery on the
finished 900-group source remains pending.

The earlier batch40 Tcl-aborted discovery and runner-main-guard diagnostic
remain preserved. Their two test-owner disposal repairs are proved separately;
no product GC policy or timeout was weakened. Exact newly published-head
Windows/Linux, CodeQL and packaged-app results remain separate gates.
Version 1.0.148 is unreleased; no merge or release is authorized by this checkpoint.

### Previously recorded batch41 checkpoint

Batch41 contained **869/900, with 31 remaining**, adding eight independently
reviewed behavior groups after batch40's 15. Its combined
[focused integration](v148-batch41-focused-integration.json) passed **47/47**
methods with 970 unchanged Python hashes. The complete discovery subsequently
failed as reported above; the focused result is not a substitute for that gate.
The [application](v148-batch41-application.md),
[rendering](v148-batch41-rendering.md), [runtime](v148-batch41-runtime.md) and
[delivery](v148-batch41-delivery.md) ledgers preserve the original evidence.

### Previously recorded batch40 checkpoint

Batch40 contained **861/900, with 39 remaining**, adding A4001, R4001–R4004,
P4001–P4005 and N4001–N4005. The [application](v148-batch40-application.md),
[rendering](v148-batch40-rendering.md), [runtime](v148-batch40-runtime.md) and
[native/calibration](v148-batch40-native.md) ledgers retain their focused evidence.
Export/publication, target revalidation and owned-image cleanup completed existing
contracts without additional IDs. Its incomplete full-suite attempts are retained
above and are not presented as successful gates.

### Previously recorded batch39 checkpoint

Batch 39 completes four recovery, preview and Pixel preparation corrections.
**R3901/global845** shares exact horizontal source segments during component
collection, and **P3901/global846** bounds necessary CPU palette RGB preparation.
Required-image recovery and preview result ownership complete existing contracts
with zero new IDs. The total is **846/1,000 implemented; 154 remaining**.
All 844 preceding registry entries and 134 earlier JSON reports, including
84 benchmark reports, are preserved.

The final four-module integration passed **32/32 new tests in 4.298 s**.
Full local discovery passed **4,768 tests in 263.504 s: 4,682 passed and
86 skipped**, with no failures/errors. Four existing real Linux/Xorg workspace
and shutdown cases passed in 20.254 s. All three runs bind the same **958
unchanged source/configuration/fixture hashes**. The 5,000-cycle source gate
and 1,423-file source-package check passed without warnings.

The [ledger](v148-batch39-recovery-preview-and-pixel.md),
[validation](v148-batch39-validation.json) and
[raw evidence](v148-batch39-evidence.json) retain exact before/after results,
initial fixture/runner diagnostics, every paired timing sample and slower
controls. The CPU RGB-composite payload is bounded to 49,152 bytes for the
measured large sources; required image-sized inputs/outputs remain. Pixel
planning avoids the duplicate scan and segment objects with identical outputs.
The mixed whole-caller timings do not establish a general speedup or a lower
whole-plan/RSS peak.

Exact published-head Windows/Linux, dependency, CodeQL and packaged-app
verification is reported separately in
[draft PR #46](https://github.com/Vxiey/Image-Draw-Bot/pull/46).
Version 1.0.148 remains unreleased. Merge and release require explicit approval.

### Previously recorded batch38 checkpoint

Batch 38 completes eight profile, image and planner corrections. One opaque
Auto-count preparation group, **P3801/global844**, is new; the remaining
completions receive zero IDs. The current total is **844/1,000 implemented,
156 remaining**. All 843 preceding registry entries and 132 earlier JSON
reports, including 84 benchmark reports, are preserved exactly.

The final eight-module integration passed **63/63 new tests in 3.785 s**, with
no errors/skips. Full local discovery passed **4,736 tests in 250.327 s:
4,650 passed and 86 skipped**. Seven existing native profile cases separately
passed on real Linux/Xorg in 29.465 s. All three runs bind the same 954
unchanged source/configuration/fixture hashes. The 5,000-cycle source gate
also passed. The [ledger](v148-batch38-lifecycle-and-planning.md),
[validation](v148-batch38-validation.json) and
[raw evidence](v148-batch38-evidence.json) retain before/after results,
measurements, slower controls and rejected work.

Extra Fast retains its original candidate selection and reuses exact path
costs within bounded operation-local storage. The broader axis experiment
was rejected after complete-plan measurements. Auto-count reduces private
opaque-source preparation while preserving pixel and recommendation parity.
Observed channel samples and Python-traced allocation are not process-RSS or
physical GPU measurements. Whole-plan timings are local Linux observations.

Exact published-head Windows/Linux, dependency, CodeQL and packaged-app
results are reported separately in
[draft PR #46](https://github.com/Vxiey/Image-Draw-Bot/pull/46).
Version 1.0.148 remains unreleased. Merge and release require explicit approval.

### Previously recorded batch37 checkpoint

Batch37 completed four existing lifecycle contracts with zero new IDs:
843/1,000 and 157 remaining. Its final combined local pass ran 26/26 new
regressions, including five real native UI cases, in 23.993 s with 919 stable
hashes. The [ledger](v148-batch37-lifecycle-fixes.md) and
[validation](v148-batch37-validation.json) retain that scope. All seven
checks passed for b8fb914 after one unchanged Windows-job retry; Windows
reported 4,673 tests, 4,669 passed and four skipped, while Linux reported
4,587 passed and 86 skipped. The initial Windows timeout, retry and exact
job links remain in the [PR history](pr46-history-through-batch37.md).
Those results verify that earlier head, not this continuation.

### Previously recorded batch31 checkpoint

Batch 31 records **843 total distinct improvements, with 157 remaining**.

Batch 31 records **843 distinct improvements, 157 remaining**. One contour-prefix work-reduction group is registered as R3101/global843. Local import-stream and outer Portrait-plan ownership complete existing contracts with zero IDs. All 842 preceding registry entries and 80 prior benchmark JSON reports are preserved. Completed frozen discovery ran **4,569 tests in 244.002 seconds: 4,496 passed and 73 skipped**, with all 947 source/configuration hashes unchanged. Fourteen Linux/Xorg native cases, the 5,000-cycle source gate, eight exact existing-raster fixtures and initial package hygiene (1,370 files) passed. The package check after final metadata passed with 1,372 files and no warnings. Seven complete historical Portrait public-plan pairs retain finite time-fitting, actual rescue and borrowed inputs. The contour experiment compares the whole published Portrait module within shared current dependencies: 3 complete preparations, 39 exact helper/public comparisons and 9 workloads with six balanced pairs and separate traced allocations. Scanning and the cell-winner dictionary remain; whole-helper and whole-public-plan observations, slower controls and allocation costs are kept separate. Early source maps, expected red proofs and initial harness diagnostics remain explicit. No universal application speed, RSS, physical drawing or GPU improvement is claimed. Published parent e49 passed seven exact-head checks and all fourteen Windows steps on attempt one; the new head requires its own CI. Version 1.0.148 remains unreleased.

[Final validation](v148-batch31-validation.json), [contour budget](v148-batch31-portrait-edge-budget.md), [Portrait plan ownership](v148-batch31-portrait-plan-ownership.md), [local import ownership](v148-batch31-import-stream-ownership.md) and [lossless raw evidence](v148-batch31-completion-evidence.json).

<details>
<summary>Previous batch30 checkpoint</summary>

Batch 30 records **842 total distinct improvements, with 158 remaining**.

Batch 30 records **842 distinct improvements, 158 remaining**. 2 new behavior groups are registered: R3001, R3002. Background cleanup preserves detail already protected by the border flood; picture-palette growth avoids retesting unchanged centers. Portrait stroke ownership, Stop across image-copy handoff and test-fixture Tcl disposal complete existing contracts with zero IDs. All 840 prior registry entries and 78 earlier benchmark JSON reports are preserved. Completed frozen discovery ran **4,551 tests in 231.751 seconds: 4,478 passed and 73 skipped**; all 943 source/configuration hashes were unchanged. Fourteen Linux/Xorg native cases, the 5,000-cycle source gate, eight exact raster fixtures and initial package hygiene (1,359 files) passed. The package check after final metadata passed with 1,361 files and no warnings. The incomplete process attempts and the Tcl-aborted attempt remain negative evidence. A proved old calibration fixture released borrowed Tcl aliases after real cleanup; no product GC policy, skip, assertion or timeout was weakened. The final background and Portrait historical comparisons and the six-workload/six-pair palette measurement retain their original 892-file map; the final 893-file map differs only in the two explicitly recorded fixture files. Historical checks retain 20 exact background controls and 24 intended corrections, 14 Portrait helper and seven public pairs, and 32 palette comparisons including four public plans. The cold red picture-palette helper and direct refinement improve in all six pairs; unchanged-work controls are not treated as algorithm gains. No universal speed, peak-memory, process-RSS, physical Paint or GPU improvement is claimed. Parent 4b90 has seven green checks after one unchanged Windows-job rerun; the new head requires its own exact-commit CI. Version 1.0.148 remains unreleased.

[Final local validation](v148-batch30-validation.json), [background detail](v148-batch30-background-details.md), [palette growth](v148-batch30-palette-growth.md), [Portrait ownership](v148-batch30-portrait-stroke-ownership.md), [Stop handoff](v148-batch30-stop-copy-completion.md), [fixture ownership](v148-batch30-fixture-ownership.md) and [lossless raw evidence](v148-batch30-completion-evidence.json) record distinct scopes and all failed attempts.


</details>

<details>
<summary>Previous batch29 checkpoint</summary>

Batch 29 records **840 total distinct improvements, with 160 remaining**.

Batch 29 records **840 distinct improvements, 160 remaining**. One independently assessed preview-worker cost-handoff group is registered as R2901. Accuracy input borrowing and Portrait preparation/ownership complete existing contracts with zero IDs. All 839 preceding entries and 76 prior raw benchmark reports are preserved. Frozen discovery completed **4,522 tests in 240.202 seconds: 4,449 passed and 73 platform/hardware cases skipped**, with all 937 source/configuration hashes unchanged. Fourteen real Linux/Xorg native cases, the 5,000-cycle source gate, eight exact existing-raster fixtures and package hygiene passed on 887 root Python sources. Complete historical comparisons retain all four Accuracy public plans and metrics/heatmaps, and 47 Portrait helper pairs plus five public plans including actual finite-time fitting. Their recorded replay maps and any explicitly permitted standalone benchmark-only difference remain separate from the final gate map. The final ETA experiment compares seven workloads with six balanced pairs and separate allocations. Both actual worker estimate calls are measured together, including the first snapshot; whole-pipeline observations remain separate. Every fallback/control cost, slower pair, rejected tuple experiment and intermediate compact-byte diagnostic remains visible. Copy counters are not peak/RSS measurements, and no general application-speed or physical input/GPU claim is made. Parent bfa43deb has seven green exact-commit GitHub checks; the newly published head requires its own Windows/package checks in PR46. Version 1.0.148 remains unreleased.

[Final local evidence](v148-batch29-validation.json) binds the completed gates. [Preview-worker ETA](v148-batch29-estimate.md) records the count decision and all measured controls. [Accuracy inputs](v148-batch29-accuracy-inputs.md) and [Portrait preparation](v148-batch29-portrait-preparation.md) complete existing contracts with zero IDs. [Raw image completion evidence](v148-batch29-completion-evidence.json) retains before/after/historical artifacts and their exact source provenance.


</details>

<details>
<summary>Previous batch28 checkpoint</summary>

Batch 28 retains **839 total distinct improvements, with 161 remaining**.

Batch 28 completes existing Sketch physical-preview and private PNG-snapshot contracts with zero new IDs: **839 total improvements, 161 remaining**. All 839 registry entries and 75 preceding raw benchmark reports are preserved. Frozen discovery completed **4,498 tests in 224.479 seconds: 4,425 passed and 73 platform/hardware cases skipped**. All 933 source/configuration hashes remained unchanged. Fourteen real Linux/Xorg native cases, the 5,000-cycle source gate, eight exact existing-raster fixtures and package hygiene passed on the same 883 root Python sources. Five actual public/controller-to-executor Sketch comparisons now have exact physical-model previews, including the prior 32-versus-15-pixel axis failure and both scaled Balanced fixtures. Native actions and delivered pixels are unchanged in those fixed controls. Corrected Accuracy/delta-E may legitimately change an active tuner rescue decision. PNG export removes one unnecessary identity copy for unrotated private snapshots while preserving decoded pixels, ICC, borrowed inputs, Stop and atomic publication. Historical batch27 replay is pinned to its published caller graphs and adds no timing samples. This is no physical Paint, general speed, peak-memory or GPU claim. Parent f800 has seven green exact-commit GitHub checks; the new published head requires its own Windows/package checks in PR46. Version 1.0.148 remains unreleased.

[Final local evidence](v148-batch28-validation.json) binds the frozen source. [Sketch physical previews](v148-batch28-sketch-preview.md) and [PNG snapshot reuse](v148-batch28-png-snapshot.md) complete existing contracts with zero IDs. [Raw completion evidence](v148-batch28-completion-evidence.json) preserves the actual before/after controls and all diagnostic provenance. [Pinned historical replay](v148-batch28-historical-replay.json) keeps the prior experiment reproducible.


</details>

<details>
<summary>Previous batch27 checkpoint</summary>

Batch 27 implements **839 total distinct improvements, with 161 remaining**.

Batch 27: 4,481 tests completed in 218.814 seconds: 4,408 passed and 73 platform/hardware cases skipped, with 931 source/configuration hashes unchanged. One independently reviewed Sketch Fill presentation-handoff group brings the total to 839, with 161 remaining; all 838 preceding entries are preserved. Current RAM recommendation matching, legacy CPU source-white handling, direct GPU-installer ownership, responsive Mobile Preview discovery and monochrome/Sketch image lifetime complete existing contracts with zero additional IDs. Fourteen real Linux/Xorg native cases, the 5,000-cycle source gate, package hygiene and eight existing-raster fixtures passed. Complete historical comparisons cover 22 public cases and eight native-executor raster cases over three complete caller graphs, plus eight separate current-ink/outline pairs. Eight workloads have six balanced pairs and separate peak/retained allocation probes. The timed graph holds current PixelData constant but includes the uncounted DrawBot/Sketch ownership work; its entire delta is not attributed solely to the new group. All final gates bind the same 881 root Python hashes. Slower individual pairs, control allocation costs and the pre-existing scaled Sketch preview/native-model discrepancy remain explicit. Exact-commit Windows/package checks are recorded separately in PR46. Version 1.0.148 is not released.

[Final local evidence](v148-batch27-validation.json) binds the frozen source. [Sketch Fill](v148-batch27-sketch-finalization.md) records the one new group. [Completion evidence](v148-batch27-completion-evidence.json) preserves the actual before/after observations for [RAM recommendations](v148-batch27-scheduler-completion.md), [CPU source-white](v148-batch27-cpu-white-completion.md), [GPU installers](v148-batch27-gpu-installer-completion.md), [Mobile Preview](v148-batch27-mobile-discovery-completion.md) and [monochrome ownership](v148-batch27-monochrome-ownership-completion.md).


</details>

<details>
<summary>Previous batch26 checkpoint</summary>

Batch 26 implements **838 total distinct improvements, with 162 remaining**.

Batch 26: 4,431 tests completed in 215.945 seconds: 4,361 passed and 70 platform/hardware cases skipped, with 923 source/configuration hashes unchanged. One independently reviewed topology-reuse group brings the total to 838, with 162 remaining; all 837 preceding entries and the incoming batch25 implementation and fixture repairs are preserved. OpenCL host-failure ownership completes already-counted P2504; strict calibration/grid/legacy/cache storage, shared GIF publication, normalized dictionary round trips and unused shadow-output retirement complete existing contracts with zero IDs. Ten real Linux/Xorg native cases, the 5,000-cycle source gate, package hygiene and eight existing-raster fixtures passed. Complete historical comparisons cover 36 regional score pairs, 38 full public plans including two active-timer pairs, 24 independent brush-one rasters and 692 GPU cases against each of two historical checkpoints. Seventeen workloads have six balanced pairs and separate allocation probes; the OpenCL comparison reproduces already-counted work against586, not a new gain over837. All final gates bind the same 873 root Python hashes. Slower controls and topology retention costs remain disclosed, without a general planner/GPU/RSS claim. Exact-commit Windows/package checks are recorded separately in PR46. Version 1.0.148 is not released.

[Final local evidence](v148-batch26-validation.json) binds the merged source. [Target topology](v148-batch26-topology.md) records the one unique group; [OpenCL completion](v148-batch26-opencl-host.md), [palette storage](v148-batch26-color-storage-completion.md), [GIF publication](v148-batch26-gif-storage-completion.md), [dictionary persistence](v148-batch26-word-storage-completion.md) and [shadow ownership](v148-batch26-shadow-ownership-completion.md) record zero-ID completions.


</details>

<details>
<summary>Previous batch25 checkpoint</summary>

Batch 25 implements **837 total distinct improvements, with 163 remaining**.

Batch 25: 4,372 tests completed in 209.654 seconds: 4,302 passed and 70 platform/hardware cases skipped, with all 919 source/configuration hashes unchanged. Seven independently reviewed groups bring the total to 837, with 163 remaining; all 830 preceding entries and concurrent batch24 implementation are preserved. Existing widget/worker/calibration, Stop, image-handoff and whole-click completions add zero IDs. The 5,000-cycle source gate, 1,284-file package hygiene and eight existing-raster geometry fixtures passed. Three rendering workloads have six balanced pairs and share 863 unchanged root Python hashes; unchanged/slower controls and added Fill allocation are disclosed without a general speedup claim. Fill diagnostics remain within the documented categorical model. The parent checkpoint passed all seven remote checks; new exact-commit Windows/package/native sampling results are recorded separately in PR46. Version 1.0.148 is not released.

The seven groups cover timed Pixel paint order, categorical contour/seed Fill footprints, measured compute-route recommendations, an applicable RAM signature, real executor measurement, necessary OpenCL host preparation and bounded native screen sampling. [Final local evidence](v148-batch25-validation.json) binds the merged source; published-commit Windows/package/native results are recorded in [PR46](https://github.com/Vxiey/Image-Draw-Bot/pull/46).


</details>

<details>
<summary>Previous batch24 checkpoint</summary>

Batch 24 implements **830 total distinct improvements, with 170 remaining**.

Batch 24: 4,308 tests completed in 205.763 seconds: 4,242 passed and 66 platform/hardware cases skipped, with 900 source/configuration hashes unchanged. Two independently reviewed groups bring the total to 830, with 170 remaining. Manual palette analysis stays responsive and Pixel scheduling bounds active-list removal work. Prepared Paint workflow, Upscale keyboard, widget timers and retained image ownership complete existing contracts with zero IDs. Ten real Linux/Xorg native cases, the 5,000-cycle source gate, package hygiene and eight existing-raster fixtures passed. Complete historical parity covers 54 palette-controller cases, 72 scheduler pairs and 24 complete public plans/independent rasters. Nine queue workloads have six balanced pairs and separate traced allocations, all bound to the same 850 root Python hashes. The preceding bb6dfa6 checkpoint passed all seven remote checks and Windows/package/native GUI gates; the new exact commit is verified separately in PR46. Version 1.0.148 is not released.

[Final local evidence](v148-batch24-validation.json) binds all source and historical comparisons. [Palette analysis](v148-batch24-palette-scan.md) and [component scheduling](v148-batch24-component-queue.md) describe the two new groups. [UI workflow](v148-batch24-ui-workflow.md) and [widget lifetime](v148-batch24-widget-lifetime-completion.md) record existing-contract completions.

</details>

<details>
<summary>Previous batch23 checkpoint</summary>

Batch 23 implements **828 total distinct improvements, with 172 remaining**.

Final frozen-source integration completed **4,270 tests**: **4,211 passed and 59 platform/hardware cases skipped**, with all 891 source/configuration hashes unchanged. The two new groups reduce repeated mixed-colour scoring and oversized input allocation when reading small local JSON files. Accepted profile import/reset revokes the old Drop-In request, and older native CTk tests use the existing owned window lifetime; those completions add zero IDs.

The concurrently published `5c32b6883c454268e06e199a8f15264ca9ec26e9` batch22 is preserved, including all 826 preceding registry entries and its detail-protection, portrait-tile, spectrum-search and UI changes. The 5,000-cycle source gate, package hygiene, eight existing-raster geometry fixtures and independent reviews passed. Complete historical comparisons cover 582 colour cases, 79 reader cases and eleven full reader/consumer workloads. Twenty-one workloads share 841 root Python hashes and have six balanced timing pairs each, with separate traced-allocation evidence and slower controls retained. [Final local evidence](v148-batch23-validation.json) is separate from the new exact-commit Windows/CI gate in [PR46](https://github.com/Vxiey/Image-Draw-Bot/pull/46).

The preceding `5c32b68` checkpoint passed all seven checks, including Windows tests, source/packaged self-tests, bundle validation and packaged GUI/native drag-and-drop. [Exact prior run](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42401939021). No 1.0.148 release has been published; the release condition remains 1,000 independently verified behavior changes.


</details>

<details>
<summary>Previous batch22 checkpoint</summary>

Batch 22 implements **826 total distinct improvements, with 174 remaining**.
Final frozen-source integration completed **4,246 tests: 4,187 passed and 59 platform/hardware cases skipped**, in 197.237 seconds. All 892 checked source/configuration hashes stayed unchanged, and the runtime Paint cache was absent before and after the suite. The 5,000-cycle source gate, 1,235-file package hygiene and eight exact-raster cases using existing assets passed. [Final local evidence](v148-batch22-validation.json) records exact source and measurement bindings; the published commit's Windows/package checks remain separately recorded in [PR46](https://github.com/Vxiey/Image-Draw-Bot/pull/46).

The three new groups preserve individually correct protected details during correction, keep portrait operations consistent across GPU tile sizes, and reduce Python work in Paint spectrum search with exact chosen-color parity. Explicit preview Stop, recoverable shutdown, native numeric ownership and destination resize allocation complete existing contracts with zero additional IDs. [Rendering](v148-batch22-rendering.md), [platform](v148-batch22-platform.md), [spectrum](v148-batch22-native-spectrum.md) and [UI](v148-batch22-ui-workflow.md) ledgers disclose evidence and limits.

Integration retains concurrent checkpoint `92d5a86709a61802821780f5866409da6cd8cf2e` and its follow-up `be30fa54a0c58a8d2b6535d31cb6672727f4e6cc`. The latter fixes the demonstrated Windows fixture newline failure and isolates the older Paint recovery tests' actual storage. The original 823 registry entries remain unchanged. No release has been published; the release condition remains 1,000 independently verified behavior changes.


</details>

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

Keep publication paused while the requested work and integration verification are incomplete. Do not manufacture a count of 900 by counting assertions, affected lines, repeated options, documentation or metadata edits as independent improvements.

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
