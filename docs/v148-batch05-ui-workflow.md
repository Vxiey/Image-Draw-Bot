# v1.0.148 UI workflow improvements — batch 05

Baseline: **5f3fcfb5c4519e5ed1b9b770ba951918819d725d** (668 previously reviewed improvements).
This scoped batch contains **13 independently reviewed distinct improvements, UW01–UW13**.
Tests, fixtures, benchmarks and documentation are not additional improvements.
The combined release is still in development.

Regression abbreviations:

- **D** — [drop and registry regressions](../test_v148_ui_workflow_batch05.py)
- **U** — [guide, overlay and picker regressions](../test_v148_ui_workflow_batch05_runtime.py)

| ID | Previous behavior and resulting change | Implementation and evidence |
|---|---|---|
| UW01 | HTML drops could select a script URL, a non-image data-src attribute or an image inside a comment/template before the actual dragged image. The parser now reads image elements and visible image links, ignoring inert/comment content and unrelated attributes. Quoted/unquoted attributes are decoded once, and duplicate attributes follow their first value. | CanvasDropPayload._ImageHTMLParser; D:test_only_real_image_attributes_can_outrank_the_dragged_image, test_html_with_only_inert_images_does_not_fall_back_into_its_markup, test_unquoted_html_attributes_decode_entities_once, test_duplicate_html_attribute_uses_the_first_browser_value. These are one HTML source-provenance group. |
| UW02 | A text/uri-list comment containing a short image URL could win instead of the actual dropped URI; multiple file URI lines also required Tcl preprocessing. Standard URI-list lines are now recognized with comments/blank lines excluded, and supported files are found without Tcl splitting. | CanvasDropPayload._uri_list; D:test_uri_list_comments_cannot_become_the_selected_image, test_uri_list_supports_multiple_file_uris_without_tcl_splitting. Existing item limits remain applicable. |
| UW03 | TIFF, ICO and APNG files already decoded successfully through ImageImport but were rejected by the drop extension filter. File drops and the shared file-picker pattern now admit those same formats. | CanvasDropPayload.IMAGE_FILE_PATTERNS; root consumes the shared pattern in DrawBot.open_file. D:test_local_tiff_ico_and_apng_drops_reach_the_existing_decoder decodes actual generated files. This is one format-parity improvement, not a count per extension. |
| UW04 | An inline image was parsed/stat-tested as a filesystem name, creating thousands of Path components from base64 slashes. Repeated case-insensitive matching also processed the case-sensitive base64 body unnecessarily. URI sources now skip filesystem parsing, the body uses its explicit ASCII alphabet, and already matched spans are not rescanned. Ordinary image URLs also skip irrelevant search-query parsing. | CanvasDropPayload.parse_canvas_drop and its data/URL helpers; D:test_inline_image_never_allocates_path_components_or_stats_a_filename, test_ordinary_image_url_does_not_parse_a_search_engine_query. Exact-output CPU/allocation comparison below. These related parser-work reductions form one group. |
| UW05 | An open guide continued showing Paint instructions after a profile change. The current topic now follows the live profile without requiring the user to close the guide or navigate to another page. | GettingStarted.show_guide; U:test_profile_change_refreshes_the_current_topic_without_navigation. Capability-appropriate static instructions complete UP06, as recorded below. |
| UW06 | Every guide Configure event reconfigured every label and queried the same width per label, including height-only changes. Events now coalesce into one idle callback; an unchanged wrap width produces no label updates. | GettingStarted.resize/resize_now closures; U:test_height_only_events_are_coalesced_without_reconfiguring_labels. Actual callback instrumentation: 1,000 height-only events, 6,000 label updates/6,000 width queries → 0/1. |
| UW07 | The guide treated a physical widget width as CTk logical pixels and forced a 240-pixel minimum wrap, allowing text to exceed scaled or compact viewports. Wrapping now divides by the widget scale and fits the available logical width. | GettingStarted._guide_wrap_length; U:test_wrap_uses_logical_ctk_pixels_and_fits_a_compact_body includes 150% scaling and compact/unrealized bodies. This concerns text wrapping, separately from earlier outer-window size fitting. |
| UW08 | Guide navigation required pointer operation of its buttons/menu. Alt+Left/Alt+Right now navigate bounded topics and Escape closes the guide; the shortcuts are visible in the guide. | GettingStarted.show_guide; U:test_keyboard_navigation_is_bounded_and_close_is_idempotent. No shortcut starts drawing or changes settings. |
| UW09 | Reopening an existing iconified guide only raised it and did not request restoration. Reopen now deiconifies and raises the existing window. | GettingStarted.show_guide; U:test_reopening_an_iconified_existing_guide_makes_it_visible. No duplicate guide is created. |
| UW10 | Each CTk guide scroll frame installed wheel/Shift callbacks on the root, but destruction left those callbacks and their frame references registered. The scoped frame now removes only its own callback IDs, including partial construction, without unbinding other widgets. | UiCompatibility.scoped_scrollable_frame; U:ScopedScrollTests and WindowsWorkflowTests.test_repeated_guide_close_removes_its_global_callbacks. Profile traces and pending guide jobs also end with the guide. This is callback ownership, distinct from UI07's invalid event-widget guard. |
| UW11 | Smart Canvas Drop passed signed desktop positions as Tk geometry offsets; negative offsets actually address the right/bottom screen edges. The overlay is now positioned with typed System32 SetWindowPos calls and checked against GetWindowRect. It stays visually hidden during realization/mapping and is revealed only after verification. | SmartDropInCanvas.place_canvas_overlay; root integrates it before DnD registration. U:OverlayPlacementTests and WindowsWorkflowTests.test_actual_window_can_be_placed_at_signed_desktop_coordinates. Official Tk8.6 wm geometry documentation: https://www.tcl-lang.com/man/tcl8.6/TkCmd/wm.htm . |
| UW12 | Stop during the screen-area picker's 250ms launch delay did not cancel its independently scheduled overlay; a late selection could still be delivered. The picker now observes the supplied cancellation callback before capture, while open and before delayed delivery, cancels its own jobs, restores prior window states and disposes undelivered crops. | RegionPicker.select_region(cancelled=...); root forwards its Stop/closing state from DrawBot.set_boundary and guards the callback. U:RegionCancellationTests cover all three phases. This user-modal lifecycle is distinct from NR03's subprocess cancellation propagation. |
| UW13 | Loading a large custom-profile registry rebuilt the full case-folded name set for each record, producing quadratic startup work. One incrementally maintained set now preserves the same normalized-name and storage-owner rules. | GameProfiles.load_custom_profiles; D:ProfileRegistryTests.test_loading_indexes_existing_names_once_and_preserves_first_valid_owner. Exact full-registry output comparison and 1,000-profile measurement below. |

