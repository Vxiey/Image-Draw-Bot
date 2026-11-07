# v1.0.148 batch 22 — explicit preview Stop and truthful shutdown

Baseline: `ec22fd8739573adc2df1b3e33dbe1a98a09b9c99` (821 recorded
improvements). These changes complete the existing A1501/BA01 cancellation and
GP15 root-lifetime contracts. They add **zero improvement IDs**. No release,
native drawing speed or physical GPU result is claimed.

## Explicit Build preview retains Esc during its preparation

The automatic-preview handoff preserved Stop in batch 20, but an explicit
Build preview still passed `reset_stop=True` into `begin_worker`. That cleared
an Esc received while reading options, copying the source, or constructing the
screen-window owner. The worker then ran a complete public plan even though
the user had just stopped it.

`DrawBotApp.update_plan` now clears an earlier Stop when a valid explicit
request enters preparation. Its worker always uses `reset_stop=False`, so any
later Esc survives the handoff. An explicit request after an old Stop still
builds normally. Automatic requests retain their existing no-reset behavior.
Private source snapshots still close on refused startup and after accepted
workers finish. The current source and completed public-plan images retain
their previous ownership.

The same entry now uses the existing `_profile_action_ready` predicate before
reading options or copying the source. A pending profile apply/clear cannot
prepare a mixed context or clear Stop before the existing worker gate refuses
it. Busy and closing behavior is preserved.

`test_v148_ui_batch22_preview_stop.py` uses the shipped
`assets/image-draw-bot-icon.png`, real controller methods, tracked threads,
queued result adoption and the public planner. It creates no image fixture
file. Its five methods cover Manual, Auto light, Auto full and explicit full
detail; Esc during options, source-copy and worker setup; successful explicit
work after an earlier Stop; unchanged original pixels; closed cancelled
snapshots; and incomplete profile/clear contexts.

Before the correction those five methods produced **nine failed subcases**;
the successful explicit-request controls still passed. After the correction,
all five methods and the 16 existing automatic-preview methods passed:
**21 tests in 2.606 seconds**, no skips. Records:
`batch22-preview-stop-before.log` and `batch22-preview-stop-after.log` in the
parent scratch directory. These are regression durations, not performance
measurements.

## Failed native teardown remains retryable without erasing recovery

The scoped root already kept a native destroy failure visible and retryable.
Its application caller, however, set `shutdown_complete=True`, cleared the
real recovery checkpoint and marked the run clean **before** calling
`root.destroy`. The caller then swallowed any Tcl/RuntimeError and refused
subsequent Close requests because `closing` was already true. A still-live
root could consequently remain disabled with recovery discarded.

`_finish_shutdown` now has a separate in-progress guard. It retires workers,
hotkeys and sharing as before, calls native destruction, and records completed
shutdown/clears recovery only after destruction succeeds. The existing exact
already-destroyed Tcl classification remains an idempotent success.
Other Tcl/RuntimeError failures are logged with their traceback, leave the
checkpoint and run marker intact, and show a concrete Close-again message
when the status widget remains available. A subsequent Close retries teardown
without re-saving settings or restarting work. Unrelated exception types
still propagate; the guard resets so a later retry remains possible.

Converging Close/Destroy callbacks cannot recursively commit shutdown. The
existing recovery-encoder waiting path remains unchanged and still finishes
that worker before destroying the root.

`test_v148_ui_batch22_shutdown.py` uses the actual application controller and
scoped-window wrapper with real temporary recovery/marker files. Its five
portable methods substitute native window allocation/destruction and unrelated
settings, hotkey, sharing and overlay boundaries. Teardown sequencing and
recovery/marker ownership remain real.
They cover a live Tcl failure and successful retry, RuntimeError, reentrant
Close, propagation of an unrelated exception, and already-destroyed success.
No image data is needed. Before the correction, four methods failed; afterward
the shutdown/recovery/root-helper selection completed **28 tests in 0.527
seconds: 23 passed, five existing/display-dependent cases skipped**.
Records: `batch22-shutdown-before.log` and `batch22-shutdown-after.log`.

One additional isolated native method uses the actual public `create_root`,
injects a single failure at `tk.Tk.destroy`, then exercises a real Destroy
callback and retry with the same recovery/marker assertions. It is enabled on
Windows or a supplied Tk display. Local native execution was attempted using
the installed Xorg dummy driver on isolated display `:91`, but Xorg could not
open its local/unix listening sockets and exited before server initialization.
`batch22-Xorg.log` records that blocker. This is not a native pass; the new
method requires the published-commit Windows gate.

## Adjacent verification and prior CI-log observation

The combined preview, source lifecycle, worker/plan adoption, Studio workers,
update handoff, recovery, branding and root-helper selection passed **148
tests in 5.867 seconds: 146 passed and two native cases skipped**. No production
test assertions or platform skips were removed. Record:
`batch22-ui-related.log`. `git diff --check` passed.

The exact preceding Windows job
[`128475495241`](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42396698234/job/128475495241)
contains the already disclosed Tcl background errors in older native
fixtures, mainly `_windows_set_titlebar_icon`/`_set_scaled_min_max`, plus
appearance/DPI poll callbacks. Several implicated older tests allocate raw
CTk roots; the batch 19 public-root/window ownership tests in that same job
passed. This observation does not establish that every background error has
been attributed or fixed. Neither Tcl errors nor native test assertions were
globally suppressed by this patch.

Independent source review, frozen whole-project verification and the new
exact-commit Windows checks are separate integration gates.

Integration note: this batch was rebased onto concurrent checkpoint
`92d5a86709a61802821780f5866409da6cd8cf2e` (823 improvements).
The initial reproductions above used `ec22fd8`; final validation and paired
measurements use the integrated source and are recorded separately.
