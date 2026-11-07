# v1.0.148 batch 02: delivery, verification and planning diagnostics

Baseline: `1c09774ad22088c5c30a8f8220b6b451fdee9659`.

This batch records **73 distinct behavior or allocation changes, DP01–DP73**. Tests, fixture corrections, documentation and measurement work do not add to that count. Related validation branches and repeated image cleanup sites are grouped into a single entry. The changes use synthetic images, fake clocks, temporary files and local planning; validation does not exercise physical mouse input or claim target application performance.

The public correction-planning keyword API and `RuntimeSafetySession.as_dict()` counter/fill schema are preserved. Verification, scoring and edge processing accept an optional cancellation callback. Root integrates `stop.is_set` and snapshot ownership in `DrawBot.py`; those integration edits are outside this agent's file scope and are not additional entries here. Missing snapshot evidence remains a failed/unavailable check. `DrawTimeEstimate.py` belongs to the storage/learning batch.

## Evidence and tests

Five new test modules contain **87 regression tests**:

- **D** — `test_v148_delivery_batch02.py` (22): canvas, delivery policy, EMA timing and visual verification.
- **C** — `test_v148_delivery_batch02_correction.py` (23): snapshot trust, correction geometry/budgets and review state.
- **P** — `test_v148_delivery_batch02_diagnostics.py` (18): brush evidence, diagnostic raster, debug allocations and preview buffers.
- **R** — `test_v148_delivery_batch02_reports.py` (11): report evidence, concurrency and failed publication.
- **B** — `test_v148_delivery_batch02_benchmarks.py` (13): benchmark evidence, input isolation, cancellation and timing boundaries.

The table's test references use these prefixes. Assertions compare to independent expected geometry, Pillow rasterization, exact numeric budgets or explicit publication outcomes. The source contains no real desktop-input tests.

## Canvas and delivery policy

| ID | Previous behavior and concrete evidence | Change | Regression evidence |
|---|---|---|---|
| DP01 | A valid normalized subrectangle such as `(0.1,0.1)`–`(0.9,0.6)` was rejected by pixel-area thresholds applied before scaling; thin normalized vertices could also collapse. | Scale and round to screen coordinates before duplicate/area validation. | D: `test_normalized_subrectangle_is_validated_after_screen_scaling`, `test_normalized_thin_vertices_are_not_deduplicated_in_fraction_units`. |
| DP02 | Auto anchor coordinates were inferred independently. `(0,1)` could become normalized while other anchors from the same area-relative set remained local pixels. | Resolve one coordinate space from the full center/tip set. | D: `test_auto_anchor_space_is_inferred_for_the_whole_group`. |
| DP03 | NaN/out-of-range confidence, nonfinite orientation and unknown coordinate-space names could be clamped or bypass validation. | Validate anchor evidence and coordinate-space names explicitly, including dataclass inputs and the no-area path. | D: `test_nonfinite_and_invalid_anchor_evidence_is_rejected`, `test_unknown_coordinate_space_is_rejected_without_area`. |
| DP04 | A supplied polygon could extend beyond the already selected drawing rectangle. | Require valid area dimensions and contain every polygon vertex in that area. | D: `test_polygon_cannot_enlarge_selected_area`. |
| DP05 | Rounding a mathematically inside boundary point could put it outside; the fallback centroid was returned without proving containment. Triangle `(0,0),(10,0),(0,3)` lost a valid vertical crossing near `x=8`. | Check rounded containment, search nearest integer boundary neighbors, and verify every fallback. | D: `test_fractional_boundary_projection_keeps_valid_integer_dot`. |
| DP06 | Every `SafePolygon.contains*` call rebuilt float vertices and ran the full polygon predicate, including rectangles. | Prepare immutable geometry once, freeze nested public geometry too, reject outside bounds quickly and use an exact rectangle interior path while retaining boundary tolerance semantics. | D: `test_prepared_membership_matches_reference_at_edges_and_negative_origins`, including caller-list mutation; paired measurement below. |
| DP07 | Cancellation was checked between paths but could be delayed by a very long transform, source-validation or clipping pass. | Forward cancellation through preview construction, `apply_edge_behavior`, boundary projection and CanvasGuard path loops at bounded intervals. | P: `test_edge_clipping_observes_cancellation_during_large_path`; existing canvas/edge/preview suites. |
| DP08 | Nonfinite or overflowing `stroke_step_px` could reach the resolved delivery policy. | Resolve invalid spacing to the finite profile default before applying profile limits. | D: `test_invalid_delivery_spacing_falls_back_to_finite_profile_policy`. |
| DP09 | Retry spacing imposed a 2 px minimum, making an existing 0.5/1 px step coarser. | Never increase the original step during retry; reject invalid base spacing/delay. | D: `test_retry_never_makes_a_small_step_coarser`. |
| DP10 | A verifier response such as `{'matched':'false'}` became a successful match via truthiness. | Require a literal boolean match and identify malformed verifier responses. | D: `test_verifier_requires_literal_boolean_match`. |
| DP11 | Transient foreground wording could classify an explicit interrupt/deadline or `CanvasSafetyStop` as recoverable. | Give explicit stop types/deadlines precedence and treat CanvasGuard exceptions as hard stops. | D: `test_explicit_stop_and_canvas_exception_override_transient_text`. |
| DP12 | `TimeAwareColorBudget` ignored persisted operation EMA `average_seconds` because it looked for raw count/total fields. | Consume the validated EMA first, preserving the legacy count/total fallback. | D: `test_color_budget_consumes_persisted_ema_format` independently expects a measured 2.5 s color cost. |

