# v1.0.148 application workflow — batch 04

This batch implements **27 distinct behavior improvements** against
`1d48eabaf349a5fd8049a2c96ef5426745c3078c`. The later `2aca72a` commit only repairs
the pip test fixtures and does not change the product count. Independent review and frozen whole-program integration are complete; see the checkpoint results below.

Related call sites, tests, documentation and completions of previously counted
work do not add IDs. Regression evidence is in the application batch04
[analysis](../test_v148_application_batch04_analysis.py),
[settings](../test_v148_application_batch04_settings.py),
[recovery](../test_v148_application_batch04_recovery.py),
[planning](../test_v148_application_batch04_planning.py) and
[editing](../test_v148_application_batch04_editing.py) modules.

| ID | Behavior improvement | Evidence |
| --- | --- | --- |
| AW01 | Read the exact deterministic palette-refinement sample through bounded 256 × 256 tiles instead of copying and converting the entire source raster. Sample order, duplicate indices, transparency and original source coordinates are preserved. | `test_samples_equal_full_visible_conversion_in_original_order`, `test_large_source_conversion_is_bounded_by_tile_area`, `test_refined_palette_matches_original_full_raster_sampling`; 12 MP paired benchmark. |
| AW02 | Reject invalid palette seeds, wrapped/out-of-range RGB channels, nonintegral or nonpositive palette sizes and oversized seed sequences before refinement allocation. | `test_palette_contract_rejects_wrapped_colors_and_fractional_sizes`. |
| AW03 | Weight palette strokes by their covered raster length rather than Manhattan length, which disproportionately favored diagonal strokes when ranking color groups. | `test_diagonal_weight_is_covered_raster_length`. |
| AW04 | Bound reduced-palette merging against every original source color, preventing successive near-color merges from drifting beyond the advertised color-distance limit. | `test_chain_merge_cannot_exceed_original_color_distance_limit`, with an independent per-source distance check. |
| AW05 | Compute OKLab metrics once per source color and keep one representative accumulator per hue family instead of retaining every family member and calculating the same metrics twice. | `test_streamed_representatives_equal_independent_member_list_oracle`; 16,000-color paired benchmark. |
| AW06 | Require matching, finite, nonnegative hue weights and valid family limits/chroma thresholds; reject overflowing total mass rather than publishing invalid coverage. Zero mass/capacity avoids color work. | `test_invalid_weight_domains_cannot_publish_nan_coverage`, `test_invalid_cap_or_threshold_is_rejected`, `test_zero_capacity_or_mass_does_not_compute_color_metrics`. One shared hue-input contract. |
| AW07 | Isolate malformed local settings fields so one corrupt scalar cannot abort unrelated valid preferences; portable imports reject those same invalid domains before publication. | `test_corrupt_fields_do_not_abort_unrelated_valid_settings`, `test_profile_import_rejects_malformed_scalar_settings_before_write`. |
| AW08 | Apply settings as a guarded UI transaction: suppress intermediate profile callbacks and restore prior variables/geometry if a setter fails. | `test_apply_error_rolls_back_values_geometry_and_transition_guard`, `test_settings_application_suppresses_intermediate_profile_callbacks`. |
| AW09 | Preserve the selected profile's defaults for absent legacy settings and display extras instead of replacing them with generic fallback values. | `test_partial_file_preserves_selected_profile_defaults_for_absent_fields`; coordinated `ProfileIsolation.restore_extra` change. |
| AW10 | Recognize unsupported settings schemas and preserve the existing document through later saves until the user explicitly resets that profile. | `test_unsupported_schema_is_preserved_through_later_save`. |
| AW11 | Remove consumed legacy setting aliases after migration so portable-profile validation accepts migrated older documents while giving explicit current keys precedence. | `test_legacy_aliases_migrate_without_unknown_setting_failures`. |
| AW12 | Persist and restore the chosen Gartic opacity in the active profile. | `test_gartic_opacity_round_trips_with_profile_settings`. |
| AW13 | Propagate a failed settings save to dependent operations: retain the active profile/selection, and block export or import that would otherwise continue with stale settings. | `test_save_result_exposes_disk_failure_and_preserves_old_document`, `test_failed_profile_save_retains_selected_active_profile_and_resume`, `test_failed_save_cannot_export_stale_settings_or_start_import`. One failed-save propagation contract. |
| AW14 | Reject duplicate canvas fields across portable-profile sections and nonobject canvas sections instead of silently overriding or ignoring ambiguous input. | `test_canvas_data_cannot_appear_twice_or_as_empty_nonobject`. |
| AW15 | Prevent profile management while a profile transition is queued/running or the application is closing, keeping the requested identity and stored settings consistent. | `test_pending_profile_change_or_shutdown_blocks_profile_management`. |
| AW16 | Verify/hash/decode a recovery image in a tracked, cancellable worker; apply it only after that worker completes, with a fresh idle/shutdown check after the recovery dialog. | Recovery deferred-worker, modal-race, between-result-and-completion Stop, hash-chunk Stop and post-decode Stop tests. |
| AW17 | Explicit recovery clearing cancels a queued checkpoint and suppresses re-creation; forget in-memory resume state only after successful deletion. | `test_explicit_clear_cancels_queued_save_and_forgets_resume_only_on_success`, `test_failed_clear_retains_in_memory_resume`. |
| AW18 | Disarm native input before recovery profile/settings/image work so an exception during recovery cannot leave the previous armed state alive. | `test_recovery_failure_disarms_before_loading_or_applying_state`. |
| AW19 | Stream recovery-directory enumeration and filter names before creating Path objects instead of retaining every unrelated directory entry during cleanup. | 10,000-entry paired benchmark verifies identical results and retained unrelated files; existing recovery-integrity deletion tests. |
| AW20 | Respect portrait time semantics: Unlimited does not impose the numeric fallback budget or time-based thinning; short explicit budgets can reduce below the old minimum stroke counts. | `test_unlimited_portrait_keeps_quality_strokes_despite_large_time_estimate`, `test_short_portrait_budget_can_reduce_below_old_minimum_of_120_strokes`, existing real portrait time-fit test. |
| AW21 | Base end-to-end tuner statistics on the visible white-canvas composite, preventing invisible RGB/keyed transparency from being reported as visible chromatic content. | `test_transparent_statistics_use_visible_white_canvas`. |
| AW22 | Permit a bounded Pixel Accurate quality rescue for an Unlimited photo plan, rather than treating the absence of a deadline as a one-second budget. The existing target-pixel limit remains enforced. | `test_unlimited_photo_can_use_bounded_pixel_accuracy_rescue`. |
| AW23 | Quality rescue moves planning resolution upward or preserves Extreme; it no longer downgrades Extreme to Ultra. | `test_quality_rescue_never_downgrades_extreme_resolution`. |
| AW24 | Remove a previous Quick Sketch renderer policy when a rescue chooses another renderer, preventing the next planning pass from overwriting the rescue's detail/quality choices. | `test_old_quick_sketch_policy_cannot_override_rescue_on_next_plan`. |
| AW25 | Planning watchdog Off disables its hidden automatic deadline, while user Stop and the separate bounded dry-run policy remain available. Heartbeat text reports the actual timeout state. | `test_off_removes_automatic_timeout_but_dry_run_keeps_its_explicit_bound` and `test_actual_draw_worker_has_no_off_deadline_but_still_observes_stop_and_shutdown`. |
| AW26 | Watchdog fallback preserves explicit Pixel Accurate/Unlimited quality fields, while allowing CPU/GPU execution-route fallback and retaining finite attempt limits when enabled. | `test_fallbacks_preserve_explicit_pixel_accuracy_and_unlimited_quality`. |
| AW27 | Treat a verified, fully completed sequence checkpoint as a completed no-op before target activation, countdown, drawing or post-draw correction; preserve Stop and unconditional input cleanup. An empty remaining sequence no longer falls back to drawing legacy color groups again. | `test_v148_sequence_resume_execution`: real executed/JSON-round-tripped checkpoint with duplicate operations, partial resume, and Stop on complete state. |

