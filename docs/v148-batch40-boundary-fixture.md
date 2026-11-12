# Boundary fixture lifetime completion

**Classification: zero additional improvement IDs.** This fixes ownership in
existing native-boundary test fixtures. No application code, GC policy, test
timeout, skip policy or substantive workflow assertion changed.

## Root cause

The attempted full batch40 suite aborted at the batch39 preview-publication
regression with `Tcl_AsyncDelete: async handler deleted by the wrong thread`.
That run is incomplete and is not claimed as a passing whole-suite gate.

An instrumented run identified live references from the preceding area fixtures:
`Mock` call-argument tuples retained the real Tcl root passed to
`RegionPicker.select_region`; retained `delivered` and `picked` exception frames
also retained their `_owner` argument. The fixtures had correctly released all
Tk variables on their creating thread, but these other aliases kept the
interpreter alive until collection during later preview work. Main-thread
collection removed those exact referrers. The failing preview test was where
the old fixture lifetime became visible, rather than its owner.

The two picker boundaries now use direct replacement functions, because their
Mock call histories were not used by the assertions. Each immediately releases
its unused, borrowed `_owner` argument. The controller, detectors, real child
helper, errors, rollback and image assertions still execute unchanged.

Files: `test_v148_ui_batch37_boundary.py`,
`test_v148_ui_batch38_saved_area.py`, and
`test_v148_ui_batch40_boundary_fixture_ownership.py`.

## Evidence

The two new subprocess tests run all six selection workflows and all six
saved-area workflows. A profiling callback intentionally retains the actual
picker frames, including real exceptions and their tracebacks, through fixture
cleanup. Weak references and the original variable destructors establish that
all interpreter owners and variables are disposed on the creator thread before
a later worker explicitly collects cycles. Automatic GC remains enabled.

Substituting just the historical `select` and `probe_child` fixture methods from
`fc3f927` fails both subprocess probes at the expected live-owner assertion.
The corrected **37 → 38 → 39 → fixture-proof** selection passes **21/21 methods**,
without failures, errors or skips. The recorded source hashes are stable before
and after the run. The nested subprocess workflows are not added to that count.

[Machine-readable evidence](v148-batch40-boundary-fixture-validation.json)
contains the exact selection, historical assertions and source hashes. The
combined, isolated whole-suite gate remains a separate integration requirement.
