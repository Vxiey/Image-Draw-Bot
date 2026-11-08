# Batch 30 — complete Portrait stroke image ownership

## Status and classification

**Focused before/after tests, independent review and complete historical output
parity and integrated validation are verified. This is an existing-contract completion with zero new improvement
IDs.**

IW08/global582 covers owned image lifetime and preservation of borrowed caller
images. PL37/global177 covers Portrait cancellation; PL38 covers the analysis
session, while GP12/global564 and GP14/global566 already cover finite stroke
caps and priority selection. Batch03 explicitly treated Portrait lifetime as an
uncounted IW08 completion. Batch29 completed preparation and the public
caller's private gray-image ownership. This follow-up closes the remaining
local image-view owners during stroke generation; the individual loops and
failure variants are not separate improvements.

## Actual published before behavior

The baseline is published batch29
`4b90b715a9128a022774f411e14e8a1b45676339`. The before observer and permanent
regressions used the frozen batch29 checkout, private runtime/calibration
directories, disabled bytecode writes and a repository-write/network audit.
All **887 root Python files** were unchanged, canonical map digest
`48245acbd0a159956f998b1009f022a5d7b0245f977f741eef84016c9ffbb4bc`.

The actual public chain is `make_plan` → `prepare_portrait_image` →
`portrait_strokes` → the selected CPU analysis/selection loop. The cancellation
callback latches Stop only after the selected real loop has acquired its
`PixelAccess`, blur or score-generator view. The probe retains the original
exception and inspects its actual frames before releasing any test-owned
references.

Batch29's caller `finally` already closes the private prepared gray wrapper.
That alone did not retire the native image views retained by the later stroke
frames. For the public 127 × 96 gray image, the old saliency Stop kept the
private blur open and three readable `PixelAccess` aliases alive, even though
the gray wrapper was closed. These are three references, not a claim of three
distinct native image allocations.

| Actual interrupted branch | Owners visible in the retained old traceback | Corrected ownership |
| --- | --- | --- |
| Saliency row loop | Outer `px`, saliency `px` and `bp`; private blur still open | Local views retired; private blur closed and its weak reference dead |
| Priority sort | Outer `px`, selection `pixels`, its `scores` closure cell and generator frame | Local view and shared closure cell retired |
| Priority heap | The same selection owners, reached with a real finite cap | Same cleanup while retaining the existing heap policy |
| Dot row loop | `_dot_strokes.px` | Local view retired |
| Edge row loop | Outer and edge `px` | Local views and edge host aliases retired |
| Direct RGBA stroke caller | The saliency views of its private L conversion | Views retired; caller RGBA remains open and unchanged |

The finite before fixture explicitly sets Manual mode and all applicable
3-second fields. The real selector observes 94 candidates with priority 1 and
takes the heap branch. The unlimited control observes the same 94 candidates
with priority 24 and takes the sort branch. An earlier diagnostic intended as a
heap control still left Unlimited mode selected; its raw callback correctly
records `sort`. That report remains preserved and is not presented as heap
coverage.

The scoped eight-case raw summary is
`pending-batch30-portrait-strokes/before-scoped/summary.json`, SHA-256
`d9be8fdd82134c005925831f39563b26419ae3cc46264136003c0642f5df8d98`.
Its `probe_completed` flag means the observer finished with unchanged sources
and no audit violations; it does not mark the recorded old ownership behavior
as passing.

## Minimal correction and native-failure boundary

Only five functions in `PortraitPlanner.py` change. Their existing numeric
bodies execute inside local `try/finally` boundaries:

- `_saliency_map` retires its two pixel views and closes its private blur after
  its last consumer, including Stop and callback errors.
- `_select_tone_candidates` clears the shared `pixels` closure cell, so a
  retained score generator cannot retain that view after its consumer exits.
- `_dot_strokes` and `_portrait_strokes_impl` retire their own local views.
- `_edge_strokes` retires its local view and local Sobel-array aliases without
  modifying borrowed arrays or acceleration metadata.

