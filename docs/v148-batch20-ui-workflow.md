# v1.0.148 batch20 — accepted image previews and browser drawing regions

Baseline: `47777158e5b1daf759993190e638fe507e7691da` (818 published
improvements). This ledger contributes **zero new improvement IDs**. The source
handoff completes BA01's existing automatic-preview/completion contract for
the other supported import and edit paths. Its Stop and private-image cleanup
are parts of that same working action, not separately counted features. The
browser work completes RT53's existing complete-target adoption and
CanvasGuard's selected-area contract. Its caller, cache and physical-tool
checks are also **zero additional IDs**.

## BA01 completion — preview accepted imports and edits after their worker

The actual `loaded` and `background_removed` consumers attempted to schedule
automatic planning while the tracked loader/editor still owned `activity`.
`_maybe_auto_preview` correctly refused busy work, and neither consumer retained
a request for its matching `done`. The upscale result consumer did not request
an automatic preview at all. The visible source changed, but the selected
`Auto light`/`Auto full` mode left the old plan invalidated without rebuilding it.
Bitmap Paste already had the working idle handoff from BA01.

Accepted file/URL imports, background removal and resampling now use that same
`needs_plan` handoff. `poll` consumes it only once the operation releases the UI,
then uses the existing bounded automatic-preview pipeline. Undo of a resize
uses its existing source-adoption consumer and obtains the same new preview.
No-op background removal retains its original image and existing plan.

Manual remains a hard lock. The new request does not authorize drawing:
explicit Drop-In and the existing source/profile/request-bound Browser
One-Click continuation retain their earlier callback priority. Entering their
tracked worker cancels the still-unstarted automatic preview. Import-only
continues to import only; no URL scheme, persistent switch or one-shot drawing
permission changes here.

The real keyboard Stop signal exposed two related unfinished paths. Esc after
an accepted bitmap but before loader completion could still schedule planning;
Esc after timer scheduling could be cleared by the subsequent automatic
`begin_worker`. Automatic scheduling and callback entry now observe Stop. The
final worker handoff uses `reset_stop=False` for automatic requests, retaining
an Esc received during options/snapshot preparation. An explicit Build preview
is a new user request and still starts after a previous Stop.

## Private preview source ownership

`update_plan` owns a source snapshot before starting its tracked worker. It now
closes that snapshot if startup is refused or raises, and passes its cleanup to
the existing `begin_worker` owner after successful acceptance. Cleanup also
runs if Stop skips the task or a planner exception retains a traceback.

The public planner creates independent plan/reference/preview images. The
regression keeps those images and the accepted original alive, checks their
pixels after worker completion, and verifies that only the private input
snapshot is closed. This completes existing image-ownership behavior at zero
additional count; it makes no new memory-throughput claim.

## Evidence

`test_v148_ui_batch20_auto_preview.py` contains 16 test methods. The successful
routes use actual file loading, border-connected background removal, pixel-art
resampling, tracked threads, queued results, `done`, `poll`, `update_plan`, and
the public `make_plan`. They compare the resulting normalized source preview
with the accepted pixels, including the newly transparent background and
resized dimensions. The only GUI substitutions are the Tk scheduler, native
window visibility and UI rendering boundaries. Browser setup replaces its
screen-discovery boundary; drawing continuation is observed at actual tracked
worker acceptance without emitting native input.

The tests cover both automatic modes, Manual, bitmap compatibility, no-op
background results, Stop before/after adoption and after timer scheduling,
Esc delivered during options preparation, explicit Build after Stop, resize
Undo, Drop-In, persistent Browser One-Click, its explicit force alternative,
and private snapshot cleanup. The accepted-but-not-yet-executed cancellation
test uses a real thread held at a bounded gate, then the real worker wrapper.

Before the correction, the first 11 methods produced nine subtest failures;
the additional options-handoff test also failed. All three later snapshot
ownership checks failed while keeping the image objects strongly reachable.
After both corrections, **all 16 methods passed in 1.879 seconds**. The adjacent
Manual/Start-preview, clipboard, source/plan feedback, lifecycle and Browser
One-Click gate passed **89 tests in 1.971 seconds**.

