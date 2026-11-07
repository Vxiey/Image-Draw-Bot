# v1.0.148 batch 17 — actual layered-color mapping diagnostics

## R1701 — report the palette pixels produced by the layered planner

**Status:** implemented, focused verification passed, independent root review
closed without blockers. This is one distinct behavior group. The baseline is
`e87bcf1b783b33ff866c2188e10c8b5d22a22707` (the published batch 16 checkpoint).
The global registry and release decision belong to the integrated batch gate.

`AdvancedColor.build_color_strokes` already assigns every drawable source
pixel to its actual primary or secondary palette color. Its diagnostics called
a separate sampler which always chose the nearest single palette swatch. The
resulting tone and color-error fields therefore described a different mapping
from the one shown in the quantized target and delivered to planning.

The real call chain is:

`DrawBot.make_plan → build_color_strokes → advanced_color_meta → planned event
→ DrawBotApp._handle_event → StudioUI's bound summary label`.

The final planner and `PreviewQuality.full_preview_options` both retain the
requested layered policy. The ordinary reduced-detail preview deliberately
disables layering; this change does not alter that preview policy.

## Reproduced before behavior

An 8 × 8 RGBA image of `(90, 90, 90, 255)`, calibrated black/white swatches and
`Layered color mix` / `Full color mix` produces 40 black pixels and 24 white
pixels. Both actual final and full-preview plans already had this exact
quantized target. Nevertheless their mapping diagnostics treated all 64 pixels
as white, and the real bound workspace label displayed those measurements.

| Mapping measurement | Before: nearest white swatch | After: actual Bayer pixels |
| --- | ---: | ---: |
| Measured source lightness | 38.24 | 38.24 |
| Mean mapped lightness | 100.00 | 37.50 |
| Lightness drift | +61.76 | −0.74 |
| Luminance drift | +878.07% | +266.78% |
| Mean ΔE2000 | 48.28 | 34.49 |
| Mean ΔE76 | 61.76 | 47.06 |
| Mean OKLab error | 53.24 | 49.19 |
| Fidelity rating | Very Poor | Very Poor |

The visible summary changes from `ΔE00 48.3 · luminance +878%` to
`ΔE00 34.5 · luminance +267%`. The image has not become more accurate; the
diagnostics now measure its existing emitted colors. Main visual accuracy,
the preview raster, palette selection and native drawing behavior are retained.

The initial five regression methods reproduced **44 failing subcases**. The
separate actual-label baseline reproduced both final/full-preview display
failures before the product patch. There were no fixture errors.

## Implementation and sampling limits

The builder passes its effective layer mode to the diagnostic sampler. For an
active layered policy, the sampler uses the same cached primary/secondary
choice and the actual source `(x, y)` Bayer phase, then applies the existing
color metrics to the selected real palette RGB. It never substitutes an
idealized mixed or averaged RGB for the emitted pixel.

Changing only the selected RGB would leave a second error: the old regular
stride can alias the four-by-four Bayer matrix. For a uniform 128 × 96 image,
the old stride is four and visits only one matrix phase. Layered diagnostics
now visit complete, evenly spaced four-by-four cells instead. The 768-pixel
budget covers 48 complete cells in this fixture: **480 actual black samples and
288 actual white samples**, matching the full raster's 10:6 phase ratio.

Small images within the budget are measured completely. Larger images remain a
bounded deterministic sample, not an exact measurement of all source pixels.
Partial edge cells contribute only their in-bounds pixels. Transparent and
source-white-skipped sites do not contribute color evidence, so the reported
sample count can be below 768. An empty sample remains `Unavailable` with
`evaluated=False`. Budgets smaller than one whole cell cannot represent all
Bayer phases; production continues to use the existing 768-pixel budget.

The old coordinate selection and nearest-swatch metrics remain unchanged for
nonlayered matching and for `RGB nearest`, including its layer-enabled setting
which intentionally does not create a second color. The existing post-sampling
Stop check still discards a cancelled plan. No drawing, verification, clipping,
brush, quality or resource guard was changed.

## Regression evidence

`test_v148_rendering_batch17_layered_diagnostics.py` contains nine methods:

- An independent rasterizer checks exactly one owner per drawable source pixel
  across both palette orders, dots/runs, white skipping and every layer mode,
  including the effective `Off → Dual-color mix` behavior.
- A literal independent Bayer matrix verifies the full 128 × 96 raster and the
  exact 480:288 sample split that the old stride-four audit missed.
- Real ThreadPool workers use chunks whose starting rows have different Bayer
  phases; their complete groups and published diagnostics match serial output.
- Nonlayered modes retain the previous sampled metrics on seeded RGBA data.
- Partial edge cells, transparency, semitransparent compositing and source white
  skipping are compared against actual independently rasterized palette pixels.
- Real calibrated custom swatches cover every existing custom-color workflow,
  including `Custom colors only`, with colored and semitransparent sources.
- Zero-evidence results, source-image immutability, Stop during measurement,
  bounded/unique coordinates and thin or partial image shapes are checked.
- Real final and full-preview `make_plan` results pass through the actual
  `planned` handler and the actual Studio label factory bound to a Tcl variable;
  both the underlying metadata and displayed text must match the raster oracle.

The final focused command passed **41 tests in 1.744 seconds**:

```sh
.venv/bin/python -m unittest \
  test_v148_rendering_batch17_layered_diagnostics \
  test_advanced_color_v108 test_advanced_color_matching_v109 \
  test_color_fidelity_v10120 test_v148_planning_batch04_color -q
```

Root independently read the product diff and raster oracles, then passed a
43-test integration scope including all nine new methods in 2.741 seconds.
These durations describe verification runs, not application speedups.

## Complete historical parity

The import-safe manual verifier is reproducible from the checkout:

```sh
.venv/bin/python verify_v148_rendering_batch17_layered.py
```

It loads the complete historical `AdvancedColor.py` from the baseline commit,
then compares it with the current module on 160 serial build pairs covering
both palette orders, all four fidelity policies, five layered-policy settings,
dots/runs and skip-white. Two additional full-image pairs use serial and real
ThreadPool planning. All groups and other builder metadata are identical.

Four paired real public plans cover two source sizes, final/full-preview modes
and a 96 × 64 canvas. Every returned field and image is compared, excluding
only the deliberately corrected `color_fidelity_diagnostics` and measured
planning-profiler fields. This retains exact selectors, groups, path order,
execution sequences, counts, physical planning, target/preview/diagnostic image
bytes, guards, estimates and remaining metadata. Resource probes are fixed
equally for both sides; original source bytes are preserved.

Raw evidence is in `v148-batch17-layered-diagnostics-evidence.json`. Per-plan
digests bind the paired run, including its temporary calibration context; they
are not cross-machine golden hashes. The verifier checks that the current
AdvancedColor source hash is unchanged during the comparison.

- Historical AdvancedColor SHA256:
  `bcb333361ea65d39438b87040047a98e2febf0b4af6f32b3d64fa49fb0651c9a`.
- Current AdvancedColor SHA256:
  `922d8ffef1c02f12f3cc0a7341037506f822babb12f416ffecc182a7ed7c16b6`.
- Final evidence JSON SHA256:
  `6366f95431eb63e5a0dabed97ed90690b128b3086b25253de19b2e72a2a12c4a`.

## Deduplication

- **PB02** already corrected overlapping primary/secondary raster ownership.
  R1701 leaves that corrected raster intact and fixes the independent metadata
  sampler and its visible consumer.
- **CQ05** addressed skip-white before quantization and palette budgeting in
  `DynamicColors`. R1701 preserves skip behavior and reports only the selected
  real layered colors.
- **CQ11** established `Unavailable` when no measurements exist. That invariant
  remains unchanged and has a regression here.
- **RP03** remapped browser renderers and their diagnostics after final palette
  eviction. This change does not alter a palette or browser remapping; it fixes
  ordered spatial layer selection in AdvancedColor's sampled evidence.

The layer selector and phase-aware sampling together complete one truthful
mapping-diagnostics contract, so this is **one verified R1701 group**, not a
separate count for each mode, test, sample size or UI label. No speed, memory,
visual-accuracy uplift, GPU result or Windows-native result is claimed.