## Visual verification and final-canvas evidence

| ID | Previous behavior and concrete evidence | Change | Regression evidence |
|---|---|---|---|
| DP13 | Batch probe selection materialized all candidates and could truncate coverage to an early prefix; a zero sample limit was not an empty request. | Use bounded deterministic streaming decimation, include the batch tail and honor zero. | D: `test_sampling_zero_is_empty_and_long_batch_includes_tail`, `test_sampler_allocations_remain_bounded_for_large_batch`; memory/timing tradeoff below. |
| DP14 | Overlapping L-shaped boxes or more than 80 boxes became an enclosing rectangle, hiding unintended ink in gaps. | Merge only exact rectangular unions and compare sorted row intervals without a lossy enclosing-box fallback. | D: `test_box_union_does_not_hide_l_shaped_or_many_disjoint_gaps`, `test_outside_change_in_l_shaped_gap_is_detected`. |
| DP15 | Screen coordinates were treated as capture pixel coordinates even when their scales differed. | Map probe centers, brush radius and outside-change positions between screen and capture dimensions. | D: `test_scaled_snapshot_uses_screen_to_capture_coordinates`. |
| DP16 | Baseline/capture dimension mismatches and invalid verification geometry could raise or produce a misleading comparison. | Return unavailable failure for incompatible snapshots, invalid area, RGB or brush geometry before private conversions. | D: `test_mismatched_baseline_and_invalid_area_are_unavailable`. |
| DP17 | Empty/all-outside probe sets could report success; one missed probe did not always raise an issue. | Require actual valid sampled evidence and apply the match gate to every nonempty sample count. | D: `test_empty_outside_or_single_wrong_probe_never_reports_success`; root absent-snapshot integration uses the same failed/unavailable semantics. |
| DP18 | A square-grid stride did not bound work for very wide, short captures. | Derive explicit row/column counts whose product stays within the sample target and spans the full image. | D: `test_skinny_capture_grid_has_a_real_sample_bound`. |
| DP19 | Long probe generation/comparison could finish after cancellation; private RGB conversions were not explicitly released. | Check cancellation during candidate generation, duplicate/invalid paths, comparisons and grid rows; close owned conversions on every exit. | D: `test_cancellation_is_checked_within_long_sampling_and_before_conversion`. |
| DP20 | A high trust label could override explicit `trusted=False`/`available=False`, or invalid percentage fields. | Share one consistent trust predicate across correction, review and completed-result analysis; explicit negative evidence wins. | C: `test_explicit_negative_or_malformed_evidence_cannot_be_promoted_by_label`. |
| DP21 | Negative/nonfinite fitted/canvas dimensions could be silently normalized into a tiny crop. | Validate finite positive geometry and reject fitted dimensions larger than the selected canvas before cropping. | C: `test_crop_rejects_nonfinite_negative_and_overlarge_fitted_geometry`. |
| DP22 | A requested comparison size could allocate arbitrarily large scoring/correction buffers. | Require positive integer dimensions, at most 16,384 per axis and 4,000,000 pixels before crop/analysis allocation. | C: `test_comparison_budget_is_validated_before_crop_allocation`, including NumPy integral compatibility. |
| DP23 | RGB conversion revealed hidden transparent pixels in simulated/quantized expectations and correction images. | Flatten alpha against the same visible background used by evaluation. | C: `test_transparent_simulation_is_compared_as_visible_white`; correction uses the same normalization boundary. |
| DP24 | Missing or invalid visual metric output could still become a trusted final score. | Reject absent/nonfinite/out-of-range visual evidence and return unavailable scoring metadata. | C: `test_missing_visual_measurement_cannot_be_reported_as_verified`. |
| DP25 | Scoring caught cancellation as a diagnostic failure and left private crop/normalization buffers to implicit cleanup. | Propagate `InterruptedError`, check analysis stages and close every owned image while preserving caller images. | C: `test_scoring_preserves_cancellation_and_releases_private_crop`. |

