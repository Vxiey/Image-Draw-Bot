# v1.0.148 color quality and analysis — batch 03

This ledger records **16 distinct behavior improvements** against
`2fb7abf470a4ef498df9c53f42cddda62d8b652b`. Tests, helper extraction, documentation,
integration call sites and completion of previously counted changes do not add
IDs. Production changes passed independent review and are frozen for whole-program
integration. This is a development checkpoint, not a release or an antivirus
verdict.

Regression modules: [color correctness](../test_v148_colour_batch03.py),
[CPU analysis and Stop](../test_v148_colour_batch03_analysis.py), and
[picture palette transactions](../test_v148_colour_batch03_picture.py).

## Counted behavior changes

| ID | Before | New behavior and code | Regression/evidence |
| --- | --- | --- | --- |
| CQ01 | Hex channel parsing accepted signs through `int(..., 16)`, producing negative RGB or values above 255; malformed prefixed values could become named colors. | `Colors` and `NamedColorIntelligence` require ASCII hexadecimal digits in explicit hex literals, preserving legacy AARRGGBB and supported underscore separators. | `test_hex_channels_never_accept_signs_or_non_ascii_digits`; includes `#-10000`, malformed ARGB and valid legacy input. |
| CQ02 | `rgb (17,34,51)` and whitespace variants were diverted to the bare comma-list parser despite being supported by the functional parser. | `Colors.normalize_rgb` dispatches RGB/RGBA/ARGB syntax with whitespace before the opening parenthesis. | `test_functional_colors_accept_whitespace_before_parenthesis`. |
| CQ03 | An otherwise correct preview with an extra unrelated contour could retain 100% edge accuracy because only source edges were scored. | `AccuracyEvaluator` scores the union of source and preview edge locations, penalizing missing and unexpected contours. | `test_extra_contours_cannot_keep_perfect_edge_accuracy`; unchanged image remains 100%. |
| CQ04 | Combining disjoint 3% regions still reported approximately 3% coverage, incorrectly protecting merged large regions as tiny details. | `RegionAwareQuantization._weighted_stats` adds disjoint quantizer coverage while preserving weighted averages for other properties. | `test_merged_region_coverage_is_additive`; two 3% regions become 6% and no longer receive the tiny-detail conflict flag. |
| CQ05 | Skipped white source pixels consumed the quantizer/color budget, could contaminate retained colors and inflated mapped-pixel diagnostics; merged RGB could also turn drawable pixels into skipped white. | `DynamicColors` determines the source drawable mask before quantization, quantizes only that mass and uses it for region measurements, adjacency, coverage and runs. White skipping is independent of merged/rendered RGB. | Source-white budget, source-whiteness-before-merge, ignored-background adjacency and empty-source tests. A nine-white/one-red fixture retains red in a one-color budget and reports one mapped pixel. |
| CQ06 | Horizontal-run construction executed a Python state machine for every pixel, including background. | `DynamicColors._groups_from_labels` uses row-sized lookup/difference arrays and visits only run boundaries; dot output remains supported. | Independent scalar pixel-walk oracle across holes, repeated labels, dots and one-pixel images; paired CPU timing. |
| CQ07 | Stop requested during read-only source-color analysis could still allow later region statistics, adaptive-count search or final named-color diagnostics to publish success. | `DynamicColors`, `RegionAwareQuantization` and `AdaptiveColorCount` check Stop after costly stages and before results, and pass it into their bounded search work. | Late diagnostic Stop returns no plan; Stop after conversion cannot publish an empty plan; Stop after contrast skips histograms; Stop after adaptive edge analysis prevents the curve. Backend interruption propagation itself is an existing-group completion, below. |
| CQ08 | Floor-step/prefix sampling excluded late source pixels and the high end of sorted candidate RGB values, even when an exact desired source color existed. | `ExactColorEngine._nearest_actual` checks exact matches in bounded strips and spreads approximate sampling across the entire source/candidate range. | Exact desired RGB at position 15,999 and a near-white match beyond the old 2,048-candidate prefix. This is a representative-quality correction, not a speedup claim. |
| CQ09 | Cost-only palette/shadow decisions also computed CIEDE2000 diagnostics for every candidate. | `ExactColorEngine.candidate_cost` shares the same scoring components without computing unused diagnostics; `DynamicColors` and `ShadowToneMapper` consume it. Full diagnostic scoring remains available. | All fidelity-mode costs/winners match the full scorer, while a failing CIEDE2000 stub proves the cost-only path does not call it; paired CPU timing. |
| CQ10 | Every previously unseen named-color query repeatedly normalized and compared each static vocabulary entry in Python. | `NamedColorIntelligence` caches an immutable numeric vocabulary and computes the distance vector once, preserving deterministic row/tie order and exact extended aliases. | Scalar vocabulary oracle for random/exact colors in CSS and extended modes; identical displayed distances; paired uncached-query timing. |
| CQ11 | An empty mapping with zero measured pixels was labeled “Excellent.” | `ColorFidelity.finalize_mapping_stats` marks no-evidence results “Unavailable” with `evaluated=False`; valid evaluated results retain their metrics. | `test_no_mapping_measurements_are_not_rated_excellent`. |
| CQ12 | Different source clusters mapped to the same identical palette action produced repeated selection phases and separately split adjacent runs. | `DynamicColors` coalesces only actions with the same rendered RGB, selection kind/index and exact/fallback contract; coverage is combined while source-cluster diagnostics remain separate. | Two source colors mapped to black become one full run/phase with all pixels counted; differing exact-selection contracts remain separate. |
| CQ13 | Picture palette preparation constructed complete stroke geometry it never used and evaluated edge additions even when the custom-color budget was already full. | `build_dynamic_color_palette` returns the same colors/selectors/metadata without groups; `PictureCustomPaletteLegacy` also skips unusable edge augmentation. | Palette-only output equals the full planner's nongeometry output; run-builder and full-budget edge-helper rejection tests; paired analysis timing. These related unused-work eliminations share one ID. |
| CQ14 | CPU visual importance retained a full RGB difference cube and several redundant full-size weighted planes. | `VisualImportanceMap._cpu_map` accumulates channel differences into a 2D plane, reuses normalized edge storage and releases intermediate planes before later work. | Bit-exact unoptimized-formula oracle for random, flat and thin images; complete metadata parity; paired CPU/memory measurements. |
| CQ15 | Edge-color sampling materialized every image RGB tuple, every edge value and all candidate RGB tuples before imposing its 24,000-sample limit. | `PictureCustomPaletteLegacy._edge_detail_colors` uses a compact edge mask/index list and materializes RGB only for the bounded row-major sample. | Independent scalar sampler preserves threshold, order, cap and ranked quantizer output; paired CPU/memory measurements. |
| CQ16 | Regional palette anchors and Smart Color retained a record and two coordinate-list entries per stroke. | `ColorSpatialSummary` streams bounds and cell accumulation in two passes, shared by `AdaptivePaletteFidelity`, `RegionAwareQuantization` and `SmartColorEngine`. Both passes use the same representable geometry records. One-shot iterators retain compatibility through a one-time materialization. | Exact materialized-grid oracle, unchanged anchors/Smart Color diagnostics, overflow-skip compatibility, iterator and empty-input tests. Memory is reduced substantially; the second traversal can cost CPU time and is explicitly reported below. |

