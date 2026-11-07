# Batch27 — Mobile Preview discovery completion

## Classification and scope

This completes the existing **090** Mobile Preview contract and adds **zero
improvement IDs**. The existing MP01 encoder queue and MP02 accepted-image
publication remain separate, unchanged contracts. This work does not claim a
new encoding, planning, drawing or network throughput improvement.

The concrete defect was the actual application's **Mobile Preview** action:
`DrawBotApp.show_mobile_preview` called `server.start` or
`server.refresh_addresses` synchronously on Tk. Both enter local address
discovery, including `socket.gethostbyname_ex`. There was also a second resolver
boundary: `_start`, under the server's state lock, constructed a standard
`HTTPServer`, whose `server_bind` calls `socket.getfqdn`, which calls
`gethostbyaddr`. Moving the whole existing `start` call to a thread would leave
Tk's actual Stop and Close waiting for that state lock.

## Actual before evidence

The before probes are preserved in review scratch under
`pending-batch27-mobile/`. They read the frozen final-integration workspace:
workspace HEAD was `a3b7b929b1332772a089e1819143471ae5d58c68` with the
then-uncommitted batch26 changes. That exact product snapshot was later
published as `8e0a0e4c61ca0742dfb7857649103477cd307516`; its 873 root Python
files have the same frozen manifest used for the published batch26 gates:
`e4057cf13bd9e97e52b07dbdba90f6962a9bbb012c0c78430d782418d8d0442d`.
The raw before JSON remains unchanged: its `baseline_commit` records the
workspace HEAD, while the source manifest identifies the tested product
snapshot. It does not describe a clean checkout of that earlier commit.
The implementation starts from published
`8e0a0e4c61ca0742dfb7857649103477cd307516` in the separate batch27 worktree.
Neither prior worktree was edited by these probes.

Scripts and raw observations:

- `mobile_dns_before.py`: actual native controller, dialog, server and stdlib
  bind call chain, with controlled OS resolver barriers.
- `run_mobile_dns_before.py`: a private Xorg server and a separate Python/Tk
  process per case.
- `before/summary.json`: all nine confirmed observations, before/after source
  hashes, and zero source mutations.
- `before/<case>.json` and `.log`: ordered events, thread identities, held
  resolver snapshots, exact outcomes and callback diagnostics.

| Actual before case | Observation while the resolver barrier remained held |
| --- | --- |
| Unblocked Show control | A real listener, native panel and QR are adopted normally. |
| Forward DNS during Show, queued Mobile Stop | Show has not returned; the queued heartbeat and Stop have not entered. |
| Forward DNS during refresh, queued panel Close | The existing panel/server remain; heartbeat and panel Close have not entered. |
| Forward DNS during Show, queued app Close | Heartbeat and app Close have not entered. |
| Reverse DNS during Show, queued Mobile Stop | The actual stdlib bind stack reaches reverse DNS; heartbeat and Stop cannot enter. |
| Reverse DNS during Show, queued app Close | The same bind boundary prevents Close from entering. |
| Existing `server.start` placed in a scratch worker, Mobile Stop | Stop enters on Tk but cannot return while the worker holds the server lock; the heartbeat also stops. |
| Existing `server.start` placed in a scratch worker, app Close | Close enters and sets its closing/Stop flags, but cannot finish the locked server stop or service the heartbeat. |
| Forward DNS during Show, actual keyboard-thread `_request_stop` | The real thread-safe callback sets Stop, but the old synchronous Show still creates the session/panel after DNS returns. |

All nine diagnostic cases confirmed their specified **before behavior**. This
is not a claim that the desired responsiveness already passed. A bounded
250 ms barrier observation is an event-order proof, not a performance sample.
After the external watchdog released DNS, the previously queued actions
completed; no callback error, Tcl background error or native teardown error
occurred.

The probes did not contact an external service or open a browser. Forward and
reverse DNS outcomes and the no-packet UDP interface probe were controlled.
The real TCP bind/listen boundary was confined to loopback. An audit hook
rejected any repository write or non-loopback socket operation; there were
zero violations. Calibration, recovery and log paths belonged to per-case
scratch directories. The recorded reverse-DNS stack includes the real
`socketserver.__init__ -> HTTPServer.server_bind -> socket.getfqdn` path; the
resolver call itself is the held OS boundary.

## Completed behavior

`MobilePreviewDiscovery` owns one live, daemon resolver thread and at most one
replaceable pending ticket. Cancelling a request sets its own permanent event.
The old OS lookup continues to own the slot until its thread actually exits;
repeated Show/Stop/reopen actions cannot multiply stuck resolver threads.
Only the newest live intention is started or returned by its plain mailbox.
Retirement discards queued or late results without joining the resolver.
Errors cross this boundary as text, without exception tracebacks.

The worker receives no Tk widget, application, server, image or presentation
callback. The application's existing `poll` takes the result on Tk and checks
the current request, server identity, start/stop generation, port/token and
any existing panel owner before adoption. Closing or replacing that panel
therefore cannot cause a late result to reopen it. A later explicit Show can
queue a new intention while the obsolete resolver remains active.

