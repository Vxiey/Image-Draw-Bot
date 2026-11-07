# Batch 22 — bounded Paint spectrum search

Initial reproduction: `ec22fd8739573adc2df1b3e33dbe1a98a09b9c99`.
Final paired baseline: `be30fa54a0c58a8d2b6535d31cb6672727f4e6cc`.

## N2201: remove per-pixel Python work without changing the chosen color

The actual custom-color spectrum search called Pillow `getpixel` and evaluated
the floating-point RGB metric separately for every sampled point. The shipped
720 × 393 screenshot required 31,521 such calls; a 1,600 × 1,000 crop required
64,169. Selecting many custom colors repeats this work, sometimes twice per
color when the brightness slider is used.

`ScreenGuard.GuardedMouse.calibrated_modal_nearest_color_rect` now evaluates
the same coarse sample grid in small NumPy strips. The same refinement grid
then surrounds the same coarse winner. Byte RGB distances use exact integer
weights 30/59/11 to find candidate colors. The original floating-point metric
still decides every distinct minimum candidate in its first row-major order.
This preserves even the rounding-sensitive ties and the existing coarse
winner's priority during refinement. Fields/refinements of at most 256 samples
keep the scalar path; legacy non-byte targets also keep that behavior.

Native crops have at most 64 rows and numeric batches at most 16,384 samples.
The integer score is bounded by 6,502,500, inside signed 32-bit arithmetic.
Private crops close and exported arrays are cleared on failure as well as
completion. If an optional numeric allocation fails, the arrays are released
before the original constant-space scalar search resumes. Its strict ordering
also preserves a winner from already processed strips. The existing capture
limits, physical coordinates, modal ownership
checks, selected-color validation, click guards, UI delays and brightness
search remain unchanged. No cache survives an operation.

This is **one behavior improvement**. Its tests, scalar control, tie handling,
memory bounds and documentation are not additional IDs.

## Reproduction and independent review

`test_v148_native_batch22_spectrum.py` uses shipped screenshots and numeric RGB records, with
the read-only desktop-capture boundary substituted. It compares complete
coordinates, RGB values and exact scalar errors against the historical coarse
and refinement algorithm. It covers reversed bounds, negative monitor offsets,
sample budgets, tiny controls, invalid modal ownership and retained exceptions.

The work-count regression fails on the historical module with **31,522 reads**
against a bound of 256, while still returning the same result. That count
includes the test's final check that its capture was closed. The benchmark
counts below exclude that assertion read. All seven final methods pass.

Independent review verified 370 further numeric cases, including narrow grids,
offsets, strides 1–2,000, retained coarse winners and mathematical ties whose
floating-point errors differ. One such pair is retained as a permanent numeric
regression, with 3,672 samples and both candidate orders within/across strips:

| Expected RGB | Candidate RGB | Integer score | Original scalar error |
| --- | --- | ---: | ---: |
| (100, 100, 100) | (100, 101, 136) | 14315 | 11.964530914331744 |
| (100, 100, 100) | (100, 112, 123) | 14315 | 11.964530914331743 |

No new image file is created, rendered or displayed by these regressions.
The seven-method final module includes first/third-strip allocation failure and
exact scalar recovery. Independent review checked 18 more interrupted numeric
searches with both rounding-sensitive color orders and different coarse seeds;
every result matched the original scalar oracle, including failure after a
partial minimum had already been selected. Non-memory exceptions still
propagate through the existing error handling.
Independent source, numeric-parity and ownership review is closed without a
blocker. The prior related spectrum, modal input and color-recovery selection
passed 51 tests; the permanent tie method was then verified with the earlier
17-test spectrum/UI selection (16 passed, one display-dependent skip).

## Measured CPU work and its memory cost

[Raw measurements](v148-batch22-spectrum-benchmarks.json) compare against the
integrated `be30fa54` baseline and bind the final source
and test hashes. Each workload has six balanced AB/BA timing pairs, a warm
comparison, independent work counting and separate allocation tracing. Every
invocation compares the entire returned coordinate/RGB/error tuple. Source
pixels and relevant source hashes remain unchanged.

| Existing raster workload | Before median | After median | Before / after `getpixel` calls | After traced peak |
| --- | ---: | ---: | ---: | ---: |
| Application screenshot, 720 × 393 | 30.449 ms | 1.427 ms | 31,521 / 81 | 512,220 bytes |
| Application screenshot crop, 1,600 × 1,000 | 61.587 ms | 3.895 ms | 64,169 / 169 | 901,262 bytes |
| Paint reference, 76 × 76 | 5.211 ms | 0.456 ms | 5,801 / 25 | 184,341 bytes |
| Tiny scalar control, 8 × 8 | 0.316 ms | 0.278 ms | 76 / 76 | 29,116 bytes |

All six pairs improve for each of the three numeric-strip workloads. The
unchanged scalar control measures lower in 5 of six pairs, but it performs
the same scalar work; no general tiny-field speedup is claimed. The old traced peak is 29,116 bytes for each workload.
The new numeric strips deliberately add bounded scratch memory, with a maximum
observed traced peak below 0.9 MiB. This is not a memory-saving claim.

These are complete Python spectrum-search calls, including capture-copy
ownership and read-only geometry checks at substituted native boundaries.
They do not measure screen-capture latency, Paint responsiveness, physical GPU
performance or total drawing time. Tracemalloc excludes most native Pillow
cores and process RSS. Reproduce from the baseline-containing checkout with:

```sh
.venv/bin/python benchmark_v148_spectrum.py --output docs/v148-batch22-spectrum-benchmarks.json
```

Whole-project regressions and the published commit's Windows/package checks
are recorded separately in the integration report and PR46. Version 1.0.148
remains under development.

Integration note: this batch was rebased onto concurrent checkpoint
`92d5a86709a61802821780f5866409da6cd8cf2e` (823 improvements).
The initial reproductions above used `ec22fd8`; final validation and paired
measurements use the integrated source and are recorded separately.