## Correction planning and review

| ID | Previous behavior and concrete evidence | Change | Regression evidence |
|---|---|---|---|
| DP26 | Zero correction caps could still allow work; rounded area caps could exceed the requested fraction. | Validate caps, honor zero as disabled and floor the allowed pixel fraction. | C: `test_zero_caps_disable_correction_and_fraction_never_rounds_up`, `test_invalid_palette_or_caps_do_not_create_corrections`. |
| DP27 | Row-major truncation of a tied top-K threshold could discard a strictly higher-error pixel. | Retain all strictly higher scores, then fill the remaining slots from cutoff ties deterministically. | C: `test_tied_cutoff_keeps_strictly_higher_error_pixels` expects `[True,False,True]` for scores `[1,1,2]`, cap 2. |
| DP28 | Malformed palette colors could be replaced with arbitrary default colors during correction. | Require bounded finite RGB triplets and reject an invalid correction palette. | C: `test_invalid_palette_or_caps_do_not_create_corrections`. |
| DP29 | Palette indices beyond 32,767 overflowed signed 16-bit correction maps. | Keep selected/wanted indices in signed 32-bit storage. | C: `test_wide_palette_index_does_not_overflow_int16` selects color index 32,768. |
| DP30 | The distance temporary multiplied a pixel tile by the entire palette. | Tile palette colors as well, bounding each distance block to 262,144 pixel/color pairs and preserving first-index ties. | C: `test_palette_distance_tiles_bound_pairs_and_keep_first_equal_color`; measured peak reduction below. |
| DP31 | Building correction groups scanned the entire frame once for every palette color, including unused colors. | Iterate only actually selected nonnegative color indices. | C: `test_unused_palette_colors_do_not_each_scan_the_entire_correction_mask`; identical execution groups in the paired fixture. |
| DP32 | Correction ignored a crop's negative geometry verdict; NaN brush/fitted values could also be hidden by min/max clamping. | Require verified crop geometry and finite positive brush/fitted axes before footprint verification. | C: `test_uncertain_snapshot_geometry_blocks_corrections`, `test_nonfinite_brush_or_one_fitted_axis_cannot_be_clamped_into_valid_geometry`. |
| DP33 | Budget capping forced at least one path and allowed a minimum 5% fraction even when that exceeded headroom. | Validate timing, floor the affordable path count and disable correction when no complete path fits. | C: `test_single_path_must_fit_budget_and_invalid_timing_is_rejected`, `test_exact_path_budget_has_no_minimum_five_percent_overrun`. |
| DP34 | Correction analysis time itself was absent from the remaining-headroom calculation. | Subtract elapsed planning time before applying the execution budget cap. | C: `test_analysis_time_is_deducted_from_verified_headroom` uses an independent fake monotonic clock. |
| DP35 | Path caps retained pixel/color counts from discarded geometry. | Recompute retained correction raster counts and filter empty colors after capping; report the selected fraction against candidate pixels. | C: `test_path_cap_metadata_counts_only_remaining_geometry` expects one remaining pixel and 1% of 100 candidates. |
| DP36 | Long run extraction and interrupted/early-return correction paths retained work/buffers until later cleanup. | Check within long row scans, propagate stage cancellation and explicitly release owned source/crop/filter images on all exits. | C: `test_row_run_scan_checks_cancellation_inside_long_row`, `test_private_canvas_is_closed_on_early_rejection`. |
| DP37 | Retry/review state could use old trusted evidence after an explicitly untrusted correction result or treat string readiness flags as permission. | Respect fresh correction trust/metric failures and require literal booleans for correction and readiness gates. | C: `test_latest_untrusted_post_correction_result_requires_review`, `test_retry_hints_require_booleans_and_consistent_trust`. |
| DP38 | Any reason containing “within” or “already” could display success, including “not within correction gates”. | Require the exact standard success reason plus trusted evidence and no outstanding correction need. | C: `test_negative_reason_text_does_not_turn_failure_into_success`. |

