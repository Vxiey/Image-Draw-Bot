# v1.0.148 — profile, image and planner lifetime fixes

## Scope and counting

Baseline: `b8fb914b020f879a6c1c72434abb6f9f0f6725dd` on the draft
`improve/v1.0.148` branch. Eight related corrections cover profile publication
and identity, saved-area cancellation, private image ownership, Auto color
sampling and repeated Extra Fast cost preparation. Recovery PNG formats,
profile formats, dependencies and the application version remain compatible.

**One new group, P3801/global844: 844/1,000 implemented; 156 remain.** The
new group reduces private full-resolution preparation for opaque Auto-count
inputs. The other corrections complete existing contracts and receive zero
new IDs. Tests, failure branches, repeated consumers, documentation and helper
extraction are not additional improvements. All 843 preceding registry entries
are preserved exactly.

## Implemented corrections

### 1. Replace-import retires the destination's legacy calibration

Replacing a profile could remove or overwrite canonical calibration while
leaving a fallback that the next actual reload consumed. Generic imports now
retire `positions.txt` and `palette.json`; Paint imports retire
`paint-tools.json`. Retirement belongs to the destination owner and joins
the existing staged file-set publisher. Copy import, custom profiles
and unrelated built-in profiles retain the original owner's files.

Handled backup/publication failures restore the previous files when rollback
succeeds. If rollback itself fails, the publisher retains recovery backups and
reports their paths without reloading the profile. Individual renames are
atomic; the file set does not claim crash atomicity. Reset shares the same
small ownership helper. These
changes complete **066/global66**, **067/global67** and **SR08/global412**.

### 2. Imported documents must fit their actual readers

The portable package ceiling was larger than the normal settings/calibration
readers' limits. A valid portable package could therefore publish a profile
that failed its immediate reload. Validation now checks the final serialized
UTF-8 document after owner rewriting and Paint-to-generic conversion:
256 KiB for settings, 128 KiB for tools/exact colors, and 2,000 JSON values for
Paint tools. The existing writer preserves these exact bytes on Windows.

Oversized output is rejected before any file or profile-register publication.
Exact limits remain accepted, and a converted copy is assessed against its
actual destination document. This completes **SS03/global183**,
**AW07/global621** and the existing guarded import-publication contract.

### 3. Export includes the legacy calibration currently in use

Normal profile loading still accepted generic and Paint legacy calibration,
but export silently omitted it. Export now captures those sources when the
canonical data is absent. A pure `Colors.read_legacy_calibration` shares the
existing position/RGB validation without modifying global color objects or
caches. Paint export reads its fallback with the real reader's byte/value
limits and does not perform a migration write.

Canonical files retain priority. Missing optional sources remain optional;
partial, malformed, oversized, unresolved or nonregular fallback sources stop
export before its chooser and publication. An existing destination therefore
survives a failed source capture. Regular links preserve content semantics.
This completes the existing profile portability and source-validation contract.

### 4. Resume identity includes active legacy calibration

Generic fallback positions/colors were absent from the calibration fingerprint.
Changing the actual click positions could leave an old partly completed render
checkpoint apparently compatible. The fingerprint now includes these files
only when the normal generic canonical path is absent and its fallback applies.

Canonical calibration, explicit alternate palette paths and other profiles
remain independent of shadowed generic legacy files. A broken link is
distinguished from a missing optional file; existing bounded-read and regular
file checks still apply. The actual `RenderResume` consumer now rejects the
reproduced stale checkpoint without any change to its own implementation.
This completes **SR20/global424** and existing render identity.

### 5. Stop owns the saved-area target probe

The controller did not forward cancellation to the existing isolated target
capture helper. Saved-area reuse also omitted browser-region rollback and
could accept late metadata or update status during shutdown.

`capture_target` now forwards Stop/closing state and checks it again after
browser-region preparation, before publishing target metadata. Explicit reuse
clears an older Stop only after its idle/profile guards accept a new attempt.
On failure it restores all previous geometry, including the browser region;
shutdown receives no late status update. Success retains normal invalidation
of the old preview/plan and saved setup state.