## Shared completions, not additional IDs

- Remaining safe recovery preferences now round-trip through one shared allowlist.
  This completes original improvement 058 and is not counted again.

- Opaque automatic-image statistics now resize directly, removing a remaining
  full-source RGB copy. This completes the existing bounded source-probe/copy
  work in SS37 and RT54; the measured gain below is not another count.
- Closing rejected worker images, stale upscale results, superseded target
  previews and temporary composites completes IW08. Additional cancellation
  propagation completes the existing source-analysis/import cancellation items.
- Cross-editor Undo invalidation and late upscale-dialog/result source checks
  complete the existing stale-image/Undo boundaries in RT42 and IW32.
- Strict/bounded settings JSON loading completes SS03. Serializing render-resume
  publication with recovery clearing completes SS04.
- `SmartTools` now treats malformed optional point/container data as absent
  calibration evidence. The normal UI already loads validated Paint controls;
  this helper hardening is not counted as a newly exploitable input defect.
- The Detail Zoom base-plus-detail execution sequence belongs to the planning
  ledger. `PreviewDiagnostics` and `PreviewSafety` render that same order and
  brush policy, preserving the fill/background prelude; GUI integration and
  its raster tests do not add IDs here.
- Cancellable isolated target-probe calls belong to the platform ledger.
  Forwarding Stop from the browser/Paint calibration workers is part of that
  same behavior, rather than a separate improvement per call site.

## Paired measurements

[Reproduction script](../benchmark_v148_application.py) and
[raw samples](v148-batch04-application-benchmarks.json) retain five alternating
before/after runs after exact output comparisons. These are local synthetic CPU
helper measurements, not promises about complete drawing, Windows input or GPU
performance. Python allocation tracing excludes most native Pillow memory.

| Workload | Before median | After median | Allocation/equality evidence |
| --- | ---: | ---: | --- |
| Automatic statistics, 4000 × 3000 RGB | 31.34 ms | 12.36 ms | Exact statistics; Python peaks effectively unchanged because the removed full-size Pillow buffer is native. |
| Palette refinement, 4000 × 3000 RGB | 132.83 ms | 103.35 ms | Exact palette; Python peak 72,074,865 → 1,433,186 bytes. |
| Dominant hue summary, 16,000 colors | 140.87 ms | 75.73 ms | Exact complete summaries; Python peak 3,120,908 → 142,944 bytes. |
| Recovery cleanup, 10,000 unrelated files | 30.69 ms | 8.50 ms | Same retained files; Python peak 4,270,753 → 30,513 bytes. |

Current focused results are recorded in the task workspace. Independent review corrected an unsupported-schema reread failure within AW10. Final frozen-source integration results are recorded below. No new release, code signature or antivirus verdict is claimed.

## Frozen integration checkpoint

Independent area and cross-area reviews are closed. Whole-program discovery ran
**2,934 tests in 75.509 seconds**, passing with 23 platform/hardware skips; source
hashes were unchanged during the run. The 5,000-cycle release source gate,
source-package hygiene and eight exact-raster engine fixtures also passed.
This batch is included in the 668-improvement development checkpoint. Its own
Windows/Linux CI is pending; 1.0.148 is not yet released.
