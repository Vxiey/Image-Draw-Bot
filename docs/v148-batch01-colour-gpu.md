# v1.0.148 development batch 01: color, image and GPU work

This batch contains **40 additional behavior or performance improvements**, with
local IDs **CG01–CG40**. The comparison baseline is commit
`94a748ec7690eebb542c70311c594aa835434a98`. The original 100 improvements remain
in place. Documentation, version edits, test cases and formatting are not counted
as improvements. Related validation checks and related pair-comparison reuse
are grouped into single entries.

## Implementation ledger

| ID | Previous behavior | New behavior and implementation | Regression evidence |
| --- | --- | --- | --- |
| CG01 | A cached numeric, spectrum or eyedropper method could be selected after its required controls, keyboard backend or sample became unavailable. | `AdaptiveColor.method_candidates` rechecks each cached method's prerequisites and the exact-color constraint. | `test_v148_color_correctness.ColorCorrectnessTests.test_cached_color_method_still_requires_its_controls` |
| CG02 | Creating a tiny probe copied an entire smart path and another slice before using its first distinct segment. | `AdaptiveColor.probe_item` consumes only the necessary prefix, retaining the same bounded probe geometry. | A generator raises if the unused tail is read: `test_probe_consumes_only_first_distinct_segment`. |
| CG03 | Worker palette matching used the global palette's length rather than the supplied palette. An exact match at index 23 could be ignored when the global palette contained 18 colors. | `AdvancedColor._candidate_indices` accepts the actual supplied palette size; cached matching and layering use it. | `test_worker_uses_entire_supplied_palette` verifies exact selection and a worker run beyond the global palette length. |
| CG04 | With Skip white disabled, CPU color planning turned fully transparent source pixels into white strokes. The accelerated path already left them undrawn. | Serial and worker `AdvancedColor` paths exclude alpha-zero pixels, break runs at transparent gaps and exclude them from mapping diagnostics. | `test_transparent_pixels_break_cpu_runs_when_white_is_enabled` checks serial/worker agreement and the gap. |
| CG05 | Scalar RGB-nearest matching still applied perceptual fidelity penalties, so it could disagree with the universal CPU/CUDA/OpenCL score definition. | `ColorFidelity.palette_match_cost` uses RGB distance alone for RGB-nearest mode. Perceptual modes retain their fidelity terms. | Thirty generated source colors across all fidelity settings agree with an independent squared-RGB reference and the vector scorer. |
| CG06 | Serial color planning rebuilt the same palette and names for every pixel. | `AdvancedColor.build_color_strokes` keeps one palette snapshot and calls the existing bounded caches directly; diagnostics use that same snapshot. | `test_serial_mapping_uses_one_palette_snapshot`; exact old/new groups and metadata in the CPU benchmark. |
| CG07 | Basic serial planning unpacked four channels directly from the supplied image and crashed on ordinary RGB, grayscale and palette-mode images. | `PixelData.build_strokes` normalizes decoded input to RGBA before either planning path. | `test_basic_strokes_normalize_decoded_image_modes` compares each mode with its explicit RGBA equivalent. |
| CG08 | Rounding both fitted dimensions upward could exceed `prepare_image`'s hard pixel budget, including on thin panoramas. | `PixelData.prepare_image` applies the integer budget after rounding while retaining positive dimensions and the original fitted geometry. | `test_rounded_preparation_never_exceeds_pixel_budget` covers rectangular and thin images with budgets from 1 to 157 pixels. |
| CG09 | Standard image preparation could continue converting/resizing an already cancelled image or return a result after Stop arrived during resize. | `PixelData.prepare_image` checks cancellation before image work and after either resize path. | `test_preparation_checks_cancellation_before_and_after_resize`. |
| CG10 | Reloading `palette.json` changed RGB values but left the nearest-color cache keyed to the previous palette. | `Colors.load_palette` clears the cache after successful complete validation and publication. | `test_reloading_palette_invalidates_nearest_color_cache` swaps black and white and verifies the new winning index. |
| CG11 | Accuracy evaluation flattened source transparency but discarded preview alpha, treating hidden black pixels as visible black. A same-size cached source in grayscale/RGBA could also fail shape validation. | `AccuracyEvaluator.evaluate_preview` normalizes both visible buffers consistently, including a supplied cached source. | `test_preview_and_cached_source_are_compared_as_visible_rgb` verifies transparent white and grayscale inputs. |
| CG12 | Importance maps were quantized to 8 bits even at their original size. A value of 0.62 became approximately 0.6196 and fell below the important-feature threshold. | `AccuracyEvaluator._importance_weights` preserves float values and uses float-image interpolation only when resizing; nonfinite maps are rejected. | `test_importance_keeps_fractional_values_at_protection_threshold` checks exact same-size values and a float interpolation reference. |
| CG13 | NaN coverage could be clamped into a displayed 100% score; nonfinite execution scores had the same problem. | `AccuracyEvaluator.evaluate_preview` requires finite optional percentages before expensive work. Valid finite values retain the existing 0–100 clamping. | `test_nonfinite_percentage_cannot_be_reported_as_perfect_accuracy`. |
| CG14 | Stop arriving during late summary/heatmap work did not prevent publication of the completed accuracy result. | `AccuracyEvaluator.evaluate_preview` checks cancellation at its completion boundary. | `test_finished_accuracy_result_is_not_returned_after_stop` injects Stop during summary calculation. |
| CG15 | The delta-error heatmap retained a full RGB float staging image before copying it into RGB bytes. | `AccuracyEvaluator._delta_e_preview` writes each interpolation band directly into the byte output, preserving the color ramp. | Color-stop/clipping regression and byte-for-byte old/new benchmark comparison; measured peak allocation below. |
| CG16 | General numeric RGB APIs inferred scale only from the brightest value, interpreting integer RGB(1,1,1) as normalized white. | `UniversalGpuAcceleration._rgb01` treats integer arrays as byte RGB, preserves normalized floating input, and rejects nonfinite channels before dispatch. `oklab_array` and `perceptual_pair` retain the original dtype until normalization. | Integer/normalized-float comparisons against scalar OKLab; nonfinite input cannot dispatch or quarantine a backend. |
| CG17 | An empty pairwise palette produced an indexing exception. | `UniversalGpuAcceleration.pairwise_oklab_distance` returns a float32 0×0 matrix without requesting a compute backend. | `test_empty_distance_matrix_needs_no_compute_backend`. |
| CG18 | Forced-CUDA routing could crash on malformed stored throughput or select infinite/nonpositive benchmark values. | `UniversalGpuAcceleration.select_route` checks the score collection, finite positive rates/timings and usable device IDs before ranking verified CUDA candidates. | `test_forced_cuda_ignores_invalid_scores_and_selects_verified_candidate`. |
| CG19 | Negative OpenCL indices selected devices from the end of Python lists; malformed CUDA IDs could silently become device zero. | Shared backend-ID parsing requires the correct backend and nonnegative ASCII integer indices. Invalid stored routes select CPU. | `test_invalid_backend_indices_never_select_python_negative_index`. |
| CG20 | Several numeric GPU paths caught cancellation as a backend failure and retried on CPU. Completed work could also escape a late Stop, and the advanced color caller did not forward its callback. | `UniversalGpuAcceleration` propagates `InterruptedError` without quarantine and checks completion; `AdvancedColor` forwards the callback and discards cancelled accelerated results without retrying. | Backend-interruption, late CPU result and advanced-planner callback regressions in `test_v148_gpu_numeric`. |
| CG21 | Backend-health mutation and snapshot iteration were unsynchronized. | `UniversalGpuAcceleration` protects health reads/writes with a dedicated lock, separate from potentially slow OpenCL context creation. | A real reader thread waits for a coherent two-entry health update in `test_health_snapshot_waits_for_coherent_mutation`. |
| CG22 | CPU palette matching repeated OKLab/features for each tile pair and allocated a pixel×palette×RGB difference cube. | `UniversalGpuAcceleration` reuses palette and source-tile features and accumulates three distance channels into bounded 2D buffers. Pixel and palette tile limits remain in force. | Exact dense-distance comparison, dense palette winner/tie comparisons, transform-call bound and existing CPU/C++ kernel-reference regressions. |
| CG23 | Picture-palette cache loading read the entire file and allowed parser recursion failures to escape. | `PictureCustomPaletteLegacy.load_cached_palette` reads at most 1 MiB plus one sentinel byte and treats oversized, deeply nested and unreadable cache data as misses. | `test_oversized_or_deep_cache_is_a_miss` verifies oversized data never reaches the JSON parser. |
| CG24 | Cache validation coerced invalid schema/dimensions/RGB values, accepted inconsistent color groups, and converted nonfinite coverage into plausible values. | Picture-cache payload validation requires supported exact metadata types, valid RGB bytes, bounded unique complete groups, and matching finite coverage values. These related payload checks count as one improvement. | Four payload-integrity tests in `test_v148_picture_palette_cache` cover metadata, RGB, groups and coverage. |
| CG25 | Saving an invalid palette could replace an existing valid cache with data that should never be trusted. | `PictureCustomPaletteLegacy.save_palette` validates before atomic publication and serializes strict JSON. | `test_invalid_save_keeps_previous_valid_cache` confirms the previous bytes and reusable palette survive a rejected save. |
| CG26 | The image cache key hashed a 512-pixel thumbnail, so visible source edits could disappear during resampling and reuse an old palette. | `image_fingerprint` hashes all visible pixels in row strips, preserving original dimensions and avoiding a full extra image buffer. | A 1024×1024 single-channel edit reproduces the old thumbnail collision; streamed RGBA hashing matches an independent full visible-pixel digest. |
| CG27 | A cancelled palette request could still hash the image, return a cache hit or continue edge-color sampling. | Picture-palette preparation, fingerprint strips, cache-hit return and completion paths honor the callback. | Tests cancel before hashing, during a strip and while returning an existing cache entry. |
| CG28 | Failure to access or write the optional cache could prevent a valid in-memory picture palette from being used; lookup also created an empty directory. | Cache lookup is read-only and tolerates I/O failure; preparation returns its completed palette if optional persistence is unavailable. Explicit `save_palette` still reports write failures. | `test_optional_cache_failure_keeps_computed_palette_usable` and `test_cache_lookup_does_not_create_empty_directories`. |
| CG29 | Already-opaque RGB images were converted through RGBA, and analysis helpers copied newly owned RGB images again. | `ColorMatchingEngine.visible_rgb_image`, `AccuracyEvaluator.normalize_source`, `PictureCustomPaletteLegacy` and `AdaptiveColorCount` avoid those redundant copies while returning independently owned visible pixels. | Ownership/transparency regression; opaque 1920×1080 old/new pixel comparison and timing. |
| CG30 | Region measurement scanned the full label image separately for every color. | `ColorMatchingEngine.measure_quantized_regions` groups labels once with a stable ordering and measures each indexed region; opaque RGB inputs need no separate alpha plane. | Independent-mask comparison includes regions exceeding the representative sampler's size; 64-label benchmark isolates grouping from statistics. |
| CG31 | Region measurement computed median and low/high percentiles in separate passes. | `ColorMatchingEngine` and `ExactColorEngine` request the relevant order statistics together. | Separate NumPy mean/median/percentile references match the combined results; measured 100,000-pixel statistics timing. |
| CG32 | Source-backed representative selection repeatedly normalized the same target and computed Python scalar distances for every candidate. | `ExactColorEngine._nearest_actual` reuses canonical cached OKLab coordinates and reduces the distance vector once, retaining real source candidates and existing sampling/tie order. | Thirty generated candidate sets agree with the scalar perceptual winner, including exact source matches; 2,000-candidate benchmark. |
| CG33 | Adaptive selection could keep two colors despite an explicit one-color maximum. | `AdaptivePaletteFidelity.select_adaptive_palette` honors a positive limit of one and rejects nonpositive limits. | `test_explicit_single_color_budget_is_authoritative` checks retained colors, mapping and metadata. |
| CG34 | Adaptive palette analysis repeated symmetric CIEDE2000 comparisons and recomputed the same candidate pair costs across trials. | `SmartColorEngine` evaluates each unordered pair once; `AdaptivePaletteFidelity` keeps call-local comparison caches. These related pair-work reductions count as one improvement. | Mapping/tie parity with uncached trials, unordered-pair call bound and old/new Smart Color weight/metadata comparison. |
| CG35 | GPU importance normalization lacked the CPU fallback for collapsed percentile ranges, yielding different sparse/flat maps. | `VisualImportanceMap._normalize_gpu` uses the same finite-range and sparse-map fallback. | NumPy-backed evaluation of the GPU formula matches the CPU formula on constant, zero, sparse and random maps. This is formula coverage, not a physical-GPU claim. |
| CG36 | Importance analysis read hidden RGB values from transparent pixels, creating detail that the user would not see. | `VisualImportanceMap.build_importance_map` measures composited visible RGB. | `test_transparent_hidden_colors_do_not_create_importance` compares transparent source data with its visible equivalent. |
| CG37 | A 128 MiB floor could override a small explicit importance-map VRAM budget, and malformed budget values could abort analysis. | Importance-map dispatch respects the explicit positive budget and selects CPU for invalid/nonfinite budgets. | `test_small_or_invalid_vram_budget_does_not_dispatch_gpu` verifies CPU output and no GPU call. |
| CG38 | Importance analysis could return a CPU/GPU result after Stop; a GPU interruption could be swallowed as ordinary fallback. | `VisualImportanceMap` checks completion and propagates cancellation directly. | `test_stop_during_cpu_or_gpu_map_never_publishes_result`. |
| CG39 | Preset swatch detection retained a tuple for every component pixel solely to calculate its size and bounding box later. | `PaletteMaps.detect_preset` updates count/bounds during traversal and retains only the traversal stack. | Exact swatch positions and ambiguity rejection remain covered; large rejected-background fixture measures memory and time. |
| CG40 | Every refinement-quality check expanded weighted color errors back into one entry per sampled pixel. | `PicturePaletteRefinement._weighted_tail_error` locates weighted p95 order statistics without expansion and retains NumPy's interpolation/dtype rules. | Fifty generated weighted fixtures and the all-unit-weight case equal the expanded percentile exactly. |

