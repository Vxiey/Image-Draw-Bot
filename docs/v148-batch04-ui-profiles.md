# v1.0.148 UI and profile helpers — batch 04

This batch contains **13 distinct behavior improvements** against
`1d48eabaf349a5fd8049a2c96ef5426745c3078c`. The later `2aca72a` checkpoint fixes
unrelated pip test fixtures and does not change this comparison. No release or
antivirus result is claimed.

Regression evidence is in
[test_v148_ui_profiles_batch04.py](../test_v148_ui_profiles_batch04.py) (`P`) and
[test_v148_ui_layout_batch04.py](../test_v148_ui_layout_batch04.py) (`L`). Tests
use plain variables, widget/scheduler fakes, actual CustomTkinter class methods,
and an isolated Windows-only Tk layout test. They do not send desktop input.

| ID | Previous behavior and concrete change | Validation |
| --- | --- | --- |
| UP01 | The final `ProfilePolish` pass undid `ProfileEngine`'s explicit Pixel Accurate lock and Unlimited time choice in the four core profiles. The engine also failed to preserve the current `Unlimited / Accuracy` spelling. Both automatic passes now share the same protected-setting contract; normal Auto presets and Manual settings retain their behavior. | P: `test_pixel_accurate_lock_survives_the_production_policy_chain`, `test_both_unlimited_modes_survive_every_automatic_profile_pass`, `test_ordinary_auto_defaults_and_manual_choices_keep_their_contract`. |
| UP02 | Region-fill enablement and aggressiveness were absent from the profile-default snapshot. A new target with no settings file could inherit the preceding target's disabled fill engine or Aggressive policy. `ProfileIsolation` now resets these controls and includes the current detail/quick-sketch variables in its shared snapshot. The detail-zoom viewport also resets with the other preview pages. | P: `test_fill_controls_cannot_leak_into_a_profile_without_saved_settings`, `test_detail_zoom_viewport_resets_with_the_other_preview_pages`. One profile-reset completeness group, not one count per variable. |
| UP03 | StudioUI disabled Paint's secondary Prepare Paint & draw button using the obsolete test/lock/preflight sequence even when the controller's primary button and setup wizard allowed preparation. The secondary button now mirrors the controller's actual state. The workspace model has an explicit Paint preparation mode with optional diagnostics; it does not claim `can_test` before calibration exists. | P: `test_paint_can_prepare_without_claiming_calibration_or_test_readiness`, `test_paint_sidebar_mirrors_the_controller_start_and_uses_one_readiness_snapshot`, `test_sidebar_never_overrides_a_disabled_primary_start_or_busy_state`. Native authorization is unchanged. |
| UP04 | The local F1 help binding conflicted with the global F1 Quick Start binding. Help now uses Shift+F1 and its tooltip identifies both shortcuts. | P: `test_help_shortcut_no_longer_claims_global_quick_start_f1` executes the actual binding callback without creating a window or triggering drawing. |
| UP05 | A single workspace refresh independently checked target locks, preflight and dry-run validity twice for its checklist and wizard. It now reads each once and shares that snapshot, avoiding duplicate calibration-backed validation and disagreement between the two displays during a refresh. | P: `test_paint_sidebar_mirrors_the_controller_start_and_uses_one_readiness_snapshot` requires exactly one call per validity method. No end-to-end GUI timing claim. |
| UP06 | The beginner wizard instructed manual-only targets such as Kleki, Magma and Drawize to use browser Auto setup. It now selects its action and setup label from the actual target capability, and treats optional tool calibration consistently when a palette is already usable. | P: `test_manual_targets_are_given_available_calibration_actions`, including generic/custom and automatic browser targets. |
| UP07 | A successfully unlocked wizard still said that Start was locked and asked for another Unlock. Its status and next action now point to Start while the confirmation is valid, and revert to Unlock when it expires. | P: `test_armed_wizard_points_to_start_instead_of_requesting_another_unlock`. |
| UP08 | Case folding decomposed valid letters such as `ǰ` and `ΐ` after the word guesser's NFC normalization. Its own letter validator then rejected them or miscounted the pattern. A final NFC pass restores canonical letters before validation, indexing and wildcard matching. | P: `test_casefolded_letters_are_recomposed_before_validation_and_matching`; file loading, decomposed input and one-letter wildcards. |
| UP09 | CTk sliders/scrollbars wrap Canvas or Frame widgets, so native class-name checks missed their existing wheel handlers and scrolled the surrounding panel as well. The dispatcher now recognizes those actual CTk control classes while walking the event target's ancestors. | L: `test_customtkinter_slider_keeps_its_wheel_without_also_scrolling_the_panel`. |
| UP10 | On Windows, CTk's one-pixel scroll increment made the coalesced handler move only one pixel per 120-delta notch. The dispatcher preserves CTk's normal 20-pixel distance while retaining fractional accumulation and the bounded 12-notch batch. Generic canvases and macOS/Linux keep their existing units. | L: `test_windows_pixel_increment_preserves_twenty_pixels_per_wheel_notch`, `test_generic_and_nonwindows_canvases_keep_their_original_scroll_units`. |
| UP11 | Moving the pointer to another panel before the 16 ms wheel flush discarded the first panel's complete queued motion. The dispatcher flushes that motion to its original panel before changing the destination. | L: `test_switching_panels_within_one_frame_does_not_discard_the_first_wheel`. |
| UP12 | A compact sidebar group hid existing controls before packing its new shell. If that pack or a later group's construction failed, the supposed original-layout fallback left controls hidden. Group and whole-install rollback now restore prior packing/options/order and destroy only the newly owned shells. CTk controls retain their logical padding so repacking and profile visibility do not apply DPI scaling twice. | L: `test_shell_pack_failure_restores_control_order_and_keeps_hidden_controls_hidden`, `test_later_group_failure_rolls_back_prior_groups_before_falling_back`, `test_ctk_padding_snapshot_uses_logical_values_before_the_widget_rescales`; native Windows test repeats opening/closing at 150% widget scale. Cleanup errors are attached to the original error and retained in the layout error report. |
| UP13 | Sidebar discovery repeatedly crossed the Tk boundary for the same text/tree data, and genuine CTk containers without a `text` option raised an uncaught `ValueError`. Installation now indexes the original tree once, treats those containers as non-text widgets, preserves scoped preorder matches, and releases the index after installation. | L: `test_real_customtkinter_controls_without_text_are_not_invalid_widgets`, `test_tree_lookup_preserves_preorder_and_scoped_matches_with_one_tk_read`; real Windows `test_real_profile_group_can_be_installed_opened_and_scoped`; paired lookup measurement below. One sidebar-discovery group. |