## Preview and debug allocation

| ID | Previous behavior and concrete evidence | Change | Regression evidence |
|---|---|---|---|
| DP39 | Debug sampling rounded/copied every point before keeping 80. | Select indices before conversion and reuse existing integer tuples. | P: `test_debug_sampling_has_bounded_allocations_and_retains_endpoints`; paired timing/memory below. |
| DP40 | The 80-point limit applied independently to every output subpath, so one event could grow without bound. | Apply one shared event output budget across representative subpaths, retaining full output-count metadata. | P: `test_debug_event_total_subpath_sample_is_bounded_but_metadata_is_complete`. |
| DP41 | Once the 160-event log was full, every later path still constructed a discarded event. | Count the resolved action directly after saturation; avoid unused geometry samples. | P: `test_saturated_debug_log_keeps_counts_without_building_discarded_events`. |
| DP42 | Detail previews performed redundant full-resolution orientation/RGBA conversions before a small resize. | Borrow already oriented inputs and resize compatible image modes before channel expansion; preserve palette/keyed-alpha handling. | P: `test_preview_resampling_preserves_legacy_rgba_raster_in_all_supported_modes`; 20 full-pipeline parity cases and paired timing below. |
| DP43 | Grayscale previews used hidden RGB from transparent pixels. | Normalize visible color before grayscale detail analysis. | P: `test_gray_preview_ignores_hidden_rgb` expects a completely white visible result. |
| DP44 | Detail preview cancellation could leave owned resize/sharpen images alive, and expensive stages lacked cancellation boundaries. | Track and close private buffers explicitly, keep the returned image open, and check after analysis stages. | P: `test_detail_cancellation_closes_private_resizes_without_closing_source`; existing detail-preservation tests. |

## Runtime and completed-result reports

| ID | Previous behavior and concrete evidence | Change | Regression evidence |
|---|---|---|---|
| DP45 | Millisecond timestamp filenames could collide for two independent sessions. | Add a per-report UUID to both filenames. | R: `test_same_timestamp_sessions_publish_distinct_report_pairs`. |
| DP46 | Repeated/concurrent save calls could write extra reports and change completion metadata. | Serialize save publication with an instance lock and return detached copies of the saved result. | R: `test_concurrent_repeated_save_is_idempotent_and_returns_detached_payload`. |
| DP47 | JSON could be published while text publication failed. | Stage/publish the report pair through the shared rollback-capable file-set helper. | R: `test_report_text_publish_failure_rolls_back_json`; no orphan report or staging files remain. |
| DP48 | Latest-report loading was unbounded and trusted malformed flags/counters. | Use a bounded JSON reader, validate report evidence, skip unreadable/invalid newer files and continue to valid older reports. | R: `test_latest_report_skips_oversized_and_invalid_counters`. |
| DP49 | `safe_save` could throw a second serialization exception while handling the first, masking the draw outcome. | Preserve independently available counts/fills even when both publication and full serialization fail. | R: `test_secondary_serialization_failure_preserves_fill_evidence`; `as_dict()` schema remains unchanged. |
| DP50 | Missing draw predictions became a fabricated near-zero estimate and ETA-error result. | Keep prediction/error/efficiency unavailable when no finite valid estimate exists. | R: `test_unknown_prediction_stays_unavailable`. |
| DP51 | Missing or contradictory final quality evidence could still yield optimistic efficiency or speed/fill advice. | Require trusted observed quality for efficiency and complete quality/coverage evidence before more aggressive speed recommendations. | R: `test_missing_or_contradictory_quality_does_not_recommend_more_speed`. |
| DP52 | Invalid elapsed duration/count inputs could create apparently completed telemetry. | Require finite positive duration and a nonnegative integer completed count. | R: `test_completed_evidence_requires_real_positive_elapsed_and_integer_count`. |
| DP53 | Completed history loaded unbounded JSON and kept malformed schema/duration rows. | Bound history reads and filter to supported records before applying the retention limit. | R: `test_history_is_size_bounded_and_schema_filtered`. |
| DP54 | Concurrent completion writers could read the same history and lose one append. | Hold the profile history transaction lock across read/append/publication. | R: `test_concurrent_completions_do_not_lose_history_rows` preserves eight distinct completions. |
| DP55 | Sequential latest JSON/text/history writes could leave mismatched generations after failure. | Publish all three through rollback-capable replacement and update in-memory success metadata only afterwards. | R: `test_history_publish_failure_restores_all_old_report_files`. |

