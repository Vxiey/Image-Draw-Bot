# Batch 21 — reuse polygon vertices within clipping

Baseline: `ec22fd8739573adc2df1b3e33dbe1a98a09b9c99` (821 registered
improvements). R2102 is one verified behavior group; its frozen-source gates are recorded
below. Projection, centroid and membership helpers are parts of this
same change, not additional IDs.

## Actual repeated work

The real `execute_plan` sends compound drawing paths through `EdgeBehavior`,
`CanvasGuard.clip_path_to_safe_subpaths` and the public polyline clipper before
the final native-input guard. Each segment rebuilt the same polygon vertices;
each midpoint, rounded endpoint and projection membership query rebuilt them
again. These repeated validations apply to already validated float tuples.

A read-only before probe at the exact baseline exercised eight compound paths
of 640 points through the actual executor with a recorded-action mouse and
no-wait clock. It counted **185,152** `_float_point` calls. Of those, **102,240**
were repeated polygon-vertex conversions inside the membership predicate,
and **30,672** came from re-normalizing polygon vertices and segment endpoints.
The full action/probe digest was
`83bf5da4bda148f6af682881af5682b9e591b6991395e4c8f5080413644148f9`.

## Change and safety boundaries

Each public segment or polyline call now prepares a private immutable tuple of
finite polygon vertices once. The existing intersection, midpoint selection,
rounding, gap preservation and endpoint-merging algorithm borrows that tuple.
The rare integer-safe projection path also borrows it through the unchanged
centroid, nearest-boundary, candidate ordering and inward-nudge arithmetic.

Every derived query point still passes finite-number validation. Public input
validation order is retained, including empty and malformed input. Source
points remain checked against the full selected canvas. Result points remain
checked against the safe inset, and FinalMouseGuard still checks the live
cursor before press/click. Existing cancellation polls remain at their original
input and segment boundaries. No operation-wide/global geometry cache or new
rectangle shortcut is introduced. A later call observes the caller's current
polygon.

This differs from **DP06 / global 337**, which prepared the immutable
`SafePolygon.contains*` object's membership geometry and rectangle fast path.
The generic segment/polyline/projection path did not use that object and still
performed the repeated conversions demonstrated above. DP06's membership
checks, and DP07's cancellation contract, remain in place. Their correctness
coverage is not counted again.

## Verification

`test_v148_delivery_batch21_clipping.py` contains seven methods:

- Independently known horizontal/vertical rectangle intervals, in both
  directions and with a negative origin.
- Explicit concave split gaps, duplicate points, boundary dots, polygon
  winding/rotation and fractional thin-polygon projection results.
- Nonfinite/malformed coordinates and a polygon with no verified integer
  coordinate, preserving the original exceptions.
- Stop during both input preparation and segment processing, with unchanged
  poll counts.
- Fresh caller geometry on the next operation and unmodified caller inputs.
- The actual executor's complete recorded action/probe digest and reduced
  validation work.
- Source points outside the canvas and a physically moved cursor still
  preventing native press.

The new and adjacent canvas, edge, projection, probe and preview-placement gate
passed **74 tests in 1.008 seconds**, without skips.

`benchmark_v148_clipping_batch21.py` loads the complete historical CanvasGuard
module, then links its imported aliases in the real DrawBot, EdgeBehavior and
PreviewSafety callers. Both sides use the same current caller bodies and other
dependencies. This isolates the geometry change from the parallel calibration
observation. It does not substitute an abbreviated old algorithm or combine a
historical guard with the new FinalMouseGuard class.

There are **3,386 exact historical comparisons**: 840 each for public segment
clipping, polyline clipping, safe projection and nearest-boundary selection,
20 malformed/extreme-input outcomes and six cancellation schedules. Their
combined digest is
`b9f89abc2fc960357812b9cf53ae4ce3a1116537a731761cd4e28eca194a902a`.
All eight helper/actual-caller workloads also preserve their full compared
outputs. Complete public-plan comparisons exclude only the declared elapsed
instrumentation, including the four PixelStroke stage timers and timer-derived slowest-phase
labels; geometry,
execution costs, labels, raster images and other metadata are retained.

