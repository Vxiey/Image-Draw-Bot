# v1.0.148 UI workflows — batch 18

Base checkpoint: `d7721a36975a36137b583beda9ff3c47c05208fd`.
This ledger does not claim a release or completion of the 1,000-improvement
target. One independently reviewed behavior group is recorded below, pending
the combined integration gate. Mobile Preview session presentation completes
existing behavior 090 and contributes no additional improvement ID.

## U1801 — Explicitly leave browser contour/current-ink mode

The actual **Single-color sketch (current ink)** switch enables the supported
contour renderer outside Paint. The separate **Black contour sketch** switch
advertised an Off action returning to color drawing, but did not end that
dependency. Its next public `DrawBot.options()` call silently changed the
visible Off value back to On, and `make_plan` continued producing black
contours. The reproduction fails for both Skribbl and Gartic Phone.

The explicit Off callback now ends the dependent current-ink choice outside
Paint and uses the existing deferred palette/configuration refresh. Both
visible switches and the resulting full-color plan agree. The tooltip explains
the relationship. This does not change the options compatibility normalization
for saved current-ink settings.

The opposite transition remains independent: turning **Single-color sketch**
off can retain a separately chosen palette-based black contour. Paint can
still use its current ink with the supported shaded portrait renderer.
Busy/closing callbacks retain their existing guards, and no callback starts
native input or grants drawing authorization.

### Actual-flow evidence

`test_v148_ui_batch18_sketch_mode.py` executes the actual StudioUI switch
constructors, CTk variable traces and toggle commands, controller callbacks,
deferred palette refresh and `set_busy`, then public `options` and `make_plan`.
Only the native widget surface and external calibration/timing I/O
boundaries are substituted. The planner processes real colored PIL pixels.

Before the patch, the five test methods produced two failing browser subcases
in the mode-exit test. The four other control methods passed. After the patch,
all five pass; the color-exit plans use multiple actual color groups and the
current-ink/independent-contour controls retain their respective real renderer
branches. The focused suite was:

```text
python -m unittest test_v148_ui_batch18_sketch_mode test_game_sketch_v1097 \
  test_v148_rendering_batch06_profiles test_v148_ui_batch12_switches -v
31 test cases: 29 passed, 2 native Windows cases skipped, 0.767 seconds.
```

### Count and review

U1201 covers native keyboard delivery for existing boolean controls. A1402
covers explicit Paint tool preparation; R901 covers physical brush width.
None describes the contradictory browser mode-exit behavior corrected here.
U1801 is **one** workflow group, not one per profile, callback, tooltip, option
or regression. Independent review of the source and actual flows closed without
blockers; the reviewer reran all five methods successfully in 0.377 seconds.

## Existing 090 — Mobile Preview dialog session presentation

Reopening the sharing panel refreshed the server's LAN addresses but opened a
second independent window. The old window retained its earlier text, QR and
Open URL, while Copy read the application's new URL. After Stop and restart,
its retained Stop callback could stop the new server session. The actual
controller and local HTTP reproduction produced six failing subcases across
four initial methods; ordinary window-close without stopping sharing already
worked and remains supported.

`MobilePreviewDialog.py` now owns one panel for the current server object,
port and session token. Reopening that session refreshes the existing text and
QR together and restores its window. Copy, Open and Stop require that same
live owner. Controller Stop first closes and revokes the panel, then uses the
existing server shutdown. A normal window-close releases the panel while
sharing continues; opening it again creates a fresh owner. Old callbacks and
late old Destroy events cannot affect that replacement. A failed panel
construction/refresh closes the partial window and follows the existing
controller failure path; a QR-generation failure clears the old image and
keeps a usable, matching text address.

The native Tk regression also exposed resource-lifetime gaps: a destroyed
CTkLabel could retain the owned QR PhotoImage through Python references, and
CTkToplevel left its own global focus callback registered. The panel explicitly
releases its native image and scopes its CTk global binding tokens and delayed
callbacks to its window lifetime. CTkTextbox scrollbar checks and a Stop
button's click animation also schedule child-owned callbacks; before subtree
destruction, only timers whose script is exactly one Tcl-command token in
that subtree's registered command set are cancelled. Normal widget destruction
still owns command deletion. Other windows' and root's timers and observers
remain present. This view introduces no periodic refresh jobs or variable traces.

CTk's process-shared DPI poll is a separate owner. Its first widget can be
inside this panel when the app root initially has no widgets. Cancelling that
first tick left CTk's loop flag active but stopped actual polling. The narrow
fix delegates precisely `ScalingTracker.check_dpi_scaling` to the app root's
`after`, using bound-method equality; it does not alter tracker registries or
loop flags. All other panel callbacks keep their local lifetime.

### Actual-flow and native evidence

`test_v148_ui_batch18_mobile_dialog.py` uses the actual show/stop/copy
controllers, real QR encoding and a real local HTTP server. Portable tests
replace native widget allocation, LAN interface discovery, PhotoImage's Tk
boundary and browser opening. They assert one panel, matching text/QR/Copy/Open,
token rotation, current-token HTTP 200 and old-token 404, stale callbacks,
external Destroy, failure/retry and QR fallback. No server security or image
publication function is substituted.

```text
python -m unittest test_v148_ui_batch18_mobile_dialog \
  test_v148_application_batch07_mobile test_mobile_preview_v1069 \
  test_mobile_preview_security -q
28 test cases: 26 passed, 2 native Windows cases skipped, 2.417 seconds.
```

Both native methods were run explicitly against real Xorg/Tk and passed in
0.892 and 0.645 seconds. The first uses a fresh subprocess, an unmodified CTk
tracker startup state and a widget-empty root. It opens and closes Mobile
before the first DPI tick, then verifies actual DPI probing of the surviving
root/widget and preservation of another window's timer. Before the fix, this
test observed zero probes. The second uses actual CTk windows, Tcl commands,
clipboard and PhotoImages; checks address/QR refresh and old-image deletion;
destroys the window externally; verifies owned-command/timer cleanup; and
exercises native refresh failure, reopening and the real CTk Stop-button
Enter/Release handler, including its animation timer. Both collect Tcl
`bgerror` as well as Python callback errors and continue the event loop after
closure. The strengthened gate exposed the child scrollbar callback before
its cleanup was added. Windows CI remains the Windows platform proof.

Independent source/lifecycle review and the root's review both closed again
after the final DPI/child-timer completion, without blockers. The review
checked exact token ownership, raw Tcl timer cancellation, normal widget-owned
command deletion and preservation of the shared poll and other windows.

This completes the sharing-panel refresh and cancellation contract already
recorded in **090**. It contributes **zero new improvement groups**. HTTP
token rotation, request/client restrictions and accepted-image publication
retain their existing server implementations and regression gates.
