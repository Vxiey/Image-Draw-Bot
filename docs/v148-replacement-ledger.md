# Image Draw Bot 1.0.148 — authorized replacement ledger

The original Batch 43 patch and register were not recovered. This ledger documents
replacement behaviors, not equivalence to that batch. Existing entries 1–886 remain
unchanged. Tests, trigger markers, documentation and build milestones add no IDs.

Focused tests below are the behavioral evidence pointers. Final combined test results,
exact-main CI, Windows install/upgrade, publisher signing and antivirus verdict are
separate checks and are not claimed by this ledger. Apply this ledger only to an
integration containing all referenced implementations and tests.

## 887 — Rendering

Check Detail Zoom proposals against original-image error using real modeled brush footprints, keeping only improvements that do not worsen neighboring pixels.

Evidence: test_v148_detail_zoom_quality.py; Standard, Hybrid and Auto replay.

Scope: 878 budgets optional paths; quality admission is separate.

## 888 — Rendering

Use physical brush-aware sampling and prefer exact packing in explicitly selected fixed-brush Extra Fast.

Evidence: test_extra_fast_physical_sampling.py; portrait raster simulation.

Scope: 877 prices retained Fill transitions, not physical stroke density.

## 889 — Rendering

Keep legacy Extra Fast scanlines when a Fill action cannot actually be executed.

Evidence: test_v148_rendering_batch08_fill.py; test_legacy_extra_fast_without_fill_actions_keeps_rectangle_scanlines.

Scope: 877 prices executable calibrated Fill.

## 890 — Timing

Charge canvas clearing once in the final draw budget, so it cannot falsely reject a job that fits.

Evidence: test_auto_canvas_clear_v10114.py; test_actual_draw_worker_does_not_charge_planned_canvas_clear_twice.

Scope: 864 concerns progressive-render delivery costs, not double charging at handoff.

## 891 — Input

Limit web image imports to public HTTPS and verify connect destinations without inheriting proxy or credential settings.

Evidence: test_image_import_network_policy.py; test_v148_platform_batch07_import_redirects.py.

Scope: 77 concerns release-check timing, not image destinations.

## 892 — Input

Reject raw UNC and device paths before image import opens or inspects them; mapped drives and reparse points are outside this policy.

Evidence: test_image_import_network_policy.py; test_remote_share_never_reaches_filesystem.

Scope: 224 interprets file://localhost, not denial of remote paths.

## 893 — Updates

Require separate explicit consent before update download and before installer launch; decline or cancellation must stop the action.

Evidence: test_v148_application_batch16_update_handoff.py.

Scope: Adds user consent, not signatory verification or a duplicate integrity group.

## 894 — Privacy

Do not encode, queue or serve the source Original in Mobile Preview by default.

Evidence: test_mobile_preview_security.py; test_original_is_never_encoded_or_served_by_default.

Scope: 743–744 concern encoding overhead and preview invalidation.

## 895 — Release

Use read-only access for the Windows build and isolate write access to the manually gated publisher; revalidate the exact same-run artifact.

Evidence: test_release_v100.py; publication and scope checks.

Scope: 698 addresses draft concurrency rather than the permission boundary.

## 896 — Privacy

Require explicit consent before Mobile Preview starts a LAN server or discovery; decline, closing and modal reentry must not start sharing.

Evidence: test_v148_ui_batch18_mobile_dialog.py; test_v148_ui_batch27_mobile_discovery.py.

Scope: Separate from 894: whether the service starts, not which content it exposes.

## 897 — Recovery

Keep the recovery checkpoint when the recovery prompt is dismissed without an explicit restore or discard decision.

Evidence: test_recovery_ui_rc4.py; test_dismissal_keeps_checkpoint_without_loading_or_deleting.

Scope: Changes cancellation outcome, not prior checkpoint identity or cleanup.

## 898 — Preview

Stop the preview at a fatal canvas error so its execution replay does not display strokes that native execution would never deliver.

Evidence: test_v148_preview_execution_order.py; test_preview_stops_at_same_fatal_stroke_as_native_execution.

Scope: Changes fatal-operation ordering rather than preview ownership.

## 899 — Release

Pin Windows release workflow actions to immutable commit SHAs rather than mutable release tags.

Evidence: test_release_v100.py; test_windows_release_pins_every_external_action.

Scope: Separate from 895: dependency identity versus token privileges.

## 900 — Privacy

Use anonymous labels in diagnostics archives rather than exposing dump filenames or process IDs through the dump inventory (dump-files.json).

Evidence: test_v148_platform_batch06_diagnostics.py; PerAccountDumpsTests.

Scope: 31 controls symlink privacy, not dump label disclosure.
