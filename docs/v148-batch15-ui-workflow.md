# Batch 15 — UI and image workflow

Baseline: `43a1c968eb56a63224827f1567e4ccc354acdadb` (796 recorded groups).

## U1501 — paste already supported local and inline image sources

Paste handled native clipboard bitmaps and file lists, but its text fallback
accepted only HTTP(S). A quoted Copy as path string, a `file:` URI and a PNG
data-image URI all produced the generic copy-an-image instruction without
starting a loader. The same sources already decoded through the shared drop
parser and importer. The baseline reproduction decoded all three to exactly
`(12, 34, 56, 78)` while the actual Paste method made zero loader/fetch calls.

`ClipboardImport.parse_text_source` now normalizes that text fallback into the
existing `CanvasDropSource` contract. It retains the shared local-path and
file-URI rules, raster types and payload bound. Quoted paths preserve spaces,
Unicode, `#` and percent characters; file URIs use the existing one-pass URI
decoding. Inline images use the existing allowed MIME and strict decoder
policy. The text helper performs no image decoding or download.

A valid direct HTTP(S) source retains its complete address, including case,
signed percent escapes, punctuation and query values that happen to contain
`data:image` or another URL. It is recognized before the drop parser's
embedded-image ranking. This preserves the previous direct-URL Paste behavior;
arbitrary prose, HTML and unsupported URL schemes cannot become new import
sources. The original clipboard-text length is checked before trimming or
parser work.

The controller checks bitmap and native file-list formats first. HTTP sources
retain the existing visible URL field and `fetch_url` route. Local and inline
sources enter the ordinary tracked `load_source` worker, decoder and UI result
consumer. The normal image/resume/subject/edit-state invalidation remains in
that consumer. Decode failures or Stop preserve the previous image; rejected
owned results are closed.

The import keeps the existing explicit Drop-In action and never sets the
canvas-drop force flag. Ordinary import-only behavior remains unchanged when
Browser One-Click is off. An already enabled Browser One-Click mode creates a
fresh A1405 request for the newly adopted image, while the old request stays
revoked. There is no new source of automatic drawing permission.

All three newly reachable text forms belong to this one clipboard workflow.
UW02/UW03/MP03 already define accepted URI/file/raster formats, and BA01 already
owns bitmap preparation outside Tk. This change wires the missing text-entry
path into those existing contracts; it does not count formats, test cases or
the controller handoff separately.

### U1501 validation

`test_v148_ui_batch15_clipboard_text.py` has ten integration regressions. They
exercise the actual Paste method, real loader thread, public image decoder,
`loaded`/`done` events and UI adoption. Generated PNG fixtures retain all six
RGBA pixels, including partial and zero alpha. The native OS clipboard and
HTTP transport boundaries are replaced; file reads, Requests handling and
image decoding remain real. The existing UI presentation fixture avoids
requiring a display server.

Coverage includes native bitmap/file-list priority, direct/quoted/file-URI/
data-URI sources, HTTP byte preservation, explicit Drop-In completion ordering,
A1405 request replacement without inherited force, cancellation before
adoption, byte/pixel/raster limits, malformed data, unsupported schemes,
non-source text and live busy/profile/closing guards. An independent reviewer
found the direct-URL/query-data ambiguity during review; the final HTTP
regression includes that exact case and verifies the one fetched address and
decoded pixels.

The expanded clipboard/browser/drop/profile-lifecycle/decoder/redirect
selection passes **151 tests, no skips or failures**. These portable tests do
not establish an actual native clipboard interaction or physical drawing run.
Whole-project and Windows gates belong to the final shared checkpoint.

Independent review is closed without remaining blockers. The reviewer repeated
the original HTTP-query ambiguity, confirmed preservation of the complete
address and passed 30 new/adjacent clipboard/drop tests with the final code.

## U1502 — precise, state-checked contrast control

The active Contrast row used a raw CTk slider without a displayed value or
local keyboard adjustment. Its installed CTk 6 wheel handler also bypassed
`state='disabled'`: a real handler call changed the linked contrast from 1.25
to 1.325 while invoking the settings callback. The controller correctly
disabled the control during work, but that did not prevent this setting change.

The real row now uses `KeyboardSlider` and displays its current multiplier.
It has one logical Tab stop, a visible focus outline and the shared
scroll-to-focused-control behavior. Arrows adjust by 0.01, Shift or Page keys
by 0.10, Home/End select the existing 0.5/2.0 limits and Backspace restores
neutral 1.00. Adjustment joins the hundredth grid after an arbitrary pointer
position. Repeated input at a limit or reset value does not issue another
settings change.

All user adjustments retain CTk's original value-update path, including the
linked variable update before the existing `options_changed` callback.
Pointer clicking and dragging stay available, with pointer focus assigned to
the logical control. Programmatic variable and profile changes refresh the
readout through native drawing updates without issuing user commands or adding
a second variable trace. Disabled, destroyed, unmapped, unfocused or clipped
controls cannot accept keyboard/wheel adjustment. Existing application keys
and modified shortcuts continue through their original bindings.

Wheel input adjusts contrast only while the live control owns focus. Otherwise
the existing SmoothScroll dispatcher can scroll the surrounding panel through
the row. Its native CTk slider, scrollbar and text-widget ownership rules remain
unchanged; this explicit focus policy is specific to the new Contrast control.
This prevents both accidental setting changes during panel navigation and the
disabled-wheel mutation during an active job.

This is one complete numeric-control behavior. UK01 already owns button
activation, UW806 option-menu selection, U1001 changed-text numeric-entry
commits, U1201 switch activation and UP09 native wheel ownership. Their shared
focus helpers and regression tests are reused; no individual key, readout,
callback or call site is a separate improvement.

### U1502 validation

`test_v148_ui_batch15_contrast.py` contains seven portable regressions and two
native Windows cases. Portable tests execute the active StudioUI row and
registration, CTk's real `_clicked`, `_update_value`, `set`, reconfiguration and
variable-trace code, the actual controller's settings invalidation and busy
transition, and the actual SmoothScroll dispatcher. Only native widget
allocation/drawing/event delivery is replaced. They verify variable-before-
command ordering, exact bounds, numeric steps, no-op limits, pointer-to-keyboard
focus, programmatic readout refresh, disabled wheel/key/pointer behavior,
unchanged shortcut bindings, panel scrolling and owned-trace cleanup.
The dedicated Browser One-Click case also runs real `begin_worker` and
`set_busy` with a valid A1405 request: wheel, key and pointer input leave its
contrast, plan generation and request unchanged throughout setup.

The native Windows cases use actual Tk focus traversal and event delivery,
including the decorative canvas, pointer click followed by KeyPress, explicit
`focus_set`/`focus_force`, a disabled neighbor, offscreen Tab reveal and Tcl
command teardown. These two cases are skipped in this displayless Linux
environment and remain part of the Windows CI gate.

The focused contrast/button/selector/switch/numeric/preview/layout/workspace
selection ran **128 tests: 115 passed and 13 native Windows cases skipped**,
with no failures. `git diff --check` passed. No native interaction or general
application performance claim is made from this local run.
The final added Browser One-Click regression was then run together with the
complete contrast and A1405 modules: **21 passed, two native Windows skips**.

Independent U1502 review is closed without remaining blockers. The reviewer
checked the complete subclass/mixin/native CTk call order, actual StudioUI row,
scroll ownership, state and visibility guards, variable-before-command order
and trace teardown, then ran the final nine-method module: **seven passed and
two native Windows cases skipped**. No production patch was needed after review.