The original formulas, iteration and tie order, quality settings, sort/heap
decision, finite caps, GPU-session scope and cancellation points are unchanged.
The historical verifier removes only the new owner initialization and outer
`try/finally` structure and confirms **all five original function AST bodies
are identical**. No generic traceback clearing is added to product code.

A separate directed native-failure control passes an intentionally malformed
GaussianBlur radius through the real Pillow filter call. It produces Pillow's
real `TypeError: must be real number, not str`. This is an injected transport
failure, not an observed valid GUI setting. Before and after the fix,
`PIL.ImageFilter.GaussianBlur.filter` retains its own readable `ImagingCore` in
the third-party `image` local while that exception is held. The correction
retires our Portrait views and owned wrappers while deliberately preserving
that Pillow frame, the original error object and its diagnostic traceback.
**This control does not establish that all native image cores disappear while
an arbitrary Pillow exception remains alive.**

Caller-owned L/RGBA sources, metadata and EXIF remain usable and unchanged.
Successful public plans keep their independent returned images and previews.

## Permanent regressions and independent review

`test_v148_rendering_batch30_portrait_strokes.py` contains seven actual-flow
methods. Against the frozen published baseline they give **13 expected
assertion failures across seven methods, zero errors and zero skips**. The
source map remains the original 887/48245 map. The before summary is
`tests-before/summary.json`, SHA-256
`655936f9b405d2125e0d1ca6ca3e4ba19748677495f0cad86be3de10f1d8b6dc`.

After the correction, **7/7 pass in 0.628 seconds**, no skips. An independent
reviewer read the complete diff and test module and ran **7/7 in 0.654 seconds**,
also with no skips or blockers. These are test durations, not performance
measurements. The tests cover actual saliency/sort/heap/dot/edge Stop, original
callback-error identity, direct borrowed and converted inputs, the real Pillow
failure boundary, and successful imported Auto/Portrait/dot public plans.

The initial after observer records all eight cases with unchanged sources and
no audit violations. The actual Stop cases have no retained Portrait image
views; both native-failure cases retain only the explicitly described Pillow
owner. This was an intermediate **888-source** checkpoint, digest
`f13a320fa28939f470e1f1b5558ed9704188cb591c848ade8238ba50f51a7df8`,
not the final integrated source inventory. Its summary SHA-256 is
`e6f55cc1be6033df096474a3f92be12cfa0aa17e33e7d22d78b8376c2ca8b73c`.

| Frozen file or focused log | SHA-256 |
| --- | --- |
| PortraitPlanner.py | `8bbc6958fa212532c70b16eff6ac1cfb761bbdcf0cbbe13a9773e1e2630a4903` |
| New regression module | `26c712a054c7fc97c799a6fed910e995a6bad1ab8abcc190c6afe45979a08bd9` |
| `targeted-after-initial.log` | `b016aefc7051964757f757d01c65b02479329a31949263f802a2523d7453c90c` |
| `batch30-portrait-independent.log` | `574f3416209b2ae4e17880d01a6a91aba3b2f7c36a50d1d84a8e84a3fa7d33da` |

## Complete historical output replay

The untimed verifier loads the **complete published PortraitPlanner and
DrawBot modules together** from 4b90, with the historical Portrait import
installed throughout each historical call. Other current dependencies are
explicitly shared. This compares the complete historical caller/stroke pair,
not every historical repository dependency. Both sides use the same actual
private calibration directory and real importer/UI options.

All **14 helper pairs and seven complete public-plan pairs are exact**. The
comparison includes returned geometry, ordering, stroke statistics, acceleration
metadata, prepared-gray pixels/metadata/EXIF and fitted dimensions, every stable
plan field and image bytes. Only the seven existing profiler-clock paths from
the preparation parity fixture are excluded. No timing or memory claim is made.

The helper matrix covers all five qualities, lines/dots, caps 0/1/79, borrowed
L and converted RGBA, subject focus off and edge generation off. The public
matrix also exercises imported opaque/partial-alpha images and real finite
time fitting:

