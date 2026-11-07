# v1.0.148 UI workflow — batch 09

Baseline: `ab2a59bd1432aac7528d378cef2c4ebcf689a47b` (759 reviewed and
published behavior groups). This development batch currently contains **three
distinct improvements**, U901–U903. It is not a release announcement.

| ID | Reproduced previous behavior | Change and validation |
| --- | --- | --- |
| U901 | Four active StudioUI drawing readouts passed their Tk StringVar as literal label text. The label factory only connected `textvariable` through its `var` argument, so color-plan, estimate, live-time and total-time values displayed an internal variable name instead of following progress. The actual factory/statement regression failed for all four bindings before the fix. | Bind the four readouts through `var=`. One shared live-readout correction, not four counts. `test_v148_ui_batch09_readouts.py` executes the actual nested factory and four active statements with real Tcl variables; the Windows test additionally checks initial text, several updates, Unicode, an empty value and preservation of the native label objects. The parent independently reviewed the exact four substitutions and repeated the focused tests successfully. |
| U902 | Word helper filtered the whole dictionary but displayed only the first 200 matches, with no way to reach later words. Every refresh also inserted those 200 rows through separate Tcl calls. | `WordHelperResults` retains the complete deterministic result and shows bounded pages of at most 200 rows through Previous/Next. Status identifies the exact visible range and page. A new query or dictionary starts on the first page; empty/error results clear the old selection. The original Copy action reads the visible selected row. The actual `DrawBot.update_guesses` method delegates only presentation to the helper, while `WordGuesser.find_candidates` remains unchanged. `test_v148_ui_batch09_words.py` exercises all 451 matches through the real filter callback, page boundaries, changed/invalid queries, replacement dictionaries, actual Copy with a mocked clipboard boundary, late busy/closing/destruction, and the actual workspace state refresh. The Windows test uses real Tk listbox rows and existing KeyboardButton Return/Space delivery. |
| U903 | The progressive plan readout always used the legacy forms/contours/details counters. Actual Sketch Fill and Pixel Accurate plans therefore displayed three zeros despite having real scheduled passes, and other renderers' additional phases were omitted. Both actual `make_plan` → workspace summary regressions failed before this change. | `ProgressiveSummary` uses each renderer's existing metadata: Sketch Fill's three passes, Pixel Accurate's four counters, the hybrid renderer's four counters, and the legacy three counters. Incomplete counters, Deadline's additional phases, extended Pixel correction passes and future schemas use the complete declared phase order instead of invented zeros. `test_v148_ui_batch09_progressive.py` verifies real Sketch Fill and Pixel Accurate plans, legacy/hybrid metadata, Deadline and extended correction orders, incomplete/invalid data and disabled metadata. An execution-sequence sentinel proves the actual UI callback does not scan drawing geometry for this summary. |

## Scope and limits

- U902 counts one complete-result browsing flow. The 200-row insertion changes
  from up to 200 Tcl calls to one per populated page; it is part of this same
  behavior group, not a separate performance count. No end-to-end speedup is
  claimed and no new dictionary indexing algorithm is introduced. UI10's
  existing dictionary cache remains unchanged.
- Navigation never starts drawing, changes target settings or sends desktop
  input. The controller's original Copy method is unchanged; tests replace its
  clipboard boundary. Late UI lifecycle guards complete existing contracts
  and do not add counts.
- The complete list of matches is retained as one immutable tuple. The widget
  holds only the visible page. Existing word-list size and validation limits
  remain unchanged.
- U903 only changes presentation. It neither creates/reorders strokes nor
  grants input authorization. Explicit zero counters remain meaningful; absent
  counters are unknown. Reading the existing small metadata record avoids
  adding sequence traversal to recurring UI refreshes. No speedup is claimed.

## Uncounted existing-contract completion

AW15/068's profile identity and reset contract also covers the confirmation
dialog. A reproduced nested-modal callback switched from `My brushes` to
`Other custom` after the first name was displayed. The old actual Reset flow
deleted the second profile's settings. The dialog now snapshots both name and
storage key and passes them to `reset_profile`, which rechecks the current idle
state and exact identity before publication. A mismatch or shutdown preserves
both profiles. The destructive dialog defaults to No, matching existing Remove
behavior. Shutdown never reads a destroyed Tk variable or opens feedback.
Direct `reset_profile(app)` callers remain compatible. This is **zero** new
improvements, not U904.

`test_v148_ui_batch09_profile_completion.py` has six actual dialog/reset-flow
regressions with real temporary profile files. Native messageboxes are mocked;
profile publication/deletion is real. They cover changed name, rebound storage
owner, worker/pending operations, shutdown before or during the dialog, cancel,
successful selected-only reset and direct API compatibility. Existing profile
rollback and settings preservation tests remain unchanged.

## Verification

The new readout and word-flow modules contain nine tests: seven portable cases
pass and two native Windows cases are skipped on Linux. The combined new and
related word/UI suite passed **79 tests in 0.189 seconds**, including six
platform skips. These are one overlapping combined selection, not additional
unique test counts. `git diff --check` passed.

```text
python -m unittest test_v148_ui_batch09_words test_v148_ui_batch09_readouts test_guesser_drop test_v148_ui_batch01 test_v148_ui_profiles_batch04 test_v148_ui_batch07_keyboard test_v148_ui_batch06_workspace
```

The progressive-summary module adds seven portable tests. Its combined run
with the two other new modules and existing UI/progressive regressions passed
**40 tests in 0.982 seconds**, including two Windows-only skips:

```text
python -m unittest test_v148_ui_batch09_progressive test_v148_ui_batch09_words test_v148_ui_batch09_readouts test_v148_ui_profiles_batch04 test_progressive_renderer_v1021 test_rc9_progressive_drawing
```

The Reset completion and related profile suites passed **45 tests in 0.211
seconds**, with no skips:

```text
python -m unittest test_v148_ui_batch09_profile_completion test_rc4_profile_integrity test_v148_ui_batch08_profile_management test_profile_portability_step27 test_v148_storage_batch02_profiles
```

Imported fixture TestCase classes were moved behind module references so
unittest discovery does not rerun those unrelated classes. The latest two
selections ran concurrently; their durations are functional-test observations,
not performance comparisons. These selections overlap and must not be summed
as unique tests.

U901, U902 and U903 independent source reviews are closed. The parent also
closed the Reset completion review after independently reading the identity
checks and six cases and repeating them with related integration tests.
The new checkpoint's Windows/Linux CI gates are pending.
Product/test source remains frozen through the parent's index snapshot. No commit,
remote publication or release was performed by this area worker.

## Frozen checkpoint validation

Batch 09: final frozen-source discovery passed 3,514 tests in 190.952 seconds (42 platform/hardware skips), with unchanged Python and batch-script hashes. All four area source reviews are closed. The 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures passed. This checkpoint still requires its own Windows/Linux, dependency, CodeQL and packaged Windows checks. No 1.0.148 release is published.
