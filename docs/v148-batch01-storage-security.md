# v1.0.148 batch 01 — storage, security and resources

Date: 2026-11-06. Baseline: `94a748e` on `improve/v1.0.148`.

This batch contains **41 additional behavior improvements**. Tests, documentation,
version changes, formatting, repeated callsites, and follow-up corrections to a
new implementation are not counted separately. The original 100 improvements
remain the baseline. This ledger is one contribution to the larger requested
1,000-improvement target; it does not claim that target is complete.

The two focused regression modules are `test_v148_storage_security.py` (storage
and calibration cases) and `test_v148_resource_safety.py` (resource and planning
cases). Test method names below are searchable in those modules.

## Implemented behavior

| ID | Previous behavior | New behavior and implementation | Regression evidence |
| --- | --- | --- | --- |
| SS01 | `atomic_write_text` ignored every `fsync` failure and could replace good state after a real disk error. | `RuntimePaths.atomic_write_text` propagates storage/permission errors, preserves the old destination and removes staging files. Only explicitly unsupported sync operations retain the previous fallback. | `test_real_fsync_errors_preserve_existing_state_and_remove_staging`, `test_write_failure_also_removes_staging_before_flush`, `test_unsupported_fsync_retains_atomic_replace_fallback` |
| SS02 | Tool calibrations and scheduler saves skipped durable flushing; the performance tuner reused one staging filename; release metadata was written in place. | `AppTools`, `ExactColorTools`, `ResourceScheduler`, `PerformanceAutoTuner` and `ReleasePackage` use the same unique, flushed, atomic text publication helper. This is one shared persistence improvement. | `test_shared_atomic_savers_do_not_replace_good_files_after_disk_failure`, `test_concurrent_tuner_saves_use_independent_staging_files`, `test_checksum_publish_preserves_previous_document_on_io_failure` |
| SS03 | Several local state readers loaded arbitrary file sizes and accepted ambiguous duplicate keys, nonfinite numbers or excessive nesting. | `RuntimePaths.read_json` bounds reads before decoding and limits depth/items. It serves calibration, learning, release-state and tuner/scheduler readers. The generic limit is 4 MiB, exact/tool calibration 128 KiB, scheduler 256 KiB and welcome state 16 KiB. Duplicate keys and nonfinite JSON numbers are rejected. | `test_local_json_limits_reject_duplicate_nonfinite_and_nested_state`, `test_json_reader_never_reads_more_than_limit_plus_one`, `test_release_state_oversize_falls_back_to_first_run` |
| SS04 | Atomic replacement did not prevent two learning writers from reading the same old database and losing one update. Resets and migrations could race with writes. | `RuntimePaths.file_transaction` coordinates threads and cooperating processes; timing, feedback and correction history hold it across read/modify/write and reset. Timing migration uses the same guard. Lock waits default to five seconds, reject invalid durations, support same-thread nesting and preserve an operation error if native unlock also fails. Retained sidecars are excluded from source archives. | `test_cross_process_transaction_preserves_every_increment`, `test_timing_concurrent_samples_and_failed_save_preserve_counts`, `test_feedback_concurrent_updates_are_not_lost`, `test_correction_concurrent_appends_are_not_lost`, transaction timeout/reentrancy/unlock tests |
| SS05 | A profile key limited to 80 Unicode characters could still exceed a filesystem component's encoded-byte limit once its filename prefix was added. | `ProfileStorage.safe_profile_key` also bounds UTF-8 bytes, truncates on a character boundary and preserves a digest suffix. Existing ordinary ASCII keys keep their filenames. | `test_multilingual_profile_keys_fit_actual_filesystem_components` creates actual files for long CJK and supplementary-plane names. |
| SS06 | Boolean/fractional schema values passed equality/coercion checks; a list/string in exact-color `controls` could raise `AttributeError` during availability checks. | `AppTools` and `ExactColorTools` require integer supported schemas; exact-color controls must be an object and malformed files raise controlled `ValueError`. | `test_exact_control_schema_and_container_errors_are_controlled` |
| SS07 | Exact-color points accepted arbitrarily large integers even though normal tool calibration already bounded positions. | `ExactColorTools._point` applies the existing tool-coordinate domain of −100,000 through 100,000 to each coordinate. Negative multi-monitor positions remain valid. | `test_exact_control_coordinates_and_usable_spectrum_geometry` |
| SS08 | Degenerate/inverted spectrum rectangles and coincident brightness endpoints could be advertised as usable custom-color calibration. | `ExactColorTools.validate` rejects zero/inverted spectrum area and identical slider endpoints; horizontal and vertical nonzero sliders remain supported. | `test_exact_control_coordinates_and_usable_spectrum_geometry`, existing spectrum/numeric-color tests |
| SS09 | Numeric-only custom-color capability probing loaded and validated the same file twice; a concurrent replacement could also produce inconsistent observations. | `ExactColorTools.custom_rgb_available` checks both supported workflows against one loaded snapshot. | `test_custom_color_availability_reads_one_consistent_snapshot`; measured read count is 2 → 1. No overall elapsed-time improvement is claimed. |
| SS10 | Corrupt timing sample counts, ratios or runtime containers could crash estimation or prevent future good samples from being recorded. | `DrawTimeCalibration._load_raw` validates record domains and discards unusable records, retaining a cold model that can learn again. Strict schema handling preserves supported integer legacy versions. | `test_timing_corrupt_records_do_not_crash_estimator_or_prevent_relearning`, `test_malformed_schema_returns_cold_learning_state` |
| SS11 | Invalid operation counters or `last_average_seconds` could raise during learning, and invalid raw operation values could be persisted. | `DrawTimeCalibration` validates finite operation durations and integer counters before merging/storing; invalid operation rows are excluded while valid measurements remain usable. | `test_timing_invalid_operation_values_are_not_persisted`, existing operation-EMA tests |
| SS12 | Delimiter characters inside a policy dimension could produce the same serialized context key as a different combination of dimensions. | Timing and feedback key builders escape delimiters and percent signs independently in each dimension, retaining ordinary existing keys. | `test_context_delimiters_cannot_merge_different_timing_or_feedback_policies` |
| SS13 | A legitimate previous MAPE of zero was replaced with the new error by a truthiness fallback, exaggerating learned error after the next sample. | `DrawTimeCalibration.record_sample` distinguishes zero from an absent value before applying the EMA. | `test_zero_error_history_is_preserved_in_timing_ema` |
| SS14 | Invalid snapshot accuracy could become trusted after clamping; an `available` snapshot with no numeric visual score could crash feedback recording. Contradictory explicit trust flags were ignored. | `AutoTunerFeedback._actual_snapshot_accuracy` requires finite in-range metrics and respects explicit Boolean availability/trust. Unusable snapshot evidence falls back to the existing clearly labeled runtime delivery proxy. | `test_invalid_snapshot_metric_uses_labeled_proxy_without_crash`, `test_explicitly_untrusted_snapshot_cannot_override_delivery_proxy` |
| SS15 | Malformed stored feedback counters/history/EMA values could raise in recommendations or subsequent recording. | `AutoTunerFeedback._valid_context` rejects unusable contexts before recommendation or update. The shared finite-domain guard also rejects integers too large for floating-point arithmetic without raising `OverflowError`. | `test_feedback_discards_corrupt_counters_and_bounds_context_database`; large-integer and malformed learning cases |
| SS16 | Per-context sample histories were limited, but the number of feedback contexts could grow without bound as strategies/settings changed. | `AutoTunerFeedback` retains at most 256 recent contexts, preserving the context currently being updated. Each context retains the existing 12-sample history bound. | `test_feedback_discards_corrupt_counters_and_bounds_context_database` checks exact newest-context retention. |
| SS17 | Zero visual accuracy, coverage or confidence could disappear or be replaced by a positive secondary value in correction history. | `CorrectionHistory.compact_result_metrics` falls back only for missing/`None` primary values. | `test_correction_zero_metrics_do_not_fall_back_to_positive_secondary_values` |
| SS18 | Nonfinite/malformed calibration evidence could become high confidence, and an unexpected health-scoring exception was reported as nonblocking. | `CalibrationHealth` validates evidence types/domains and does not promote contradictory unavailable palette data. `CalibrationState` reports scoring failure as blocking. | `test_health_invalid_evidence_cannot_become_verified`, `test_health_score_failure_is_reported_as_blocking`, existing healthy-layout tests |
| SS19 | Final-canvas evidence with missing/invalid metrics or truthy non-Boolean flags could teach ETA calibration as a trusted completed draw. | `CompletedDrawLearning.timing_sample_gate` requires explicit valid flags and finite score/coverage in the percentage domain before trusted learning. Capture-unavailable completed execution still has its distinct execution-only confidence. | `test_trusted_completed_draw_requires_finite_score_and_coverage`, existing incomplete/low-quality/resume gates |
| SS20 | Worker selection used machine CPU count even when the process could use only a restricted CPU set. | `ResourceAllocation.logical_cpu_count` prefers `os.process_cpu_count` when available, then process affinity on supported systems, with the existing CPU-count fallback. | `test_process_cpu_affinity_limits_worker_selection`, `test_cpu_probe_falls_back_when_affinity_is_unavailable` |
| SS21 | Linux available-memory estimates used free pages and ignored reclaimable memory, producing unnecessarily restrictive budgets. | `ResourceAllocation.available_ram_mb` uses the kernel's `MemAvailable` estimate when present, retaining the existing portable fallback. | `test_linux_available_memory_includes_reclaimable_ram` |
| SS22 | One allocation probed CPU count and available RAM twice, so the budget and reported hardware could describe different moments. | `resolve_allocation` probes each once and passes the same snapshot through resolution and returned metadata. There is no long-lived hardware cache. | `test_allocation_uses_one_consistent_hardware_snapshot` asserts one call to each probe and consistent results. |
| SS23 | Known available RAM below 128 MiB was rounded up to a larger planning budget; tuner recommendations could also exceed very low available memory. | Allocation refuses unsupported sub-128 MiB conditions with an actionable error. The tuner uses a bounded custom value between 128 and 511 MiB instead of recommending 512 MiB. Unknown memory retains the previous fallback. | `test_known_exhausted_memory_cannot_resolve_to_larger_budget` |
| SS24 | The eight-row minimum and subsequent pressure scaling could override computed memory limits for wide images. | Allocation and scheduler share a row-budget calculation. Memory limits take precedence over preferred chunk size; a row that cannot fit is rejected and pressure scaling never enlarges a small chunk. | `test_wide_image_chunks_obey_ram_budget_even_below_eight_rows`, `test_pressure_scaling_never_increases_a_small_safe_chunk` |
| SS25 | Python 3.12 executor `map` submitted every task eagerly, allowing a large pending-work allocation and unnecessary queued work after failure. | `ResourceAllocation.parallel_map` keeps at most two tasks per effective worker outstanding, preserves input ordering and cancels the remaining submitted window after an error. Running work is still allowed to finish. | Bounded-executor, worker-failure and real-thread ordering tests |
| SS26 | Explicit process mode with more than 61 Windows workers could fail at `ProcessPoolExecutor` construction. | `parallel_map` caps the Windows process executor at the documented supported maximum and at the number of tasks. Thread mode is unaffected. | `test_windows_process_executor_respects_documented_worker_limit` |
| SS27 | The scheduler respected CPU mode for matrix work but still labeled correction scoring for GPU routing. | `resolve_resource_schedule` also respects explicit CPU mode for correction scoring. | `test_explicit_cpu_mode_also_controls_correction_scoring` |
| SS28 | Invalid persisted scheduler schemas, worker counts, engine names or benchmark scores could crash selection or enter runtime recommendations. | `ResourceScheduler` validates stored recommendation structure/domains, rejects corrupt recommendations and safely ignores invalid injected worker suggestions. | `test_corrupt_scheduler_recommendations_fail_closed` |
| SS29 | Default recommendation loading reconstructed the machine signature from the stored CPU count, allowing an old CPU capacity to validate itself. | Default loading compares the saved signature with current usable CPU capacity. Explicit caller-provided current signatures remain supported. | `test_saved_scheduler_recommendation_must_match_current_cpu_capacity` |
| SS30 | `run_auto_tune(save=False)` still called the scheduler benchmark with `save=True`. | The no-save option now reaches both scheduler and hardware benchmarking and prevents tuner-result publication. | `test_auto_tune_save_false_does_not_persist_scheduler_or_hardware` |
| SS31 | A structurally shallow tuner cache check could load invalid CPU counts and unsupported planning/RAM/engine selections into the UI. | `load_tune_result` validates effective/logical worker counts, supported resource choices, GPU availability flag and elapsed-time domain before returning a cached result. | `test_corrupt_tune_settings_are_not_loaded_into_ui` |
| SS32 | After a hardware benchmark error, the tuner loaded a cached profile without checking it against current hardware. | The fallback requests normal current-hardware validation; an invalid/missing cache leaves CPU metadata in place. | `test_failed_hardware_benchmark_cannot_reuse_unvalidated_machine_profile` |
| SS33 | Explicit profiler stop tokens left active marks behind and repeated stops could double-count a phase. | `PerformanceProfiler.stop` consumes each token once, removes its matching active mark and preserves a newer nested mark. Stored profiler data remains JSON-serializable. | `test_profiler_tokens_are_consumed_once_and_nested_marks_survive` |
| SS34 | An all-zero or unknown-only profile reported the first known phase as a bottleneck despite having no positive measurement. | `dominant_phase` considers only finite positive measured phases and otherwise returns no dominant phase. | `test_profiler_has_no_false_bottleneck_for_unmeasured_phases` |
| SS35 | Execution telemetry copied every path in a color group at once and allocated a slice for each pairwise distance traversal. | `ExecutionTelemetry` processes one path tuple at a time and uses pairwise iteration. Cost-model inputs, color ordering and complete metrics remain unchanged. | `test_telemetry_streams_groups_without_changing_cost_inputs_or_counts`; exact baseline-output comparison and allocation measurement below |
| SS36 | Known target lookups eagerly constructed unused fallback objects, and immutable classification sets were rebuilt repeatedly. | `TargetCapabilities` constructs fallback objects only for unknown targets and reuses immutable built-in catalog views. | `test_capability_catalog_reuses_immutable_results_and_known_objects`; benchmark below |
| SS37 | The bounded source probe copied a full-size RGB image before reducing it to at most 128 pixels on its long edge. | `EndToEndAutoTuner._bounded_stats` resizes common RGB/greyscale inputs before conversion, preserves original statistics and closes owned temporary images. Other modes preserve the prior RGB-conversion semantics. | `test_rgb_probe_resizes_before_any_conversion_and_preserves_statistics`; exact baseline-output comparison and benchmark below |
| SS38 | Cancellation arriving during source color analysis did not prevent the next probe or publication of source features. | `analyze_source` checks cancellation again after color analysis and after the bounded statistics probe. | `test_cancellation_after_color_analysis_skips_next_probe` |
| SS39 | Missing, negative or nonfinite projected time became zero, allowing a timed plan to pass the deadline gate. | `evaluate_plan_acceptance` keeps unavailable timing distinct from zero; required deadline checks need a valid estimate and valid positive budget. | `test_invalid_or_missing_time_estimate_cannot_pass_timed_acceptance` |
| SS40 | Invalid quality thresholds defaulted to zero, while out-of-domain percentage metrics could pass acceptance. | Acceptance validates numerical percentage domains and treats missing/invalid required quality evidence as unverified, retaining the existing combined visual-quality policy and advisory component checks. | `test_invalid_quality_threshold_and_out_of_range_metrics_cannot_pass`, existing acceptance/rescue tests |
| SS41 | The signing walk could follow a native-file symlink and pass an external target to SignTool. | `CodeSigning.sign_distribution` preflights the complete tree for root/directory links or junctions and linked/special native files before its first signing operation. Existing valid upstream-signature handling remains unchanged. | `test_signing_link_preflight_stops_before_any_signature_is_changed`, existing signing tests |

