# v1.0.148 UI, import and preview improvements — batch 01

This ledger records **41 distinct runtime improvements**. Related implementations of the same correction count once. Test cases, documentation, version promotion and benchmark tooling do not count as improvements. These changes are undergoing integration review; this document does not claim that version 1.0.148 has been released or that the requested total of 1,000 has been reached.

Regression modules: [UI helpers](../test_v148_ui_batch01.py), [UI runtime](../test_v148_ui_runtime.py). Test names below identify behavioral assertions or injected failure cases in these modules.

| ID | Runtime change | Evidence |
| --- | --- | --- |
| UI01 | Mixed file drops and clipboard file lists continue past unsupported files to find the first usable image. | `test_mixed_file_drop_reaches_the_first_supported_image`; clipboard uses the same parser. |
| UI02 | Bound raw drop input, total item characters and item count before filesystem/regex processing; scan HTML/URL candidates without retaining all matches. | `test_oversized_drop_is_rejected_before_filesystem_or_regex_work`; 16,001-URL measurement below. |
| UI03 | Interpret `file://localhost` as a local path instead of a UNC share. | `test_localhost_file_urls_keep_local_path_and_reject_control_bytes`. |
| UI04 | Reject decoded control bytes in file URLs before filesystem use. | NUL-containing URI fixture in the same parser regression. |
| UI05 | Switching preview tabs lays out only the changed pages; selecting the visible page avoids a redundant layout. | `test_selecting_same_page_does_not_relayout_or_hide_siblings`, including OptionMenu's early variable update. |
| UI06 | Reject duplicate or blank preview page names before allocating widgets and orphaning pages. | `test_duplicate_or_blank_page_is_rejected_before_allocating_a_widget`. |
| UI07 | Contain Tk errors from destroyed CustomTkinter scroll targets. | `test_destroyed_scroll_target_does_not_raise_tcl_error`. |
| UI08 | Reuse existing profile presets without constructing a discarded generic preset on every lookup. | `test_builtin_lookup_does_not_allocate_a_discarded_generic_preset`; measured lookup workload below. |
| UI09 | Protect shared profile preset defaults from caller mutation while returning an editable export copy. | `test_shared_defaults_cannot_be_modified_by_a_caller`. |
| UI10 | Handle malformed optional calibration metadata when producing profile warnings. | `test_invalid_and_explicit_empty_calibration_metadata_are_handled`. |
| UI11 | Honor an explicitly supplied empty calibration state rather than falling back to stale state inside options. | Explicit-empty regression in the same test. |
| UI12 | Treat a warning string as one warning instead of rendering each character as a warning. | `test_single_warning_string_is_not_rendered_as_individual_characters`. |
| UI13 | Preserve elapsed time when updating the same start state and use one clock snapshot for watchdog output. | `test_repeated_state_updates_keep_elapsed_time_and_bounded_history`; `test_watchdog_uses_one_consistent_clock_snapshot`. |
| UI14 | Logging failures cannot interrupt valid start transitions or bypass invalid-transition rejection. | `test_logging_failure_cannot_break_or_skip_state_transitions`. |
| UI15 | Require an actual supported integer calibration-anchor schema version. | `test_schema_requires_an_integer_and_coordinates_fit_windows_long`. |
| UI16 | Validate stored and translated calibration coordinates against signed Windows LONG bounds while retaining negative monitor coordinates. | `test_translated_points_cannot_overflow_native_coordinates` and anchor rectangle fixtures. |
| UI17 | Reject invalid layout tolerances consistently instead of truncating fractional tolerances or raising overflow errors. | `test_invalid_layout_tolerance_fails_as_validation_error`. |
| UI18 | Read only the version-history viewer's bounded character budget. | Instrumented stream read in `test_history_reads_only_the_viewer_budget_and_tries_readable_fallback`. |
| UI19 | Try a readable bundled version-history fallback when the preferred existing file is inaccessible. | Permission-error injection in the same history regression. |
| UI20 | Bound dictionary bytes during the read, including files that grow between metadata inspection and reading. | `test_word_list_read_is_bounded_even_if_the_file_size_changes`. |
| UI21 | Index immutable dictionary snapshots by letter count and reuse them across searches without stale results after caller list changes. | `test_word_length_index_preserves_patterns_and_mutable_dictionary_updates`; identical-result measurement below. |
| UI22 | Keep native paste behavior in multiline text and spinbox controls, including Tcl widget path events. | `test_text_and_spinbox_paste_stays_native_even_with_a_tcl_widget_path`. |
| UI23 | Block clipboard imports while closing or waiting for a clear operation, preserving the in-flight operation's image state. | `test_clipboard_is_not_read_during_close_or_pending_clear`. |
| UI24 | Apply EXIF orientation exactly once to pasted image objects without changing the clipboard source. | `test_pasted_exif_orientation_is_applied_once`. |
| UI25 | Recognize uppercase HTTP schemes and reject malformed hosts/ports before starting an image-fetch worker. | `test_uppercase_url_from_clipboard_is_imported`; `test_malformed_url_is_reported_without_starting_a_worker`. |
| UI26 | Roll back all worker startup stages, including hide/busy/thread-construction failures, while preserving the original error if cleanup also fails. | `test_all_startup_failures_restore_idle_and_the_screen_window`; `test_cleanup_failure_does_not_hide_the_original_startup_error`. |
| UI27 | Respect cancellation that arrives before a non-screen worker begins its task. | `test_cancellation_before_non_screen_task_start_skips_the_task`. |
| UI28 | Yield the UI event loop after a 15 ms drain budget instead of processing up to 250 expensive events in one uninterrupted call. | `test_event_drain_yields_with_backlog_and_preserves_fifo_order`; queued events remain in order. |
| UI29 | Contain canvas destruction during the preview error-message fallback itself. | `test_destroyed_canvas_during_error_fallback_is_contained`. |
| UI30 | Copy the mobile-preview URL without creating an unused Tk StringVar for every call. | `test_missing_mobile_url_never_creates_an_unowned_tk_variable`. |
| UI31 | Encode GIF recordings to a unique staging file, flush before atomic replacement, and preserve existing recordings on failure. | `test_recording_uses_unique_staging_and_preserves_unrelated_tmp_file`; `test_failed_encode_or_flush_preserves_the_previous_recording`. |
| UI32 | Close captured and quantized recording frames after success or partial capture failure. | `test_partial_capture_failure_closes_all_owned_frames`. |
| UI33 | Sample long safety-preview paths before coordinate conversion instead of allocating a transformed copy of every point. | Byte-identical layer hashes and 200,000-point allocation measurement below. |
| UI34 | Check preview cancellation before allocation, inside long individual paths and before returning completed layers. | `test_large_safety_path_is_cancelled_inside_the_path`; `test_cancelled_preview_does_not_allocate_images`. |
| UI35 | Reuse the correctly composited source when preview dimensions already match, avoiding duplicate resizing and alpha compositing. | `test_same_size_source_is_not_resized_twice_and_layers_do_not_alias`. |
| UI36 | Skip nonfinite fill-region boxes without discarding otherwise valid auxiliary preview layers. | `test_bad_fill_box_does_not_discard_valid_preview_layers`. |
| UI37 | Commit a recaptured tool window identity only after anchor layout validation succeeds. | `test_failed_recapture_does_not_commit_an_incompatible_window_identity`. |
| UI38 | Keep subject-selector thumbnail bounds positive on compact desktops. | Compact-screen fixture in `test_subject_selector_handles_compact_desktop_and_closes_before_callback`. |
| UI39 | Destroy the subject-selection modal before invoking the application callback, including callbacks that raise. | Callback failure fixture in the same modal regression. |
| UI40 | Restore an initially minimized region-picker owner to its minimized state instead of leaving it withdrawn. | `test_region_capture_start_failure_restores_an_iconic_owner`. |
| UI41 | Release region-picker full-desktop buffers on selection/cancellation while leaving the delivered crop usable. | `test_region_capture_releases_desktop_buffers_on_selection_and_cancel`. |