## Shared integrations and previous groups: no additional count

- Dynamic fully transparent pixel gaps extend the existing CG04 alpha-exclusion
  contract; CQ05 counts only the separate skip-white-before-quantization error.
- Picture RGB preparation now checks Stop and fresh target/modal ownership before
  each input action, does not send Escape after Stop or to a foreign target,
  verifies callbacks before publication and always disarms. Direct legacy calls
  delegate to the same transaction. This completes RT06/RT07/RT18. Root's ignored
  cancelled `picture_palette_complete` event completes RT44. No physical input
  was used in these tests.
- Picture preparation no longer substitutes an empty calibration fingerprint
  when calibration reading fails. This completes the prior SR20 fail-closed
  calibration-fingerprint contract.
- `AccuracyEvaluator`, `ShadowDetailEngine` and `VisualImportanceMap` use the shared
  corrected thin-image/border gradient. The GPU/platform owner counts this as
  one shared GP behavior, not additional CQ changes.
- Prepared-picture mapping and shadow analysis forward/observe the existing
  PixelMap cancellation callback. The rendering/planning owner counts that shared
  pipeline behavior. Adaptive-count backend interruption now propagates instead
  of falling back, completing CG20 rather than adding another ID.
- Explicit disposal of edge-analysis images and fixtures is part of the existing
  image-ownership work. No separate buffer-cleanup item is counted.

