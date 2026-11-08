# Batch 31 — complete the outer Portrait plan lifetime

This is **zero new improvement IDs**. IW08/global582 already requires owned
image buffers to close on cancellation/partial failure while caller-owned and
successfully returned images survive. RP26/global540 covers discarded planner
trials, shared assets and late cancellation. The batch27 Sketch owner and
batch29/batch30 Portrait preparation/stroke completions do not establish the
remaining outer Portrait finisher/time-fit/rescue ownership boundary.

## Published before evidence

The observer reads published batch30
`e49e2535c5f8edea80e47824fe56cae58781b971`, without changing that checkout.
All 893 root-Python hashes remain unchanged, with canonical manifest digest
`0da8de7641efb47fea77c62ece22629b27f9425c137e9d8ccd8d7e9933ae5845`.
Runtime/calibration files are private temporary data; an audit rejects writes
to any repository and all network binds/connections. No native input is sent.

The actual route is imported RGBA → real application options → public
`make_plan` → real Portrait preparation/strokes → real `finish_plan`.
The finite fixture uses a 320 × 240 partial-alpha source, High likeness,
detail 10, delay .025, Manual 180 seconds and a 1200 × 900 drawing area.
Its completed control actually finishes twice: 952 source strokes produce
777 final paths with a 198.86625-second estimate; the real time-fitting pass
reduces 728 source strokes to 611 final paths and 153.80375 seconds.
These are model outputs, not measured physical drawing durations.

| Actual terminal boundary | Before, while the original exception is retained |
| --- | --- |
| First real finisher observes Stop | Its private RGBA input and the earlier private accuracy-source copy remain open. The prepared gray wrapper is already closed by batch29. |
| Second real time-fit finisher observes Stop | Both private finisher inputs and the first unpublished plan's 11 distinct image fields remain readable. |
| Second finisher's actual Pillow allocation raises TypeError | The same unpublished images survive, while the original Pillow traceback remains available. |
| Second finisher with explicitly borrowed source/target/cache images | The private input/first-plan leak remains. All borrowed inputs are nevertheless open and unchanged, defining the preservation control. |
| Completed two-pass plan | The final plan remains usable; this positive control proves that the extra pass is a real planner decision. |

The allocation-failure control deliberately supplies an invalid color object
to the real second-finisher `Image.new` call. This is an injected native-failure
boundary, **not** a claim that valid user settings normally produce that
TypeError. The partially constructed Image in Pillow's own frame is reported
separately. No third-party frame is cleared or rewritten.

Raw complete observation is scratch
`pending-batch31-portrait-plan/before-complete/summary.json`, SHA-256
`cdc59bb8559c9eb4498d284b2201bf8e7b426d9fdccfbc70c7df99a1c87d72e1`.
Five cases complete with unchanged source hashes and an empty audit record.
The earlier `before/summary.json` is retained as an incomplete diagnostic: its
observer incorrectly treated a partially initialized Pillow Image's
`AssertionError` during inspection as an unexpected failure. Its first three
completed cases already show the ownership defect; it is not represented as
the complete five-case proof. `observe-initial.py` preserves that observer.

## Narrow correction

Only the Portrait outer ownership boundary in `DrawBot.py` changes:

- Capture the original caller's known image fields before planner copies or
  derived options replace them. The source, explicit accuracy/quantized target
  and normalization-cache images are borrowed.
- Give the Portrait operation the existing `_PlanImageOwner` and existing
  thread-checked image scope for preparation, every real finisher, finite
  time-fitting and actual tuner rescue.
- Capture private finisher inputs before their consumer can fail. On a terminal
  failure, retire the previously successful but unpublished plan too.
- Transfer only the plan actually returned by the outer operation. A successful
  rescue keeps its new result; the existing fallback after a non-Stop rescue
  error keeps the original usable plan. Shared images retained by that selected
  plan remain open.
- Restore an already active parent image scope and register the returned plan
  with that parent. No owner, cache, opt-in flag or other private state enters
  the returned plan/options.

The Portrait geometry, generated strokes, timing limits, sampling formulas,
calibration, CanvasGuard and finisher algorithms are unchanged. The original
Stop/TypeError objects and tracebacks remain available. There is no GC policy
change, recursive arbitrary-object cleanup or traceback clearing.

## Regression evidence and review

The initial seven-method regression was run against the frozen published
tree. After correcting a fixture setup mistake that asked the full-color Auto
tuner to tune an already current-ink request, **five intended ownership
failures and zero errors** remained; two success/outer-scope controls passed.
The preliminary four-failure/one-fixture-error report is preserved separately.
The completed red report is
`pending-batch31-portrait-plan/tests-before-complete.json`, SHA-256
`01bb4cbb37deabab54357cdd4322f3be8aac33377e2673d0f07ddc7e9217424d`.

After the correction, those seven methods passed. The final test file adds
successful real rescue and real rescue-error fallback, and extends the parent
scope control through retained Stop. Its **eight methods pass in 7.396 seconds**,
without skips, errors or audit violations, with an unchanged 895-source
checkpoint `c845b2b6025e917fd8f054c34ec953a6a019986e8ffb22dfa8f2efab7b9e91e0`.
The eight-method final set is not claimed to be the earlier seven-method red
set. No planner result or numerical consumer is stubbed. The earlier seven-test
source is preserved as a verified reconstruction in scratch
`test-seven-before.py`, SHA-256
`a95393c2f1a99ea0384214690e83dbb0a3913945037c05d395ac2f44b0a9e90c`,
matching both its red and initial green report's recorded test hash.