A separate process compiled the exact three historical controller method
bodies from `47777158e5b1daf759993190e638fe507e7691da` and ran the same final
16-method suite against them, without editing the checkout or index. The
historical run produced **13 subtest failures, zero errors and zero skips**;
the current run passed all 16. These include assertions about the newly
available preview competing with authorized continuations, so they are not
13 independent product defects. The local evidence is recorded in
`batch20-auto-preview-compare.json` and the corresponding before/after logs in
the parent scratch directory.

Independent source/flow review is closed without a blocker. The reviewer ran
these 16 methods together with the seven preview-ETA methods: **23 passed in
5.066 seconds**. Later frozen whole-project/native CI gates are tracked
separately from these focused results.

## RT53 / CanvasGuard completion — keep the selected browser drawing region

The original controller reproduction used a 1600 × 900 Gartic screenshot,
actual canvas/palette detectors, calibration files, cache, tracked workers,
queued result adoption and the mandatory drawing refresh. Only the native
picker, capture and window boundaries were substituted. The user selected
`(700, 600)–(1100, 850)`, a 400 × 250 drawing region inside the detected
932 × 522 full canvas at `(580, 490)–(1512, 1012)`.

`set_boundary` initially accepted the selected region. Its automatic setup
result then replaced it with the full canvas. Restoring the selected corners
did not work: the mandatory pre-input refresh expanded them again, and the
independent visual-preflight recovery also adopted the full canvas. Directly
passing the smaller region to the full-canvas detector correctly failed with
a 412-pixel mismatch; treating that failure as permission to expand the user
selection was the defect. A screenshot retaining all 72 palette colors but
removing the canvas instead cleared the selected area on each repeated
selection and sent the user back to the same action.

The original before evidence is retained in `batch20-manual-area-probe.json`.
An independent root run of that same probe against the corrected controller
is recorded separately in `batch20-manual-area-probe-after.json` and its log.
It retains the exact 400 × 250 region through adoption, refresh and independent
visual preflight. Both palette-only selection attempts retain that new region
as unverified, keep Start blocked, and reject mandatory refresh. Both probe
routes emit **zero mouse calls**. The direct detector comparison still rejects
the smaller box; no visual verification rule was relaxed.

### Separate geometry and identity

`BrowserDrawingRegion` represents the user's explicit selection in client
coordinates. It is bound to the current profile, native window handle, client
dimensions and DPI. It keeps the first verified full-canvas layout separately
from the latest verified canvas. A same-size window move translates the
selected region exactly. A different window/profile, changed client size,
changed DPI, changed canvas layout, or region outside the freshly detected
canvas requires a new selection. Detection edge jitter is compared with the
original layout, so repeated detections cannot accumulate a tolerated shift
into an enlarged drawing area. No scaling policy was added.

The object supplies geometry, never drawing authorization. Existing Browser
One-Click source/profile/request ownership remains in force. Its workers and
queued results additionally retain the exact region owner they scanned;
replacement or Stop cannot mark a new selection verified. The record is not
restored from settings or recovery. Same-profile Reset, profile changes and
safe recovery retire it. Explicit Full Setup and dropping on the newly
highlighted full-canvas overlay choose that new full target and retire an old
manual subregion; ordinary image import retains the current selected region.

`capture_target` creates the region only from the current explicit selection
and freshly captured target metadata. Auto Setup, One-Click and pre-input
refresh independently detect the full canvas, prove containment, and retain
the selected corners for planning. Current-ink mode performs its existing
canvas-only verification without inventing a palette requirement. A newly
selected palette-only result can remain visible as **unverified**, with the
concrete next step to show the complete canvas and run Auto setup browser.
An older unbound or other-window canvas is still cleared under RT53.

### Cached setup, independent verification and physical tools

