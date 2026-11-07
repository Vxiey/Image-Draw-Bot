# Batch 17 — restore legacy tests to the actual unittest gate

This maintenance earns **zero improvement IDs**. It makes existing behavioral
coverage run under the repository's `python -m unittest discover` gate.

An AST audit found three older modules whose free `test_*` functions were never
discovered by unittest: four layout-fingerprint tests, five real-speed-budget
tests, and six safe-fill-mask tests. They are now `unittest.TestCase` methods.
Their temporary directory fixture has the same per-test lifetime through
`TemporaryDirectory` plus `addCleanup`. Existing inputs and assertions remain,
apart from the two documented historical expectations below.

The safe-fill version assertion still named release 1.0.124; it now verifies the
current 1.0.148 development metadata. This does not change the application
version or create a release.

The palette test expected an unconditional black slot, a policy superseded by
the existing dominant-hue-family reducer. The original five-color input now
checks its exact retained green/blue/yellow slots and a complete multiset of all
original stroke geometry. A second input with two red shades checks that a
fourth slot preserves black after all three chromatic families are represented;
the three-slot control still has exactly those three families. The production
palette selection policy was not changed to satisfy the stale test.

Before the oracle correction, activating all 15 existing tests produced 14
passes and that one historical-policy failure. After correction, the 15 tests
and all five existing dominant-hue-family tests passed: **20 tests, 0 skips,
0.049 s**. The independent maintenance review checked the original test bodies,
temporary-directory lifetime and the current palette policy before the
expectation was updated.

Command:

```sh
python -m unittest test_layout_fingerprint_v1076 test_real_speed_budget_v1077 test_safe_fill_mask_v1052 test_step3_dominant_hue_preservation_v10127 -v
```

The two existing Hypothesis properties also now enter the unittest gate; their
unchanged generators and 1,000-example settings are recorded separately in
`v148-batch17-dependency-maintenance.md`. These discovery repairs add no product
behavior claim and no new count toward the 1,000-improvement target.

## Source-package cache completion

The first complete gate passed 3,985 tests, but the real release inventory then
contained 1,390 files. Inspection identified **248 generated Hypothesis
example/constant cache files** among those source-archive entries. The existing
cache exclusions omitted `.hypothesis` because these properties had not been
part of the ordinary gate. This completes the existing source-archive exclusion
and case-insensitive privacy contract; it adds no improvement ID.

`.hypothesis` now uses the same case-insensitive directory pruning and nonfatal
validation policy as the other test caches. The project ignore list also names
it explicitly. The real ZIP privacy regression was extended with root, nested
and mixed-case cache paths, while retaining an ordinary committed
`tests/fixtures/hypothesis/example.json`. All three new exclusion assertions
failed before the correction and passed afterward. The ten adjacent privacy,
inventory and historical-maintenance archive tests passed in **0.054 s**, with
no skips. The actual source inventory fell from 1,390 to **1,142 files**, exactly
those 248 generated cache entries; the inventory remains clean.

Independent source review closed without blockers. The initial successful
whole-suite run is kept as pre-completion evidence; the final source-hash-bound
whole-suite and package gates are rerun after this correction and recorded in
`v148-batch17-validation.json`. Final documentation files can increase the final
inventory count; they do not reintroduce generated cache contents.