## Measurements

Measurements used CPython 3.12.14 on Linux x86-64, comparing baseline module source
from `git show HEAD:<module>.py` with the working implementation. Values are
medians of five repeats; they are local synthetic measurements, not promised
whole-application speedups or Windows performance results.

| Workload | Baseline | New | Interpretation |
| --- | ---: | ---: | --- |
| Numeric-only exact-color availability, 2,000 calls per repeat | 31.439 µs/call; two file reads | 31.973 µs/call; one file read | One consistent read replaces two. Added strict JSON validation offsets the saved I/O in this hot-cache measurement, so no elapsed-time speedup is claimed. |
| Known-target lookup plus browser-key-set query, 100,000 iterations per repeat | 2.286 µs/iteration | 0.223 µs/iteration | Approximately 10.2× for this narrow lookup pair. |
| Telemetry for one group of 5,000 paths, 32 points each | 45.284 ms; 1,523,976 traced temporary bytes | 44.531 ms; 2,048 traced temporary bytes | Exact output equality; the meaningful improvement is bounded temporary allocation. `tracemalloc` measures Python allocations, not total process RSS. |
| RGB source statistics, 2,400 × 1,600 seeded random input, 10 calls per repeat | 8.342 ms/call | 7.031 ms/call | Exact statistics equality and approximately 15.7% lower elapsed time locally. The removed full-size RGB copy represents 11,520,000 nominal pixel bytes; this is not a measured RSS reduction. |