The actual tuner compatibility control first obtains a real full-color Auto
context, then supplies an explicit supported current-ink Portrait choice.
The real acceptance/proposal functions produce a quality rescue; no fabricated
plan or mocked rescue decision is used. The ordinary UI current-ink policy is
not claimed to enable the full-color Auto tuner by itself.

| Source or focused artifact | SHA-256 |
| --- | --- |
| DrawBot.py at the focused checkpoint | `c44743a70d3c4eda21bbae0fb5740b10f6532a8c4056a3997e1555a73ea5f581` |
| test_v148_rendering_batch31_portrait_plan_ownership.py | `53ae58ab601f39729f07bae714108d98d04623e3704774cece31df9919ac43a7` |
| tests-after-complete.json | `b62faf9fc397a07c6ca475015127eb5c513a39e84ba5d746c9ec251304301ac1` |

Independent read-only review of the complete product diff and eight methods is
closed without a source blocker. Complete historical public-plan parity and
the combined batch31 gates pass and are recorded below. No elapsed
speed, peak-memory, process-RSS or GPU improvement is claimed by this cleanup.

## Complete historical public-plan comparison

The final untimed replay passed **seven of seven actual public-plan pairs**.
It loads the complete published `DrawBot.py` and `PortraitPlanner.py` from
`e49e2535c5f8edea80e47824fe56cae58781b971`, links those two historical modules
together, and compares them with the current pair. The remaining recorded
dependencies and the private calibration context are shared. This is distinct
from the separate contour benchmark, which deliberately shares current
`DrawBot.py` on both sides to isolate the contour selection change.

The seven pairs cover Auto with an opaque source, an alpha-bearing Portrait,
Dots, a finite 3 s budget, actual 180 s time fitting, time fitting with explicit
borrowed source/target/cache images, and a real quality rescue. Complete plan
values, image bytes, metadata and actual finish-call observations agree. Only
the already declared clock-derived `VOLATILE_PATHS` are excluded from the
comparison; the raw report records each excluded path. All borrowed images
remain unchanged.

Both 180 s cases reach two actual finalizations: **952 → 728 source paths** and
**777 → 611 final execution paths**, with estimates
**198.86624999999998 → 153.80375000000004** on both versions. The real quality
rescue reaches passes **0 → 1**, with 3,816 final paths in each pass on both
versions. These are genuine public planner calls, not constructed plan stubs.

All **897 root Python hashes** remained equal before and after the replay:
`325d536b457d8b384a0738efab531ae0f6d773db5fb30fa569e56dbc0d7e329f`.
The read-only audit reported no repository writes or network access. The
earlier 895-file focused checkpoint above is retained with its original map;
it is not relabelled as a run of this later source snapshot.

| Historical artifact | SHA-256 |
| --- | --- |
| pending-batch31-portrait-plan/historical-final/summary.json | `c9fe43cbad4482eda3f134c7cd0796db98ba8b8ff7af82c96643f4e9300891a0` |
| pending-batch31-portrait-plan/historical-final.log | `b5aaff846dcaa7a58d85dcb03a020cb23e6d2a551934bd74da35f77a637c8b5f` |

The complete stdout/stderr, verifier source and before/after preview PNGs are
preserved with that report. Integrated full discovery, native widgets and
source/raster/package gates remain separate requirements; no new-head Windows
validation is claimed here before publication and its exact-commit CI.


## Integrated frozen-source result

Batch 31 records **843 distinct improvements, 157 remaining**. One contour-prefix work-reduction group is registered as R3101/global843. Local import-stream and outer Portrait-plan ownership complete existing contracts with zero IDs. All 842 preceding registry entries and 80 prior benchmark JSON reports are preserved. Completed frozen discovery ran **4,569 tests in 244.002 seconds: 4,496 passed and 73 skipped**, with all 947 source/configuration hashes unchanged. Fourteen Linux/Xorg native cases, the 5,000-cycle source gate, eight exact existing-raster fixtures and initial package hygiene (1,370 files) passed. The package check after final metadata passed with 1,372 files and no warnings. Seven complete historical Portrait public-plan pairs retain finite time-fitting, actual rescue and borrowed inputs. The contour experiment compares the whole published Portrait module within shared current dependencies: 3 complete preparations, 39 exact helper/public comparisons and 9 workloads with six balanced pairs and separate traced allocations. Scanning and the cell-winner dictionary remain; whole-helper and whole-public-plan observations, slower controls and allocation costs are kept separate. Early source maps, expected red proofs and initial harness diagnostics remain explicit. No universal application speed, RSS, physical drawing or GPU improvement is claimed. Published parent e49 passed seven exact-head checks and all fourteen Windows steps on attempt one; the new head requires its own CI. Version 1.0.148 remains unreleased.

Final gates bind **897 root Python files**, compact SHA256 `325d536b457d8b384a0738efab531ae0f6d773db5fb30fa569e56dbc0d7e329f`, and **947 source/configuration files**, compact SHA256 `1ae580174ddabeb86dc289c6fdfbc17eddcea9085b9c4671ce71ae6b3182501e`. Earlier red and focused checkpoints retain their original maps and labels; no failed harness or expected before failure is presented as a passing integrated gate. The parent Windows run is separate from the new head. Independent metadata review and post-metadata package hygiene are recorded separately in [final validation](v148-batch31-validation.json).