## Completed earlier contracts, without additional counts

- **UP06:** Static guide instructions use the target's declared setup capability, extending the beginner wizard's existing manual/automatic setup distinction. U:test_manual_targets_are_not_told_to_use_an_unavailable_browser_detector. UW05 counts only refreshing the already open guide when the profile changes.
- **026 / CAL22:** RegionPicker now loads user32 with WindowsSystem.load_system_library. Its existing capture test mocks the shared loader.
- **IW08:** The picker closes captures and undelivered crops. Successfully delivered crops transfer to the callback: GetColorPositions retains its snapshot; root closes DrawBot's synchronous analysis crop in finally. The helper does not close a successfully retained palette snapshot.
- **IW31 / existing dialog rollback:** Guide construction/page staging cleans up partial owned widgets; picker crop-allocation failure no longer leaves a completed-but-uncloseable modal. These supporting failure paths are not separate counted entries.
- **Existing URL integrity / IW37:** Only balanced outer wrappers are removed, and a malformed encoded token cannot be accepted by dropping its invalid suffix. Tests cover signed trailing braces, uppercase MIME syntax and invalid token suffixes. No extra count.
- **RT32/RT34/RT35/RT37:** Root integrates drop lifetime, Stop/busy/stale callback checks and point_in_canvas. Those are completion of the earlier authorization/edge contracts, not new overlay or parser counts.
- **NR03/CAL05/RT39:** Missing cancellation arguments at existing browser-probe call sites remain the same previously counted cooperative-cancellation contract.
- ResponsiveRows has no active production call site and was not changed or counted.

## Validation

The combined focused run completed **188 tests: OK, with 4 Windows-only skips**.
The additional encoded-token boundary regression passed separately. Independent
read-only review checked the implementation, ownership/cancellation contracts,
all six benchmark source hashes and improvement-count overlap; it accepted
UW01–UW13 without a remaining concrete blocker. Full-project validation belongs
to the parent batch gate.

The native Windows tests create only application Tk widgets. They exercise
actual callback removal and signed-coordinate placement; they do not send
operating-system mouse or keyboard input. Linux mocks verify pointer-sized
window handles, native failures, verification order, cleanup, profile changes
and cancellation between scheduled callbacks.

## Reproducible measurements

[Benchmark script](../benchmark_v148_ui_workflow.py) and
[raw measurements](v148-batch05-ui-workflow-benchmarks.json).

    ../security-venv/bin/python benchmark_v148_ui_workflow.py --output docs/v148-batch05-ui-workflow-benchmarks.json

Seven alternating paired warm samples compare the actual baseline/current
functions and assert identical complete outputs. The JSON includes every
sample, output hashes, Python version and implementation hashes.

| Case | Baseline median | New median | Supporting result |
|---|---:|---:|---|
| Parse a 2,363,706-character inline PNG | 46.56ms | 2.46ms | Exact kind/label/source. Python temporary allocation peak 8,790,891 → 2,413 bytes. |
| Load 1,000 custom profiles | 48.89ms | 4.54ms | Identical complete registry. Python allocation peak unchanged at 1,054,510 bytes. |
| 1,000 height-only guide events | 2.73ms | 0.26ms | Identical text/wrapping. Label updates 6,000 → 0; width queries 6,000 → 1. |

The guide benchmark runs the real callbacks with fake widgets, not native Tk
rendering. Its recorded Python allocation peak includes fake call recording;
the useful portable evidence is the avoided widget calls. Parser/profile
timings are local CPU measurements, not guarantees about overall startup or
drawing speed. tracemalloc excludes native allocations and process RSS.
