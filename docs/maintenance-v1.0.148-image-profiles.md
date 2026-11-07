# v1.0.148 maintenance: images, profiles, and recovery (051–075)

These 25 entries describe changes in runtime behavior. Tests and documentation
are evidence for the changes and are not counted as separate improvements.

The recovery changes keep source images local. Recovery restores configuration
and work only: preview returns to Manual and target selection, preflight,
small-test, dry-run, and input arming must all be completed again.

## Change ledger

| ID | Problem and implemented behavior | Focused regression evidence |
| --- | --- | --- |
| 051 | `SessionRecovery._safe_primitive` previously retained NaN and infinities. Saving drops nonfinite option values, and loading rejects nonfinite JSON numbers. Valid integers, booleans, and bounded strings remain supported. | `test_rc4_session_recovery_integrity.SessionRecoveryIntegrityTests.test_finite_recovery_options` |
| 052 | Python equality allowed boolean/float recovery schemas and truthiness accepted strings such as `"false"` for `has_image`. Schema IDs now require an integer, and the image flag requires a boolean. Legacy absent image flags still mean false. | `test_schema_and_image_flags_are_not_coerced` in the same module |
| 053 | Session and render JSON previously used unbounded `read_text`. Reads are now limited to 128 KiB and 8 MiB respectively, with depth/item limits and safe handling of invalid UTF-8, decoder recursion, and nonfinite numbers. A broken render file still permits a valid session to load. | `test_json_size_utf8_depth_and_render_load_fail_closed` |
| 054 | Saving and loading used different canvas-coordinate validation, and coercing infinity could raise `OverflowError`. Both paths now use one validator for exactly two pairs of integer coordinates within ±200,000, without silently truncating floats or accepting booleans. | `test_saved_area_roundtrip_and_invalid_coordinates` |
| 055 | Target-lock hints copied arbitrary nested lists and unbounded scalar values. Only known metadata fields are retained with explicit shapes, lengths, numeric limits, and types. Live handles and authorization remain excluded. | `test_target_hint_is_flat_bounded_non_authoritative_metadata` |
| 056 | A fixed PNG temporary filename and separately replaced image/state could mix concurrent saves or change the previous snapshot's pixels after a state-write failure. New schema 3 publishes uniquely staged, SHA-256-addressed images before the state file. A thread lock and OS advisory lock serialize publication and cleanup. Successful saves retain the current and previous image generations; failed publication preserves the current snapshot. | `test_failed_state_publish_keeps_old_image_and_render_checkpoint`, `test_simultaneous_process_saves_publish_matching_bounded_images`, `test_image_digest_detects_tampering_and_previous_generation_is_retained`, `test_legacy_image_migrates_without_losing_source_or_restoring_arming` |
| 057 | Cached images previously decoded without a size gate. Loading now limits encoded bytes to 256 MiB and dimensions to 40 million pixels, treats Pillow decompression warnings as rejection, and verifies a new snapshot's image digest using the same open file that is decoded. The pixel limit preserves the existing screenshot-capture ceiling. | `test_cached_image_limits_apply_before_rgba_conversion`, `test_image_digest_detects_tampering_and_previous_generation_is_retained` |
| 058 | The recovery allowlist discarded existing snapshot fields, including resource scheduling, detail zoom, visual verification, color fidelity, profile/edge behavior, sketch detail, timer reading, and render preset. These fields now survive save/load without allowing input authorization or automatic preview restoration. | `test_recent_snapshot_settings_survive_and_authorization_does_not` |
| 059 | `clear_render_resume` deleted progress before the session write succeeded. It now clears progress only after the new state file publishes successfully. | `test_failed_state_publish_keeps_old_image_and_render_checkpoint`, `test_clear_render_progress_after_successful_publication` |
| 060 | Sequence checkpoints treated valid `color_index=0` as missing because of `or -1`. Zero now remains zero through checkpoint validation and resolution; absent/None color indices retain the missing-value sentinel. | `test_rc4_session_recovery_integrity.RenderResumeIntegrityTests.test_first_palette_color_is_not_replaced_by_missing_color_sentinel` |
| 061 | A checkpoint could claim both path-level and sequence-level progress, and validation silently chose one. Contradictory modes now invalidate the checkpoint. | `test_conflicting_resume_modes_are_rejected` |
| 062 | Sequence bit validation expanded every bit into a Python boolean list. Validation and count reconstruction now use packed bytes, enforce encoded length and zero tail bits, and cap the operation count before allocation. The existing `_decode_bits` compatibility helper remains available. | `test_validation_memory_stays_proportional_to_packed_bytes` checks four million operations below 8 MiB peak temporary allocation; `test_bit_count_padding_and_non_string_input_are_validated` checks corruption |
| 063 | Custom profile names could collide by case or contain control/format characters. Creation, loading, and portable-profile validation now use printable, bounded names, and new registrations enforce casefold uniqueness while retaining ordinary Unicode names. | `test_rc4_profile_integrity.ProfileIntegrityTests.test_custom_names_reject_case_collisions_and_control_characters`, `test_registry_skips_case_and_control_names_without_changing_builtins` |
| 064 | Two registry names could reuse one custom UUID and therefore share settings/calibration storage. Loading now records existing key owners and ignores a second owner of the same key. | `test_registry_cannot_give_two_names_one_storage_owner` |
| 065 | The custom profile registry was an unbounded UTF-8 read. Loading now caps bytes and entries, rejects duplicate JSON keys, safely handles invalid UTF-8/decoder recursion, and only registers valid flat name/key pairs. | `test_registry_ignores_invalid_bounded_utf8_and_nested_json` |
| 066 | Importing profile settings and calibrations sequentially could leave a partially replaced profile. All new files are staged before publication, originals are retained as unique backups, and a reported write/move/delete failure restores prior files, including prior absence. A failed rollback retains recovery files and reports their paths. | `test_import_publish_failure_restores_updated_deleted_and_absent_files`, `test_import_staging_failure_leaves_every_original_in_place`, `test_failed_rollback_keeps_original_backup_for_recovery` |
| 067 | Import-as-copy and new imported profiles registered a UI entry before their files were saved. Registry publication is now included in the file operation, and in-memory registration happens only after all profile files and the registry succeed. | `test_custom_copy_registration_and_profile_files_roll_back_together`, `test_successful_custom_copy_publishes_matching_key_then_reloads` |
| 068 | Reset profile deleted files one at a time and could stop with half the original profile missing. Reset now uses the same backup/rollback mechanism, and does not reload defaults when a deletion fails. | `test_reset_failure_restores_files_and_never_reloads_defaults` |
| 069 | App-tool and exact-color filenames used a different sanitizer from other profile files, causing collisions such as `a/b` and `a-b`. Both now use `ProfileStorage.safe_profile_key`; ordinary built-in/custom UUID filenames remain unchanged. | `test_tools_share_profile_storage_key_without_unsafe_name_collisions` |
| 070 | Integral floating factors such as `2.0` passed validation but produced floating resize dimensions, while size suggestions accepted dimensions rejected by actual upscaling. Upscale calculations now normalize supported numeric factors to integers and share strict positive-integer dimension validation with suggestions. | `test_rc4_image_processing_integrity.ImageProcessingIntegrityTests.test_integral_floating_upscale_factor_produces_integer_dimensions`, `test_size_validation_is_consistent_for_estimates_and_actual_upscales`, `test_invalid_factors_fail_before_image_conversion` |
| 071 | Corner color previously used exactly the Auto border model. It now samples small patches at the four actual corners and uses the dominant corner-color cluster. Full-border Auto modeling remains unchanged. Border connectivity, transparency preservation, and destructive-removal guards still apply. | `test_corner_color_samples_actual_corners_and_preserves_side_subject` checks a side-touching object that Auto removes but Corner color preserves; `test_corner_mode_retains_uniform_and_existing_transparency_guards` |
| 072 | Background removal checked cancellation only after EXIF/RGBA allocation and could return a result after cancellation during final alpha work. It now checks before allocation, before segmentation, and at every result-return boundary, including preservation branches. | `test_pre_cancelled_background_request_does_not_allocate_or_transpose`, `test_background_cancellation_after_alpha_work_never_returns_result`, `test_preserve_branch_also_honors_late_cancellation` |
| 073 | Profile reset discarded `one_click_setup_after` without cancelling its Tk callback. It now cancels the old profile's pending setup callback before clearing its token and payload. | `test_rc4_profile_integrity.ProfileIntegrityTests.test_reset_cancels_previous_profile_setup_callback` |
| 074 | Scheduling a recovery checkpoint cancelled unrelated preview, setup, profile, capture, and drawing timers. `DrawBotApp._schedule_recovery_checkpoint` now reschedules only its own recovery timer and preserves image-request coalescing. | `test_recovery_ui_rc4.RecoveryUiTests.test_checkpoint_reschedules_only_its_own_timer_and_coalesces_image_request` (root integration) |
| 075 | Recovery loaded a cached image unconditionally, ignoring the snapshot's image flag and identity. `DrawBotApp._apply_recovery_snapshot` now requires `has_image is True` and passes `image_sha256` to the loader. The recovered UI remains disarmed. | `test_recovery_ui_rc4`: `test_snapshot_without_image_never_uses_an_unrelated_cached_file`, `test_recovery_passes_exact_snapshot_digest_and_keeps_input_disarmed`, `test_legacy_snapshot_can_load_its_legacy_image` (root integration) |