| Actual public pair | Canvas | Paths on both sides | Actual finalization passes on both sides |
| --- | --- | ---: | ---: |
| Auto / Balanced, opaque RGBA | 128 × 96 | 582 | 1 |
| Portrait / High likeness, partial alpha | 128 × 96 | 1,267 | 1 |
| Portrait / Balanced dots | 128 × 96 | 1,792 | 1 |
| Portrait / Balanced, Manual 3 seconds | 128 × 96 | 19 | 1 |
| Portrait / High likeness, Manual 30 seconds | 480 × 360 | 126 | 1 |
| Portrait / Maximum likeness | 160 × 120 | 1,365 | 1 |
| Portrait / High likeness, Manual 180 seconds | 1200 × 900 | 611 | 2 |

The last case sets `manual_max_seconds`, `max_seconds` and Manual mode
consistently; its source is 320 × 240, detail 10 and delay 0.025. Both real
planner calls perform two finalization passes and report time fitting. It does
not manufacture fitting metadata or alter the clock. The earlier batch29
finite fixture also resolved to 180 seconds through its real manual setting;
this replay records the effective value explicitly.

Historical module SHA-256 values are
`5fcb6fc29084d173c734c34808fb0deb150907532c58f24673f37f340a224c67`
for PortraitPlanner and
`c378c40658fe26828cf627cc899c53a6dbdf4b4c1c2949ba70336260bda2bf83`
for DrawBot. The final replay leaves all **892 current root Python sources**
unchanged, canonical digest
`ce9691bce3bdb6b6e992ab3383b323e803f85e8df95c6a99ff6f409a9d345abd`.
Its entire map was compared, not only its digest, with the batch30
prebenchmark freeze and is identical. Every entry also matches that snapshot's
full **942 source/configuration**
map, digest
`d9c61fbb5e914dcd37682fc08b5b19c20a7eec2bb4ab806b0cbe3806d9fea156`.
The later fixture-only gate correction below has a separately recorded source
map; this report is not relabeled as if it executed that later inventory.

The final report is
`pending-batch30-portrait-strokes/historical-parity-complete/summary.json`,
SHA-256
`2e7d5d5f408cf5bf6c708d065271db5cb53d30155bacb2131f3e8cb0c8884121`.
Both sides' seven image PNGs are preserved beside it. Repository-write and
network audit violations are zero.

## Preserved diagnostic history and limits

Earlier reports remain separate, with their original status and source maps:

- `before/summary.json`, SHA-256
  `c45b1314f68d0d9e52ea00e2e7014e050aca3f2beb0a3e13f3e78c8c503a7d44`,
  includes the initial Unlimited/sort fixture described above.
- `historical-parity/summary.json`, SHA-256
  `65ed949fc51ff63a2a5e89f00633df4d1815c1d10a073aa80bbe3aa23577ba3f`,
  records a scratch report-serialization failure on EXIF bytes after successful
  helper comparisons. The serializer was changed to lossless hexadecimal byte
  encoding; no product comparison or source policy was changed.
- `historical-parity-final/summary.json`, SHA-256
  `88e5a257a72980a6e77ac7cad670ef749440c6b4a408000d67d5b47fa51fead8`,
  records 14 helper and six public equalities but fails its additional
  requirement to exercise a second finite fitting pass. The final replay adds
  the explicit 180-second case while preserving the 3/30-second controls.

The failed historical attempts bind their own unchanged 891-source checkpoint;
they are not relabeled as final passes. This completion establishes local
ownership and output preservation on CPU. It makes no GPU throughput, RSS,
general runtime improvement or new-head Windows certification claim. Integrated
full-suite, native, source/raster and package results are reported separately by
the batch30 final gates.

## Later integrated-gate fixture diagnosis

The first integrated suite attempt ended without a final unittest summary or
after-manifest; its cause is unestablished. A subsequent attempt actually
terminated with `Tcl_AsyncDelete` and SIGILL/exit -4 after 225.816 seconds, with
the 942-source map unchanged and no completed test count. Both attempts and the
separate detached launch that produced no test evidence remain failed or
incomplete diagnostic records.

