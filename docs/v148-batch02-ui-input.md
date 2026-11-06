# v1.0.148 input, runtime and UI improvements — batch 02

This ledger records **56 distinct behavior improvements** against checkpoint
`1c09774ad22088c5c30a8f8220b6b451fdee9659`. Related call sites, regression tests,
documentation and benchmark tooling are not counted separately. This is a
development batch; neither the 1,000-improvement target nor release publication
is claimed here.

Regression modules: [input boundaries](../test_v148_input_batch02.py),
[runtime controls and queued starts](../test_v148_ui_batch02.py),
[timer and probe lifecycle](../test_v148_timer_probe_batch02.py),
[UI lifecycle](../test_v148_ui_lifecycle_batch02.py), and
[native probe metadata](../test_v148_target_probe_batch02.py).

| ID | Behavior change | Evidence |
| --- | --- | --- |
| RT01 | Reject coordinates outside signed Windows LONG range before creating a native POINT; negative-monitor coordinates remain valid. | `test_native_window_probe_rejects_wrapping_coordinates`, `test_negative_monitor_coordinates_remain_valid`. |
| RT02 | Check all four corners and the center of target/capture areas instead of accepting coverage on only one diagonal. | `test_window_capture_detects_cover_on_other_diagonal`. |
| RT03 | Fail target capture and isolated target inspection when Windows cannot return a valid process identity. | `test_capture_does_not_accept_missing_process_identity`, `test_disappearing_window_cannot_return_a_successful_probe`. |
| RT04 | Use one client-rectangle snapshot for a complete target-area validation, avoiding repeated native queries and mixed geometry. | `test_capture_uses_one_client_rectangle_snapshot`. |
| RT05 | Require custom-color modal controls to belong to the locked window or its owned foreground dialog; recheck ownership after moving to the control. | Owned-dialog, foreign-overlay, ownership-cycle, focus-change and missing-verifier fixtures in `ModalOwnershipTests`. |
| RT06 | Refresh the observed pointer after live callbacks, overlay waits and settle waits before authorizing a native action. | `test_overlay_retry_refreshes_actual_pointer_before_click`, `test_live_target_callback_cannot_leave_a_stale_pointer`. |
| RT07 | Recheck foreground identity after palette sampling instead of sending input under pre-capture focus evidence. | `test_palette_sampling_rechecks_foreground_before_press`. |
| RT08 | Honor cancellation that arrives during foreground activation before arming the mouse. | `test_cancellation_during_foreground_probe_does_not_arm`. |
| RT09 | A failed mouse rearm revokes a previous armed state. | `test_failed_rearm_revokes_prior_arming`. |
| RT10 | Sample the entire palette in one bounded capture, preserving compatibility with older monitors and rejecting incomplete batch results. | `test_palette_is_sampled_as_one_batch`, `test_partial_palette_sample_cannot_be_marked_verified`; 20 probes use one batch call. |
| RT11 | Bound modal brightness, spectrum and canvas captures before allocation. | `test_brightness_scale_rejects_huge_capture_before_grab`, `test_canvas_capture_has_a_pixel_budget`. |
| RT12 | Release owned screen-capture images on conversion, sampling, cancellation, scoring failure and runtime completion; keep caller-owned source images alive. | Conversion/sample cleanup, failed timer observation, snapshot rejection and post-draw cleanup paths. Shared cleanup behavior counts once. |
| RT13 | Reject a screenshot whose returned dimensions differ from the requested region. | `test_capture_size_mismatch_is_rejected_and_released`. |
| RT14 | Validate target identity again after a canvas capture before accepting its pixels as evidence. | `test_snapshot_rejects_focus_change_during_capture`. |
| RT15 | Reject margin captures when the selected canvas itself extends outside the target client. | `test_margin_capture_rejects_partially_outside_canvas`. |
| RT16 | Compute actual color error, confidence and sample count for the single-pixel ink/fill fallback when neighborhood sampling is unavailable. | `test_empty_neighborhood_uses_measured_fallback_error`. |
| RT17 | Recheck target identity after the ink-settle delay before accepting a matching sample. | `test_settle_rechecks_target_before_accepting_a_sample`. |
| RT18 | Check keyboard focus before every Paint clear or numeric RGB command, and propagate cancellation instead of continuing fallback input. | `test_keyboard_focus_is_rechecked_between_clear_commands`; existing numeric-color regressions. |
| RT19 | Apply a verified 100% opacity position when a prior drawing may have left the browser translucent. | `test_full_opacity_is_applied_after_previous_transparent_drawing`. |
| RT20 | Report unknown opacity and dry-run opacity honestly instead of claiming a successful opaque change. | `test_unknown_opacity_is_not_reported_as_applied_opaque`, `test_dry_run_does_not_claim_opacity_was_applied`. |
| RT21 | Require fresh selected-state evidence before reducing the brush inset; retain a conservative profile-sized guard for unknown initial selection and stop an unconfirmed adaptive switch before drawing. | Stale/fresh selection and adaptive-stop fixtures. Initial and per-pass corrections count together. The read-only selection helper in `BrowserBrushSize` is included here. |
| RT22 | Successful filenames containing words such as crash or timeout no longer turn ready UI status into an error. | `test_successful_filename_does_not_turn_ready_state_into_error`; actual save failures remain errors. |
| RT23 | Validate mouse-probe geometry before target activation or arming. | `test_invalid_area_never_activates_or_arms_target`. |
| RT24 | Always disarm the probe when activation or subsequent status reporting fails. | `test_reporting_failure_after_activation_still_disarms`. |
| RT25 | Confirm the probe's observed cursor endpoint before reporting successful movement. | `test_probe_does_not_report_success_for_unobserved_movement`. |
| RT26 | Read a timer ring from its local crop without converting the whole desktop image for each observation. | `test_ring_converts_only_its_local_crop`; paired timing below. |
| RT27 | Bound timer discovery by both image dimensions, including tall portrait captures. | `test_portrait_detection_is_bounded_in_both_dimensions`. |
| RT28 | Observe timer cancellation during component scanning, after capture and after the final observation. | Component-cancellation and final-observation fixtures. |
| RT29 | Timestamp timer acquisition before capture and analysis so analysis latency is not added back into the remaining budget. | `test_observation_timestamp_precedes_expensive_analysis`. |
| RT30 | Validate timer geometry and observation array shape before analysis/indexing, returning controlled validation errors. | `test_malformed_timer_geometry_and_rows_fail_as_validation_errors`. |
| RT31 | Treat malformed optional target-fingerprint geometry and DPI as missing values instead of crashing queued imports on overflow. | `test_invalid_optional_probe_metadata_is_a_missing_value`. |
| RT32 | Require finite, bounded Drop-In authorization lifetimes and expire at the deadline boundary, including malformed stored deadlines. | `test_unbounded_or_nonfinite_authorization_is_not_created`. |
| RT33 | A missing window identity cannot match another missing identity and authorize a queued start. | `test_missing_target_identity_cannot_match_itself`; legitimate geometry reflow retains identity. |
| RT34 | Honor Stop both before and after queued Drop-In target verification, before a worker can clear the stop event. | Escape-before-start and Escape-during-verification fixtures. |
| RT35 | Revoke queued Drop-In authorization when unrelated activity makes that start invalid. | `test_unrelated_work_does_not_leave_a_future_drop_in_start_armed`. |
| RT36 | Exclude nonfinite, invalid or out-of-client Smart Canvas Drop candidates before ranking and ambiguity checks. | Invalid high-rank and valid-fallback candidate fixtures. |
| RT37 | A tiny Smart Canvas Drop canvas cannot silently disable its edge margin. | `test_tiny_canvas_cannot_disable_its_drop_edge_margin`. |
| RT38 | Failure of the user's selected preferred drop target does not silently choose a different window. | `test_preferred_target_failure_never_silently_selects_another_window`. |
| RT39 | Allow cancellation during Smart Canvas Drop discovery, between candidate captures and inside the live detector invoked by either discovery path. | `test_discovery_cancellation_propagates_before_capture`, `test_live_discovery_forwards_stop_into_canvas_scan_and_closes_capture`. |
| RT40 | A queued preview callback while busy/closing no longer increments the generation and invalidates a running worker. | `test_queued_preview_does_not_invalidate_the_busy_worker_generation`. |
| RT41 | Background removal and its Undo update their labels and previews without a missing `image_label` import exception. | `test_background_remove_and_undo_update_labels_and_preview`. |
| RT42 | New clipboard/screenshot images and image removal discard the previous image's background-removal Undo state. | Clipboard stale-Undo fixture and clear-image regression. Related image-adoption paths count once. |
| RT43 | Bitmap clipboard imports schedule their authorized Drop-In start or browser One-Click continuation, matching file imports. | `test_bitmap_import_discards_old_undo_and_schedules_its_authorized_start`. |
| RT44 | Discard cancelled queued image, preview and calibration results before they can restore stale UI state. | `test_cancelled_worker_results_cannot_replace_current_state`. |
| RT45 | The setup wizard marks a missing palette as blocking for browser and generic targets. | `test_missing_palette_blocks_browser_and_generic_start`. |
| RT46 | The wizard's busy state overrides a previous full-drawing unlock and points to Wait/Stop. | `test_running_operation_overrides_an_unlocked_wizard`. |
| RT47 | Paint setup status names the actual Prepare Paint & draw action. | `test_paint_ready_status_uses_the_actual_paint_start_action`. |
| RT48 | Wizard next-action fallback works when supplied a generator rather than a reusable list. | `test_next_action_does_not_consume_a_generator_before_fallback`. |
| RT49 | Destroy partially created tooltip windows when label creation or layout fails. | `test_tooltip_creation_failure_destroys_the_partial_window`. |
| RT50 | Delayed tooltips do not open for controls that have become hidden or destroyed. | `test_hidden_widget_does_not_open_a_delayed_tooltip`. |
| RT51 | Compact-sidebar refresh skips destroyed widgets without preventing the remaining controls from being restored. | `test_destroyed_child_does_not_break_remaining_controls`. |
| RT52 | Reuse unchanged compact-sidebar packing and move only misplaced controls, avoiding repeated hide/show layout work. | Unchanged/reordered layout fixtures; 100 controls × 100 refreshes decrease from 20,000 pack mutations to zero. |
| RT53 | Validate complete target/canvas geometry before committing automatic setup to the UI; palette-only setup clears the old canvas and stays unready. | Invalid atomic update, nonfinite confidence and palette-only setup fixtures. |
| RT54 | Avoid redundant full-image RGBA copies in automatic preset analysis while preserving transparent-image compositing and source ownership. | Ten mode/transparency parity cases and paired timings below. |
| RT55 | Space eraser rows using the actual ink width instead of the larger conservative CanvasGuard width, avoiding uncovered gaps. | `test_eraser_spacing_uses_ink_width_not_conservative_guard`. |
| RT56 | Enforce preview pixel/dimension caps after scaling, including near-equal sizes and extremely thin images. | Preview cap and invalid-limit fixtures. |

