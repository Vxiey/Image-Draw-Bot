# 1.0.148 batch 14 — preview ownership, keyboard inspection and browser image drops

Baseline: `f7b561f479d94f307924dbc779e5c8e365422f8d` (781 recorded groups).

This ledger contains **three distinct behavior groups, U1401–U1403**. The
individual keys, preview pages, parser cases, cleanup branches and tests are
parts of those groups. Manual Paint guidance belongs to the application's
A1402 workflow. AVIF admission completes the existing UW03/MP03 format
contract. Neither completion adds another UI improvement ID.

## U1401 — own auxiliary preview memory and omit the unused color raster

`finish_plan` constructed a source-color image through `PreviewLayers` and then
immediately replaced it with the execution preview. On a resized source, that
also performed a second source resize, alpha composition and RGB conversion.
Failure or Stop during auxiliary rendering left images in retained traceback
locals, including native Pillow image cores retained by `ImageDraw` handles.

`build_auxiliary_previews` now accepts `include_color_map=False` for that real
planning caller. The standalone default still returns stroke, fill and color
images. Planning keeps its existing executed-color image. The optional flag
does not change stroke/fill pixels, preview ordering or the source image.
An ownership scope closes unpublished images and intermediate composites on
every exit. It also releases the newly created drawing handles' native core
references, including when a traceback retains Pillow's own drawing frame.
Returned images stay open and independently writable; the borrowed source is
not closed or modified.

Five regressions in `test_v148_ui_batch14_layers.py` cover early stroke and
later fill failures, late Stop, a real Pillow drawing exception, exact
same-size/scaled stroke-and-fill parity and the public `make_plan` handoff.
The failure tests retain the actual exception rather than allowing garbage
collection to hide the ownership problem. The historical module fails the
three early/fill/late-Stop cases. The final tests inspect both image wrappers
and drawing handles. Independent review reproduced released native references
and live, independent successful output images.

The measured operation reduction is exact: the real caller creates no
auxiliary color image and makes no nearest-neighbor source resize for that
discarded result. No wall-clock speedup or process-memory percentage is
claimed. UI35's same-size source reuse and UI34's cancellation checks remain
in place; this group covers the different caller waste and failure ownership.

## U1402 — inspect every preview from the keyboard

The twelve preview canvases could be dragged with the mouse, but they had no
Tab stop or local keyboard inspection controls. `StudioUI` now creates
`KeyboardPreviewCanvas` for every real preview page. It adds one focusable
canvas when a visible, live page has an image, and a native focus border that
survives canvas image redraws. Existing mouse panning retains its bindings.

Arrow keys move the visible source window by 32 display pixels; Shift uses
160 pixels. Page Up/Down move by 80% of the viewport height. Home recenters the
current page. Plus/minus use the existing bounded zoom policy, 0 selects Fit,
and 1 selects 1:1. Panning divides by the current scale once and uses the
existing viewport clamp, so an edge reverses immediately without accumulating
hidden overshoot. A clamped or Fit-mode pan does not request a redundant draw.

The bindings are canvas-local. Ctrl/Alt/Meta combinations and unrelated
application shortcuts continue through their existing bindings. Empty,
unmapped, disabled, closed, unfocused or out-of-view canvases cannot act on a
stale key event. The class owns no delayed jobs and uses the native widget's
Tcl-command cleanup.

`test_v148_ui_batch14_preview_keyboard.py` has six portable integration tests
and one native Windows test. The portable tests execute the actual
`StudioUI` page factory, its zoom/drag callbacks and the real new event
handlers, replacing the native canvas boundary only. They cover all twelve
pages, display-to-source scaling, clamp/reversal, modifier/shortcut handling,
empty-state guards and retained mouse drag behavior. The Windows test uses
real Tk traversal and generated widget key events, checks visibility, focus
and Tcl cleanup, and sends no operating-system input. That native test is
skipped in the current Linux environment, which has no display server.

UK01/UW806/U1201 provide keyboard buttons, option menus and switches; UC05/UC06
provide existing zoom and drag geometry. This group adds the separate
preview-inspection interaction through those existing policies.

## U1403 — import the selected browser image with its original HTML context

A Windows CF_HTML payload can contain images outside the selected fragment,
UTF-8 byte offsets and a source-page URL. Treating the entire payload as plain
HTML allowed an earlier context image to win. Relative `img` addresses could
instead fall back to the page's `SourceURL`, or fail despite a valid HTML
`base` element.