A successful palette cache samples palette geometry/colors; it is not proof
that the stored full-canvas rectangle is still present. When an explicit
region exists, cached Auto Setup and `one_click_setup` detect the canvas in
the same fresh capture used by the palette check. `Setup + Verify` carries the
same ownership through its initial setup and second live worker. That second
pass validates the existing visual detector's actual canvas against the
region's client/DPI/layout policy before reporting success. The regression
rejects a six-pixel layout shift even where the generic full-canvas verifier's
tolerance is wider, and rejects a changed DPI with a still-matching palette.

Brush, opacity and tool-position detectors receive the verified full canvas
only for locating controls. The selected area continues into public
`make_plan`, `execute_plan` and the real per-path CanvasGuard. There is no
replacement of CanvasGuard or bypass of independent visual preflight.

A native bucket Fill is not bounded by its seed point, so a strict browser
subregion disables native Fill and uses the existing brush-stroke fallback.
The actual planner regression requests Conservative background fill and the
region-fill engine with calibrated controls, then verifies that neither a
background-fill operation nor fill regions reappear later in planning.

Global Clear also affects the entire host canvas. The existing Eraser sweep
uses normal brush width for its spacing/inset; the application does not have
a separately verified native Eraser width. Consequently Auto clear is
rejected before worker/input for a strict subregion, even with calibrated
Eraser and Brush controls. The visible message tells the user to disable Auto
clear or select the full canvas. Explicit full-canvas drawing keeps its
existing Fill availability and native Clear behavior; Small Test's existing
no-clear policy is unchanged.

### Actual flow and fixture evidence

`test_v148_ui_batch20_browser_region.py` contains 15 product-flow methods and
one fixture-lifetime subprocess regression. The product methods use real
selection callbacks, calibration/cache files, loader and setup threads,
queued adoption, both live verification workers, reset/recovery controllers,
public planning and execution. Render options are deterministic fixtures;
native capture/window/picker/input and persistence/UI rendering are the
substituted boundaries.

The execution oracle independently paints the delivered physical round-brush
footprints onto a host-canvas image. Its native Fill and Clear deliberately
affect that entire host image, so an in-bounds seed cannot conceal escaping
effects. With a selected 120 × 90 region, drawing produces real strokes and
**zero changed pixels outside that region**. A positive full-canvas control
executes actual native Clear. Both Clear-only and calibrated Eraser/Brush
configurations reject strict-region Auto clear with zero input and without
starting a worker. Additional routes cover imported persistent One-Click
through actual execution, explicit CanvasDrop through its real loader and
force continuation, current-ink refresh, same-size translation, resize/DPI/
window mismatch, cache-only false confidence, stale results and Stop.

The adjacent browser setup, visual checks, One-Click, DPI, tools, Clear,
overlay, saved-area and RT53 suite passed **105 tests in 17.053 seconds**. The
actual same-profile Reset test confines profile paths, timing file and its
transaction sidecar, shared speed history, and both path-factory data roots
to its temporary directory.

An initial local 15-method run passed, but the independent repeat exposed a
test-fixture race followed by `Tcl_AsyncDelete` (exit 132); that interrupted
run has no completed pass count. The temporary `patch.dict(sys.modules)`
scope could restore the module table while the real loader was importing
`ImageImport`, causing its observed error. The fixture now uses the installed
DnD wrapper behind its native overlay stub and never replaces the global
module table. Its real Tcl `splitlist` reference exists only during the local
drop callback and is detached in a creator-thread `finally`, including failed
assertions. Retained scheduler/Mock callback graphs cannot keep that extra
interpreter owner alive for later worker collection.

The interrupted independent run remains in
`batch20-browser-region-independent.log`. The isolated first-four run completed
with one error in 17.867 seconds, retaining its actual traceback in
`batch20-browser-first-four.log`; the instrumented repeat in
`batch20-browser-first-four-diagnostic.log` identifies the loader's exact
`Operation failed: 'ImageImport'` event. These failed diagnostic records were
not replaced by later passing logs.