The actual listener is created only after an accepted result reaches Tk.
`_PreviewHTTPServer.server_bind` uses the unchanged real TCP bind/getsockname
operation and derives `server_name`/`server_port` from the numeric bound
address. The Mobile handler does not require a canonical hostname. This
removes the reverse-DNS operation from the locked construction path. The
standard synchronous `start` and `refresh_addresses` APIs still work; the GUI
uses their prepared, validated local-IPv4 address path.

The change keeps these boundaries explicit:

- Stop between publishing the request and submitting it cannot even start the
  cancelled lookup. A later main worker clearing global Stop does not revive
  that ticket. A new explicit Show can succeed without clearing global Stop.
- Discovery does not use `begin_worker`, change drawing activity, replace the
  current worker, disarm Browser One-Click, or overwrite an active drawing's
  status. Its pending/current state is shown in the Mobile status field.
- Current discovery failure is visible and retryable while an already shared
  session remains intact. Obsolete results/errors cannot stop a newer session.
  Current panel-construction/refresh failure retains the existing safe cleanup
  policy for that session.
- QR, visible address, Copy and Open are adopted together for the current
  session on Tk. Old panel actions remain inert after Close/Stop/restart.
- Closing only the panel preserves sharing. Mobile Stop revokes sharing, and
  application Close retires lookup ownership before destroying the root.
  Neither path waits for a held DNS call.
- A non-interruptible OS DNS call can still remain pending. The guarantee is
  a responsive GUI, bounded ownership and no late adoption, not forced
  cancellation of the operating system's resolver.

## Regression and native evidence

`test_v148_ui_batch27_mobile_discovery.py` contains nine portable
controller/ownership methods plus two native event-loop methods. The portable
cases use the real controller, resolver threads, local server and accepted
panel path. They cover repeated pending replacement, publication-before-Stop,
an actual later `begin_worker` clearing Stop, a new explicit Show with Stop
still set, both thread-start failure boundaries, current/stale resolver errors,
generation mismatch, panel Close/reopen, active-worker/Browser intent
preservation, synchronous server compatibility, validated prepared addresses
and late worker retirement.

The native cases run the real `socket.gethostbyname_ex` caller behind a
controlled OS boundary, real application `poll`, native buttons and
WM_DELETE_WINDOW, actual QR/PhotoImage creation, clipboard Copy and browser
Open dispatch. Heartbeat, Stop, Close and explicit reopen complete while the
old resolver is **still blocked**. No listener is adopted from an old result;
all native image creation occurs on the Tk creator thread. The app can finish
shutdown before DNS returns, and a later result performs no Tk work.

The prior `test_v148_ui_batch18_mobile_dialog.py` keeps all nine original test
method bodies and assertions, with only its **21 Show call sites** changed to
wait for real lookup completion/adoption. Its shared readiness helper does not
pump native timers, preserving the first-widget DPI test's requirement to
close before the first scaling tick. Normalizing only
`show_mobile_preview_ready(app)` back to `app.show_mobile_preview()` produces
identical ASTs for all nine original methods. The scratch proof is
`old-assertions-preserved.json`; no other AST field was normalized.

Final focused local gate: **78 cases, 73 passed and five existing/display
skips, 5.597 seconds**. It includes the Mobile controller/server/security/queue
tests, real shutdown, event barriers and worker handoff. Raw log:
`pending-batch27-mobile/focused-after.log`.

Separate actual Linux/Xorg/Tk 9.0.4 gate: **four methods passed**, in separate
native child processes:

| Actual native method | Result |
| --- | --- |
| New buttons/heartbeat/Stop/reopen/app Close while DNS is held | PASS, 0.312 s |
| New panel Close/late refresh/Stop/new-session identity | PASS, 0.559 s |
| Existing first-Mobile-widget shared DPI lifetime | PASS, 0.914 s |
| Existing refresh/Close/restart/Tcl-resource lifetime | PASS, 0.642 s |

Launcher: `pending-batch27-mobile/run_native_mobile_after.py`; log:
`pending-batch27-mobile/native-after-initial.log`. The older Windows-marked
class is explicitly selected in these Linux/Xorg children; its repository skip
condition, assertions and `sys.platform` are unchanged. There were no Tcl
background errors, callback errors or `Tcl_AsyncDelete` diagnostics. CTk's
pre-existing PhotoImage/HighDPI warning remains visible and is not suppressed.
This is local native evidence, not a new-head Windows CI claim.

Root's product/test review and the independent read-only review are both
closed without blockers. Root also independently ran the nine new portable
methods: **9/9 passed in 1.171 seconds**. The source and tests are frozen for the combined
batch27 gate. The final full suite, combined native gate and new commit's CI
remain the publishing owner's validation steps; no results for those pending
steps are inferred here.

## Final integrated evidence

The preserved before observations, initial observer diagnostics and final
source-bound completion checks are published in
[completion evidence](v148-batch27-completion-evidence.json).
The common-source full regression suite, native UI cases, source/raster/package
gates and scope limits are recorded in
[batch27 validation](v148-batch27-validation.json).
The new published commit requires its own Windows/package checks in
[PR46](https://github.com/Vxiey/Image-Draw-Bot/pull/46); the preceding commit’s
CI results are not substituted for those checks.
