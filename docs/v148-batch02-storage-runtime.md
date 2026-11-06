# v1.0.148 batch 02 — storage, resources and release reliability

Date: 2026-11-06. Baseline: `1c09774ad22088c5c30a8f8220b6b451fdee9659`.

This batch contributes **38 additional behavior improvements**. Repeated field
checks, callsites of one shared fix, tests, documentation, fixture maintenance
and corrections to previously counted work are not separate improvements. This
is a contribution toward the requested 1,000 improvements, not a claim that the
overall target is complete.

The new regressions are in `test_v148_storage_batch02_{learning,io,profiles,
resources,mobile,resume,release,diagnostics,update}.py`. The table names the
corresponding suffix and searchable test method where useful.

## Learning and bounded execution

| ID | Previous behavior | New behavior and implementation | Regression evidence |
| --- | --- | --- | --- |
| SR01 | A corrupt correction-history row could raise while rendering history, and invalid timestamps could be written. | `CorrectionHistory` validates row containers, finite metric domains, integer counters and timestamps, discarding unusable rows while preserving valid older entries. Invalid new timestamps are rejected before publication. | `learning`: `test_history_discards_corrupt_rows_without_losing_valid_older_entries`, `test_history_timestamp_cannot_publish_nonfinite_or_negative_state` |
| SR02 | Malformed optional live benchmark results could reach strict persistence or recommendation arithmetic, causing NaN serialization, shape errors or overflow. | `PerformanceAutoTuner` validates JSON payload size/shape, explicit availability flags, finite throughput and integer GPU capacities before recommendation. Unusable optional results take the existing safe CPU fallback. | `learning`: malformed live payload, primary-backend and GPU-flag tests include infinite capacities and invalid containers. |
| SR03 | An interrupted hardware/GPU benchmark could be caught as an ordinary driver error and publish a CPU recommendation. | `PerformanceAutoTuner` propagates `InterruptedError` through GPU probing, universal benchmarking and cached fallback loading; interrupted tuning does not save a replacement result. | `learning`: `test_benchmark_interruption_is_not_driver_failure_or_a_saved_cpu_result` |
| SR04 | Isolated capture-helper logs could expose credentials or grow with full captured output on disk. | `TargetCapture` sanitizes stdout/stderr before bounded head/tail logging and publishes the log atomically; a logging failure does not damage the helper protocol. The bound is for stored logs, not total subprocess capture memory. | `io`: `test_target_helper_log_redacts_before_bounding_and_keeps_protocol_usable` |
| SR05 | Timing databases could be written beyond their own reader's item budget, making a successful save unreadable on the next load. | `DrawTimeCalibration` keeps at most 256 recent contexts and enforces the shared 4 MiB/100,000-item limits before publication. It preserves the current context and bounds operation-kind metadata at 64 rows. | `learning`: large legacy-context retention and operation-metadata tests verify the next read retains the new observation. |
| SR06 | Planned or simulated fills and setup-only timings could be treated as completed work; actual zero-path fill runs were not represented accurately in learning. | `CompletedDrawLearning` distinguishes executed drawing operations and actual runtime fill clicks from plans and dry runs, requiring real finite numeric elapsed evidence. `DrawTimeEstimate` persists the actual fill count, and `AutoTunerFeedback` rejects empty draws. | `learning`: planned-fill/setup rejection, invalid elapsed evidence, actual zero-path fill learning, empty-feedback rejection and integer-counter tests. |
| SR07 | Feedback-adjusted outcomes were recorded under a strategy key that the next base-policy recommendation did not read, preventing the policy from learning whether its adjustment helped. | `AutoTunerFeedback` records adjustment outcomes under their base strategy, retaining the selected strategy as metadata. Explicit rescue strategies retain their own contexts. | `learning`: `test_feedback_adjusted_outcomes_update_the_policy_the_next_decision_reads` drives three poor base outcomes followed by eight successful adjusted outcomes and verifies the next recommendation changes. |
| SR08 | Resetting a profile deleted its current timing file; the next load could migrate old global timing data back into the supposedly reset profile. | `ProfilePortability` writes an empty current-format timing document during reset, preserving the migration boundary. | `profiles`: `test_profile_reset_cannot_reimport_legacy_timing_on_next_load` |
| SR09 | Preview budgeting silently raised small budgets to a 192 MiB floor, preferred pixel minima could override a real limit, and some reductions enlarged an already smaller requested dimension. | `ReleaseStabilityHardening` gives the actual memory bound priority, rejects a budget unable to fit fixed overhead and one pixel, and never enlarges a requested dimension. Coordinated `DrawBot` and `PreviewQuality.full_preview_options` integration protects both normal UI preview and direct full-detail callers; full-detail keeps its stricter 512-byte-per-pixel/8M limit. | `resources`: low-budget, dimension-monotonicity and malformed-budget tests; root's caller/direct-helper regressions cover guard failure and invalid budgets. |
| SR10 | Invalid or reversible clock/cancellation state could leave an attempt with no real deadline or allow a previously cancelled/timed-out attempt to resume. | `PreviewAttemptGuard` requires a finite positive deadline and latches cancellation and timeout, with zero remaining time after termination. | `resources`: finite-deadline, cleared-cancel-flag and backwards-clock tests. |