`CanvasDropPayload` now validates the supported CF_HTML version and offset
fields, slices at UTF-8 byte boundaries and preserves the original transfer
whitespace until those offsets are resolved. The context supplies the base
URL and inert ancestry, while only the selected fragment supplies candidate
images and links. The first applicable `base href` resolves relative to the
HTTP(S) source URL. Relative, root-relative and scheme-relative references
retain existing percent escapes and query punctuation; literal attribute
spaces are encoded without decoding signed URL bytes. Scripts, templates,
comments, unsupported schemes and malformed metadata cannot become a page-URL
fallback or a competing unselected image.

Eight U1403 tests in `test_v148_ui_batch14_html_drop.py` use an independent
CF_HTML writer with Unicode before the selected fragment, earlier/later
context images, relative links, signed query strings, inline raster content,
base elements and malformed/duplicate offsets. Three test methods against the
complete historical parser produce ten wrong-source assertion failures and
one failed import of an otherwise valid base-relative image. The current
parser passes those cases. An integration case calls the actual window drop
handler and public `read_image`; only the HTTP transport is replaced with a
real PNG body. It verifies the selected URL, decoded image pixels and the
normal import-only behavior.

Independent review also reproduced a buffered-prefix boundary: Python's HTML
parser can defer context text ending in an unfinished character reference
until the next feed. The context is now flushed before source collection is
enabled, while base URL and inert ancestry remain available. An incomplete
HTML token at the fragment boundary is rejected. Markerless offset fixtures
cover unfinished references, split image attributes/comments and script or
template context; an outside URL can no longer enter through that buffer.

Primary format references used for this implementation:

- [Microsoft's HTML Clipboard Format](https://learn.microsoft.com/en-us/windows/win32/dataxchg/html-clipboard-format)
  defines UTF-8 byte offsets, version 0.9/1.0, selected fragments and optional
  surrounding context for relative references.
- [Chromium's Windows clipboard formatter](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/ui/base/clipboard/clipboard_util_win.cc)
  writes the `SourceURL` header alongside the context and fragment offsets.
- [WHATWG's base element definition](https://html.spec.whatwg.org/multipage/semantics.html#the-base-element)
  specifies the document base URL and the first `base` element with `href`.

UW01's HTML-source provenance and inert-content handling and UW02's URI-list
rules remain unchanged. U1403 adds Windows fragment/context interpretation
and relative reference resolution, rather than counting each accepted URL
syntax as another improvement.

## Existing-contract completions and coordinated integration

The same drop test module has a ninth test for AVIF. `ImageImport` already
advertised and decoded AVIF, but the shared file-picker/drop pattern and
bounded inline-image parser omitted it. They now admit `.avif` and
`data:image/avif`. The test writes and decodes an actual AVIF image from a path,
file URI, inline URI and selected browser fragment. It is codec-gated on
platforms whose Pillow build lacks AVIF. This completes UW03/MP03 without a
new ID; decoder restrictions and existing byte/pixel budgets stay intact.

For root-owned A1402, `StudioUI`, `UIState`, `BeginnerSetupWizard` and
`GettingStarted` consume the controller's live automatic-Paint policy. The
wizard and help cards describe manual tool calibration and Unlock→Start when
an explicit Paint tool is selected. Workspace state reads the controller's
actual optional diagnostic policy. An open guide follows both profile and
tool changes with one coalesced refresh, preserves its current topic and
removes both variable traces on close. Four integration tests exercise real
controller policy, UI callbacks and Tcl-variable changes.

## Validation status

The four new UI test modules contain **25 tests**, including one native
Windows-only preview test. The final focused command covered these modules
plus the existing preview, keyboard, guide, drop, raster-decoder, canvas,
application-event and Paint suites: **215 tests, 14 environment/native skips,
zero failures** (201 executed). The separate drop/decoder run passed all 64
tests with the available AVIF codec. U1401 received independent read-only
approval, including its native-core cleanup. U1402/U1403 independent review
closed after repeating the original buffered-prefix reproduction and passing
32 focused preview/HTML tests with three native Windows skips. The shared
whole-program/Windows gates are tracked by the coordinating application task;
they are not implied by the portable local run.
