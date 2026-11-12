# v1.0.148 batch 41 — timing context and representative dry runs

## Count and baseline

Two distinct product groups, N4101 and N4102, are implemented against the local
batch40 checkpoint `fc3f927`. The aggregate registry assigns global IDs. Test
methods, individual assertions, compatibility controls, cancellation and repairs
found during review do not add extra IDs.

## N4101 — learn timings for the actual native delivery policy

`DrawTimeCalibration` formerly used the same context key for Paint Auto,
Reliable and Compatible delivery, and for different effective delays and path
spacing. Those settings change the actual schedule. For the same 97-pixel
source path, Pixel Accurate, Fast, one-pixel brush and zero configured delay,
the cold model gives 0.1545, 0.2105 and 0.1425 seconds respectively. A recorded
operation average from one policy could overwrite or be applied to another.

The key now extends the existing v4 context with a digest of the resolved input
backend, effective precision/interpolation step, path/travel/boundary waits,
press/release settling, palette/control delays and brush-switch waits. The
signature uses the real StrokeDelivery, Precision and SpeedOptimizer helpers,
and carries an explicit policy schema. Paint delivery aliases such as Reliable
and Dense share a key when they resolve identically. Existing outer v4 speed,
precision, profile, tool, brush and rendering-style tokens remain authoritative;
this change does not claim to canonicalize all older naming aliases.

Each policy can learn independently and recover its own history when selected
again. Reset removes the selected bound context and the established unbound
legacy equivalents while retaining other current delivery variants. The
operation-local calibration scope still reads one database and can select
different policy rows from that same immutable observation.

Older history remains available through the existing bounded reader and
migration. A row without evidence of its delivery policy uses the cold model
until a new completed drawing supplies a compatible measurement. A legacy-key
row with an explicit matching signature can still seed learning. The JSON
format remains version 4: only context keys and an optional row field extend it.
This deliberately retires blind legacy fallback, which would recreate the
policy collision. Existing profiles may therefore need fresh timing samples.

`test_v148_native_batch41_delivery_context.py` covers independent recorded
histories, equivalent Paint labels, effective delay/density changes, precision
caps, warm reuse, selective reset, retained unbound history and one-read scoped
lookups. The older calibration-scope fixture now distinguishes a policy-bound
legacy row from unbound old history; its migration, nested isolation and fresh
read assertions are preserved. This is separate from the previous database
read-sharing and malformed-record validation groups.

## N4102 — preserve physical brush state when sampling a dry run

A saved ordered sequence may omit a brush width after an earlier explicit
change. `FastDryRun.sample_plan` selected representative colors and paths before
resolving that state. If the width-setting operation was omitted, the next
sampled path silently inherited a different brush. Repeated references to one
entry can also have different widths at different positions in the sequence.

Sampling now walks the executor's canonical
`RenderResume.execution_sequence_with_brushes` iterator, counts valid operations
by color, and copies only the bounded selected entries with their explicit
effective widths. It preserves the original order and entry metadata without
mutating the saved plan. No full normalized-sequence copy is required. Legacy
execution groups borrow their existing source-group data instead of duplicating
an entire selected color group merely for a small cursor sample.

Independent review caught an initial implementation which let a colorless or
invalid row change inherited brush state even though the executor ignores that
row. Reusing the canonical iterator fixes the mismatch for missing, None,
non-numeric and non-finite color values. Empty rows are not brush commands.

An intentionally empty sample now also empties the legacy group fallback so
the real executor cannot revive unsampled paths. The preparation takes the
active Stop callback, including during source materialization and original-order
scans. These complete the sampler's established bounded/cancellation contracts
and do not add further IDs.

`test_v148_native_batch41_dry_sample.py` derives geometry from a real Pixel plan
of the committed small-detail raster. It verifies discarded colors and same-color
paths, repeated entry identity, original-plan preservation, ignored invalid
rows, cancellation and zero-sample behavior through the actual dry-run executor.
No input clicks or new source image assets are introduced.

## Evidence and review

- The focused calibration selection passes **51 methods**.
- The final dry-run selection passes **17 methods**.
- Seven selected methods with the exact two historical module bodies produce
  **11 failed assertions/subtests, zero errors and zero skips**. The same seven
  methods pass with the corrected implementation. Diagnostics and source hashes
  are in `v148-batch41-delivery-historical.json` and
  `v148-batch41-delivery-current.json`.
- The earlier six-method comparison is retained in the two
  `v148-batch41-delivery-before-review-*.json` records. It predates the additional
  invalid-row regression and is not presented as final coverage.
- Independent runtime review approves both count boundaries and the final
  canonical-iterator correction. Its separate 25-method selection includes the
  root delivery and dry-run cases as well as its own runtime cases.

These are source-level schedule, persistence and real controller/executor
regressions on Linux. Cold-model numbers are predictions, not measured physical
Windows drawing times. The final integrated gate and published-commit Windows
checks remain separately recorded.