## Completions and exclusions

- Missing profile-extra keys now leave current defaults intact. This is the
  shared application batch's missing-settings preservation behavior, not an
  additional UP entry.
- Destroyed profile controls and scroll targets now fail safely, and a pending
  scroll callback is cancelled on root destruction. These complete the earlier
  destroyed-widget/lifecycle guards (UI07/RT51), without a new ID.
- Busy Paint guidance uses Wait/Stop and a warning string is kept as one warning.
  These complete RT46 and UI12.
- Effective budget metadata and the standalone profile formatter now retain the
  actual Manual/Unlimited budget. The formatter has no active application caller,
  so this accompanies UP01 and is not a separate improvement.
- Root's snapshot/recovery allowlist completion remains separate from UP02's
  active-profile reset. The latter is reproduced without recovery or saved files.
- No changes were made to `ResponsiveRows`: there is no active application call
  site, so proposed changes there would not support a runtime improvement count.
- Further guide/dialog accessibility and ownership candidates remain for a later
  review. They have not been implemented or counted here.

## Reproducible lookup measurement

[benchmark_v148_ui_profiles.py](../benchmark_v148_ui_profiles.py) and
[raw samples](v148-batch04-ui-profiles-benchmarks.json) record seven alternating
before/after samples after warmup, an independent expected-result comparison,
source hashes, and a separate Python allocation measurement.

The workload looks up 49 labels in 977 deterministic widget fakes. It isolates
the search algorithm on widgets whose text-access contract the baseline
supports; it does not measure the independent unsupported-CTk-option failure,
actual Tk latency, full application startup, desktop input or GPU performance.

| Measure | Before | After |
| --- | ---: | ---: |
| Median lookup workload | 7.800 ms | 2.018 ms |
| Text accessor calls | 24,616 | 976 |
| Child enumeration calls | 24,617 | 977 |
| Peak Python allocation during lookup | 1,880 bytes | 118,736 bytes |

All returned widget identities match the expected preorder/scoped search. The
index trades about 114 KiB of temporary Python storage for fewer accessor calls;
it is cleared after sidebar installation. These synthetic timings are not a
promise about overall application responsiveness.

## Verification status

The two new test modules contain 29 tests: 28 pass locally and the real Windows
Tk test is skipped on Linux. A combined independent run of the profile, wizard,
workspace, scrolling, settings and recovery modules completed **207 tests:
206 passed and one Windows-only test skipped**. Whitespace validation also passes.

The independent application review found a future-schema protection regression:
a failed retry of an unsupported settings read cleared its protection and allowed
a subsequent save to overwrite the document. The parent corrected it within AW10;
the original reproduction and the new regression now pass. The old recovery
enumeration failure fixture was updated to target `os.scandir`, retaining its
existing failure assertion. No remaining blocker was found in that review.

Full-program integration is complete. The new checkpoint still requires its own Windows CI.

## Frozen integration checkpoint

Independent area and cross-area reviews are closed. Whole-program discovery ran
**2,934 tests in 75.509 seconds**, passing with 23 platform/hardware skips; source
hashes were unchanged during the run. The 5,000-cycle release source gate,
source-package hygiene and eight exact-raster engine fixtures also passed.
This batch is included in the 668-improvement development checkpoint. Its own
Windows/Linux CI is pending; 1.0.148 is not yet released.