## Brush evidence and diagnostic raster

| ID | Previous behavior and concrete evidence | Change | Regression evidence |
|---|---|---|---|
| DP56 | A valid brush plan from another profile enabled dynamic sizes for the current profile. | Bind named evidence to the requested active profile; preserve the legacy unnamed-plan contract. | P: `test_foreign_profile_plan_cannot_enable_brush_switches`. |
| DP57 | Infinite confidence, malformed/duplicate controls, nonexistent target positions or invalid nominal sizes could pass the dynamic-brush check. | Validate finite confidence, positive unique integer sizes, unique signed-LONG integer coordinate pairs and target membership using the same screen-point contract as fresh calibration; valid negative screen positions remain supported. | P: `test_invalid_coordinates_or_confidence_disable_dynamic_brushes`. |
| DP58 | Empty explicit `verified_sizes` fell through to the old whole-ladder fallback; subset evidence could be misinterpreted as all controls. | Treat explicit verified subsets/indices as authoritative and enable dynamic selection only with multiple usable sizes. | P: `test_explicit_verified_subset_and_empty_evidence_are_authoritative`; parent's `BrowserBrushSize` retains full nominal/control indexing. |
| DP59 | Independently clamping line endpoints changed the slope and visible diagnostic raster. | Clip raster samples while preserving the original Bresenham error phase, with work bounded by the canvas major dimension even for enormous endpoints. | P: `test_segment_clipping_matches_independent_pillow_raster`, `test_huge_off_canvas_diagonal_is_clipped_without_rewriting_slope`; additional 1,000 seeded Pillow comparisons. |
| DP60 | Entirely offscreen or inverted fill spans could paint the nearest border after clamping reversed endpoints. | Check interval/bbox intersection and ordering before drawing the clipped fill. | P: `test_offscreen_or_inverted_fill_spans_do_not_paint_border`. |
| DP61 | Explicit quantized targets and heatmaps exposed hidden RGB behind alpha. | Compare/render visible normalized pixels, including caller-supplied normalized sources. | P: `test_transparent_targets_and_heatmaps_use_visible_pixels`. |
| DP62 | Nonpositive/nonfinite heatmap scale could saturate the image or publish NaN metadata. | Require a finite positive full-error scale. | P: `test_heatmap_requires_finite_positive_scale`. |
| DP63 | Unknown/nonfinite ETA and invalid timing entries could crash diagnostics or select a fictitious dominant phase. | Keep unknown ETA unavailable and reuse the validated profiler phase selection. | P: `test_diagnostics_handle_unknown_eta_and_invalid_timing_samples`. |
| DP64 | Fresh correction history was returned in diagnostics while review used a stale `setdefault` value; diagnostics also mutated caller options. | Build review from a local options copy containing the same fresh history returned in diagnostics. | P: `test_fresh_correction_history_is_shared_with_review_without_mutating_options`. |
| DP65 | Target rendering allocated work before initial cancellation and did not check long fill-span loops. | Check before allocation and within span work, and explicitly close partial private targets on cancellation. | P: `test_target_cancellation_before_allocation_and_inside_long_fill`. |

## Benchmark validity and isolation

