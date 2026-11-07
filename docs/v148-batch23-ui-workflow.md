# Batch 23 — UI workflow and native-fixture completions

These are **completions with zero new improvement IDs**. The native-fixture
work uses the existing GP15/UW10 window-lifetime behavior completed in batch 19;
that part changes no product factory, callback policy or runtime source. The
accepted-profile reload completion below closes the existing
Step 27/RT35/RT34/UW805 Drop-In lifecycle contract with one controller call.
Initial reproduction work began at
`92d5a86709a61802821780f5866409da6cd8cf2e` (823 registered improvements).

## Integration provenance

The focused and native after results below belong to the original local
candidate based on `be30fa54a0c58a8d2b6535d31cb6672727f4e6cc`. Its frozen
full discovery also completed 4,222 tests in 199.805 seconds: 4,164 passed,
58 skipped, and 881 source/configuration hashes remained unchanged. That
pre-integration evidence is preserved under its original `batch22-*` scratch
filenames; it is not a validation claim for the later combined tree.

Before this local candidate was published, concurrent commit
`5c32b6883c454268e06e199a8f15264ca9ec26e9` advanced the registry to 826 and
published its own batch 22. These local completions therefore move to batch 23,
with that commit as the integration baseline. The published batch 22 UI ledger,
its explicit-preview Stop and retryable-shutdown changes, tests and evidence
remain unchanged. This ledger does not recount them.

At the initial integration handoff, independent read-only comparison confirmed
that all 27 remote-changed files other than `DrawBot.py` were byte-identical to
that commit. The combined `DrawBot.py` was exactly the remote file plus the one
profile-apply call below. All twelve older native-fixture edits retained their
original local bytes, and the renamed profile regression was byte-identical
to its pre-integration form. This handoff check precedes the final batch 23
registry and publication-metadata updates.
The combined frozen full-project gate has now passed **4,270 tests in
206.108 seconds: 4,211 passed and 59 skipped**, with all **891
source/configuration hashes unchanged**. The 5,000-cycle lifecycle/source
gate, eight geometry/raster cases using existing tracked assets, and package
hygiene also passed. These are the integrated local results. The new
published-commit Windows gate is still pending; the earlier Linux/Xorg native
outcomes remain tied to their stated pre-integration snapshot and do not
establish Windows titlebar behavior for the new head.

## Observed errors and exact ownership proof

The successful ec22 Windows run completed 4,162 tests in 376.741 seconds with
three GPU skips and all seven checks green. Its stderr nevertheless contained
missing Tcl commands named `_windows_set_titlebar_icon` and
`_set_scaled_min_max` during later native tests. A test's output line alone did
not identify the root that had created the failed timer. Some reporting tests
used ordinary `tk.Tk`, which cannot create CTk's titlebar callback.

The before probe ran the actual older native scaling-replay method followed by
the actual numeric-entry method in one fresh child, on Linux/Xorg with Tk 9.0.4.
The test modules received a local observing root subclass; original native
callbacks, assertions, scaling calls and destroy implementations ran unchanged.
Neither the third-party class nor `sys.platform` nor the repository skip
conditions were changed. The observer recorded exact registered command tokens
and their interpreter/root owner before destruction, then kept that closed
interpreter alive while the next real root pumped the event loop.

Both original methods passed (**2/2 in 1.394 seconds**), but the ownership probe
correctly exited 1. The first root left five scheduled timers after its native
destroy: appearance update, DPI polling and three scaling min/max callbacks.
All five registered command names were gone. The next root's event loop raised
five `bgerror` messages, each matching the recorded command token and the first
interpreter's identity. This establishes the stale-fixture ownership chain
instead of attributing an error to whichever later test printed it.

Windows schedules the titlebar icon callback through the same root `after`
boundary, but that Windows-only branch was **not** executed by the Linux probe.
Its actual post-change result remains a Windows CI responsibility.

## Completion

Twelve known older native-fixture files now construct their CTk roots with the
existing `UiCompatibility.scoped_window_class(ctk.CTk)` factory: Getting Started;
batch 06 preview/scaling/workspace; batch 07 and 08 keyboard controls; batch 09
readouts/words; numeric entries; switches; contrast; and composite pointer
focus. The ordinary-Tk preview-cache and preview-keyboard fixtures are left
unchanged. No global CTk/Tcl/GC patch is introduced.

The pointer-focus fixture's former blanket cancellation of all interpreter
timers is removed. Its root now performs the same owned callback cleanup and
shared appearance/DPI service retirement or handoff as the application. The
numeric/switch/contrast AST namespaces still live through all real callbacks
and trace-removal assertions and are released only after actual widget destroy.

The existing native scaling-replay test is strengthened, without adding a test
method or changing a skip condition. It records exact root-owned Tcl commands
and their pending timer tokens, calls real destroy, requires those timer tokens
to be absent, then pumps another real Tk root beyond the one-second scaling
delay while retaining the closed interpreter. Tcl `bgerror` must remain empty.
The test removes its own diagnostic hook in `finally`; all earlier layout,
visibility and scaling assertions remain.

## After evidence and review