## CPU and allocation measurements

Measurements used Python **3.12.14**, NumPy **2.5.4**, generated deterministic
fixtures and the NumPy/CPU path. Baseline modules were read from the commit
above, before any batch edits. Before/after outputs were compared as part of each
measurement. Smart Color weights allow only numerical roundoff; its reported
metadata matched exactly. The region-grouping comparison used the same
statistics function on both sides to isolate the grouping change.

Elapsed times below are medians of five warmed runs, except the palette-mapping
case, which uses ten alternating before/after runs. They describe these fixtures
on the development host; they are not whole-program or hardware-GPU guarantees.

| Operation and fixture | Before | After | Ratio |
| --- | ---: | ---: | ---: |
| Serial palette planning, 192×128, 18 colors | 87.49 ms | 33.76 ms | 2.59× |
| Delta-error heatmap, 1024×768 | 60.34 ms | 51.33 ms | 1.18× |
| CPU palette mapping, 256×128, 128 colors | 259.54 ms | 119.56 ms | 2.17× |
| Visible RGB preparation, opaque 1920×1080 | 13.48 ms | 1.33 ms | 10.16× |
| Region statistics, 100,000 pixels | 8.18 ms | 4.77 ms | 1.71× |
| Region grouping, 512×512, 64 labels | 76.82 ms | 22.54 ms | 3.41× |
| Representative selection, 2,000 candidates | 8.67 ms | 3.01 ms | 2.88× |
| Smart Color uniqueness, 72 colors | 22.17 ms | 11.89 ms | 1.86× |
| Preset background component, 384×384 | 150.89 ms | 121.01 ms | 1.25× |
| Weighted p95 helper, 64 colors / 16,384 pixels | 0.0823 ms | 0.0107 ms | 7.70× |