| Actual operation | Point validations before | After |
| --- | ---: | ---: |
| Rectangle polyline, 2,048 points | 62,029 | 11,591 |
| Concave polyline, 2,048 points | 65,253 | 8,743 |
| Thin polygon with integer projection, 512 points | 39,862 | 8,180 |
| 1,000 short polylines | 37,000 | 11,000 |
| Construct and use CanvasGuard, 2,048 source points | 67,971 | 16,009 |
| Actual PreviewSafety, eight compound paths | 171,778 | 40,482 |
| Actual execute_plan, eight compound paths | 185,152 | 52,240 |
| Public 96 × 72 Pixel plan | 41,382 | 9,790 |

The constructor-inclusive guard row includes 32 setup validations that the
earlier already-constructed before probe did not. Both measurements use the
same scope on their own before/after sides.

## Final measurements

[Complete raw results](v148-batch21-clipping-benchmarks.json) use six balanced
AB/BA pairs for each of eight workloads, with a warm parity pair and separate
traced allocation observations. All **826 root Python hashes** remained
unchanged and match the calibration report's manifest. Raw report SHA-256:
`0394f303031c0d99b118e1f380d019b25f14f8ce275231a74b94bf3cbcdd1164`.

| Workload | Before median ms | After median ms | Change | Faster pairs | Peak traced Python bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rectangle polyline, 2,048 points | 34.115 | 21.835 | -35.994% | 6/6 | 550,876 → 406,804 |
| Concave polyline, 2,048 points | 33.661 | 20.762 | -38.321% | 6/6 | 521,988 → 345,036 |
| Thin/projection polyline, 512 points | 23.129 | 15.088 | -34.768% | 6/6 | 195,060 → 66,204 |
| 1,000 short polylines | 20.244 | 13.371 | -33.951% | 6/6 | 397,376 → 324,328 |
| Construct/use guard, 2,048 points | 39.224 | 25.892 | -33.990% | 6/6 | 683,272 → 538,704 |
| Actual PreviewSafety, eight paths | 105.734 | 71.643 | -32.243% | 6/6 | 1,110,606 → 966,646 |
| Actual executor, eight paths | 137.216 | 101.157 | -26.279% | 6/6 | 1,159,495 → 1,015,439 |
| Public Pixel plan, 96 × 72 | 110.161 | 105.878 | -3.888% | 5/6 | 1,587,052 → 1,542,920 |

The seven geometry/guard/preview/executor workloads improved in all six pairs.
The public Pixel plan improved in five of six pairs; after samples range from
99.817 to 116.516 ms. Its lower median is an observation for this small fixture,
not a guarantee about all source images or overall application throughput.

The measured wrapper includes linking the selected geometry aliases, the real
operation, and returning its comparable output. For the complete Pixel plan,
fingerprinting and owned-image cleanup also occur inside this wrapper on both
sides. This boundary differs from the calibration report, which explicitly
measures only the public planner call. Each before/after comparison retains the
same boundary; absolute times from the two reports are not interchangeable.
The executor uses a fake mouse and no-wait clock. It preserves every recorded
input action and ink probe but does not measure physical delivery delays,
Windows painting, UI responsiveness or native application throughput.

All eight traced Python peaks are lower in this run, including construction of
retained outputs. The executor peak changed from 1,159,495 to 1,015,439 bytes;
the complete public plan changed from 1,587,052 to 1,542,920 bytes. These are
separate `tracemalloc` probes, not process RSS, most Pillow-native storage or
physical GPU allocation measurements.

The independent source/method review and raw-result review are closed without
blockers. The reviewer independently ran **61 tests in 0.791 seconds**, checked
the raw report's hash, source manifest, complete historical source linkage,
AB/BA order, all medians and work counts. The actual executor retains **21,496
SafePolygon `_contains` calls on both sides**: the removed work belongs to the
segment/polygon conversion path, not to disabled safety validation.

Final frozen-source discovery completed **4,198 tests in 199.785 seconds**:
**4,140 passed and 58 platform/hardware cases skipped**, with all **876
source/configuration hashes unchanged**. The 5,000-cycle source gate, source
package hygiene and all eight exact-raster fixtures also passed. The new
published commit's Windows/CI result is a separate gate in PR46.
