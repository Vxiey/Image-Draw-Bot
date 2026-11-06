# v1.0.148 image workflow and UI improvements — batch 03

This ledger records **40 distinct behavior improvements** against checkpoint
`2fb7abf470a4ef498df9c53f42cddda62d8b652b`. Related call sites, regression tests,
documentation, helper extraction and changes completing an existing item are
not counted again. Independent colour-agent review is closed. Final whole-program
integration passed 2,800 tests in 70.634 seconds with 22 platform/hardware skips
and unchanged source hashes; the 5,000-cycle source gate and package hygiene passed.
Windows checkpoint verification remains pending.
This is a development checkpoint, not a release or an antivirus verdict.

Regression modules: [image processing](../test_v148_image_batch03.py),
[image import](../test_v148_import_batch03.py),
[subject workflow](../test_v148_subject_batch03.py), and
[UI/export lifecycle](../test_v148_ui_batch03.py).

| ID | Behavior improvement | Evidence |
| --- | --- | --- |
| IW01 | Enforce background-analysis dimension/pixel caps even for nearly matching sizes, and keep one-pixel axes rather than distorting them to two pixels. | `test_proxy_keeps_one_pixel_axes_and_never_exceeds_limits`. |
| IW02 | Accumulate minimum background-cluster distances instead of retaining and stacking every full distance plane. | `test_cluster_minima_match_independent_stacked_reference`; 900 × 700 paired benchmark. |
| IW03 | Skip scalar neighbour-distance work for already definite background candidates or rejected edges. | `test_definite_background_does_not_compute_scalar_neighbor_distances`; identical flood output. |
| IW04 | Find connected-component seeds one row at a time instead of materializing two full-image coordinate arrays. | `test_largest_component_uses_bounded_row_seeds_and_row_major_ties`; exact component result and lower allocation peak. |
| IW05 | Estimate the removable background from visible pixels composited on white, so invisible RGB values cannot change segmentation. | `test_invisible_rgb_does_not_change_segmentation`. |
| IW06 | Count alpha visibility using 256-bin histograms rather than exporting and iterating all alpha bytes in Python. | `test_preservation_counts_alpha_threshold_without_exporting_full_bytes`; complete-removal metadata parity. |
| IW07 | Bound alpha-combination scratch buffers by rows and use byte-sized feather classification arrays. | `test_alpha_product_matches_all_65536_pairs_with_small_strips`; exact rounding for every pair. |
| IW08 | Close owned image buffers on success, cancellation and partial failure across image editing, import, exports and subject dialogs, while preserving caller-owned and successfully returned images. | Background/upscale ownership tests, rejected-worker snapshot tests, import post-decode cancellation and mask-overlay lifetime tests. One shared ownership improvement. |
| IW09 | Reject invalid/oversized background-removal sources and nonfinite feather settings before allocating an oriented image. | `test_invalid_resource_inputs_fail_before_transpose`. |
| IW10 | Reduce the background-analysis proxy before expanding it to RGB, avoiding a full-source RGB intermediate. | `test_analysis_rgb_conversion_occurs_after_proxy_reduction`. |
| IW11 | Observe Stop between orientation, large upscale/resampling and final conversion rather than continuing expensive work after a request to stop. | `test_stop_after_orientation_prevents_larger_resize`; existing oriented pixel-art output is preserved. |
| IW12 | Describe premultiplied alpha and palette-embedded alpha correctly, considering only palette entries actually used by the image. | Premultiplied-alpha and embedded-palette-alpha description tests. |
| IW13 | Inspect image transparency without a full-image alpha/RGBA conversion: extrema for alpha, 256 palette entries for indexed images and bounded strips for colour keys. | Alpha-copy, palette-conversion-size and RGB-key final-row tests; palette-label benchmark. |
| IW14 | Classify drawing styles from the visible composited image, ignoring hidden colour under transparent pixels. | `test_drawing_style_ignores_rgb_hidden_under_zero_alpha`. |
| IW15 | Sample drawing-style metrics directly into a bounded image and count colour properties with bounded arrays instead of copying the full source and building Python pixel tuples. | Full-source-copy rejection and extreme-aspect geometry tests; exact opaque metrics in paired benchmark. |
| IW16 | Honor Stop during PNG image/preview encoding, flush and publication-lock waits before replacing the destination; an interrupted export cannot publish a late file or leave an incomplete stage. | Export Stop tests, including Stop while another publisher holds the publication lock. Basic staging/atomic replacement extends UI31 and is not counted again. |
| IW17 | Encode preview PNGs in a tracked worker using a snapshot, keeping encoding off the UI thread and preventing later preview changes from altering the exported frame. | `test_export_preview_encodes_off_ui_thread_and_uses_a_snapshot`. |
| IW18 | Create background-removal Undo state only after successfully adopting a result, rather than when scheduling work that may fail. | Failure and successful-adoption Undo tests. |
| IW19 | A no-op background-removal result retains the current image, valid plan and Undo state instead of invalidating the session. | `test_noop_background_result_keeps_existing_plan_and_undo`. |
| IW20 | Reject image edit/Undo/export actions during shutdown before opening dialogs or taking image snapshots. | `test_closing_ui_does_not_open_export_dialog_or_start_an_edit`. |
| IW21 | Validate UI transaction counters and retry limits before mutation or input, so malformed metadata cannot partially change state. | Invalid-counter atomicity and retry-limit tests. |
| IW22 | Bound UI transaction history and detail strings while reporting dropped event count and still delivering every observer call. | `test_long_transactions_keep_recent_bounded_telemetry_and_all_observer_calls`. |
| IW23 | Record terminal operation/recovery failures as FAILED and preserve the original exception when failure reporting itself fails. | Original-exception identity and nonretryable/recovery failure tests. |
| IW24 | Reject automatic subject detection on fully transparent images rather than interpreting invisible RGB as a real subject. | `test_fully_transparent_colours_cannot_become_an_automatic_subject`. |
| IW25 | For partially transparent images without fully empty pixels, estimate the subject from its visible white composite, including indexed-palette transparency. | Partial-alpha and palette-alpha equivalence to the visible composite. |
| IW26 | Sample ordinary opaque subject images before channel expansion and decode alpha in bounded strips, avoiding full-size RGBA/RGB analysis intermediates. | Large-opaque conversion-size and tiled-alpha tests; exact subject-mask benchmark. |
| IW27 | Validate subject-mask dimensions, a 64-megapixel allocation limit and finite normalized rectangles before allocating the mask. | `test_invalid_rectangles_and_dimensions_fail_before_mask_allocation`. |
| IW28 | Observe subject-selection Stop during alpha scanning and after explicit ROI allocation or full-size mask expansion. | Mid-strip cancellation and Stop-after-ROI allocation tests. |
| IW29 | Show transparent subject-selection and mask previews against their visible white background rather than exposing hidden RGB. | Selector white-composite and mask-overlay content tests. |
| IW30 | Downsample compatible subject-preview sources before EXIF rotation/conversion, retaining correct rotated bounds and caller EXIF. | `test_preview_reduces_before_rotation_and_preserves_exif_and_caller`. |
| IW31 | Roll back partially built subject dialogs and keep their selection state closed after Apply/Cancel, preventing duplicate callback delivery. | Failed-dialog construction and repeated/invalid Apply tests. |
| IW32 | Bind a subject-selection result to its original image and idle operation; late callbacks cannot apply a rectangle to a replacement image or ongoing drawing. | `test_late_subject_result_cannot_change_a_different_image_or_busy_operation`. |
| IW33 | Roll back failed preview-page registration/layout while retaining the previous page, selector state and original error. | Preview page-switch and failed-registration regressions. |
| IW34 | Fit initial main/dialog geometry and minimum sizes to the current screen and CustomTkinter window scaling, avoiding oversized mandatory dimensions on smaller/high-DPI displays. | Screen-size × scaling matrix and actual StudioUI builder test. |
| IW35 | Decode local imports from a private bounded snapshot of the same regular-file handle whose size was checked; actual file growth cannot bypass the byte budget and later path replacement cannot change the decoded snapshot. | Growing-file limit and replacement-during-decode tests. |
| IW36 | Stream encoded image input into a memory-bounded spool and decode base64 in bounded blocks, avoiding full bytearray/BytesIO/encoded-substring duplicates. Reject impossible encoded lengths and invalid budgets before allocation. | Spool-rollover, pre-decode size/budget and block-size tests; 8 MiB fixture allocation benchmark. |
| IW37 | Accept the URL-safe base64 alphabet already supported by the drop parser while rejecting invalid padding or hidden trailing encoded content. | URL-safe decode and malformed-padding fixtures. |
| IW38 | Carry cancellation through every import source and after decoding; consume available HTTP body data with read1 so Stop/deadline checks do not wait for a full chunk, and preserve interruption if response cleanup fails. | Pre-I/O, local-read, download, post-decode and available-body-read tests. Socket/native reads retain their own timeout limits. |
| IW39 | Validate HTTP Content-Length and verify identity-encoded body length before decoding, while keeping compressed wire length separate from decoded-byte limits. | Invalid, truncated, compressed and HTTP-whitespace Content-Length fixtures. |
| IW40 | Run manual/automatic hardware, GPU and resource tests through the shared tracked worker lifecycle; prevent concurrent drawing/tests, snapshot Tk settings before dispatch and reject cancelled late recommendations. | Hardware-worker, startup-rejection, late-result, compute-Stop and resource-setting-snapshot tests. |