The exact first-four sequence that exposed the race then passed in
17.586 seconds. The additional subprocess regression passed in 2.731 seconds:
it retains successful callbacks and a real failed-overlay traceback, requires
dead Tcl/Variable weak references and actual finalizers only on the creator
thread, then performs successful cyclic collection on a separate worker.
Diagnostic collection is delayed only inside that child to make the boundary
deterministic; production GC and all real route assertions remain unchanged.

Final independent source/flow review is closed without a blocker. Its repeat
passed **15/15 BrowserRegionFlowTests in 61.891 seconds**, recorded in
`batch20-browser-region-independent-final.log`. The independent fixture-owner
regression passed **1/1 in 2.978 seconds**, recorded in
`batch20-browser-region-ownership-independent.log`. Both final logs remain in
the parent scratch directory alongside the unchanged failed diagnostic logs.
The 16-method module, browser helpers and controller integrations are now
frozen for the root's whole-project and packaging gates. These focused results
do not claim a new native Windows/browser run or a performance improvement.

## Existing test-fixture lifetime completion — zero new improvement IDs

The first frozen whole-project attempt subsequently aborted with
`Tcl_AsyncDelete: async handler deleted by the wrong thread`, exit **-4** after
**126.93 seconds**, with all **867** frozen source hashes unchanged. Its last
announced case was the first BrowserRegion planning/execution method, after
all 16 Auto-preview methods and the BrowserRegion ownership subprocess had
passed. There was no preceding test error. This interrupted run has no
completed test total. Its original records are preserved as
`v148-batch20-fullsuite-attempt1.log`,
`v148-batch20-local-regressions-attempt1.json` and
`v148-batch20-source-hashes-attempt1.json` in the parent scratch directory.

The narrow Auto-preview/Browser sequence passed independently, so the abort
location did not establish a defect in that product flow. Separate child
processes then ran these older, real UI test methods successfully, discarded
their cases, and requested cyclic collection on a worker. Each retained a
headless Tcl interpreter and its variables until that worker collection:

| Existing fixture | Tcl owners / variables remaining after success | Before result |
| --- | ---: | --- |
| Drawing readouts, batch09 | 1 / 4 | Wrong-thread original finalizers, abort 132 |
| Numeric-row commit, batch10 | 1 / 1 | Wrong-thread original finalizer, abort 132 |
| Actual twelve switch rows, batch12 | 1 / 12 | Wrong-thread original finalizers, abort 132 |
| Actual Contrast row/controller, batch15 | 1 / 2 | Wrong-thread original finalizers, abort 132 |

The unchanged before logs are `batch20-tcl-readouts-before.log`,
`batch20-tcl-numeric-before.log`, `batch20-tcl-switch-before.log` and
`batch20-tcl-contrast-before.log`. Diagnostic collection is delayed only in
these isolated children to make ownership deterministic; production GC is
unchanged and the original Tcl/Variable destructors still execute.

The readout fixture now uses an ordinary constructor function instead of an
unnecessary Mock whose call history retained real `textvariable` objects.
Its temporary dictionaries and app references are released in `finally`,
including a retained assertion traceback. Numeric, switch and contrast AST
factories explicitly register their exec namespaces with the owning fixture.
Those namespaces remain live through actual Help, options, preview-toggle and
value-readout callbacks. Cleanup first runs the real control destruction and
variable-trace removal, then retires only the fixture's Python references to
variables, callbacks and controller adapters. The native pointer caller and
Sketch workflow pass the same scope ownership through their existing helpers;
Sketch also releases its borrowed Tcl alias after the shared fixture cleanup.
No production control, input implementation, assertion, example count or
platform skip was removed or weakened.

The four identical after probes all reported **zero live Tcl owners and zero
live variables before worker collection**, with every original Variable
finalizer on the creator thread. Full numeric, switch, contrast and Sketch
fixture modules were also checked across the same worker-GC boundary.
`test_v148_ui_batch20_factory_ownership.py` adds four permanent subprocess
regressions. Each keeps real callback graphs and an injected assertion-frame
traceback alive while requiring dead weak references, creator-thread original
finalizers and successful later worker collection. The numeric regression
also invokes the real Help closure before teardown; the control regressions
observe actual trace removal before any fixture reference release.