## Compatibility and failure limits

The explicit-clear path in **056**, with UI handling in **075**, reports incomplete
removal if a state file, legacy image, digest-addressed image, temporary PNG, or
cache-directory enumeration is blocked. Ordinary pruning after a successful
save remains best effort. The UI does not claim that private recovery data was
deleted when cleanup failed. Coverage is provided by
`test_explicit_clear_reports_locked_hash_image_and_staging_file` in
`test_rc4_session_recovery_integrity` and
`test_declined_recovery_reports_cleanup_failure_without_restoring_or_escaping`
in `test_recovery_ui_rc4`.

Session schemas 1 and 2 remain readable and retain their `last-image.png` fallback.
The next successful save migrates the legacy image into the digest-addressed
cache. `load_cached_image()` without an argument resolves the current snapshot;
callers restoring an already-read snapshot pass its expected digest. Explicit
`expected_sha256=None` selects the legacy PNG, so a concurrent new publication
cannot substitute different pixels for an already-read legacy snapshot. A missing,
changed, invalid, or oversized cached image is not decoded into the restored UI.
An advisory-lock contention that lasts two seconds fails the new save without
replacing the existing state.

Profile imports and reset provide rollback for reported filesystem errors.
They are not a filesystem-wide power-loss transaction: a process termination
between several file moves can leave recovery backups, and a persistent disk
error can prevent automatic restoration. In that case the original backup is
kept and the error identifies the retained recovery path. No input authorization
is imported or restored by these operations.