## Measurements

Measured in the same local Python environment against unchanged commit `94a748ec7690eebb542c70311c594aa835434a98`. Results are medians of three runs (five for preset lookup), after one warmup. Peak allocations use a separate `tracemalloc` run; native image/driver allocations and total process RSS are not measured. Generated inputs and complete result hashes are deterministic. These are helper benchmarks, not physical Windows-input or GPU benchmarks.

| Workload | Before | After | Result |
| --- | --- | --- | --- |
| 30,000 built-in preset lookups | 78.94 ms; 1,192 peak bytes | 2.77 ms; 120 peak bytes | Same preset; avoided eager unused construction. |
| 100 searches over 20,000 words, reused dictionary | 796.03 ms; 2,852,010 peak bytes | 19.59 ms; 2,883,666 peak bytes | Same complete result hash; memory approximately unchanged, plus a bounded four-dictionary cache outside the warm measurement. |
| Sample 200,000-point path into three preview layers | 164.59 ms; 24,027,272 peak bytes | 15.23 ms; 388,406 peak bytes | All stroke/fill/color bytes identical. |
| Rank 16,001 URL candidates | 306.82 ms; 5,695,062 peak bytes | 241.14 ms; 3,908,748 peak bytes | Same selected image; claim a lower temporary allocation peak, not a reliable speed improvement from a few variable timings. |

Reproduce with `python benchmark_v148_ui.py --source-tree <checkout> --output <results.json>` using the same interpreter for both checkouts. Compare the `result` fields before interpreting timing differences.

## Verification

The two new test modules plus eight related existing suites passed **107 tests** locally. Whole-program integration subsequently passed 2,202 unittest tests (19 platform/hardware skips). Native Windows validation remains a separate CI gate.

[Raw integrated measurement results](v148-batch01-benchmarks.json) retain all timing samples, result hashes, fixture metadata and allocation scopes.
