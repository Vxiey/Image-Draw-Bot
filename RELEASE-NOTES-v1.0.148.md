# Image Draw Bot v1.0.148 — development release notes

**This version has not been published.** The current development checkpoint contains 699 distinct behavior improvements: the original 100-change baseline, 162 changes in batch 01, 236 changes in batch 02, 116 changes in batch 03, 54 changes in batch 04 and 31 changes in batch 05. Work continues toward the requested 1,000-improvement target before release. The [complete progress ledger](docs/IMPROVEMENTS-v1.0.148.md) maps global IDs to implementation and regression evidence. Tests, documentation and version promotion do not increase the count.

## Batch 05: drawing verification, recovery and publication identity

- Preserve a marked subject and its mode with the exact recovered image. A failed image checkpoint cannot attach another image's selection to the old raster.
- Avoid copying the remaining drawing sequence when runtime policy cannot replan. Restore known color/tool/brush state after a released-mouse pause.
- Keep correction-only retries from replaying canvas fills, use the original per-path timing reference and record a fresh before/after result for every attempt.
- Verify the brush actually selected for each entry. Clipped color probes remain unavailable evidence; boundary-spanning lines obtain a short probe from their guarded interior, and correction-only input follows the same verification contract.
- Match near-neutral colors consistently across scalar/vector/GPU paths. Represent untouched white canvas correctly when no white palette color exists, preserve isolated colored details and sample both sides of real picture edges.
- Reduce fragmented-component statistics work and preview-metric scratch memory while preserving exact results. The paired ledgers disclose slower workloads as well as improvements.
- Parse actual image elements and URI lists in drops, support the already decodable TIFF/ICO/APNG formats and avoid interpreting inline image data as a filesystem path.
- Keep an open guide synchronized with the profile, improve scaling/keyboard navigation, release owned root callbacks and coalesce redundant resize work. Position drop overlays at verified signed desktop coordinates and cancel delayed region selection when Stop is pressed.
- Fail source packaging on unreadable included trees, validate build CLI arguments before side effects, bind each release tag to its actual build commit and serialize all release publishers so their assets cannot interleave.

## Batch 04: application policies, detailed plans and native lifecycle

- Preserve explicit Pixel Accurate and Unlimited settings through automatic profile/planning policies; keep watchdog Off meaningful while retaining Stop and bounded dry-run behavior.
- Make settings application transactional, preserve unknown-schema documents, isolate invalid preference fields and stop dependent actions when saving fails.
- Recover images through a tracked cancellable worker, disarm before recovery and treat an already completed sequence checkpoint as a no-op.
- Preserve final detail execution order and actual brush footprints in previews and verification; reduce repeated palette/source analysis allocations.
- Improve setup readiness, target-specific guidance, profile resets and scaled layout. Retain pending native mouse cleanup, propagate helper cancellation and redact diagnostic metadata.

Batch 04 passed 2,934 local tests with 23 platform/hardware skips, the source gate,
source hygiene and eight exact-raster fixtures. Its published checkpoint passed
Windows/Linux, dependency, CodeQL and packaged Windows GUI/native drag-and-drop
CI. Batch 05 passed 3,059 frozen-source local tests with 26 platform/hardware
skips, the source gate, source-package hygiene and eight exact-raster fixtures.
All independent reviews are closed; its new Windows/Linux CI remains pending.

## Batch 03: visible image fidelity, bounded work and responsive operations

- Preserve every source pixel when a forced dark palette anchor displaces another retained colour. Price actual native precision and every colour revisit in progressive drawing budgets.
- Make hybrid and sketch previews depict the exact simulated brush footprint, including single pixels, even brush widths and Pillow's nearest-neighbour sampling phase.
- Score unexpected contours, skip source white before palette estimation, merge identical colour actions and reduce repeated colour-name/distance work.
- Reduce background-removal temporary arrays and unnecessary neighbour comparisons. Analyse visible alpha-composited pixels and preserve valid image/Undo/plan state for failed or no-op edits.
- Stream imports into bounded snapshots, verify byte limits and declared HTTP sizes, and carry Stop through image decoding and export publication. Preview encoding runs off the UI thread.
- Keep subject previews and ROI callbacks tied to the current image; fit window geometry to display scaling and recover safely from failed preview-page changes.
- Verify complete CUDA smoke-test outputs, respect actual available GPU memory, and compare CPU/CUDA/OpenCL benchmark workloads with matching transfers and numerical reference checks.
- Track hardware/resource tests as cancellable operations, preserve previous recommendations until successful complete publication and prevent parallel drawing from competing with those tests.

The batch includes independent reviews, corrected adversarial edge cases and
paired output-checked CPU measurements. Several changes trade CPU time for lower
temporary allocation; the area ledgers report both outcomes. Final frozen-source
discovery passed 2,800 tests in 70.634 seconds with 22 platform/hardware skips and
unchanged source hashes. All four independent area reviews are closed. The
5,000-cycle source gate, source-package hygiene and eight exact-raster fixtures
also passed. Its published checkpoint passed Windows/Linux and packaged Windows verification.

## Batch 02: calibration, execution and application reliability

- Revalidate owned Paint/color dialogs and live browser controls before using their coordinates. Fresh selected-brush evidence is required before reducing the conservative canvas inset; unknown or unconfirmed switches do not authorize drawing outside that inset.
- Apply verified full opacity, retain unknown-state reporting, and propagate Stop from live GUI setup through canvas, palette and verification scans.
- Enforce strict target/canvas containment and finite evidence before committing setup. Palette-only calibration clears a stale canvas instead of retaining another window's drawing area.
- Preserve valid normalized polygons and exact boundary projection, use immutable prepared geometry, and honor cancellation through delivery verification and post-draw scoring.
- Learn from measured completed operations and real fill clicks, preserve truthful runtime counts, and keep invalid or contradictory evidence out of learning databases.
- Enforce configured preview-memory limits, cancel queued resource work, preserve atomic profile/recovery writes and close owned image buffers on failure.
- Bound mobile header lifetimes, preserve completed release assets during failed rebuilds, produce deterministic portable ZIPs and explicitly exclude optional CUDA libraries from standard builds.
- Keep queued imports and previews from reviving cancelled work, repair background-removal Undo state, improve wizard readiness, and avoid unchanged sidebar layout work.

