# Batch 21 — actual profile calibration warnings

This completes the existing Step 19 profile guidance and UI10/UI11 metadata contracts. **Zero new improvement IDs.** The baseline is `ec22fd8739573adc2df1b3e33dbe1a98a09b9c99` (821 registered improvements).

## Reproduced application gap

`DrawBotApp.options` obtains the real calibration summary as `calibration_state['palette']['state']`. `ProfilePolish.profile_release_warnings` previously read only the older flat `palette_state` or `state` aliases. Its warning therefore disappeared when the actual Setup wizard passed the current summary. The options builder also created `profile_polish_meta` before obtaining calibration evidence and left that earlier warning list unchanged.

The before probe used the actual options builder, a private empty Skribbl profile and a real `Colors.save_calibration(state='verified')` control. An estimated palette produced no “Palette is not verified” warning in either options metadata or the public wizard formatter, although the equivalent older flat input did. The verified control correctly required no such warning.

The five permanent regression methods reproduced ten failures before the fix, including all six actual Microsoft Paint, Skribbl and generic profile combinations under Auto and Manual policy. The actual `show_beginner_setup_wizard` method also failed its missing-evidence assertion; only native widget construction and geometry are substituted in that test.

## Completion

`ProfilePolish` now accepts the nested palette mapping while preserving the original flat aliases' priority. Explicitly supplied empty calibration evidence still prevents fallback to an older options summary. Existing verified/calibrated behavior, standard profile guidance, malformed-input handling and input immutability remain covered.

After the actual calibration summary is available, `DrawBotApp.options` refreshes only the warning list in its already resolved profile metadata. The profile policy still runs exactly once. Renderer, budget, defaults, changed-setting metadata and native input authorization are unchanged.

## Validation

- `test_v148_application_batch21_profile_warnings.py`: five new methods, covering the actual options/wizard consumers, three profiles under both policies, verified evidence, fresh later reads, previous-result isolation, legacy precedence, explicit empty evidence and Mapping inputs.
- Combined new and adjacent profile/UI/color-ceiling gate: **51 tests passed in 1.961 seconds**, zero skips.
- `git diff --check` passed for the changed helper and new regression file.
- Independent peer review of the helper, actual options handoff and all five new methods closed without blockers. The five methods also passed in the reviewer's separate 12-test gate (0.701 seconds; the other seven cases concerned the parallel Undo review).
- No timing or performance improvement is claimed.

The change does not alter palette verification or its drawing gates. It makes the existing guidance consume the evidence that those helpers already produce.