Tests use real helper child processes and verify cancellation, termination,
reaping and closed pipes. They also cover the picker caller, a late Stop,
rollback after capture failure and successful retry. This completes
**NR03/global666**, **RT53/global495** and **UW12/global693**.

### 6. P3801 — smaller opaque Auto-count preparation

`AdaptiveColorCount` constructed a full visible RGB image before producing its
small BOX sample. Opaque RGB now reduces directly. Opaque L reduces first and
converts only the small result to RGB. Fully opaque RGBA processes one original
channel at a time with Pillow's complete public BOX operation and merges the
three small channels. No internal Pillow filter order is reproduced.

Mixed alpha, color-key inputs and other modes retain the original full visible
composition before resizing. Sample pixels, complete recommendation metadata
and the actual tuner caller match the historical path. This one work/storage
reduction is **P3801/global844**. It differs from **PL22/global162**'s NEAREST
style thumbnail and **C2001/global819**'s shared full-source analysis in other
color consumers.

Private samples, quantizers and partial channels are also closed on success,
failure and Stop. Those ownership/cancellation completions add zero IDs under
**IW08/global582** and **CQ07/global505**. Visible compositing retains
**AW21/global635**.

### 7. Native resize releases failed work before CPU fallback

Failed CUDA resize frames could retain native arrays while CPU fallback began
allocating. Private normalization, pre-reduction and final-fit images also
lacked explicit ownership. The native attempt now has a separate lifetime;
its completed traceback frames, including cause/context chains, are cleared
before CPU resizing starts. A VRAM preflight rejection likewise releases its
private pre-reduction before fallback uses the original gray input.

Stop propagates and borrowed source images remain open. Cubic interpolation,
unsharp mathematics and final-size fitting are unchanged. A minimal shared
`ImageOwnership` helper preserves the original exception/Stop if owned-image
cleanup also fails, adding a type-only note; a lone cleanup failure remains
visible. This completes **GP06/global558** and **IW08/global582**.

### 8. Extra Fast reuses exact costs within one operation

The existing candidate selection repeatedly priced the same immutable directed
paths. A private bounded view now uses the already-existing
`ExecutionCostModel.prepare_path_cost` API. The key contains the complete
ordered geometry and brush. Each prepared cost evaluates the actual incoming
cursor using the original arithmetic. Candidate construction, candidate
selection, caps, timed/portrait behavior and downstream selection are unchanged.

The owner retains at most **4,096 entries and 65,536 referenced points**. A
full cache falls back to ordinary pricing. Allocation failure during optional
construction, key/preparation or insertion clears/disables it before ordinary
pricing; Stop is checked first and a genuine pricing error still propagates.
The finalizer clears retained costs and drops model/cancellation references,
including when a caller retains an exception. Older lightweight cost models
without preparation keep their existing path.

This completes the already-counted immutable cost preparation in
**R1403/global789**. It receives zero new IDs. The actual public-plan tests
reduce `path_cost` calls from **141 to 68** and **432 to 94**, with identical
complete compared geometry, estimates, metadata, palette/source/preview pixels
and independent final-ink replay. Two consecutive invocations have the same
work counts, demonstrating that no prepared cache survives between operations.

## Measurements and rejected work

### Auto-count image storage and whole recommendation

Observed private PIL channel samples are width × height × bands summed over
simultaneously live observed private images. They are **not allocated bytes,
process RSS, GPU memory or all native scratch**. Six balanced process pairs
measure complete recommendation calls after two warm calls per process. Asset
loading, conversion, imports and hashing are outside the timed call. Full
sample pixels and recommendation metadata agree in all five workloads.

| Existing asset/mode | Peak channel samples, before → after | Median full call, before → after |
| --- | ---: | ---: |
| App screenshot RGBA, 1,920 × 1,048 | 6,087,168 → 2,062,848 | 14.536 → 14.370 ms |
| Same screenshot converted to L | 14,085,120 → 67,584 | 19.016 → 5.542 ms |
| App screenshot WebP/RGB, 720 × 393 | 899,568 → 50,688 | 7.366 → 7.480 ms |
| Social image RGBA, 1,280 × 640 | 2,504,064 → 865,664 | 10.264 → 10.554 ms |
| Mixed-alpha icon, 512 × 512 | 1,835,008 → 1,835,008 | 5.954 → 6.222 ms |