The telemetry workload used points `((i*3+j)%800, (i+j)%600)` and a pure cost model
returning `len(path)*.002`. The source-probe workload used NumPy seed 123 and BOX
resampling. Both old/new outputs were asserted equal before timing. File and
hardware probe counts are separately asserted by tests so they do not depend on
timing noise.

## Validation and limits

- The two new modules contain 60 focused tests, including spawned processes,
  simultaneous learning updates, independent staging files, injected disk and
  unlock failures, invalid JSON and extremely large integer values.
- Existing related calibration, timing, profile isolation, release packaging,
  signing, scheduler and acceptance tests are run alongside these tests. The
  final aggregate result is recorded by the integration owner after freezing
  the combined batch.
- Native Windows execution of the lock branch and complete release/GUI checks
  remains a CI responsibility. Linux tests exercise actual spawned processes;
  the Windows executor limit has a portable regression as well.
- Transaction coordination covers cooperating writers using the helper. It does
  not prevent unrelated software from replacing local files. Unsupported
  filesystem sync operations retain the documented atomic-replace fallback.
- The retained checked-in JSON fixtures `resource-scheduler-v2.json` and
  `verified-colors-microsoft-paint.json` remain part of source archives. Their
  existing regression explicitly distinguishes them from private runtime state.
  **Later correction (batch 21, 2026-11-07):** the actual color-cache writer uses
  that root Paint filename and overwrites the seed with local verification data.
  [The source-privacy completion](v148-batch21-source-privacy-completion.md)
  therefore moves the unchanged synthetic seed to
  `tests/fixtures/verified-color-cache-v2.json` and excludes root
  `verified-colors-*.json` runtime files. The separate fixture and documentation
  examples remain distributable. This corrects the earlier classification and
  adds no improvement ID.
