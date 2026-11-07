# v1.0.148 UI workflows — batch 19

Base checkpoint: `7f41c7ee8c4b69f750008bd2d83349d186396fd1` (815/1,000).
This work completes existing window/callback ownership contracts and adds
**zero improvement groups**. It does not claim a release or completion of the
1,000-improvement target.

## Existing GP15 / UW10 / 090 — Window callback lifetime

The earlier native Windows menu gate completed successfully, but its log also
contained a late `_windows_set_titlebar_icon` Tcl-command error. Reading the
installed CTk implementation identified both its native window timers and
AppBranding's separate 300-ms icon follow-up. The latter also ran for ordinary
Tk tooltip windows, so a normal hover/leave could delete a command while its
timer remained scheduled.

### Reproduced before changes

`test_v148_ui_batch19_windows.py` first ran three actual Xorg/Tk methods against
the original code. Each ran in a fresh process, without resetting CTk tracker
registries or loop flags. All three exposed concrete failures:

| Actual flow | Before behavior |
|---|---|
| Branded root → real StudioUI tooltip → Leave, plus actual About → CTk Close, repeated twice | Six Tcl background errors remained, including button click-animation and branding callbacks; two closed-dialog global focus observers stayed registered. Root and unrelated-window positive controls still ran. |
| Public `create_root`, with only the native TkDnD `_require` boundary failing | Two CTk roots remained alive. `tkinter._default_root` referred to the abandoned first root rather than the returned fallback. |
| Two real branded roots, first root destroyed, followed by a later new root | Actual DPI probing and appearance changes stopped on the surviving root. The later root also failed to restart DPI polling. Deleted poll/icon commands produced Tcl background errors. |

The tests record Tcl `bgerror` as well as Python `report_callback_exception`;
an already-deleted Tcl command otherwise bypasses the Python callback hook.
Only appearance detection/native DnD failure boundaries are substituted where
needed. Windows, CTk widgets, timers, branding, public controllers and native
callback registration remain real.

### Shared implementation boundary

`UiCompatibility.scoped_toplevel` and `scoped_window_class` now construct local
application subclasses backed by `UiWindowLifetime.py`. They do not replace
or monkeypatch Tk/CTk's library classes. Actual callers include the public root
factory, tool calibration, Upscale, About, version history, setup wizard,
Getting Started, subject dialogs and Mobile Preview.

The scoped window owns its additional global binding tokens and scheduled
Python callbacks. Its callback identity is revoked when cancelled, so a
retained late callable cannot run after cancellation or destruction. Teardown
also cancels child-widget timers using the already verified Mobile rule:
the timer script must contain exactly one Tcl-command token belonging to the
current widget subtree's `_tclCommands`. No prefix/name heuristic or global
timer clear is used. Raw Tcl timer cancellation leaves command deletion with
the registering widget. Other windows' timers and root observers are retained.

CTk's two process-shared services have different ownership. A Toplevel routes
the exact appearance/DPI class callbacks to its application root. When a root
retires, its pending shared poll transfers to a live root only if another
pending or currently executing owner does not already exist. If the last poll
ends with no surviving window, the service becomes stopped, allowing CTk's
normal `add`/`add_widget` path to start it for a later root. Only the closed
window's tracker entries are removed; unrelated roots and callbacks remain.

Successful destruction is recorded only after the underlying destroy returns.
A real `TclError` stays visible and retryable, and reentrant/converging close
requests do not recurse. Both a portable native-boundary control and a real
Tk root regression verify retry while another root continues polling.

AppBranding separately owns each Map follow-up with a per-window ticket and a
Destroy handler. This covers ordinary `tk.Toplevel` tooltips/overlays without
requiring a broad widget patch or changes to StudioUI's tooltip interaction.
An old delayed branding callback cannot clear or overwrite a later request.

The root factory now retains the constructed root while loading native TkDnD.
If that optional extension fails, the created root is destroyed before a clean
fallback is created. A real teardown failure remains visible rather than
silently leaving an orphan and opening another interpreter.

### Integration and maintained controls

Mobile Preview uses the same shared factory, retaining its session-token,
address/QR consistency, old-callback, HTTP and native child-timer contracts.
Its native test's private binding-list reference was renamed to the common
field; the ownership assertion remains unchanged. Six older subject-dialog
fixture patch points moved from CTk's constructor to the new native allocation
factory. All original pixel, once-only callback and Destroy assertions remain.

No StudioUI or RegionPicker caller edit was needed. AppBranding's Map-job
ownership corrects their ordinary Tk windows at the common binding boundary.
Existing Windows-menu navigation code and its assertions were not changed.

### Validation