## Local preview, resuming and profile boundaries

| ID | Previous behavior | New behavior and implementation | Regression evidence |
| --- | --- | --- | --- |
| SR11 | Failure constructing the preview server thread happened outside rollback, leaving its listener and session state allocated. | `MobilePreview.start` includes thread construction in the cleanup boundary and releases the server/session on failure. | `mobile`: `test_thread_construction_failure_releases_listener_and_session_state` |
| SR12 | A client sending header bytes just before each socket inactivity timeout could occupy a limited client slot indefinitely. | `MobilePreview` applies an absolute five-second header deadline, closing the socket when it expires and cancelling the deadline after parsing/cleanup. Normal response transfer keeps its existing socket timeout. | `mobile`: `test_header_trickle_cannot_hold_a_client_slot_indefinitely` uses an actual local socket. |
| SR13 | Malformed absolute request targets and disconnects during early HTTP errors could escape the request handler. | `MobilePreview` returns a controlled 400 for invalid target parsing and contains expected send/disconnect errors for successful and error responses. | `mobile`: malformed-target regression plus existing unauthorized, missing-route and disconnect coverage. |
| SR14 | A large opaque RGB/L preview was converted to a full-size RGBA copy before resizing. | `MobilePreview` resizes opaque inputs before conversion, retaining previous handling for alpha/color-key transparency and closing owned temporary images. | `mobile`: exact PNG equality for RGB, L, RGBA and color-key cases; reproducible benchmark below. |
| SR15 | Sequence checkpoint creation hashed the same image/context twice, materialized a full RGBA image/byte buffer and duplicated completion flags. | `RenderResume` computes the context once, streams bounded RGBA strips in the same byte order and builds the completion bitset from an iterator. Existing checkpoint content and fingerprints remain compatible. | `resume`: context-call count, last-pixel hash sensitivity and strip-bound tests; exact old/new checkpoint equality in the benchmark. |
| SR16 | A checkpoint could claim completed drawing while its prelude was incomplete, allowing resumed execution to replay fills over already completed work; writers also silently coerced invalid counters. | `RenderResume` validates integer progress ranges and requires the prelude before any completed path/color/sequence work. Invalid persisted combinations are rejected; a fresh zero-progress checkpoint remains valid. | `resume`: `test_completed_work_without_prelude_cannot_resume_and_replay_fills`, `test_checkpoint_writers_reject_invalid_completion_instead_of_clamping` |
| SR17 | Failure reading an image while fingerprinting could silently substitute its size, allowing different unreadable content to share a resume identity. | `RenderResume` requires successful image hashing and propagates a read failure instead of constructing a weaker fingerprint. | `resume`: `test_unreadable_source_cannot_be_replaced_with_a_size_only_fingerprint` |
| SR18 | Clearing render progress swallowed an unlink error and reported success while the old checkpoint remained. | `SessionRecovery.clear_render_progress` reports the storage error under the snapshot guard; callers cannot mistake retained progress for successful deletion. | `resume`: `test_clear_render_failure_is_reported_and_preserves_existing_progress` |
| SR19 | Recovery accepted a zero-width or zero-height drawing area, which cannot identify an executable canvas. | `SessionRecovery` excludes zero-extent areas while retaining valid reversed corner ordering. | `resume`: `test_recovery_area_must_have_positive_extent` |
| SR20 | Calibration fingerprinting read arbitrary file sizes and treated access failures like missing files, allowing an unreadable calibration to reuse a missing-file context. | `ProfileStorage` bounds regular calibration files at the portability limit of 8 MiB, preserves full-content hashing for valid files and distinguishes an actual missing file from an I/O/permission failure. | `profiles`: oversized/permission/missing cases; existing late-byte fingerprint regression preserves full-file identity. |
| SR21 | Copying Paint tool calibration to a custom profile relabeled its incompatible protocol as generic controls, including UI elements needing multistep Paint actions. | `ProfilePortability` converts anchored Paint calibration into generic schema 1 using only direct Fill/Eraser controls. Unanchored legacy tools are omitted and require recapture. Source package data is preserved. | `profiles`: anchored direct-tool conversion and unanchored legacy exclusion; existing profile isolation/import tests. |
| SR22 | Invalid helper deadlines, coordinates/PIDs or deeply malformed response JSON could reach a subprocess/native boundary or raise inconsistent parser exceptions. | `TargetCapture` validates finite deadlines, signed native geometry and PID domains before launch and reports malformed/deep/extreme JSON as a controlled helper-response error. | `io`: `test_target_deadline_and_area_fail_before_a_helper_is_started`, `test_deep_or_extreme_json_is_a_controlled_invalid_helper_response` |