## Reproducible CPU measurements

[Script](../benchmark_v148_colour_quality.py) and
[raw samples](v148-batch03-colour-benchmarks.json) retain five warm-run samples
per side, measured against the checkpoint above where indicated. All inputs are
generated locally and paired outputs are checked before measurement. Timings are
not CI pass/fail thresholds. Measurements use Python 3.12.14, NumPy 2.5.4 and
Pillow 13.0.0 on Linux; they do not measure physical GPU execution, Windows input
or end-to-end drawing. Tracemalloc peaks exclude untracked native/Pillow memory
and are not total process RAM.

| Workload | Before median | After median | Traced allocation peak / output evidence |
| --- | ---: | ---: | --- |
| Importance map, 768 × 512 | 35.68 ms | 25.99 ms | 27.055 → 13.472 MiB; bit-identical map and every metadata field. |
| Edge RGB sampling, 640 × 512 | 73.82 ms | 25.83 ms | 26.555 → 3.032 MiB; identical ranked detail colors. |
| Spatial anchors, 32,768 strokes | 35.56 ms | 75.70 ms | 5.312 → 0.021 MiB; identical anchors. This is a memory improvement with a CPU tradeoff. |
| Smart Color, 32,768 strokes | 55.75 ms | 49.45 ms | 5.401 → 0.109 MiB; identical weights and metadata. Timing varies across runs; this is a memory claim, not a reliable speedup claim. |
| 256 uncached extended-vocabulary color queries | 474.53 ms | 6.11 ms | Same names/RGB; distances agree within 1e-14 relative and displayed precision is unchanged. |
| 512 matching costs | 6.09 ms | 3.95 ms | Identical costs; diagnostic CIEDE2000 computation omitted only where unused. |
| Horizontal color runs, 512 × 384 | 43.80 ms | 30.64 ms | Identical complete groups against a scalar row-walk oracle; peak approximately unchanged at 4.02 MiB. |
| Picture color analysis, 384 × 256 | 74.76 ms | 21.90 ms | Identical colors/selectors/metadata with unused geometry disabled; 8.668 → 8.048 MiB. This pair uses the same current analysis with geometry enabled/disabled to isolate CQ13. |

The importance benchmark uses a repeated horizontal profile with flat outer
neighbors, isolating memory reuse from the separately corrected border-gradient
semantics. Random/thin-image regression oracles separately cover the corrected
gradient. Sampling-quality, skip-white and unexpected-contour fixes intentionally
change old outputs; they are validated by explicit corrected examples rather
than a misleading old/new equality claim.

## Validation and remaining limits

- Related suite: **487 tests, 485 passed, 2 Windows parser tests skipped** on Linux.
  The selection includes 52 existing/new color, palette, preview and planning
  test modules. After independent review corrected two boundary cases, the final
  focused rerun passed **59 tests** and the reviewer independently passed **85
  related tests**, with no remaining concrete blocker found. Earlier broad-run
  counts exclude the final two new cases.
- The **37 new regressions** cover both these changes and shared completions;
  regression count is not an improvement count.
- Exact source sampling adds a bounded-strip scan before approximation; its
  quality gain is established, but no speedup is claimed.
- Streaming summaries save memory for reusable lists/tuples; one-shot iterators
  must still be retained once to preserve their earlier behavior.
- Physical GPU, Windows UI and full application gates belong to the integrated
  checkpoint validation. These CPU measurements are not a hardware compatibility
  or antivirus-clearance claim.

Reproduce the measurements from the repository root:

```sh
../security-venv/bin/python benchmark_v148_colour_quality.py --output docs/v148-batch03-colour-benchmarks.json
```