The L workload benefits in both observed storage and time. Other medians
include small slowdowns; the mixed-alpha control preserves its original
full-composite-before-BOX path, with added opacity checks and explicit cleanup.
Every pair and the 16.617 ms social-image outlier remain in the
evidence. This is no universal CPU or whole-application speed claim.

### Rejected broader Extra Fast search

An earlier experiment compared more regional axis candidates. It preserved
the checked rasters and reduced modeled input time in one fixture, but complete
planning cost outweighed the benefit: Line Art planning grew from
**98.931 to 126.683 ms** to save only **10.804 ms** of modeled input, and the
current-color icon grew from **165.854 to 223.170 ms** without input savings.
All six balanced pairs and traced allocation costs were retained.

A subsequent three-way experiment compared original selection, expanded
selection with prepared costs and original selection with prepared costs.
Expanded selection still had an insufficient margin in the affected whole
plan. It was rejected. Its product/test source snapshots, exploratory runs
and negative measurements remain archived as historical diagnostics; **none
of that candidate-policy expansion is in the final product or improvement
count**. The accepted patch retains the original selection and only reuses
cost preparation. Final before/after evidence is kept separately.

### Accepted Extra Fast whole-plan observations

Six balanced pairs run **144 timed public `make_plan` calls in 48 fresh
processes**. Each process records its first call and two subsequent calls.
Eight separate processes measure another **16 calls with tracemalloc**.
"Cold" below means the first complete plan after imports and asset loading,
not application startup. All compared source/preview/palette pixels, final
safety-plan ink, semantic plan fields and Extra Fast metadata are identical.

| Existing asset/canvas | Cold median, before → after | Warm median, before → after |
| --- | ---: | ---: |
| Paint tools, Line Art, 320 × 200 | 113.529 → 109.347 ms | 98.512 → 96.054 ms |
| Paint tools, Line Art, 128 × 128 | 83.170 → 73.206 ms | 67.806 → 59.183 ms |
| App icon, current color, 200 × 200 | 179.974 → 159.447 ms | 167.255 → 146.060 ms |
| App screenshot, fractional fitted scale | 115.549 → 109.716 ms | 96.795 → 92.046 ms |

These are local Linux whole-plan comparisons of exact b8 with the combined
working branch. Static caller review confirms that these explicit Extra
Fast/contour cases reach neither the changed gray resizer nor Auto-count
recommendation. Their timing manifest contains 19 files plus DrawBot's AST
without its app class, not every transitive dependency. That later review does
not retroactively add historical hashes for omitted modules. Direct cache
attribution is established separately by the reduced `path_cost` counts.

All raw pairs are retained, including individual slowdowns. The fractional
screenshot's Python-traced peak increases by **14,944 bytes cold and 12,502
bytes warm**; the other three cases have slightly lower traced peaks. This is
not a general RAM saving, complete native-allocation measurement, Windows
timing or physical Paint result. Prepared-cost reuse retains the original
draw geometry and modeled input time; its benefit is less planning work.

## Executed regression and integration evidence

Each accepted pair uses identical frozen new test bytes in the exact b8
baseline worktree and the working branch. Assertion failures within subtests
are recorded separately from the number of failed methods.

| Area | New methods | Baseline passed / failed methods | Baseline assertion failures | Patched result |
| --- | ---: | ---: | ---: | ---: |
| Legacy import retirement | 7 | 2 / 5 | 8 | 7/7, 0.041 s |
| Final reader budgets | 6 | 2 / 4 | 6 | 6/6, 0.097 s |
| Legacy export capture | 10 | 2 / 8 | 19 | 10/10, 0.086 s |
| Active calibration identity | 7 | 2 / 5 | 14 | 7/7, 0.025 s |
| Saved-area cancellation | 6 | 0 / 6 | 6 | 6/6, 0.526 s |
| Adaptive sample ownership/preparation | 10 | 3 / 7 | 8 | 10/10, 0.817 s |
| Resize ownership/fallback | 9 | 1 / 8 | 12 | 9/9, 0.077 s |
| Prepared Extra Fast costs | 8 | 2 / 6 | 7 | 8/8, 2.493 s |
| **Unique total** | **63** | **14 / 49** | **80** | **63 methods passed** |