The batch includes reproducible CPU microbenchmarks for calibration scans, checkpoint storage, timer ROI analysis, preset analysis and planning helpers. Exact-output comparisons accompany the applicable optimizations. Some measured helpers remain unchanged or slower; their correctness and allocation improvements are reported separately.

## Additional planning, color and performance improvements

- Preserve protected micro-details, directed stroke geometry and exact pixel boundaries; correct int16 luminance overflow for bright source pixels.
- Enforce both path and color dry-run limits, retain semantic outline barriers and account for actual brush/color state in execution estimates.
- Bound palette fallback allocation across both image dimensions, reuse color conversions and geometry measurements, and reduce large-path preview allocations.
- Keep transparent pixels out of drawing strokes and align scalar/vector RGB matching. Validate optional palette caches and fingerprint the complete visible image.
- Check cancellation before expensive allocations, within long individual work units and before publishing completed results. Release portrait GPU sessions on all terminal paths.

## Additional persistence, resource and UI improvements

- Preserve existing state on real disk errors and serialize cooperating learning writers across threads/processes.
- Reject malformed or nonfinite learned/calibration evidence; retain legitimate zero measurements and respect explicit CPU/no-save settings.
- Bound queued executor work and row memory budgets; use one consistent hardware snapshot per allocation.
- Keep native paste in text controls, restore UI state after startup failures, yield long event queues and avoid redundant preview layouts.
- Save recordings through unique atomic staging files, preserve existing recordings on failure and release owned capture buffers.

Batch 01 passed 2,202 local unittest tests with 19 platform/hardware skips. Batch 02 passed 2,557 local tests with 22 platform/hardware skips, its 5,000-cycle source gate and eight exact-raster engine fixtures; its published checkpoint passed Windows/Linux and packaged GUI/native drag-and-drop CI. Batch 03's published checkpoint also passed those checks. Area ledgers contain reproducible CPU measurements and exact-output comparisons; physical GPU behavior and real drawing remain separate verification scopes.

## Original 100-change baseline

## GPU detection and execution

- Replace the background PowerShell GPU query with Windows' native DXGI API.
  This preserves dedicated-memory values above 4 GiB and avoids assigning a
  display-adapter ordinal to a CUDA device.
- Resolve Windows GPU utilities through OS-reported system/vendor directories
  instead of PATH, and keep distinct adapters and their metadata separate.
- Correct CUDA device selection across worker threads, kernel scalar argument
  widths, memory-pressure retries and measured CPU/GPU routing thresholds.
- Keep hardware-profile loading resilient to malformed data, avoid loading
  compute libraries solely to read package versions, and validate optional
  compute runtimes in the selected virtual environment.

## Windows, diagnostics and packaging

- Load Windows system DLLs through a System32-restricted native loader that is
  not redirected to a bundled filename by PyInstaller's ctypes wrapper.
- Publish complete diagnostics and source archives with atomic replacement;
  bound diagnostic inputs and redact additional local identifiers and secrets.
- Validate release archive paths, Windows-equivalent duplicate names, link
  entries, exact checksum coverage and manifest metadata before publication.
- Validate native target metadata and the entire saved crash-dump configuration
  before applying the corresponding operation.

## Images, profiles and session recovery

- Bind recovery state to its cached image, preserve previous work on failed
  writes, bound recovery inputs, and keep restored drawing input disarmed.
- Preserve color zero in sequence progress and validate compact resume state
  without expanding every operation into a separate Boolean object.
- Prevent custom-profile identity collisions and roll back failed profile
  imports/resets instead of leaving a partially changed configuration.
- Correct upscale input handling, make Corner color background removal distinct
  from Auto, and honor cancellation before expensive image work.

## Updates, mobile preview and UI

- Make release checks cancellable and bounded across slow responses; explain
  GitHub rate limits and detect insufficient disk space before downloading.
- Validate installer response metadata and hold a Windows handle that prevents
  the verified installer from being modified or replaced during launch.
- Keep mobile frames in request order, avoid reloading identical images, bound
  concurrent/idle clients and reconnect the phone page after stalled requests.
- Improve nested-panel and platform-specific wheel handling, retain native
  control bindings, and stop UI recovery actions promptly after cancellation.
- Resolve Paint helper executable paths through the Windows API. Its existing
  readable PowerShell UI Automation operation remains available when requested.

## Validation and antivirus status

Publication requires the source gate, complete regression suite, executable
self-tests, package validation and a silent install/self-test/uninstall round
trip. Pull-request CI also audits dependencies and opens the built Windows GUI,
including native drag and drop. The native DXGI probe runs in source, frozen and
installed self-tests.

The Windows executable and installer remain **unsigned** because no trusted
code-signing identity is configured. The application still includes Python and
native extensions; normal bundled-Python behavior can continue to match generic
detection rules. These changes do not promise zero antivirus detections, and a
scan of an older hash does not describe this release.

Planned downloads are a Windows installer, a portable ZIP, SHA-256 checksums and a
release manifest; they become available after verified publication. See the
[antivirus investigation](docs/ANTIVIRUS-REVIEW-2026-11.md)
for artifact-specific findings and unresolved observations.