The narrow Portrait diagnostic then ran all seven real new methods in a fresh
child. Delegating observers recorded **zero `_tkinter.create`, zero Tk owners
and zero Tcl variables**. A subsequent real worker-thread collection retired
6,994 cyclic objects and exited normally; the original variable finalizers were
preserved. All seven methods passed in 0.580 seconds, the 892-source map stayed
unchanged and audit violations were zero. This excludes a new Tcl allocation
in these tested Portrait flows; it does not infer the full-suite producer from
the name of the test where the crash became visible.

The separately reproduced producer was an older UI25 calibration test fixture.
Its correction changes only
`test_v148_ui_batch25_calibration_lifetime.py` and adds
`test_v148_ui_batch30_fixture_ownership.py`. All product sources, this Portrait
regression, and the image/benchmark evidence sources remain byte-identical.
The final gate inventory is **893 root Python files**, digest
`0da8de7641efb47fea77c62ece22629b27f9425c137e9d8ccd8d7e9933ae5845`,
and **943 source/configuration files**, digest
`5f6b89f5b52c9ae6f0335345f744fb887936afdab1e847eb5c22d73f3c155b41`.
The exact two-path before/after hashes are recorded in
`v148-batch30-fixture-only-source-transition.json` and the fixture ledger.
The 892-source Portrait replay remains the actual earlier checkpoint, with
that narrow later test-only difference documented explicitly. No Portrait
product or test change was made in response to the Tcl diagnosis.


## Integrated frozen-source result

Batch 30 records **842 distinct improvements, 158 remaining**. 2 new behavior groups are registered: R3001, R3002. Background cleanup preserves detail already protected by the border flood; picture-palette growth avoids retesting unchanged centers. Portrait stroke ownership, Stop across image-copy handoff and test-fixture Tcl disposal complete existing contracts with zero IDs. All 840 prior registry entries and 78 earlier benchmark JSON reports are preserved. Completed frozen discovery ran **4,551 tests in 231.751 seconds: 4,478 passed and 73 skipped**; all 943 source/configuration hashes were unchanged. Fourteen Linux/Xorg native cases, the 5,000-cycle source gate, eight exact raster fixtures and initial package hygiene (1,359 files) passed. The package check after final metadata passed with 1,361 files and no warnings. The incomplete process attempts and the Tcl-aborted attempt remain negative evidence. A proved old calibration fixture released borrowed Tcl aliases after real cleanup; no product GC policy, skip, assertion or timeout was weakened. The final background and Portrait historical comparisons and the six-workload/six-pair palette measurement retain their original 892-file map; the final 893-file map differs only in the two explicitly recorded fixture files. Historical checks retain 20 exact background controls and 24 intended corrections, 14 Portrait helper and seven public pairs, and 32 palette comparisons including four public plans. The cold red picture-palette helper and direct refinement improve in all six pairs; unchanged-work controls are not treated as algorithm gains. No universal speed, peak-memory, process-RSS, physical Paint or GPU improvement is claimed. Parent 4b90 has seven green checks after one unchanged Windows-job rerun; the new head requires its own exact-commit CI. Version 1.0.148 remains unreleased.

The final gates bind **893 root Python files**, compact SHA256 `0da8de7641efb47fea77c62ece22629b27f9425c137e9d8ccd8d7e9933ae5845`, and **943 source/configuration files**, compact SHA256 `5f6b89f5b52c9ae6f0335345f744fb887936afdab1e847eb5c22d73f3c155b41`. The original measured/evidence map remains **892 root files**, SHA256 `ce9691bce3bdb6b6e992ab3383b323e803f85e8df95c6a99ff6f409a9d345abd`. The only later differences are the old calibration fixture cleanup and its new subprocess regression; their exact sources, hashes, import boundary and diff are recorded in [raw evidence](v148-batch30-completion-evidence.json) and [final validation](v148-batch30-validation.json). No timing or image checkpoint is silently rebound. The final metadata review and post-metadata package check are recorded separately; publication of the new head does not imply its remote checks have completed.