- No signing credentials, network trust rules, antivirus exclusions, execution
  names or release triggers are changed by this batch.

## Primary implementation references

- [Python 3.12 executors](https://docs.python.org/3.12/library/concurrent.futures.html): eager `map` collection, ordered results and the Windows process-worker limit.
- [Python OS interfaces](https://docs.python.org/3.12/library/os.html): affinity, CPU count, file synchronization and atomic replacement.
- [Linux `/proc` documentation](https://www.kernel.org/doc/html/latest/filesystems/proc.html): the meaning of `MemAvailable`.
- [Python Windows CRT locking](https://docs.python.org/3.12/library/msvcrt.html#msvcrt.locking): byte-region locks and immediate nonblocking failure.
- [Python Unix file locking](https://docs.python.org/3.12/library/fcntl.html#fcntl.flock): process lock operations.
- [Python thread timeout limits](https://docs.python.org/3.12/library/threading.html#threading.TIMEOUT_MAX): supported lock timeout domain.

## Candidates for a later audit — not implemented or counted

These are separate follow-up leads, not additional completed improvements:

1. Correction history validates its outer document and bounds reads, but some
   older per-entry text/number shapes can still reach display formatting without
   a complete row schema. Verify concrete malformed-file examples before editing.
2. The performance tuner's live benchmark-result parser remains less strict than
   its persisted-result reader. Check malformed optional driver benchmark output
   and fallback behavior without running suspect drivers or downloading binaries.
3. Target-probe logging writes raw helper output before later diagnostics export
   sanitization. Audit local-log privacy and output-volume limits against actual
   helper error payloads.
4. Timing databases have a bounded reader but no explicit recent-context
   retention policy comparable to feedback's 256-context limit. Evaluate a
   writer-side size/retention contract and migration compatibility.
5. Review zero-path, fill-only learning against actual executed fill counters;
   planned fill metadata alone should not be confused with completed work.

No larger second batch is opened before combined integration testing.