## Build and release integrity

| ID | Previous behavior | New behavior and implementation | Regression evidence |
| --- | --- | --- | --- |
| SR23 | The builder deleted current-version assets before dependencies/build succeeded, and ZIP creation wrote over the completed output in place. | `build_release` creates and integrity-checks a unique staged ZIP before atomic publication and defers obsolete-variant cleanup until the final release gate succeeds. Dependency/compression failures preserve existing finished outputs. This is not an atomic transaction across every release asset. | `release`: injected compression failure preserves old ZIP and removes staging; dependency failure preserves completed assets. |
| SR24 | Identical distribution contents produced different portable ZIP bytes when checkout timestamps changed. | `build_release.zip_onedir` writes sorted entries with fixed timestamps and regular-file permissions while streaming their content. | `release`: `test_runtime_zip_is_independent_of_checkout_timestamps` compares complete ZIP bytes and runs the gate. |
| SR25 | Distribution or help collection could traverse linked/junction directories or bundle linked external content. | `build_release` preflights the complete regular distribution tree before compression; `build_exe` prunes archived/linked help directories before walking and excludes linked help files. | `release`: external file-link rejection before compression, simulated Windows junction metadata and help-junction exclusion; prior archive-filter tests. |
| SR26 | A standard build made in an environment previously used for CUDA could collect optional CuPy through imports and become an unintended GPU variant. | `build_exe` explicitly excludes `cupy` and `cupyx` for the standard variant. CUDA still explicitly collects them, and required PyOpenCL/TkDnD/CustomTkinter collection stays intact. | `release`: `test_standard_and_cuda_collection_are_explicit_even_with_a_reused_environment` |
| SR27 | Source gates did not require the application base version, Windows file version and numeric Inno installer version to agree. | `ReleaseCandidateHardening` validates all three representations, retaining permitted channel suffixes and historical fixture versions. | `release`: `test_source_gate_requires_consistent_app_and_numeric_installer_versions` |
| SR28 | The release gate decompressed an entire archive for CRC validation before rejecting clearly forbidden names or missing executable structure. | `ReleaseCandidateHardening` performs cheap path/required-executable/header checks before full CRC decompression. Valid archives still receive the integrity pass. | `release`: forbidden-entry regression asserts `ZipFile.testzip` is not called; existing valid archive/gate tests. |
| SR29 | Manifest creation silently omitted a requested missing artifact, allowing an apparently successful partial release manifest. | `ReleasePackage` rejects missing/linked explicitly requested artifacts and duplicate output names before replacing the previous manifest. | `release`: `test_manifest_cannot_silently_omit_a_requested_missing_artifact`; existing manifest/checksum tests. |
| SR30 | The certificate preflight resolved `powershell` through normal command lookup rather than the trusted Windows system directory. | `CodeSigning.validate_certificate` obtains an absolute OS-resolved PowerShell path and validates the certificate thumbprint at its own boundary. Signing policy and valid upstream signatures remain unchanged. | `release`: `test_certificate_probe_uses_os_resolved_powershell_without_path_lookup`; existing signing tests. |