Corner color intentionally uses only the dominant color represented at the
corners. It is useful when a different-colored subject touches a side of the
image; Auto remains the multi-color full-border mode. Both modes preserve the
original when segmentation would remove an implausible amount of the image.

## Verification

The focused new suites and root's UI integration suite pass **43 tests**:

```sh
python -B -m unittest -q \
  test_rc4_session_recovery_integrity test_rc4_profile_integrity \
  test_rc4_image_processing_integrity test_recovery_ui_rc4
```

A combined run of those suites plus the existing recovery, profile, image,
mouse-contract, calibration-isolation, and maintenance regressions passed
**192 tests** with no failures or skips:

```sh
python -B -m unittest -q \
  test_rc4_image_processing_integrity test_rc4_profile_integrity \
  test_rc4_session_recovery_integrity test_recovery_ui_rc4 \
  test_step10_recovery_diagnostics test_render_resume_v1042 \
  test_rc14_sequence_resume test_profile_portability_step27 test_image_upscale \
  test_profile_isolation_v107 test_background_removal_classical_v10146 \
  test_rc28_background_removal test_windows_mouse test_profiles \
  test_step9_profile_calibration_isolation_v10133 test_profile_switch_safety \
  test_smart_recovery_resume_v1079 test_auto_clear_v10102 test_hundred_improvements
```

The local run used Python 3.12 from the existing project test environment. The
concurrency regression creates two separate Python processes and exercises the
platform advisory lock. This run covered the POSIX implementation; Windows
uses the corresponding `msvcrt` byte-range lock and remains a Windows CI check.
The image tests use generated fixtures and do not send mouse/keyboard input.
Pillow emitted existing `getdata()` deprecation warnings in older tests; these
were warnings rather than test failures.