## Shared changes counted elsewhere

- Preview memory-budget enforcement and the full-detail caller belong to the
  storage/resource ledger. Their UI caller tests are in this batch.
- Stop callbacks in delivery/scoring, unavailable visual-evidence metadata and
  malformed-report recovery belong to the delivery ledger. Normal disk-failure
  report counters were already preserved by `safe_save` before this batch; the
  defensive caller integration is not a separate new improvement.
- Root-owner metadata for manual Paint modal capture belongs to the calibration
  ledger; the native helper's ownership tests are retained here.
- The Windows atomic-write retry is completion of batch 01, not a new item.

## Measurements

[Reproduction script](../benchmark_v148_runtime.py) and
[raw samples](v148-batch02-runtime-benchmarks.json) record seven alternating
before/after runs after output-equality checks, using deterministic generated
inputs and the checkpoint above. These are Linux CPU helper measurements,
excluding native Windows input/capture, widget rendering, GPU performance and
complete drawing time.

| Workload | Before median | After median | Result |
| --- | --- | --- | --- |
| Preset analysis, 3000 × 2000 RGB | 136.18 ms | 43.26 ms | Identical complete resolved options. |
| Preset analysis, 3000 × 2000 RGBA | 128.40 ms | 120.23 ms | Identical complete resolved options; timing samples overlap. |
| Read an 81 × 81 timer ring in a 3200 × 2000 image | 28.57 ms | 0.57 ms | Identical fraction, box and confidence. |
| Unchanged sidebar, 100 controls × 100 refreshes | 20,000 pack mutations | 0 pack mutations | Identical final widget order in instrumented layout fixtures. |