## Diagnostics and resource cleanup

| ID | Previous behavior | New behavior and implementation | Regression evidence |
| --- | --- | --- | --- |
| SR31 | Selecting a small diagnostics subset first sorted every matching path, retaining an unbounded candidate list. | `DiagnosticsPackage` uses bounded heap selection for summary and recent-dump inventory. It retains the intended order/selection and excludes nonregular dump entries. | `diagnostics`: `test_summary_selection_keeps_only_a_bounded_number_of_path_objects` instruments live candidate objects. |
| SR32 | Recovery profile/timestamp metadata and dump filenames could bypass content sanitization in a shareable diagnostic summary. | `SessionRecovery.diagnostics_summary` and `DiagnosticsPackage` sanitize these metadata strings before export. Existing useful identifiers remain when they contain no sensitive content. | `diagnostics`: synthetic credentials in recovery metadata are absent from the exported system summary; existing privacy suites. |
| SR33 | Authorization redaction covered Basic/Bearer but could disclose other authentication schemes such as NTLM, Negotiate or Digest. | `LocalSanitization` redacts arbitrary Authorization values, retaining familiar scheme labels where appropriate and preserving surrounding quoted JSON structure. | `diagnostics`: `test_every_authorization_scheme_is_private_and_quoted_json_stays_valid`; prior URL, request-target and compact-JSON regressions. |
| SR34 | Failed log rotation was ignored and logging continued appending beyond the configured budget. | `CrashDiagnostics` reports whether rotation made room and skips additional append when it did not. A failed filesystem operation cannot turn bounded logging into indefinite growth. | `diagnostics`: `test_rotation_failure_does_not_turn_a_bounded_log_into_unbounded_append` |
| SR35 | Python exception/startup records appended indefinitely to the open native crash stream. | `CrashDiagnostics` bounds Python-record additions while preserving the open descriptor registered with `faulthandler`; exceptions still reach the separate rotating error log. Native fatal-handler output itself is not claimed to be strictly capped. | `diagnostics`: `test_python_crash_records_keep_the_native_handler_descriptor_and_budget` |
| SR36 | Clean-exit marker ownership loaded the entire marker even though only a small record was expected. | `CrashDiagnostics` reads at most 1,025 bytes and rejects oversized/malformed ownership data before removing a marker. | `diagnostics`: `test_oversized_run_marker_is_not_read_unbounded_or_deleted_as_owned` |
| SR37 | A colour planner waiting for pooled tasks could not observe cancellation until its current result completed; the caller could then retry cancelled work serially. | `ResourceAllocation.parallel_map` polls an optional cancellation callback during waits, stops replenishing the bounded queue and cancels queued tasks. `PixelData` and `AdvancedColor` pass existing callbacks and propagate interruption. Running workers still finish during executor shutdown. | `resources`: serial cancellation, blocked-worker queue cancellation, genuine worker timeout and caller no-retry tests; existing ordered/bounded executor tests. |
| SR38 | Response-close or staging-cleanup errors could replace the real updater failure; failed `fdopen` could leak its raw temporary descriptor. | `UpdateCenter` closes raw descriptors on stream-construction failure, preserves primary download/cancellation/status failures and records secondary cleanup trouble without publishing incomplete data. Response-close failure also cannot invalidate an otherwise verified result. | `update`: cleanup-failure/cancellation/rate-limit tests, descriptor-construction failure and failed-staging-delete tests; existing TLS, host, hash and locked-launcher tests. |

## Corrections and shared integrations not counted again

- **Batch01 SS01/SS02 Windows completion:** actual Windows CI reported native
  `WinError 5` during the eight-thread tuner-save regression. `RuntimePaths`
  serializes publication and retries only native
  Windows errors 5, 32 and 33, for at most ten attempts and 0.65 seconds total
  delay. It retains the same unique staging file and atomic replacement; there
  is no delete-first fallback. Persistent permission errors still fail and
  preserve the destination. Failure injection and the existing concurrent test
  pass locally; a real Windows held-reader test awaits native CI.