The same two-flow probe now passes **2/2 in 2.574 seconds** with zero remaining
owned timers and no `bgerror`. The first root's five pending timers are retired.
The next root starts its real appearance/DPI polling and retires those jobs on
its own destruction as well.

The focused headless run completed **116 tests in 3.311 seconds: 89 passes and
27 unchanged native-display skips**. An additional explicit Linux/Xorg run
executed **25 native methods successfully** in separate child processes: the
21 affected native assertion bodies plus four existing batch 19 window/service
regressions. It included the actual full Studio layout, guide/tooltip, entry,
switch, contrast, pointer and real popup behavior. The runner rejects missing
Tcl-command, `Tcl_AsyncDelete` and ignored-finalizer diagnostics; none occurred.
These are Linux native results, not a substitute for Windows menu/titlebar CI.

Independent source review is closed without blockers. It checked all twelve
fixture diffs, exact command ownership, actual destroy before private fixture
cleanup, retained live callback globals, shared service handoff, the diagnostic
hook's teardown and unchanged original assertions/skips. No redundant peer
timing or native test run was performed.

Evidence is retained in the parent scratch directory:

- `batch22-native-timers-before.json` and `.log`: original successful methods
  with the failing five-token ownership proof.
- `batch22-native-timers-after-final.json` and `.log`: final successful
  two-flow proof and exact zero remaining owned timers.
- `batch22-native-fixtures-focused.log`: the 116-case headless gate.
- `batch22-native-fixtures-xorg.log`: all 25 explicit Linux native methods.
- `batch21-ci-tcl-bgerror-readonly.md`: the earlier Windows stderr excerpts,
  token names, source boundaries and the initially qualified attribution.

The earlier exploratory after log is also retained. Both real methods and
timer assertions passed there, but the external diagnostic runner tried to
delete a `bgerror` hook already correctly removed by the strengthened test.
Only that scratch observer's final hook cleanup was made conditional before
the final independent child run; no repository behavior or assertion was
weakened. No performance improvement is claimed for this fixture cleanup.

## Accepted profile reload retires the previous manual Drop-In request

The real import and reset routes reach `ProfilePortability._reload_profile`
and `DrawBotApp._apply_profile_change` directly. They do not pass through the
ordinary `change_profile` callback, which already disarms manual Drop-In.
Before this completion, importing a replacement or copied profile, or resetting
the current profile, cleared the old target and full-draw authorization but
left the separate manual Drop-In arm, deadline, timers, queued import/action and
start context alive. The UI could therefore continue presenting the previous
profile's Drop-In activation after the new profile had been loaded.

The before regression uses a finite `monotonic() + 60` authorization interval
and the actual public package/import/reset, file transaction, profile apply,
settings read/save and palette-refresh paths. It failed four subcases across
five methods: replacement import, copied-profile import, reset, and reset while
Stop was set all retained the old arm. The pre-existing target and queued-start
guards already prevented the retained callback from drawing in the new profile;
that positive control passed before the change. This is not evidence of an
input authorization bypass and is not counted as a new safety feature.

The single product change calls
`DrawBotApp._disarm_manual_drop_in(self, 'profile applied')` inside the accepted
`_apply_profile_change` route, after its stale-ticket, selected-profile, busy and
closing guards. The existing helper cancels the owned timers and queued work,
retires the old context and resets the visible activation state. The ordinary
explicit profile-change route may call the helper twice; that operation remains
idempotent. Rejected or stale requests never enter this new call and retain the
current legitimate request.

`test_v148_ui_batch23_profile_drop_in.py` covers the actual replace/copy/reset
call chains and source identity, settings/palette results, finite arm expiry,
queued callback cancellation, unchanged Stop, rejected/stale/busy reloads, and
a fresh explicit arm after setup is ready again. Retained old callbacks cannot
dispatch. A new explicit arm passes through the real queue policy and reaches
the final draw dispatch exactly once. The final native draw boundary is replaced
in the test; all cases assert zero native mouse input. UI scheduling and live
window verification are controlled test boundaries. Actual profile and timing
files are confined to a temporary runtime source directory, including the
speed-budget file, and ambient custom-profile registries are isolated.

The focused after gate passed **99/99 tests in 0.555 seconds with no skips**.
It includes the five new controller methods plus existing profile-switch,
Step 27 portability, profile-management/completion, manual Drop-In,
synchronization and settings-boundary regressions. Independent source review
closed without blockers and reran the five new methods: **5/5 passed in
0.025 seconds**. No assertions or existing safety guards were weakened.

Additional evidence is retained in the parent scratch directory:

- `batch22-profile-import-state-before.json`: the original successful real
  import whose old Drop-In arm and pending state survived profile replacement.
- `batch22-profile-drop-in-before-final.log`: the authoritative five-method
  before gate with the four expected retained-arm failures. An earlier
  exploratory log contains only a test-module import typo and is not used as
  product-failure evidence.
- `batch22-profile-drop-in-after.log`: the 99-case focused after gate.
- `batch22-profile-drop-in-independent.log`: the independent five-case gate.
- `batch22-profile-drop-in-reload.patch`: the reviewed one-line controller
  handoff, applied by the DrawBot owner.

This completes existing profile and explicit Drop-In request retirement, with
**zero additional registered improvements** and no performance claim.
