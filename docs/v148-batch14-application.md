# Batch 14 — application workflows

Baseline: `f7b561f479d94f307924dbc779e5c8e365422f8d`.
This ledger records four new behavior groups, A1401–A1404. The companion UI implementation
of manual Paint readiness and guides belongs to A1402, not another UI ID.
The separate browser start ownership group A1405 is recorded in
[its workflow ledger](v148-batch14-browser-start.md).

## A1401 — bounded pending display notifications

The application's FIFO retained every obsolete status, progress, timer and
deadline update while Tk was busy. A completed worker could remain behind that
backlog: the actual 6,000-path executor fixture produces more than the poll's
250-event ceiling, so its first poll could not reach completion.

`WorkerEventQueue` keeps at most one latest value per display kind within each
uninterrupted display run, ordered by the last update. Commands, image/plan
results, checkpoints, failures, unknown events and completion are lossless FIFO
barriers. Queue locking and ordinary get/put/task_done/join behavior remain
available. Native drawing, checkpoint publication and diagnostic logging are
unchanged; only obsolete UI presentation values are replaced.

The mixed 50,000-notification fixture retains five display events. The actual
executor fixture retains fewer than 25 events and its real UI poll reaches the
final 100% progress, final status and completion in one poll. Tests also cover
barrier ordering, concurrent producers, task accounting, consumed values and
unknown events. These are work-count/responsiveness observations, not a claimed
change in native drawing speed.

The related late-deadline-telemetry correction completes AX03's existing Stop
status contract and adds no improvement ID.

## A1402 — preserve the requested Paint workflow through Start

Starting Paint always ran automatic preparation, even when the user explicitly
selected Pencil, Brush, Eraser or Use current tool. Its completion switched back
to Auto and reset the UI width to 1 px, although the worker had prepared the
requested physical width. The manual Brush route could also lose its saved
calibration to automatic Pencil calibration before it was used.

Only Auto (recommended) now uses automatic preparation at Start. Explicit Paint
tools use the existing manual canvas/target/palette/tool checks and Unlock →
Start flow, including F1's existing guarded quick-start path. Main and secondary
buttons, readiness, setup wizard and the live Getting Started guide use the
same policy. Manual tools and calibration are no longer silently replaced by
Start. Diagnostic tests remain optional as prescribed by the controller.

Auto completion validates and reports the actual prepared width. An explicit
numeric width stays numeric; the Auto preference remains Auto. The verified
physical width and its analysis metadata travel with the original start request
into final preflight, so discovering a new canvas cannot make a second Auto
analysis model a different width from the one already selected in Paint.
Changing image, profile, tool or brush width revokes the delayed prepared start.
Invalid width metadata is rejected before adopting any canvas or saving settings.

The automatic worker's failure report no longer reads a Tk variable from its
background thread, and its owned screenshot closes even when detection fails.
These changes finish the same preparation workflow and add no separate IDs.

`test_v148_application_batch14_paint.py` exercises actual Start/F1/button and
completion/resume/preflight methods, all four explicit tools, missing setup,
expired unlock, physical-width handoff, invalid metadata and a thread-bound Tk
variable failure oracle. `test_v148_ui_batch14_paint_workflow.py` covers actual
UI-state construction, wizard and live guide integration. The initial related
selection passed 129 tests with four Windows-only skips; whole-program and
Windows integration results are recorded separately after the final source
checkpoint is fixed.

## A1403 — live execution time with pause-aware remaining work

The execution timer was emitted at start, after guarded paths and at completion,
but not during ordinary successful drawing. Its existing throughput projection
also treated a long user pause as slow drawing, multiplying that idle time into
the remaining estimate.

The actual execution wait loop and path completion now publish throttled live
updates, including while a long stroke is held. Elapsed time remains wall time.
Throughput uses active time, excluding both completed pauses and the current
pause; predicted total time is elapsed wall time plus the remaining work. The
UI identifies a pause explicitly. Resume countdown remains pause time, while
actual tool reselection remains active work. Completed timing and the existing
rule against training the calibration from paused draws are preserved.

Stop and the hard deadline are checked again after an emitted report callback
before any further input. Late running/paused timer events cannot replace the
Stop label; an actual completed result can still publish its final elapsed time.
Dry runs do not emit a real execution timer.

`test_v148_application_batch14_timer.py` exercises the real executor with an
advancing clock, live updates within a held stroke, a 120-second pause and
three-second resume countdown, Stop/deadline transitions inside the reporting
callback, dry run behavior and actual UI event handling. Independent review
added initial/final direct timer callback regressions, so cancellation on the
last path cannot publish a false completed result. All 30 tests in the final
focused timer/events/calibration/Paint review passed. The earlier broader
timer/calibration/event/runtime/native selection passed 44 tests before that
extra regression was added.

Independent comparison against the complete historical executor preserved
the exact 43/48/25 native action sequences and 8.88/133.08/no-recorded-time
results for ordinary/paused/dry-run fixtures. The review is closed. This is a
display/estimation correction, not a claimed increase in drawing speed.

## A1404 — show verified resume progress without reusing past runtime counts

The actual resumed batch executor painted the remaining four of eight paths,
but emitted no progress event: its local `done` never reached the full plan's
eight-path total or the ordinary periodic threshold. Its initial timer still
predicted the complete twelve-second fixture, and the last running tick claimed
7.5 seconds remained immediately before the resumed work completed in 4.74
seconds. Repeated color orders also displayed a total that counted each color
only once, although the executor intentionally visited it again.

Preparation now retains one normalized final sequence before input and reuses
it for execution. A separate presentation total describes all actual sequence
operations or color-batch visits. Verified completed batches/sequence entries
initialize its saved-work offset. A path-level prefix contributes only after
its actual runtime ordering and count match the checkpoint fingerprint; an
invalidated prefix restarts the batch without inventing completed work.

Progress is published at verified resume boundaries and at the end, while
preserving the existing periodic update policy. The elapsed timer still records
only the current invocation. Its display combines saved and new progress, and
its remaining-work calculation uses the remaining session count. The existing
cold-start estimate is proportionally reduced for resumed work; live throughput
updates it as drawing proceeds. This is an estimate based on path counts, not
a new promise that all paths have equal cost or that remaining time is exact.

The execution's `done`, `sent_paths`, measured seconds, saved plan count,
learning eligibility and checkpoint operations remain separate and unchanged.
An already completed sequence reports full progress without target input or a
new timing sample. Stop from an initial resume report is checked before target
preparation; final reports retain the ordinary hard-deadline/input gate.

Six tests in `test_v148_application_batch14_resume_progress.py` exercise actual
batch, path and sequence resume, both matching and changed path fingerprints,
fresh/resumed repeated batches, a completed no-op and Stop during the initial
report. The half-completed fixture starts at 4/8 with a six-second initial
remaining estimate and ends at 8/8, while runtime counters still record exactly
four newly sent paths and 4.74 seconds. The focused resume/timer/platform set
passes 29 tests. Independent review is closed. Its additional actual-executor
probe resumes 1/3 operations and applies a real deadline skip: progress ends at
2/3, only one new 1 px path is sent, runtime/learning counters remain one, and
the saved checkpoint contains two completed operations. An explicit raw
sequence with only an empty row reports 0/0 and sends only mandatory release,
without replaying legacy groups. Whole-program results belong to the final
checkpoint.

P1401/P1402 establish which operations may resume and their actual brush widths;
A1404 presents that verified prior work without treating it as new input or
newly measured runtime. A1403 publishes live ticks and excludes pause time;
A1404 fixes the distinct saved-work offset and denominator.
