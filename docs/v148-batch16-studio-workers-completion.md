# Batch 16 — tracked Studio jobs and owned benchmark images

This work completes **IW40 (global 614)** and **IW08 (global 582)** and adds
**zero new improvement IDs**. The batch baseline is
`d1a5e3a709745ee64263b5801cf1b9089cd6b707`. The controller reproduction was run
at the later focused checkpoint `86fa125306b9c2db8e8125fec6a38270b09c8ff9`,
where these three Studio actions still had their original raw-thread lifecycle.

## Actual caller failures

`DrawBotApp.run_performance_benchmark`, `run_benchmark_suite` and
`run_golden_image_regression` each started an untracked daemon thread. Their
initial busy check did not claim the application's activity or worker slot.
The actual controller therefore permitted another Studio job or drawing worker
while a benchmark was running, and application shutdown could finish without
waiting for that benchmark. Pending profile changes and recovery clearing were
also absent from the preflight check.

All three actions cleared the shared Stop event after reading settings. A Stop
during this preflight could be erased by the subsequent handoff. Their worker
results also lacked the cancellation filter already used by ordinary status
events. Replaying an actual queued success result after `cancel()` changed
`Stopped.` back into a benchmark-success message and replaced existing summary
content.

The performance action copied the loaded source, or created a synthetic source,
without explicitly releasing it. Its completed plan images remained open after
both success and a formatting error whose traceback stayed alive. These are
observable ownership failures, not estimates based on garbage-collection
timing.

The initial controller regression file ran 13 test methods and reported 43
failing subcases across these boundaries. A new explicit action after an old
Stop was a passing control; that behavior remains supported. Test-method and
subcase counts do not represent additional improvement IDs.

## Tracked lifecycle and result publication

The actions now use `_profile_action_ready` before reading settings or copying
the source. An accepted explicit request clears an earlier Stop before
preflight. It then uses `begin_worker(..., reset_stop=False)`, preserving any
new Stop received during settings collection or worker construction.

The shared worker owns activity, cancellation, completion and shutdown waiting.
Settings are captured on the UI thread before the deferred task starts. A Stop
after a runner returns prevents success publication, and the three result kinds
join the existing cancelled-result filter. A result that was already queued
cannot replace Stop or the previous summaries. These remain local planning
actions and do not arm native drawing input.

The performance task releases its whole temporary plan in `finally` through
the existing plan-image ownership helper. Its private source has idempotent
cleanup registered with the worker, including an accepted task skipped by
Stop. The caller retains cleanup responsibility when worker startup raises or
the worker is rejected. Source aliases in a temporary plan can be released;
images retained by the current UI plan or loaded original remain usable.

The synthetic fallback's `ImageDraw` context owns additional references to the
same native pixel storage. Independent review reproduced those references
remaining readable after a retained paint/startup exception, despite the PIL
image wrapper being closed. Its drawing context now releases `draw`, `im` and
`_image` in `finally` before worker handoff. The regression retains the original
exception traceback and checks those owners directly.

## Per-fixture plan ownership

The real `BenchmarkSuite.run` and `GoldenImageRegression.run` previously closed
their synthetic input images but left each generated plan's images open.
Separate actual-runner tests observed the first plan still readable when the
next fixture was about to be allocated. Stop immediately after planning and a
row-extraction exception with a retained traceback exposed the same missing
cleanup. Four test methods produced eight failing subcases before correction.

Both runners now keep the input and generated plan within a per-fixture
`try/finally` ownership scope. They extract the existing scalar result row and
release the plan before the next fixture begins. Cancellation and failed row
extraction take the same cleanup path. The result schema, scoring, source
fixtures, asset generation and CLI arguments are unchanged.

A real, bounded Pixel `make_plan` passed through the performance controller
revealed one additional known owned field:
`options['_accuracy_quantized_target']`. The existing `_trial_images` helper
did not enumerate this full-resolution target. That exact field is now included
in its owner list; no arbitrary traversal of options was added. The same helper
continues to preserve input images, borrowed options and a retained live plan.

## Verification and limits

`test_v148_application_batch16_studio_workers.py` contains **20 new regression
methods**. They run the production controller, `begin_worker`, result handler,
Stop and shutdown flow with deterministically advanced threads and replacement
UI surfaces. Coverage includes all three actions, profile preflight, current
successful results, duplicate/overlapping starts, Stop during settings and
construction, accepted-before-task Stop, post-runner Stop, queued results,
startup rejection/failure, retained exceptions, synthetic pixel-core owners,
source/preview aliases, and the real runner's next-fixture boundary. One
ownership regression uses the actual Pixel planner at the small source's native
size; it makes no execution-speed claim.

The final 20-method file passed after the independent review corrections. An
adjacent 101-test gate found one pre-existing Sketch+Fill motion oracle that
still counted uncapped Pixel spacing. The coordinator updated that independent
per-entry formula as part of the separate RP02/RP28 cost completion, retaining
all its other assertions. The resulting combined gate passed **29 tests**:
the Sketch ownership cases, actual delivery-cost cases, and all 20 Studio
cases. Independent source review closed without a remaining Studio blocker.

The coordinator records the subsequent frozen-source full-suite and platform
results. This completion does not claim measured CPU, memory-peak, GPU or
native drawing throughput improvements. No benchmark timings were produced for
these ownership and lifecycle corrections.
