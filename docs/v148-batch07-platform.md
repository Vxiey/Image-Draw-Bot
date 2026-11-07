# v1.0.148 batch07 — mobile publication and raster import

Baseline: `8a9c848b9dd0f2c4738aee729dace75be2a5778d`.

This batch contains **three distinct behavior groups**, MP01–MP03. Tests,
documentation, benchmark infrastructure and individual caller substitutions do
not add counts. The pre-existing HTTP authorization, LAN-only client policy,
session tokens, bounded clients and request deadlines remain in place.

## Changes and evidence

| ID | Previous user-visible behavior | Implementation and regression evidence |
| --- | --- | --- |
| MP01 | Starting mobile preview or accepting another plan synchronously resized, flattened and encoded all three PNGs on the Tk callback. Even an unchanged Original was recompressed for each plan. Equality was checked only after encoding. | `MobilePreviewServer.queue_images` captures owned snapshots on the image-owning thread and uses `MobilePreviewQueue.LatestImageQueue`: one encoder and one latest pending request. Unchanged immutable identities skip capture/encoding, individual unchanged views reuse their encoded bytes, and aliased views share one snapshot/PNG. Requests reserve generation/sequence before capture; superseded work cannot publish. Capture and encoder failures close owned buffers and allow an identical request to retry. The synchronous `update_images` API still rereads mutable inputs. `test_v148_platform_batch07_mobile_queue.py` and `_mobile_snapshots.py` exercise real PIL images, races, cleanup while exception tracebacks remain referenced, cancellation, thread construction/start failure, source mutation/closure after capture, weak identities, exact PNG parity and the actual memory limit. |
| MP02 | Several accepted source changes and plan invalidations never notified mobile preview. In Manual mode, Undo could restore a red desktop Original and clear its plan while the phone indefinitely retained the previous blue image and old plan. | Root's `DrawBot._sync_mobile_preview` coalesces a single Tk-idle callback, which reads current `PreviewViews` only when it runs. `show_previews`, `_mark_plan_stale` and existing adoption paths cover accepted source changes, settings/profile invalidation and new plans. Missing views are explicitly cleared. Mobile stop cancels the pending callback, invalidates its ticket and retains the server instance for restart, so an old native encode does not create a second independent encoder owner. Ordinary drawing Stop does not suppress already accepted images. `test_v148_application_batch07_mobile.py` exercises the real Undo and load handlers, Manual invalidation, current-state coalescing, display-layer selection, stale callbacks, session replacement/shutdown and safe retry after capture failure. |
| MP03 | Public image import tried every Pillow plugin. An EPS document named `.png`, labeled `image/png` in a data URL, or returned as `image/png` over HTTP reached Pillow's Ghostscript renderer even though the application advertises raster-image input. This renderer was outside the import worker's cooperative Stop handling. | `ImageImport.read_image` passes an explicit raster-format tuple to `Image.open`, preserving PNG/APNG, JPEG/MPO, WEBP, BMP/DIB, GIF, TIFF, ICO and AVIF. Unsupported documents/vector formats get a useful export-to-raster message before a document decoder or renderer runs. Four policy regression tests in `test_v148_platform_batch07_image_decoders.py` exercise local/data/HTTP EPS and WMF rejection with mocked renderer boundaries, all advertised raster decoders, AVIF, animated PNG and actual two-frame MPO files. Existing ICC, unsigned 16-bit, orientation, pixel/byte budgets and cancellation stay in place. |

The registry's existing **085/086** ordering and unchanged-revision guarantees
are retained, not counted again. MP01 addresses work performed before those old
checks, including the blocked caller and retained snapshot ownership. Using the
same `Simulated final`/background-toggle selection as the desktop is completion
of the existing shared-view contract (AX04), not another new group.

### Actual caller scope

At the baseline, zoom/pan alone did **not** call the mobile encoder. The old
synchronous cost occurred on mobile start, accepted image/plan events and a
reset/recovery path. The new central `show_previews` hook can also run after
viewport changes; identity skipping prevents those unchanged images from being
copied or encoded again.

The independent caller review traced Undo, image load, paste, capture-as-source,
recovery, upscale, background removal, settings/profile invalidation and plan
adoption to the central publication hooks. No Tk call occurs in the encoder.

### Raster decoder policy and its evidence

The pre-change public-reader reproduction used a minimal EPS document and mocked
`PIL.EpsImagePlugin.Ghostscript`: local, data-URL and HTTP-adapter inputs each
reached that boundary once. No Ghostscript process was executed, no input was
sent over an external network, and the observation establishes unintended
renderer dispatch rather than a Ghostscript vulnerability or malware verdict.

