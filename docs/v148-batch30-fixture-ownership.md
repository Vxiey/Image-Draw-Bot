# Batch 30 — retire calibration test fixtures on their Tcl creator thread

## Classification

This is a **zero-ID test-infrastructure correction**. It changes the cleanup of
the existing batch25 calibration fixture and adds two diagnostic regressions.
No application method, product GC policy, original assertion, skip rule or test
timeout changes. The application changes and measured palette experiment remain
byte-identical to the earlier batch30 measurement checkpoint.

## Failure and attribution

The first complete-suite attempt ended without a final unittest summary or a
runner report. Its cause was not established; its partial log is preserved and
is not counted as a passing run. A detached launch subsequently produced no
test log and started no observed tests. It is recorded separately.

The second attempt used the unchanged discovery command and timeout and exited
with signal 4 (`returncode=-4`) after 225.816 seconds. Its last test was the
second batch29 preview-sequence regression. The native diagnostic was:

```text
Tcl_AsyncDelete: async handler deleted by the wrong thread
```

All 942 source/configuration files remained unchanged during that attempt. The
complete failed log has SHA-256
`dcf95b38eb8d77dde3e86847b0ec178ccffe796f8ea1f32c3b23d09e98fc424e`.
The failure location alone does not establish which earlier fixture retained
the interpreter.

A separate probe ran all six actual `CalibrationLifetimeTests` methods with
cyclic collection delayed only inside its diagnostic child process. The tests
passed, but their normal cleanup left five Tcl wrapper owners and two real
`StringVar` objects alive. The remaining roots were borrowed through the
fixture's scoped windows; the two variables belonged to its actual Paint and
application calibration helpers. Creator-thread collection then retired all
of them. This establishes the retained fixture ownership independently of the
later test that happened to trigger collection.

One unchanged batch25 method was then run against the frozen, published
`4b90b715a9128a022774f411e14e8a1b45676339` checkout. Its ordinary assertions
passed and one Tcl owner survived cleanup. Collecting cycles on a separate
real worker reproduced the same native diagnostic and signal 4 in 0.390 seconds.
The isolated log has SHA-256
`ce67d79f70fa1db5700c1eaa0761926068a8756fcdaabd8a03097a353dab350a`.
The published checkout's complete 887-file root Python map stayed unchanged.
This is a deterministic older-fixture defect; it is not evidence that the
new palette, background, Stop or portrait product changes created that owner.

Independent probes also exercised the new Stop and portrait tests, the actual
batch29 preview-sequence tests, and the batch25 button fixture. Stop and
portrait created no Tcl objects. The preview and button fixtures released their
observed Tcl owners before a later worker collected cycles. The new background
tests additionally passed both ordinary and retained-assertion ownership
probes. Their original variable finalizers ran on their creator thread.

After the fixture correction, a third full-suite execution also lost its tool
session before producing a final summary. It had no Tcl diagnostic and its
cause remains unestablished. The preserved partial log is not counted as a
passing run. An outer supervisor then invoked the same unchanged runner and
emitted visible progress every 15 seconds. That fourth attempt completed all
4,551 tests in 231.751 seconds with 73 existing platform/hardware skips and
no failures or Tcl diagnostics. No test command or timeout was changed.

## Narrow correction

`CalibrationLifetimeTests.route` now registers an explicit cleanup that first
runs the real scoped window's `destroy`. Its `finally` then clears the fixture's
helper dictionaries, helper group and window dictionary on the test thread.
This releases borrowed interpreter aliases even when mock call history,
reentrant callbacks or retained native exception frames keep the surrounding
test objects alive. The fixture's existing cleanup order then retires the main
app variables and interpreter. No product traceback is altered or discarded.

`test_v148_ui_batch30_fixture_ownership.py` exercises all six original workflows
inside two child processes. Both require all six Tcl owners and all 134 real
variables to be dead after actual unittest cleanup and **before** starting a
worker GC. Every original variable finalizer is delegated to and must run on
the creator thread. The second child deliberately retains windows, helpers,
constructor callbacks and the native boundary's original traceback objects.
Only after those assertions does it run collection on a separate actual thread.

The original traceback is retained separately because `unittest.assertRaises`
clears the exception object's `__traceback__` itself. An initial diagnostic
assertion that overlooked this unittest behavior is preserved as an authoring
diagnostic; the tested application behavior and existing assertions were not
changed to accommodate it.

