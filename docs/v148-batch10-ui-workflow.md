# v1.0.148 UI workflow — batch 10

Baseline: published batch09 commit
`3c5fe8fc27ec3b503e2affa6f3ed00cb7856f973`, whose frozen source tree is
`1b1cc5e4efb41d192ec6d1678e1e3f0c191ecfda` (765 recorded improvements).
This development batch currently contains **two distinct improvements**,
U1001–U1002. No release is implied.

| ID | Reproduced previous behavior | Change and validation |
| --- | --- | --- |
| U1001 | The active numeric-row factory sent every FocusOut and Return directly to `options_changed`. Tabbing through an unchanged field therefore discarded a valid plan, cleared Small Test and reset input checks. Enter followed by another Enter or blur repeated invalidation even after a replacement plan was accepted. Both actual factory/controller regressions failed before the change. | `NumericEntryCommit` commits only changed displayed text through the existing controller callback. Unchanged visits and edits reverted to their original text preserve state. Return acknowledges a successful commit so its subsequent blur is not another change. The variable trace follows unfocused programmatic updates and guarded settings application/rollback. After an ordinary successful `options_changed`, a narrow controller hook acknowledges all displayed numeric values, including a still-focused brush field changed by the real Sketch action. Failed callbacks remain retryable. All numeric controls form one edit-commit flow; none is a separate count. |
| U1002 | `DrawBot.options` resolved a profile-specific automatic color ceiling but dropped it when constructing the planner options. A real Manual-render-preset / Auto-profile-policy / Photo-Shaded flow resolved Paint32 and Skribbl18, yet both actual adaptive color analyses received20. The loss could lower the intended quality allowance or exceed the selected profile's bound. | Forward the already resolved optional `exact_color_limit_profile_ceiling` unchanged into the planner options. The existing adaptive-count consumer and time-aware budget apply it as before; no profile defaults, cap algorithm, calibration or native input behavior are changed. `test_v148_ui_batch10_color_ceiling.py` runs both profiles through the actual public options and planner, checks the analysis call and resulting metadata, and separately verifies uncapped Manual policy and explicit Manual8 behavior. Both profile subcases failed before the two-line correction and pass afterward. |

## Contract and scope

- Genuine edits still call the original `options_changed` invalidation and
  planning path. Numeric validation stays in `DrawBot.options`; invalid text is
  not converted into a successful value by the presentation helper.
- `sync_numeric_commits` runs only after the ordinary invalidation and preview
  scheduling path completes. An exception does not acknowledge the pending
  edit. No generation or plan-identity heuristic decides whether a value is
  accepted.
- Existing CTk focus/class bindings are retained with additional local
  handlers. No global key hook, native drawing input or drawing authorization
  is introduced. Destruction removes the helper's owned variable trace.
- Unfocused external updates and profile/settings rollback establish a fresh
  displayed baseline. A focused ordinary edit remains pending until commit.
  A different controller action that already invalidated the settings uses
  the shared acknowledgement hook to avoid another invalidation on blur.
- This is separate from UK03's unchanged *profile selection* operation and
  UC04's unchanged *widget configuration* caching. Tests, cleanup cases and
  the shared callsite are part of U1001, not additional groups.
- U1002 forwards a computed policy value; it does not persist a new user field
  or alter the profile engine. Manual settings has no inferred profile ceiling,
  and an explicit manual count bypasses automatic count analysis. The two
  profile examples represent opposite effects of the same missing bound and
  count once. UW803's Region Fill controls and UW804's deadline reserve remain
  separate option domains and unchanged.

## Verification

`test_v148_ui_batch10_numeric.py` executes the live `numeric_row` and its actual
factory chain. Portable cases replace only native widgets/presentation and use
real Tcl StringVars plus actual `options_changed`, `_mark_plan_stale`, settings
application/rollback, Sketch action and numeric options validation.

The nine new tests passed locally with one native Windows case skipped. The
native test creates real CTk entries and checks FocusIn/Return/FocusOut, unchanged
and changed values, duplicate commits and trace disposal. It remains pending
the new checkpoint's Windows CI.