Pillow's [EPS documentation](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#eps)
describes its Ghostscript integration. Its [EPS source](https://pillow.readthedocs.io/en/stable/_modules/PIL/EpsImagePlugin.html)
shows the subprocess call with `-dSAFER`; that call does not receive this
application's Stop callback or elapsed budget. The documented
[`Image.open` formats parameter](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.open)
provides the per-call decoder boundary without changing process-global Pillow
configuration. JPEG's normal factory still identifies MPO, and PNG handles APNG.

The application now deliberately accepts its supported raster set; unadvertised
document/vector and other excluded formats require conversion first. Content
identification within that set remains independent of suffix and MIME. This is
one policy behavior, not one improvement for every format or source route. It
does not claim that native raster codecs can be interrupted during decoding or
that the supported files are intrinsically safe. Existing size limits and
between-operation Stop checks remain necessary.

The complete decoder module has **12 tests**: eight ICO-budget completion cases
and four new raster-policy cases. The related new/existing importer, redirect,
ICC, 16-bit and drop/workflow suites pass together: **67 tests, 0.181 seconds**,
no skips in this environment. AVIF parity is explicitly skipped on a Pillow
build without that optional codec; this run exercised its real decoder.

## Memory and cancellation limits

- Each request retains at most **32 MiB** of owned pixel cores, charged
  conservatively at at least four bytes per pixel, including RGB cores. Aliased
  views count once.
- Before capturing a replacement, the obsolete pending request is closed. There
  is at most **one active plus one pending/capturing request**, hence at most
  **64 MiB of retained snapshots per reused server instance**.
- If a full snapshot set would exceed the request limit, large sources are
  reduced to the existing **1,600-pixel maximum dimension** before queueing. The
  original source is not modified. Alpha/color-key conversion and resampling
  retain the existing encoder's pixel results.
- Caller-owned images, PNG bytes and Pillow/native resize/compression scratch
  allocations are **additional**. The 64 MiB statement is not a process RSS
  ceiling. The benchmark's first 25 MP request retained **12,288,000 bytes** of
  queued snapshots; it did not measure native peak memory.
- Copying, and reduction when necessary, occur on the caller thread. This is
  **not** a completely nonblocking submission API. Pillow native resize/PNG
  operations finish before supersession is observed. Checks between views and
  before publication prevent an obsolete result from becoming current.
- Reusing the same server object across stop/restart keeps the encoder ownership
  bound across sessions. The idle encoder exits; a still-active encoder can
  process the next session's one pending request after discarding its old result.
- `queue_images` is explicitly for immutable app image generations. General
  mutable callers retain `update_images`; the synchronous/queued ordering
  regression verifies that a late older result cannot overwrite a newer one.
- Errors in the background encoder log the exception **class only**. They do
  not copy source filenames, image metadata or exception arguments into a new
  log record. Network permissions and diagnostics privacy boundaries are not
  weakened.

## Reproducible measurements

Run from the repository root:

```text
python benchmark_v148_mobile_preview.py
```

Raw data: `docs/v148-batch07-mobile-benchmarks.json`. The script loads the exact
baseline `MobilePreview.py` through `git show`, uses seeded images, performs one
warmup pair and five alternating baseline/candidate pairs, and records source
SHA-256 values, Python/Pillow/NumPy versions and per-frame PNG hashes.

The measurement uses the real in-memory publication APIs and an inert server
handle: no listener, HTTP traffic, installer or external download. Caller time
includes snapshot capture/reduction. Completion time also waits for the encoder.
Hash comparisons occur outside the measured publication windows. These are
local publisher measurements, not Windows UI responsiveness or network timings.

| Workload | Median aggregate caller time, baseline → current | Median aggregate completion time, baseline → current | PNG encodes, baseline → current | Output |
| --- | ---: | ---: | ---: | --- |
| Three unchanged requests; 1600×1000 Original and two 640×400 views | 1,120.07 → **2.20 ms** | 1,120.07 → **365.95 ms** | 9 → **3** | Byte-identical PNGs |
| Three different plans sharing the same Original | 1,074.25 → **4.33 ms** | 1,074.25 → **543.76 ms** | 9 → **7** | Byte-identical PNGs |
| First request with 5000×5000 RGBA Original and two 640×400 views | 1,117.36 → **540.55 ms** | 1,117.36 → **1,089.86 ms** | 3 → **3** | Byte-identical PNGs |

The first large image therefore still spent about **0.54 seconds** in caller
capture/reduction on this machine. The substantial small-image caller reduction
does not justify claiming all mobile operations are immediate. The first large
request's total completion time was similar to the baseline.

## Validation

- **20 new backend tests pass.** PNG equivalence covers 13 mode/alpha cases,
  including RGB/L/RGBA/LA/palette/1-bit/CMYK/integer/float and color-key inputs.
- **9 root caller integration tests pass.** Combined independent run: **29
  tests, 1.068 seconds**, no skips.
- The backend plus existing mobile security, ordering, lifecycle, ownership,
  header-deadline and browser tests pass: **47 tests, 3.072 seconds**, no skips.
- These portable tests do not establish Windows GUI timing or a native peak-RSS
  limit. The common Windows CI/full-suite gates remain required for the complete
  checkpoint.

Primary implementation reference: [Pillow Image.copy and Image.resize](https://pillow.readthedocs.io/en/stable/reference/Image.html).
The library documents owned copies/resized images; the exact alpha and PNG
compatibility claims here are established by the repository's parity tests and
paired measurements, not inferred from documentation alone.

## Existing-contract completions — no additional groups

### IW36/IW38: intermediate image redirects respect bounded/cancellable transport

The public `ImageImport.read_image` reproduction accepted a 79-byte PNG with a
128-byte configured download budget after Requests had already read and retained
a **1,048,576-byte redirect body**. `stream=True` did not prevent that eager
intermediate read, and the importer could not inspect Stop/deadline until it
finished. This is a gap in the existing bounded/cancellable import contract, so
it adds **zero new improvement IDs**.

`ImageImport._download` now uses a short-lived Requests session whose `send`
checks the exact prepared HTTP(S) destination and the existing Stop/deadline
before every network hop. A response hook closes each unread redirect response
and exposes an empty body before Requests accesses `response.content`. The
standard Requests resolver still handles relative URLs, quoting, fragments,
authorization stripping, cookies, proxies and its existing redirect-count limit.
Final response size/Content-Length checks and cooperative body-read limits are
unchanged. Response/session cleanup cannot hide the primary cancellation/error.
This introduces no new host allowlist or ban on legitimate local HTTP images.

`test_v148_platform_batch07_import_redirects.py` contains **10 new public-import
tests**, using real Requests sessions/redirect machinery and an in-process
recording adapter with no external network. It verifies zero redirect-body reads,
all five normal redirect statuses, relative quoting/fragments, same-origin auth,
cross-origin stripping, cookies, proxy/TLS/timeouts, local HTTP compatibility,
invalid destinations, the existing loop limit, Stop/deadline before the next
request, cleanup failure and final body-limit enforcement. Six older mock call
sites in `test_v148_import_batch03.py` now intercept `requests.Session.get`; their
existing assertions remain intact.

Independent local run of the new redirect module, existing import suite and
current ICC/16-bit import suites: **40 tests passed, 0.101 seconds**. As before,
an active connection/header read is governed by socket timeouts; the elapsed
budget is cooperative and not a hard wall-clock interrupt.

Primary evidence: the [official Requests session source](https://requests.readthedocs.io/en/latest/_modules/requests/sessions/)
shows `resolve_redirects` consuming `response.content` before advancing, including
the path that prepares the next request when automatic redirects are disabled.

### Existing import pixel budget: inspect ICO payload before eager decode

Pillow loads an ICO's selected PNG/DIB payload inside `Image.open`, before the
importer's ordinary dimension check. Directory dimensions are limited to 256,
but they can disagree with the embedded payload. A complete **3,132-byte** icon
fixture contains a valid, streamed one-bit PNG of **25,001 × 1,000 pixels**. The
exact batch baseline reached the PNG pixel decoder with those dimensions despite
the normal 25 MP budget; the current importer rejects it before any pixel load.
The test replaces the decoder boundary, so neither version allocates that large
decoded image during verification.

`ImageImport._preflight_icon_size` scans fixed-size directory entries, retains
only the entry selected by Pillow's existing stable area/depth ordering, and
checks the actual PNG IHDR or supported DIB dimension header before opening the
icon. It observes Stop during long directories and restores the stream position.
The normal size check still runs for all imported images. No process-global
Pillow limit is changed, and an oversized *unselected* entry does not invalidate
an otherwise usable selected image. This closes an existing budget gap and adds
**zero new improvement IDs**.

`test_v148_platform_batch07_image_decoders.py` adds **8 tests** for the real
default and custom budgets, supported DIB header layouts and top-down height,
exact pixels from genuine PNG/DIB multisize icons, stable selection order,
unselected payloads, Stop and truncated directories. Combined with the existing
import and new redirect modules: **32 tests passed, 0.078 seconds**.

Primary implementation evidence: [Pillow's ICO decoder source](https://pillow.readthedocs.io/en/stable/_modules/PIL/IcoImagePlugin.html)
calls `load` from `_open` and uses the embedded PNG/DIB dimensions. The directory
selection and decoded-pixel compatibility are checked against the installed
Pillow implementation in the regression suite.

## Final local integration gate

The frozen source passed **3,355 tests in 71.096 seconds**, with **35 platform/hardware skips** and no failures. Source hashes were unchanged during the run. All independent area reviews are closed. The 5,000-cycle source gate, source-package hygiene and all eight exact-raster fixtures passed, with zero mismatched pixels. Windows/Linux CI on this new checkpoint remains pending; version 1.0.148 is not published.