- Review reproduced a transaction/publication lock inversion in the first
  retry implementation. Logical transaction stripes are now separate from one
  reentrant publication lock, shared by ordinary and file-set publication and
  always acquired after any logical transaction. Bounded spawned-process tests
  force stripe collisions between two writers and cover success and rollback
  for both ordinary and file-set saves. This corrects the existing shared
  publication/transaction work and adds no improvement count.
- `RuntimePaths.replace_text_files` extracts the reviewed profile rollback
  implementation, validates aliases before mutation and handles interruption.
  Its guarantee is in-process exception rollback, not crash atomicity or a
  transaction for independent readers/processes. The paired Paint-calibration
  save using this helper belongs to the calibration batch.
- Recovery's strict JSON reader and reentrant shared snapshot lock complete
  SS03/SS04 coverage. Atomic release manifest/checksum calls complete SS02.
  Aborting the signing preflight on an unreadable subtree completes SS41.
- ETA final-canvas learning now also uses the shared snapshot trust predicate
  to reject explicit contradictory trust/geometry metadata. Legacy valid
  metadata without a feedback label still passes. This closes SS19's trust
  boundary consistently with the delivery batch, without a new entry here.
- The two-byte executable header read and updater's final cooperative deadline
  check extend previously counted bounded-read/deadline behavior. They are not
  new entries here.
- `TargetCapture.owner_root_handle` validation supports the calibration batch's
  owned-window capture behavior. The root preview-budget caller belongs to
  SR09. Runtime-report export/counter defenses are owned by the delivery batch
  where applicable, and are not counted in this ledger.
- Fixture changes preserve each test's intended historical release or profile
  scenario. They are not product improvements.

## Reproducible measurements

Run `python benchmark_v148_storage_runtime.py` from the repository with its normal
Python dependencies installed. It reads baseline module source from local Git
with no fetch/download and writes `docs/v148-batch02-storage-benchmarks.json`.
The baseline is the full commit named above; current shared dependencies are
used for both module versions. Output equality is asserted before measurement.

The recorded run used CPython 3.12.14, NumPy 2.5.4 and Pillow 13.0.0 on Linux.
Times are medians of five repeats. Native Windows and full-application throughput
are not measured by this script.

| Workload | Baseline | New | Meaning |
| --- | ---: | ---: | --- |
| Sequence checkpoint, 5,000 operations, 2,400 × 1,600 RGB image | 133.742 ms; 31,279,219 Python-traced peak bytes | 44.384 ms; 2,522,306 Python-traced peak bytes | Identical complete checkpoint. About 3.01× for this isolated workload. Traced Python allocation is not process RSS. |
| Mobile PNG, seeded RGB 2,400 × 1,600 reduced to a 1,600-pixel longest edge | 351.388 ms | 322.709 ms | Identical PNG bytes and about 8.2% less elapsed time locally. The removed full-size RGBA copy represents 15,360,000 nominal pixel bytes, not a measured RSS reduction. |

## Verification and limits

The nine new focused modules contain **73 tests**. All pass locally; one test
requires native Windows. They cover injected disk/permission/cleanup failures,
actual local sockets, controlled threaded cancellation, malformed persisted
state and deterministic synthetic release artifacts. Existing related tests
are run separately: 346 related tests pass with four platform skips; the
additional learning/report cross-check has 84 passing tests. These suites
overlap and are not summed. Final combined Linux/Windows results belong to the
root integration checkpoint.

Native Windows CI is still required for sharing retries, Windows handles,
system-directory certificate probing and the actual PyInstaller/Inno build.
No old installer or unknown binary was downloaded or executed for these tests.
No antivirus classification, signature policy, trust rule or required runtime
binary was weakened to change a scanner result.

Primary references used for platform behavior:

- [Python 3.12 filesystem APIs](https://docs.python.org/3.12/library/os.html)
- [Windows CreateFile sharing modes](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- [Windows DeleteFile behavior](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew)
- [Python socket timeout and shutdown behavior](https://docs.python.org/3.12/library/socket.html)
- [Python HTTP server handlers](https://docs.python.org/3.12/library/http.server.html)
- [PyInstaller module-exclusion option](https://pyinstaller.org/en/stable/usage.html)