All accepted pairs have zero errors/skips. Five of the renderer's baseline
failures assert the new owner exists; one additional method contains its two
public work-count failures. These are not seven pre-existing user bugs or
seven new improvements.

The final eight-module integration ran **63/63 in 3.785 seconds**, with no
errors/skips. Complete headless discovery ran **4,736 tests in 250.327
seconds: 4,650 passed, 86 skipped, zero failures/errors**. A separate real
Xorg/Tcl/Tk/CustomTkinter pass ran **7/7 native profile-load and profile-action
cases in 29.465 seconds**, with no skips. These seven existing methods are
part of the headless suite's skips, not additional new methods. All three
runs bind the same **954 unchanged source/configuration/fixture hashes**.

```bash
python -m unittest -v \
  test_v148_application_batch38_profile_legacy_context \
  test_v148_application_batch38_profile_legacy_export \
  test_v148_application_batch38_profile_legacy_import \
  test_v148_application_batch38_profile_reader_limits \
  test_v148_colour_batch38_adaptive_sample \
  test_v148_platform_batch38_resize_ownership \
  test_v148_rendering_batch38_prepared_paths \
  test_v148_ui_batch38_saved_area
python -m unittest discover -v
# With a real local display:
python -m unittest -v \
  test_v148_ui_batch36_profile_load.NativeProfileLoadTests \
  test_v148_ui_batch37_profile_reload_feedback.NativeProfileReloadFeedbackTests
```

Earlier adjacent selections passed 41 profile, 10 saved-area, six resize and
10 prepared-cost cases. The final profile selection separately ran 39 cases:
30 new plus nine existing controls. These selections overlap and are never
summed as new tests. Independent source/test reviews approved all eight
groups. The 5,000-cycle source gate and `git diff --check` also passed.
Local verification used Python 3.12.14 and Pillow 13.0.0 on Linux.
Source-package hygiene passed for **1,415 files**, with no forbidden paths,
missing requirements or warnings. All final filenames existed at that check;
only its result/evidence metadata was recorded afterwards.

The [validation record](v148-batch38-validation.json) contains commands,
counts, the final source map, count audit and review scopes. The
[evidence archive](v148-batch38-evidence.json) retains normalized raw focused
reports, logs, all measurements, rejected work and source manifests. Its
manifest references can be losslessly expanded; original raw-file SHA-256
values are retained. The large full-suite and native logs are separate
downloadable workspace artifacts with their hashes in the records.

## Compatibility and evidence boundaries

New image tests read existing repository assets and derive ordinary modes or
sizes. No new source motif, mockup or AI-generated image was introduced.
Controlled exceptions and device/process boundaries exercise real Pillow,
NumPy, filesystem publication/rollback and controller/consumer code. They do not
establish physical GPU execution, actual Microsoft Paint interaction or all
Windows display-scaling combinations.

The seven profile/image/saved-area modules first passed together as **55/55**
in **1.589 seconds**, with **954 unchanged source/configuration/fixture
hashes**. The renderer was finalized afterwards; that earlier integration is
not the final eight-module or complete-suite result. Earlier diagnostics and
intermediate test selections are retained separately and never added to the
unique-method count.

The initial profile registry-shape fixture and reader-order oracle were
corrected before their accepted frozen comparisons. An earlier nine-method
legacy-export selection preceded the final Paint-budget test. Earlier adaptive
and GPU selections retain their logs and hashes, but no separate copies of
those old test sources were saved. The final accepted pairs were rerun on both
sides with identical final test bytes. These diagnostics and the rejected
renderer experiments remain distinct from the final 63-method inventory.

The previous PR description, including batch37's exact-head results and its
first Windows timeout followed by an unchanged successful retry, is preserved
in [the batch37 history](pr46-history-through-batch37.md). Earlier green checks
are not verification of this patch. Current exact-head Windows/Linux/package
results belong to [draft PR #46](https://github.com/Vxiey/Image-Draw-Bot/pull/46).
No merge, tag or release is performed without explicit user approval.