## Shared changes and previous work

- Background cancellation before allocation and at return boundaries completes
  original item 072; additional checks inside that algorithm do not add a new ID.
- Atomic staged PNG export extends the existing GIF-publication behavior in UI31;
  IW16 counts only the newly cancellable export-publication boundary.
- Picture palette Stop/ownership checks complete RT06/RT07/RT18, and its cancelled
  result rejection completes RT44. They are not additional items here.
- Pixel-map categorical validation and detector/planner cancellation integrations
  belong to the rendering/planning ledger. GUI forwarding does not add an item.
- GPU/resource benchmark algorithm cancellation and completed-profile publication
  belong to the GPU/platform ledger. IW40 covers the previously untracked GUI
  worker/concurrency lifecycle.
- `ImageGeometry`, `ImageImport`, the atomic-writer helper and tests are implementation
  mechanisms, not separately counted features.

## Paired measurements

[Reproduction script](../benchmark_v148_image_workflow.py) and
[raw samples](v148-batch03-image-benchmarks.json) retain five alternating before/after
samples after exact output checks, using generated local inputs and the baseline
above. Measurements cover CPU helpers, not real drawing speed, network latency,
GPU execution or Windows UI. Python allocation tracing excludes most native
Pillow allocations; it is not total process RAM.

| Workload | Before median | After median | Measured memory/evidence |
| --- | ---: | ---: | --- |
| Four background-cluster distance minima, 900 × 700 | 22.28 ms | 23.23 ms | Python peak 33.65 → 24.03 MiB; lower allocation, no speedup claimed. |
| Definite-background flood, 240 × 180 | 159.77 ms | 43.03 ms | Exact mask, distances and counters. |
| Largest component, 350 × 250 | 69.32 ms | 62.60 ms | Python peak 0.893 → 0.102 MiB; exact size and box. |
| Drawing-style metrics, 4000 × 3000 opaque RGB | 31.81 ms | 13.40 ms | Exact complete metrics; Python peak 1.472 → 0.135 MiB. |
| Subject mask, 2000 × 1500 opaque RGB | 85.04 ms | 81.79 ms | Exact full-size mask; Python peak 9.534 → 6.781 MiB. |
| Complete background removal, 240 × 180 | 151.33 ms | 52.89 ms | Exact output pixel bytes and metadata. |
| Indexed image transparency label, 3000 × 2000 | 7.45 ms | 2.04 ms | Exact label. Full native RGBA/channel image copies are removed; Python peak grows by about 74 KiB for palette metadata. |
| Base64 image import with 8 MiB encoded source fixture | 22.72 ms | 23.26 ms | Exact image and format metadata; Python peak 29.33 → 2.23 MiB. Timing essentially unchanged. |

Transparency corrections intentionally change results for invisible/partly visible
source data; the parity benchmarks use opaque or previously correct fixtures.
Tests separately verify the corrected visible-image behavior.