| ID | Previous behavior and concrete evidence | Change | Regression evidence |
|---|---|---|---|
| DP66 | Required p95/correction-safety evidence could be absent and still pass a golden case; an empty suite reported success. | Require finite in-range mandatory quality metrics and literal safe evidence; an empty suite cannot pass. | B: `test_golden_required_metrics_cannot_be_missing_nonfinite_or_out_of_range`, `test_unknown_estimates_and_empty_golden_suite_never_pass`. |
| DP67 | Golden fixture factories ran three times per new asset and twice just to get dimensions for an existing asset; custom subsets generated unrelated fixtures too. | Generate once per requested case and reuse that image's dimensions, preserving existing-file behavior. | B: `test_fixture_factory_runs_once_per_selected_case`. |
| DP68 | Missing estimates appeared as zero-time FIT; nonfinite quality averages and truthy acceptance strings made benchmark output misleading. | Preserve unavailable timing/quality/gates and use only finite valid measurements and boolean acceptance in summaries. | B: `test_unknown_estimates_and_empty_golden_suite_never_pass`, `test_benchmark_invalid_quality_and_nonboolean_acceptance_are_unavailable`. |
| DP69 | Shallow option copies let one planner mutate nested settings used by later cases or the caller. | Deep-copy options independently for every benchmark case and engine. | B: `test_benchmark_options_are_independent_for_every_case_and_engine`. |
| DP70 | The legacy and adaptive planner received the same mutable image, so the first could contaminate the second comparison. | Give each engine an owned source copy. | B: `test_hybrid_comparison_cannot_mutate_the_other_engines_source`. |
| DP71 | Pre-cancelled golden runs wrote assets; cancellation from the last planner could be reported as success; benchmark image buffers lacked deterministic closure. | Check before fixture generation and after each planner, propagate callbacks into the hybrid suite, and explicitly close owned images on success/failure/cancellation. | B: `test_precancelled_golden_run_creates_no_assets`, `test_last_planner_cancellation_propagates_and_owned_inputs_close`, `test_planner_exception_closes_benchmark_input`, `test_suite_precancellation_prevents_fixture_creation`. |
| DP72 | Hybrid suite failures left tracing active; ordinary runs could stop caller tracing or claim its historical peak as local memory. | Track trace ownership, release owned traces in `finally`, preserve caller sessions and report local peak as unavailable under an external trace. | B: `test_failed_hybrid_quantization_releases_owned_trace`, `test_existing_caller_trace_is_preserved_and_not_claimed_as_local_memory`. |
| DP73 | Baseline timing included shared quantization while adaptive timing omitted mandatory fill/group preparation; quality simulation boundaries also differed. | Report shared quantization separately and include each engine's preparation, path creation and quality simulation in its planning time. | B: `test_fair_timing_includes_adaptive_preparation_and_both_quality_simulations` expects 2 s common, 4 s baseline and 15 s adaptive from independent stage durations. |

## Measured allocation and timing results

The complete executable harness is `benchmark_v148_delivery_planning.py`; every raw timing sample, exact fixture parameter and current source digest is recorded in `docs/v148-batch02-delivery-benchmarks.json`. Reproduce with:

```sh
python -B benchmark_v148_delivery_planning.py \
  --baseline 1c09774ad22088c5c30a8f8220b6b451fdee9659 \
  --repeats 7 --detail-repeats 3 \
  --output docs/v148-batch02-delivery-benchmarks.json
```

Environment: Linux workspace, CPython **3.12.14**, NumPy **2.5.4**, Pillow **13.0.0**. These are synthetic CPU-side microbenchmarks, not measured Windows drawing time. Traced peaks are Python/tracemalloc-visible allocations; native Pillow buffers are not fully represented.

Before implementations were loaded from the fixed baseline commit into separate Python modules. The prepared inputs were allocated before timing/tracing. The first four fixtures used one warm call followed by seven alternating before/after samples; values are medians. A separate invocation after garbage collection recorded each traced peak. The detail resize fixture used three samples per implementation. Source/output parity was checked where behavior is intended to be identical; the visual sampler intentionally adds tail coverage.