The two focused regressions pass in 1.486 seconds with no skips. Their log has
SHA-256 `9e4bfe3542690bd9e86e3508e2ae8a56229f0b7308485b73e118ccd84c8448a7`.
Independent review and the final integrated gates are recorded in the batch30
validation artifact rather than inferred from this focused result.

## Source provenance

| Checkpoint | Root Python files / map SHA-256 | Full source/configuration files / map SHA-256 |
| --- | --- | --- |
| Product measurement and parity | 892 / `ce9691bce3bdb6b6e992ab3383b323e803f85e8df95c6a99ff6f409a9d345abd` | 942 / `d9c61fbb5e914dcd37682fc08b5b19c20a7eec2bb4ab806b0cbe3806d9fea156` |
| After fixture-only correction | 893 / `0da8de7641efb47fea77c62ece22629b27f9425c137e9d8ccd8d7e9933ae5845` | 943 / `5f6b89f5b52c9ae6f0335345f744fb887936afdab1e847eb5c22d73f3c155b41` |

The exact transition is limited to the modified
`test_v148_ui_batch25_calibration_lifetime.py` and new
`test_v148_ui_batch30_fixture_ownership.py`. All product files, benchmark
drivers, measured dependencies and earlier parity tests remain byte-identical.
Earlier experiment manifests continue to identify the source version actually
tested; they are not rewritten to claim the later fixture checkpoint.

The raw completion evidence preserves the partial first attempt, failed second
attempt, failed detached launch observation, isolated before crash, source-map
transition, focused regressions and independent ownership reviews. These are
portable Linux fixture proofs, not evidence of native Windows input or a
release-ready build. Exact published-commit CI remains a separate gate.


## Integrated frozen-source result

Batch 30 records **842 distinct improvements, 158 remaining**. 2 new behavior groups are registered: R3001, R3002. Background cleanup preserves detail already protected by the border flood; picture-palette growth avoids retesting unchanged centers. Portrait stroke ownership, Stop across image-copy handoff and test-fixture Tcl disposal complete existing contracts with zero IDs. All 840 prior registry entries and 78 earlier benchmark JSON reports are preserved. Completed frozen discovery ran **4,551 tests in 231.751 seconds: 4,478 passed and 73 skipped**; all 943 source/configuration hashes were unchanged. Fourteen Linux/Xorg native cases, the 5,000-cycle source gate, eight exact raster fixtures and initial package hygiene (1,359 files) passed. The package check after final metadata passed with 1,361 files and no warnings. The incomplete process attempts and the Tcl-aborted attempt remain negative evidence. A proved old calibration fixture released borrowed Tcl aliases after real cleanup; no product GC policy, skip, assertion or timeout was weakened. The final background and Portrait historical comparisons and the six-workload/six-pair palette measurement retain their original 892-file map; the final 893-file map differs only in the two explicitly recorded fixture files. Historical checks retain 20 exact background controls and 24 intended corrections, 14 Portrait helper and seven public pairs, and 32 palette comparisons including four public plans. The cold red picture-palette helper and direct refinement improve in all six pairs; unchanged-work controls are not treated as algorithm gains. No universal speed, peak-memory, process-RSS, physical Paint or GPU improvement is claimed. Parent 4b90 has seven green checks after one unchanged Windows-job rerun; the new head requires its own exact-commit CI. Version 1.0.148 remains unreleased.

The final gates bind **893 root Python files**, compact SHA256 `0da8de7641efb47fea77c62ece22629b27f9425c137e9d8ccd8d7e9933ae5845`, and **943 source/configuration files**, compact SHA256 `5f6b89f5b52c9ae6f0335345f744fb887936afdab1e847eb5c22d73f3c155b41`. The original measured/evidence map remains **892 root files**, SHA256 `ce9691bce3bdb6b6e992ab3383b323e803f85e8df95c6a99ff6f409a9d345abd`. The only later differences are the old calibration fixture cleanup and its new subprocess regression; their exact sources, hashes, import boundary and diff are recorded in [raw evidence](v148-batch30-completion-evidence.json) and [final validation](v148-batch30-validation.json). No timing or image checkpoint is silently rebound. The final metadata review and post-metadata package check are recorded separately; publication of the new head does not imply its remote checks have completed.
