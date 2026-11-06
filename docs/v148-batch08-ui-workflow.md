# v1.0.148 UI and profile workflow — batch 08

Baseline: `73788a51c1a3502f03f007e4d2ffe0152f56b7e6` (745 previously counted improvements).
This working batch currently contains **six distinct behavior groups**, UW801–UW806.
It is not a release. Further audit and independent review are in progress.

Regression modules:

- **P:** `test_v148_ui_batch08_profiles.py`
- **B:** `test_v148_ui_batch08_budget.py`
- **C:** `test_v148_ui_batch08_controls.py`
- **M:** `test_v148_ui_batch08_profile_management.py`

## Counted changes

| ID | Previous behavior and evidence | Change and validation |
|---|---|---|
| UW801 | A transient startup read failure left valid custom profiles on disk but absent from `PROFILES`. The next ordinary Add or Import as copy built the complete replacement registry from that incomplete in-memory view and erased the old registrations. A real `load_custom_profiles` → Add reproduction retained the original bytes after the failed read, then lost the existing name on the next Add. | `GameProfiles` freshly reads and strictly validates the disk registry for each mutation, merges compatible current registrations, rejects conflicting identities and preserves unreadable/invalid files. Add and import-copy hold one process-local registry lock through publication and in-memory registration. Previously unseen disk registrations become available in the UI only after successful publication. P exercises the actual Add dialog and public import-copy path, a fresh disk addition, casefold collisions, malformed/ambiguous data, read/write failure and missing-file recovery. The tolerant startup loader remains compatible. Existing file-set publication rollback remains the shared original067 contract; no cross-process or crash-atomic registry guarantee is claimed. |
| UW802 | Empty or nonnumeric Manual time text blocked every drawing mode before the effective profile policy was resolved. Fixed game presets and Unlimited therefore failed even though their policy never uses the manual numeric field. | `DrawBot.options` validates the field after the effective profile policy is known and requires its whole-number/range contract only for Manual/Custom. Inactive invalid text stays unchanged in the UI and uses a bounded internal fallback. B covers every supported fixed/unlimited spelling, valid/invalid active Manual/Custom, unknown modes, brush validation and both directions of an automatic profile override. |
| UW803 | Use Region Fill Engine and Fill aggressiveness were displayed, saved and validated, but omitted from the final options dictionary. Actual `options` → `make_plan` with the switch off and Safe still enabled the region engine at Balanced when Auto Fill was enabled. | Transfer both existing controls to effective planner options. C uses real saved anchored Brush/Fill calibration and the real planner to verify the disabled branch, all three aggressiveness values, independence from legacy Auto Fill, and settings save/read. This is one Region Fill control-propagation group, distinct from UP02's profile-default isolation. No detector, leak-safety algorithm or input gate changes. |
| UW804 | Options and target-stroke admission always resolved the Auto reserve, while planning later honored the selected reserve. The final draw guard still compared against the earlier options. Actual `draw` rejected a 56-second plan for Skribbl60/Off because its outer limit remained53 seconds even though the plan correctly allowed60. | Resolve the existing complete budget policy once in `options`, including the selected reserve, and derive its numeric limit, active/unlimited state and target cap consistently. B verifies all advertised reserve choices across fixed/custom/manual/unlimited modes and exercises the actual draw worker through its final guard with a56-second plan. Auto interpolation and explicit reserve policy remain unchanged; RB02 owns the interpolation correction. |
| UW805 | Custom profiles could be added, imported, exported or reset, but had no rename/removal flow. Unwanted names remained permanently in the selector and occupied the1000-profile allowance. Reset removed contents while preserving the registry entry. | The active custom-profile section now provides Rename and Remove. Rename preserves the storage UUID and owned file bytes, permits case-only changes and saves current settings before reload. Remove confirms the exact name/UUID, publishes deletion of only canonical per-profile paths together with the registry, then selects the generic profile. Builtins, collisions, stale modal identity, busy/closing/pending contexts and failed publications preserve data. M verifies actual dialog callbacks, capacity recovery, ordinary/case-only/no-op renames, byte-for-byte rollback, unaffected other profiles/source/export/shared recovery files and revocation of transient input authorization through existing controller methods. Rename and Remove count together as one custom-profile maintenance flow. |
| UW806 | CustomTkinter option selectors in the actual settings factory had no local keyboard selection and focused decorative children. Mouse-only selectors prevented keyboard access to the existing options. | Use one logical Tab stop with bounded arrows/Home/End through the original variable and command callback, native menu opening, Escape, live disabled/value/lifetime checks and shared focus-ring/scroll-reveal helpers. Tooltips bind to logical focus. The actual factory, callback semantics, unchanged global bindings and native Windows focus/traversal/reveal are covered in `test_v148_ui_batch08_keyboard.py`. All option selectors and gestures form one behavior group; existing button behavior remains UK01. |

## Uncounted completions

- **RP24/UP01:** both supported Unlimited spellings now carry the same canonical
  `unlimited_time` result before the Gartic worker decides whether to observe its
  timer. The actual `options` → `draw` worker regression failed for
  `Unlimited / Accuracy`: it observed the timer and replaced Unlimited with
  Manual before planning. Both Unlimited spellings now skip that observation;
  Manual still observes it. This completes existing Unlimited consistency.
- **AW15:** new profile-management dialogs recheck current work, closing, pending
  clear/profile changes and the exact name/storage UUID after modal event
  processing. The shared idle guard also recognizes a pending clear operation.
  These protections are not separate counted additions.
- The management transaction uses the existing rollback-capable publisher,
  canonical profile paths, normal forced profile reload and existing disarm
  methods. It never deletes the shared recovery snapshot or starts drawing.

## Verification and limits

The initial P+B set passed10 tests; parent independently repeated it successfully.
P plus management/legacy portability/isolation checks passed45 tests. B+C plus
related timer, policy and planning checks passed44 tests. These suites overlap;
their counts must not be added as unique tests.

The new behavior tests run without physical input or GPU requirements. Native
window/input boundaries are mocked; the options, profile publication, planner
policy and draw-worker control flow under test remain actual production code.
No performance claim is made for this batch so far.

Review status: UW801/UW802 and the Unlimited completion independently reviewed by
root; the platform reviewer independently closed UW801–UW805 after 23 new tests.
UW806 source review independently found no other blocker after identifying
one tooltip-focus integration gap. That route is corrected with portable and
native regressions; root reran the actual ToolTip and selector/button suite.
The focused combined selection passed 26 tests with five Windows-only skips.
Full native delivery remains a Windows CI gate.
