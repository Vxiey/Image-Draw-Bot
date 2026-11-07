# Batch 26 — complete shadow guidance lifetime

This completes **RC02 / global 734** and adds **zero improvement IDs**. The
existing [batch 07 contract](v148-batch07-rendering.md) removed unnecessary
copies inside shadow analysis while preserving all guidance formulas and
borrowed inputs. This completion addresses the remaining caller reference
that kept unused returned arrays alive during later PixelMap stages.

The fresh before proof used integration baseline
`5b0c22ac5dc620a911fa2a1f6216e272f644f7db`, with 837 registered groups.
The later `a3b7b929b1332772a089e1819143471ae5d58c68` integration changes only a
prior test fixture and documentation. Only `PixelAccuratePlanner.py` changes
for this completion; `ShadowDetailEngine.py` is unchanged.

## Actual caller evidence

`build_pixel_map` calls the real `analyze_shadow_contours`, which returns eight
array planes plus metadata. The caller consumes `contour_map`, `shadow_map`
and `shadow_detail_map`. Its local `tone` dictionary nevertheless retained all
five other planes through `micro_detail_map`, `importance_map` and
`protect_tiny_features`, including when a later stage raised an exception.

The actual direct caller and complete `DrawBot.make_plan` caller were probed
using real 64×48 input, real shadow analysis and real consumer functions.
Observers retained only weak references and primitive output fingerprints.
Before the correction, all five unused planes were alive at each of the three
consumer entries in both callers:

| Unused returned plane | Dtype | Array payload at 64×48 |
| --- | --- | ---: |
| `luma_map` | float32 | 12,288 B |
| `local_tone_map` | float32 | 12,288 B |
| `contour_mask` | bool | 3,072 B |
| `shadow_detail_mask` | bool | 3,072 B |
| `deep_shadow_mask` | bool | 3,072 B |
| **Total still alive** | | **33,792 B** |

This measures live array contents, equal to 11 bytes per pixel for these five
returned planes. It is **not a total peak-allocation, process RSS or runtime
measurement**. All three consumed planes already had the correct identity,
and the borrowed input image's pixels and metadata were unchanged.

The seven permanent regression methods produced twenty expected assertion
failures across six methods, with the external-owner positive control passing:
seven methods, no test errors, 0.107 s. Failure subcases are not additional
improvements. The raw proof and logs are
`batch26-shadow-guidance-before.json`, `batch26-shadow-guidance-before.log`
and `batch26-shadow-guidance-before-tests.log` in session scratch.

## Minimal ownership change

After the existing post-analysis Stop check, the caller stores references to
the three consumed planes and metadata. A `finally` then drops only its own
`tone` reference before any micro-detail, importance or protection work starts.
The same local references are passed to the existing consumers and returned
PixelMap. The Stop check stays in the same position and the analyzer's formulas,
metadata, dtypes and fallback policy are unchanged.

No dictionary is cleared or mutated. If an external owner retains the returned
analysis mapping, it keeps every key and all eight arrays. Releasing that
external owner then releases the otherwise-unused planes. This distinction
also holds while a real consumer's exception and traceback remain referenced.
On Stop or a callback error immediately after analysis, the private mapping
reference is released during the same unwind.

The ownership observation after the patch finds all five unused planes dead
before all six direct/public consumer boundaries. The three guidance planes
remain alive, are passed by identity and stay owned by the returned PixelMap.
The after probe is `batch26-shadow-guidance-after.json` with its matching log.

## Regression and complete historical parity

`test_v148_rendering_batch26_shadow_ownership.py` has seven methods covering:

- Actual direct creation with opaque, mixed and transparent input, independent
  reference maps, all three real consumer boundaries and exact guidance identity.
- Complete public Pixel-plan output, preview rasters and unchanged source data.
- An intentional external owner that retains every analysis field unchanged.
- Post-analysis Stop and a failing cancellation callback with retained errors.
- Each real later consumer computing its result and then failing, while its
  original exception traceback remains referenced.
- The real public palette-fallback path after a backend failure, retaining
  complete output parity and the same shadow ownership contract.

The new methods plus existing RC02, shadow, cancellation, transparent-fallback
and public Pixel tests passed **40/40 in 0.377 s**, without skips. The log is
`batch26-shadow-guidance-after-tests.log`. Root and an independent rendering
reviewer read the full product diff and all seven methods and closed their
reviews without blockers.

An untimed scratch verifier also loads the **complete historical
PixelAccuratePlanner module** from `5b0c22a` and rebinds its actual consumer
aliases. Both sides use identical current DrawBot and shared dependencies.
It compares **48 complete historical/current caller pairs: 36 direct PixelMaps
and 12 actual public plans**. Cases include singleton axes, ordinary images,
opaque/mixed/empty alpha, Skip-white on/off and genuine palette-backend failure
forcing the existing fallback. All 48 pairs passed; input pixels and metadata
remain unchanged. Every output field remains in parity except the existing
explicit elapsed-planning exclusions. This is not a complete historical
DrawBot pipeline or a performance benchmark.

The final report is `batch26-shadow-historical-parity.json`; its script and
log have the same stem in session scratch. Relevant source identities are:

| Source | SHA-256 |
| --- | --- |
| Complete historical PixelAccuratePlanner, 26,377 bytes | `1c3249101ada653e37e511a87d2536b236c63827f553caa9ea3b6d10d5354562` |
| Current PixelAccuratePlanner | `f5516987640f0f4381cf8df4a52bc65185eb8e77180f07c654ae23e431c4b64c` |
| Unchanged ShadowDetailEngine | `9565c2f04ea08b815533323a56b030b27b355524eaaa0ac710be4efc7f1c3ded` |

The first scratch run passed its 48 strict comparisons but then rejected an
additional cross-process hash assertion for the two earlier public probes.
Those independent probes used different temporary calibration directories;
their plans therefore included different correction-history storage paths at
four diagnostic locations. Two unchanged-current diagnostic runs confirmed
exactly those four differences. The initial failure log is preserved as
`batch26-shadow-historical-parity-initial.log`, together with
`batch26-shadow-current-control-1.json` and `-2.json`.

The final verifier records that context difference instead of claiming those
independent public hashes match. Its twelve historical/current public pairs
share one calibration context and compare those storage paths exactly; no
additional output exclusions were introduced. The separate direct probe
fingerprint matches exactly before and after. Final combined project and
platform gates are recorded by the batch finalizer; no new timing or universal
memory-reduction claim is made here.