| Fixture | Before median | After median | Before traced peak | After traced peak | Interpretation |
|---|---:|---:|---:|---:|---|
| 10,000 two-point vertical paths, 130 visual probes | 44.0372 ms | 70.1030 ms | 8,649,048 B | 163,172 B | Approximately 98.1% less traced peak and tail coverage. This recorded sample is slower (about 59%); after samples range 45.6–78.7 ms. This is a memory/coverage change, not a speedup. |
| 100,000 debug points, retain at most 80 | 40.9262 ms | 0.0590 ms | 9,720,864 B | 1,560 B | Avoids converting the 99,920 discarded points. |
| 20,000 membership probes in a 1,000×700 rectangle | 49.1715 ms | 8.3877 ms | 174,312 B | 173,192 B | About 5.86× faster in this repeated-predicate fixture; exact predicate results agree. |
| 64×64 correction, 256 colors, one selected color | 33.2692 ms | 33.7812 ms | 17,238,814 B | 8,903,118 B | Identical execution groups and 4,096 selected pixels; approximately 48.4% lower traced peak. Timing is approximately unchanged (about 1.5% slower in this recorded run). |
| Seeded random 4,000×2,000 RGBA → 240×120 Detailed preview | 166.3952 ms | 174.4124 ms | 7,957,400 B | 7,956,731 B | About 4.8% slower in this three-sample run. The code removes redundant full-image copies, but this run establishes no elapsed-time improvement; native image allocations are not captured by the near-equal traced peaks. |

Reproduction fixture definitions:

```python
paths = [((i, 0), (i, 20)) for i in range(10_000)]
debug_points = [(i, i % 61) for i in range(100_000)]
guard = CanvasGuard.from_area((100, 200, 1000, 700))
probes = [(100 + i % 1000, 200 + i % 700) for i in range(20_000)]
# Correction: black 64x64 source; white actual image; palette black + 255 whites;
# trusted visual=60, coverage=0; CPU, brush=1; max_fraction=1,
# max_pixels=4096, max_paths=10000. Compare execution_groups before timing.
```

Baseline loading for a module:

```python
import subprocess, sys, types
baseline = '1c09774ad22088c5c30a8f8220b6b451fdee9659'
module = types.ModuleType('before_VisualVerification')
sys.modules[module.__name__] = module
source = subprocess.check_output(['git', 'show', baseline + ':VisualVerification.py'])
exec(compile(source, 'VisualVerification.py', 'exec'), module.__dict__)
```

The complete detail-preview parity check used seed 14802 and a 91×67 random RGBA image resized to 31×23 through RGB, RGBA, L, LA and P modes, each at Fast, Balanced, Detailed and Micro detail. All **20 full-pipeline comparisons had zero changed channels**, and the committed boundary test independently compares resized RGBA samples against Pillow. Earlier exploratory timings varied, especially under concurrent integration work; the table reports the stored reproducible-harness run, including regressions, without selecting only favorable runs.

## Validation and integration status

The focused/related command covered **288 tests, all passing**, including the five new files and existing canvas, edge, stroke delivery, recovery, time-aware palette, snapshot, correction, preview, report, golden, brush packing and engine finalization suites. The new tests can be rerun with:

```sh
python -B -m unittest -q \
  test_v148_delivery_batch02 \
  test_v148_delivery_batch02_correction \
  test_v148_delivery_batch02_diagnostics \
  test_v148_delivery_batch02_reports \
  test_v148_delivery_batch02_benchmarks
```

The existing RC6/RC23/RC25 brush-packing fixtures previously identified a target `(10,10)` outside their own control-position lists. They now identify a real listed control, preserving every original raster/packing assertion. The subject-phase merge fixture now passes its active profile explicitly. These fixture corrections are not counted as improvements and do not relax the new evidence checks.

File-set report publication rolls back ordinary exceptions through `RuntimePaths.replace_text_files`; it does not claim a multi-file filesystem crash transaction. Shared profile history locks coordinate concurrent writers. Existing runtime report schemas without an explicit schema field remain readable when their actual evidence is valid.

Follow-up candidates for a later audit, not counted or changed here: visible-alpha brush classification in `AutoBrushWidth`; long-path point-limit adherence in remaining path builders; source-size and integer-width limits in independent hybrid simulation helpers. They need separate reproductions before inclusion.