The p95 timings average 100 helper calls within each timed run. That helper's
small absolute saving must not be described as a 7.7× improvement to the whole
palette-refinement operation.

| Operation | Before peak allocation | After peak allocation |
| --- | ---: | ---: |
| Delta-error heatmap | 28,410,452 bytes | 12,508,020 bytes |
| CPU palette mapping | 9,438,978 bytes | 7,866,434 bytes |
| Preset background component | 11,506,477 bytes | 6,461,869 bytes |
| Weighted p95 helper | 136,356 bytes | 6,656 bytes |

Peak values are `tracemalloc` observations. They exclude GPU memory and native
allocations that Python's allocator does not track. No claim is made that every
operation has lower peak memory: stable label grouping trades an index array for
the previous repeated full-image scans.

## Validation

The four new regression modules contain **50 tests**:

- `test_v148_color_correctness.py` — 15 tests.
- `test_v148_gpu_numeric.py` — 10 tests.
- `test_v148_picture_palette_cache.py` — 12 tests.
- `test_v148_color_performance.py` — 13 tests.

The combined scoped run completed **440 tests in 4.462 seconds, with no failures
and 3 skips**. It included those tests plus the existing color/fidelity/palette,
picture preparation, subject focus, pixel accuracy, GPU routing/setup/native ABI,
hardware benchmark, resource allocation, shadow, background-removal and image
format/upscale suites. Existing Pillow deprecation warnings did not fail the run.

The skipped cases require native Windows or physical compute devices. New GPU
regressions use controlled dispatch failures, numeric references and a
NumPy-backed formula check; they do not certify a specific CUDA/OpenCL driver.
The repository's source, complete-suite and Windows build/install gates remain
separate integration requirements.

No drawing inputs, downloads, package installations, network operations or
remote writes were performed for these measurements. Native input arming,
preflight and calibrated target validation remain outside this batch's numerical
changes. The remaining Paint UI Automation helper and required bundled Python
runtime are retained; these improvements make no antivirus-clearance claim.