Those four regressions passed in **1.539 seconds**. The combined chain ran
**62 cases in 10.793 seconds: 56 passed and six unchanged native-platform
skips**, in `batch20-tcl-fixtures-final-chain.log`. It includes the four older
UI modules, Sketch workflow, new ownership cases, all Auto-preview cases and
the exact BrowserRegion case at the interrupted whole-suite boundary.

An independent agent reproduced and completed the same fixture ownership
class in the older HTML-drop and Mobile-dialog tests. Their successful methods
had retained respectively one Tcl owner and one owner plus nine variables,
then aborted 132 during worker GC. The fixes detach the borrowed HTML parser
reference and retire Mobile fixture references after real stop/destroy. The
two permanent success/retained-failure ownership regressions passed in
**1.779 seconds** (`batch20-auxiliary-tcl-after.log`); their related 20-case
gate ran in **3.506 seconds: 18 passed and two unchanged Windows-native skips**
(`batch20-auxiliary-tcl-focused.log`). The original
`batch20-html-tcl-before.log` and `batch20-mobile-tcl-before.log` remain intact.
These are verification-lifetime completions, not additional product features.

The same independent audit reproduced one remaining owner in the older
GuideHarness: a successful actual profile/topic refresh left one Tcl
interpreter and one StringVar for worker collection, then aborted 132
(`batch20-guide-tcl-before.log`). Its test-only exit now destroys the real
guide, closes its patches and then releases its private app/interpreter
references. A new child regression keeps the successful and failed actual
flows' menu/Alt/Esc callbacks alive and verifies they remain inert after
cleanup, while requiring the same creator-thread finalizer/weak-reference
boundary. Its 20-case module gate passed with **18 successes and two unchanged
Windows-native skips in 0.252 seconds**. Independent source review closed
without a blocker; the fake Widget and production guide were not changed.

The numeric, switch, contrast and pointer-switch native cases also passed
independently in four separate Linux/Xorg Tk 9.0.4 processes, retaining all
original callback, focus, readout, trace and global-binding assertions. Times
were respectively **0.085, 0.149, 0.087 and 0.188 seconds**, recorded in
`batch20-native-factory-xorg-final.log`. This verifies the actual scope handoff
through widget destruction locally and does not claim new Windows evidence.

Peer review caught one fixture reporting detail: the nested Sketch test case
must propagate a false `doCleanups()` result to the outer test. Its explicit
assertion now preserves that failure signal while the borrowed Tcl alias is
still released in `finally`. The final Sketch plus four ownership regressions
passed **9/9 in 1.895 seconds**, recorded in
`batch20-factory-ownership-final.log`. All original behavior assertions and
the real destroy-before-release guards remain in place.
Final independent source review of all four older fixtures, the two shared
factory callers and the new ownership regressions is closed without a
blocker. Source/test files are frozen for the repeated whole-project gate;
the interrupted attempt is retained as failed evidence.

## Final shared integration gate

The repeated frozen-source discovery completed **4,162 tests in 200.541
seconds: 4,104 passed and 58 existing platform/hardware cases were skipped**.
All **869 source/configuration hashes** remained unchanged; the canonical
manifest SHA-256 is
`d1b653faf0929b07759357f7edc83419ccaf6a76b0e67ce107a5d7eaf082f517`.
This is the accepted whole-project result. The interrupted attempt and focused
before failures above remain separate records. The 5,000-cycle source gate,
package hygiene and all eight exact-raster engine fixtures also passed.
The shared final evidence is [v148-batch20-validation.json](v148-batch20-validation.json).
New published-commit Windows/Linux and CodeQL results are recorded separately
in PR46; the local Xorg checks do not substitute for Windows CI.
