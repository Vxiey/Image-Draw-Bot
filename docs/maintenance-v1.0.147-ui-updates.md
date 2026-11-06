# v1.0.147 improvements 076–100: updates, mobile preview and UI

These entries describe separate behavior changes. Version edits, documentation
and additional tests are not counted as improvements. Native Windows coverage
also runs in GitHub Actions; a skipped local Windows test is not a pass there.

| ID | Improvement | Implementation and regression evidence |
| --- | --- | --- |
| 076 | Stop can cancel a release check before a request or between metadata chunks; cancellation remains distinct from a network error. | `UpdateCenter.check_for_updates`, wired to the existing Stop event in `DrawBot`; `test_update_maintenance_rc4` cancellation tests. |
| 077 | Release checks enforce a 30-second elapsed-time budget between redirects and response chunks, in addition to socket timeouts. An active socket read remains subject to its read timeout; this is not a hard wall-clock interruption. | `UpdateCenter._check_transfer_budget`; between-chunk budget regression. |
| 078 | Version parsing accepts either `v` or `V` consistently and rejects ambiguous non-ASCII numeral tags. | `normalize_tag` / `parse_version`; version-prefix and Unicode-numeral regression. |
| 079 | Release-page links are constructed for the selected tag in this repository instead of trusting an arbitrary `html_url`. | `check_for_updates`; malicious and unrelated metadata URL cases. |
| 080 | An installer asset still being uploaded is not offered as a completed update. | `installer_asset`; asset-state regression. |
| 081 | Installer handoff validates metadata again and holds a Windows read handle that denies writes and deletion while hashing and starting the verified file. | `launch_installer` / `_open_locked_installer`; native Windows replacement/write-denial and invalid-metadata tests. |
| 082 | Update downloads check available disk space before a network request or partial-file creation and explain how much space is required. | `download_installer`; low-space test verifies no request or staging file. |
| 083 | Binary downloads request unencoded bytes and reject unexpected content encoding or a conflicting Content-Length before reading the body. | `download_installer`; invalid transfer-envelope tests and existing streamed digest checks. |
| 084 | GitHub rate-limit failures explain the limit and Retry-After delay, and retain the Releases-page alternative. | `_raise_rate_limit`; HTTP 403 rate-limit regression. |
| 085 | A slower, older mobile-preview encode cannot replace a newer frame within the same session. | `MobilePreviewServer.update_images`; two coordinated encoding threads. |
| 086 | Unchanged mobile image content keeps its revision, avoiding repeated image reloads on phones. | `update_images`; identical-copy and changed-frame regression. |
| 087 | The opt-in preview server caps concurrent clients at 12 instead of creating unbounded request threads. | `_PreviewHTTPServer`; live sockets prove excess connections close and worker slots are recovered. |
| 088 | Idle or stalled preview clients have a five-second socket timeout, freeing workers and bounding slow writes. | `_PreviewHTTPServer.get_request`; idle-client expiry followed by a successful HTTP request. |
| 089 | Failure to start the preview server thread closes its socket and rolls back the published session state. | `MobilePreviewServer._start`; injected thread-start failure. |
| 090 | LAN discovery runs outside the image/state lock; cached addresses refresh when the sharing panel is reopened, and Stop cancels an in-progress start. | `start` / `state` / `urls` / `refresh_addresses`; blocked-discovery, cache and changed-network tests. |
| 091 | Advertised preview addresses are valid allowed IPv4 LAN addresses, deduplicated and sorted numerically; unusable public/IPv6 strings are omitted. | `local_ipv4_addresses` / `_is_local_client`; mixed-address discovery regression. |
| 092 | The phone page aborts stalled status requests, handles HTTP errors, hides stale images on disconnect and retries a failed image even when the frame revision has not changed. | Embedded mobile script; Node executes stalled-request, HTTP-error and same-revision image-retry browser fixtures. |
| 093 | The phone page uses image availability to show an empty state without requesting missing images, and gives the selected view and image accessible labels. | Embedded script; empty-frame and Original-view browser fixtures. |
| 094 | Invalid or non-finite wheel deltas no longer poison accumulated fractional scroll motion. | `SmoothScroll.ScrollAccumulator`; invalid-values regression. |
| 095 | Wheel input at the end of an inner panel can scroll its enclosing panel. | `SmoothScroll.install_scrolling`; nested-boundary routing regression. |
| 096 | Tree views, combo boxes, spin boxes, sliders and Shift-wheel retain their native input bindings. | Wheel dispatcher; native-control and horizontal-scroll regressions. |
| 097 | macOS source runs interpret native wheel units without incorrectly dividing them by Windows' 120-unit scale. | Wheel dispatcher; Aqua wheel fixture. |
| 098 | Cancellation prevents recovery input after a failed transaction, is never retried as a transient exception, and is checked again before accepting a successful operation. | `UiTransaction.retry`; cancellation-before-recovery, broad-retry and post-operation tests. |
| 099 | Invalid, NaN and infinite pacing parameters are rejected before they can reach UI waits. | `AdaptivePacer`; finite-configuration regressions. |
| 100 | Paint and its readable UI Automation PowerShell helper resolve their executable paths through the Windows API instead of trusting environment directory overrides. | `PaintPreparation` / `WindowsSystem.system_directory`; override regression and existing native PowerShell transport tests. |

The remaining Paint UI Automation operation still legitimately uses PowerShell.
The Python runtime and native extensions also remain part of the application.
These changes do not promise zero antivirus detections.