```text
python -m unittest test_v148_ui_batch19_windows \
  test_v148_ui_batch18_mobile_dialog test_v148_ui_workflow_batch05_runtime \
  test_v148_subject_batch03 test_v148_ui_runtime \
  test_v148_ui_batch06_calibration test_app_branding \
  test_v148_platform_batch03_native -q
95 cases: 84 passed, 11 native cases skipped, 1.912 seconds.
```

Nine native methods then ran explicitly against real Xorg/Tk and all passed:

| Native control | Seconds |
|---|---:|
| Actual root destroy error, retry and surviving-root polling | 0.877 |
| Shared services across surviving and later roots | 1.312 |
| Public root factory and native DnD failure rollback | 0.874 |
| Actual tooltip/About close, other timers and Tcl background errors | 0.916 |
| Mobile first-widget DPI poll | 0.821 |
| Mobile refresh/failure/reopen/Stop and native resource lifetime | 0.637 |
| Existing button pointer/keyboard focus | 0.139 |
| Existing switch pointer/keyboard focus | 0.182 |
| Existing real selector popup, navigation and focus | 1.191 |

The new native methods use bounded isolated processes and do not modify
process-wide tracker startup flags to fabricate their starting condition.
The portable exact-token control also proves that similarly named commands,
compound scripts and argument-bearing scripts remain untouched, and that
timer cancellation does not delete the child-owned command.

These timings describe regression-test durations, not a performance claim.
Native Windows execution of the new cases remains the platform gate. Root
integration is applied. Independent final source review closed without
blockers after reading the complete helper, factories, branding and caller
diffs, the installed CTk/TkinterDnD lifecycle implementation and the retained
regression assertions. That review ran no additional CPU jobs during the
combined batch measurement freeze. Combined validation remains a separate
gate.

### Full-discovery fixture ownership correction — no product change

The first combined discovery attempt aborted with native
`Tcl_AsyncDelete: async handler deleted by the wrong thread` while an existing
source-timer test was running: exit **-4** after **116.483 seconds**, with no
completed suite count. Its archived diagnostics are
`v148-batch19-before-fixture-teardown-fullsuite.log` and
`v148-batch19-before-fixture-teardown-local-regressions.json`. The new UI19
native tests had not run in that headless process, and all 857 frozen
source/configuration hashes remained unchanged.

A deterministic isolated reproduction ran one actual successful
`SourceTimerTests.test_actual_noop_background_result_preserves_source_plan_and_completed_time`,
discarded its case, and collected cycles on a real background thread. It
aborted with exit 132. The existing fixture retained its real Tcl variables
through app-bound methods, mock callbacks and two temporary AST factory
namespaces whose functions retained their own globals. The next worker could
therefore become the interpreter's final owner. This was an older test-owner
defect exposed by full discovery, not a failed drawing or background-removal
assertion.

The readout-only AST helpers now clear their temporary namespace after
constructing the same actual labels. `PlanStatusFixture` keeps every created
app alive through its case and releases its variable/method/mock references
on the interpreter's creator thread during cleanup. Any genuine still-live
fixture worker receives Stop, is unpaused and must join within three seconds
before the Tcl owner is released; a timeout remains a test failure. Real Tcl
variables, worker execution, source pixels and existing assertions are kept.
There is no production GC change or test skip.

The exact isolated reproduction then exited successfully and printed both
completion markers. A new bounded subprocess regression runs that actual
source-timer test, observes the original `Variable.__del__` implementation and
weak references, verifies creator-thread release before a real worker calls
`gc.collect`, and rejects native or ignored-finalizer errors. Automatic GC is
delayed only inside this diagnostic child to make the former failure
deterministic.

The focused readout/plan-status/source-timer/window-ownership gate completed
**33 cases in 2.154 seconds: 28 passed and five native cases skipped**. The new
isolated regression also passed directly in 0.401 seconds and independently
under root in 0.378 seconds. `git diff --check` passed. Independent read-only
review of all three fixture-only diffs is closed without blockers; no product
code changed. The aborted whole-suite attempt remains recorded separately. Final complete
discovery subsequently passed **4,083 tests in 117.859 seconds: 4,025 passed
and 58 platform/hardware cases skipped**, with all **857** source/configuration
hashes unchanged. All three benchmark suites were repeated against the same
final 807-file root Python snapshot after this test-only repair.

### Count decision

GP15 already covers truthful, retryable root teardown. UW10 already covers
owned global callbacks without removing other widgets' observers. Mobile's
090 completion established the same window/subtree timer rule. Extending
those contracts to the demonstrated actual callers and native constructor
failure is completion work: **zero new IDs**, not one per window, callback,
test, factory or lifecycle branch.