The related selection passed **108 tests in 0.428 seconds**, including seven
platform skips. This is a functional check, not a performance claim:

```text
python -m unittest test_v148_ui_batch10_numeric test_v148_ui_profiles_batch04 test_v148_ui_batch07_keyboard test_v148_ui_batch08_keyboard test_v148_ui_batch06_workspace test_v148_ui_runtime test_v148_application_batch04_settings test_v148_application_batch07_profile
```

`git diff --check` passed. The parent independently reviewed the helper,
factory/controller integration and retry/settings boundaries, repeated the
nine focused tests (one Windows skip), and closed the U1001 source review.

U1002's three new tests and related profile-policy/lock/wizard tests passed
**38 tests in 7.164 seconds**, with no skips:

```text
python -m unittest test_v148_ui_batch10_color_ceiling test_v148_ui_profiles_batch04 test_profile_engine_v1045 test_step19_20_profile_polish_setup_wizard_v10143
```

The parent independently reviewed the two-line U1002 forwarding change and its
three actual planner tests, repeated them with three renderer regressions
(six tests passed in 5.362 seconds), and closed the U1002 review. The selections
overlap and must not be summed as unique test counts. Combined batch10 gates
and Windows execution remain pending.

## Existing-contract completion — no additional count

Original063 already establishes case-insensitive profile-name identity, and
AW15 covers fresh context after modal callbacks. A valid exported profile named
`MY BRUSHES` nevertheless skipped the collision dialog when `My brushes`
existed locally, then failed the registration uniqueness check. Both real
Replace and Copy callback regressions failed before this completion.

`ProfilePortability` now resolves the canonical existing label and storage UUID
for the collision dialog and for direct Replace imports. Replace preserves
that UUID; Copy still creates a new owner using the existing transaction.
The dialog binds the displayed destination identity and rechecks it after
each modal response and again after saving current settings, before any import
publication. Rebinding or renaming the destination, pending work or shutdown
cannot turn the confirmation into permission to change another profile.
If no collision existed when the dialog inspected the package, an explicit
expected-absence flag also prevents a subsequently registered name from being
silently replaced. The regression reproduces a save callback creating that
name and a real settings file, and verifies those exact bytes remain intact.
Case-insensitive built-in labels must still match their original target key.
Cancellation does not save or publish anything, and shutdown does not open a
subsequent copy-name or result dialog. The direct API keeps its default Replace
and explicit Copy behavior; the new expected-identity keywords are optional.

`test_v148_ui_batch10_profile_completion.py` uses the actual import dialog and
backend with valid temporary profile packages, real registry/files and mocked
native dialogs. Its nine tests cover both choices, both cancellation points,
name/UUID changes in modal callbacks, busy/shutdown states, built-in identity,
direct API compatibility, a reentrant save and a newly appearing collision.
The new and related profile selection passed **56 tests in 0.273 seconds**,
with no skips:

```text
python -m unittest test_v148_ui_batch10_profile_completion test_profile_portability_step27 test_rc4_profile_integrity test_v148_ui_batch08_profiles test_v148_ui_batch08_profile_management test_v148_ui_batch09_profile_completion
```

`git diff --check` passed. The parent independently reviewed the initial
completion and ran its eight tests. That review identified the expected-absence
gap; after its correction, the parent independently reviewed the narrow
follow-up, repeated all nine actual import cases (passed in 0.062 seconds), and
closed the review. This completion adds no improvement ID. The area worker
performed no staging, commit or remote publication.

## Frozen checkpoint validation

Batch 10: final frozen-source discovery passed 3,579 tests in 125.869 seconds (43 platform/hardware skips), with unchanged Python and batch-script hashes. All four area source reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. Paired rendering and recovery measurements bind the final source snapshot and disclose unchanged or slower total-work results. This checkpoint still requires its own Windows/Linux, dependency, CodeQL and packaged Windows checks. No 1.0.148 release is published.
