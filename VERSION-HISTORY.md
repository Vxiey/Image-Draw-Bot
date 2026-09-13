# Image Draw Bot v1.0.146-rc2 — Background Removal & Recognition-First Extra Fast

- Promote the classical non-AI background-removal hardening merged after rc1.
- Promote target-profile + Drawing Style aware Extra Fast planning so recognition and region structure win over generic line soup.
- Preserve the final-execution-sequence ETA model and measured local timing calibration.
- Correct the installer numeric version resource to 1.0.146.0 and synchronize active version regressions.
- Keep the complete Windows release gate authoritative before publication.

# Image Draw Bot v1.0.146-rc1 — Release Build Recovery

- New RC line based on 1.0.145-rc29.
- Windows release packaging fixes `DrawingStyleProfiles` PyInstaller argument ordering and adds a focused regression test.
- Runtime drawing/planner behavior is intentionally unchanged from the validated rc29 baseline.

# Image Draw Bot v1.0.145-rc29 — Stability & Planner Validation

- Ignore stale preview plans with a monotonic preview generation ID so cancelled/settings-invalidated workers cannot overwrite a newer UI state.
- Route all centralized background-worker exceptions into the consolidated debug error log while preserving normal session diagnostics.
- Quality-gate local ETA learning: incomplete execution, untrusted final-canvas evidence, low accuracy and missing coverage cannot train future timing estimates.
- Keep full-detail Preview on the real final planner geometry while retaining its bounded CPU-only preview resource policy.
- Preserve existing Paint/browser pre-input target validation, CanvasGuard and auto-recalibration rather than duplicating a second safety system.
- Remove rc27/rc28 one-off integration triggers/scripts/workflows before mainline release.

# Image Draw Bot v1.0.145-rc28 — Background Remover & PNG Workflow

- Add **Remove BG** beside image import. It converts only border-connected background pixels to transparent alpha instead of deleting same-colour details inside the subject.
- Transparent pixels are passed directly into the existing planners as empty canvas, so they produce no strokes and can materially reduce real drawing time.
- Add **Undo** for the background-removal edit without interfering with the existing upscale restore path.
- Add **PNG** export for the current RGBA image, preserving transparency.
- Run removal and PNG encoding in cancellable workers so large source images do not freeze the UI.
- Report removed area and approximate drawable-pixel work reduction immediately; final stroke count and ETA remain authoritative after Build preview.
- Fail closed when the detected background would consume more than 98.5% of the image.

# Image Draw Bot v1.0.145-rc27 — Completed Drawing Intelligence

- Save a profile-local Completed Drawing Analysis after clean real draws with predicted vs actual time, typed operation costs, brush decisions and prioritized optimization suggestions.
- Show a real **Drawing Accuracy Score 0–100** from the final canvas snapshot versus the original source whenever safe screenshot capture is available, independent of Auto Tuner state.
- Keep screenshots and source pixels in memory only; completed reports persist metrics, not image data.
- Expose Gartic brush selection as the real five-level **1–5** control while keeping calibrated physical footprints separate for CanvasGuard and stroke simulation.
- Add Gartic opacity **Auto / 10–100%**. Auto analyzes edge density, color complexity and smooth tonal variation; reduced opacity is fail-closed unless the slider is visually verified.
- Time opacity changes as real UI operations so ETA/optimization work can learn their cost.

# Image Draw Bot v1.0.145-rc26 — Gartic Google Drop-In & Canvas Detection

- Google/Chromium image drags can be released directly over the detected Gartic canvas and continue through the guarded Browser One-Click start path.
- Gartic canvas discovery now ranks multiple candidates and has a conservative violet-frame fallback for partly drawn canvases.
- F1 Quick Start uses the existing safety/setup path instead of bypassing it.
- rc25 Extra Fast regional planning and the five-brush Gartic ladder remain intact.

# Image Draw Bot v1.0.145-rc25 — Extra Fast Regional Quality Fix

- Extra Fast now budgets whole connected regions instead of destructively truncating individual paths after planning.
- Gartic keeps the verified 2/4/8/16/28 px brush ladder and the regional scheduler can spend time on large safe coverage before structure/detail recovery.
- Simulated final now follows the same adaptive regional execution sequence as the real draw, including per-path brush widths.
- Stale Strong simplify settings no longer leak into Extra Fast.
- Existing calibrated Fill safety and the rc24 exact H/V raster guarantees remain intact.
- Release metadata, installer and active regression version assertions are synchronized atomically.

# Image Draw Bot v1.0.145-rc24 — Regional Axis + Sketch Dense Hybrid

- Extra Fast can choose exact horizontal or vertical runs per connected region using the existing execution-cost guard.
- Dense Gartic Sketch regions can use cheaper exact H/V runs while thin structural contours remain on the contour tracer.
- Raster coverage remains exact with no gap bridging or dropped pixels.
- Release metadata, installer and regression version assertions are synchronized atomically.

# Image Draw Bot v1.0.145-rc23 — Region Brush ROI Packing

- Multi-brush connected-region packing now allocates temporary masks only for each component bbox.
- ROI paths are translated back to global coordinates before cost/execution.
- Exact coverage, spill rejection and residual fallback remain authoritative.

# Image Draw Bot v1.0.145-rc22 — Learned Cursor Travel Integrity

- Learned stroke timing no longer erases real cursor distance.
- Generic stroke runtime measurements feed short/long stroke planning through safe aliases.
- ExecutionCostModel v4 preserves stateful routing after calibration.

# Image Draw Bot v1.0.145-rc21 — Complete Cost Model Unification

- Live planner cost decisions now converge on one stateful ExecutionCostModel.
- Fill seals and engine benchmarks use the same model; Region Fill fallback is deterministic.
- HybridCostModel remains only for compatibility, not live planner selection.

# Image Draw Bot v1.0.145-rc20 — Pixel Accurate Unified Execution Cost

- Pixel Accurate local orientation and component order now use the same stateful execution-cost model as Extra Fast, Region Fill and visible ETA.
- Exact coverage and correction behavior are unchanged.
- Legacy cost-aware planning can still be disabled explicitly.

# Image Draw Bot v1.0.145-rc19 — Extra Fast Unified Execution Cost

- Extra Fast 2.0 now uses the same stateful execution-time model as Adaptive Hybrid, Region Fill and visible ETA.
- Source-to-canvas scale participates in path-limit and reorientation decisions.
- Complete downstream baseline fallback remains authoritative.

# Image Draw Bot v1.0.145-rc18 — Unified Region Fill Cost

- Fill-vs-stroke decisions now use the same stateful ExecutionCostModel as Adaptive Hybrid and Estimated Draw Time.
- Fill safety logic is unchanged; only execution-time comparison is unified.
- Legacy Fill costing remains fallback-only.

# Image Draw Bot v1.0.145-rc17 — Unified Execution Cost ETA

- Estimated Draw Time now shares the planner's stateful execution-cost model.
- Region Fill timing reuses the batch-aware Fill estimator.
- Local measured timing is applied once, not inside both base model and visible ETA correction.

# Image Draw Bot v1.0.145-rc16 — Preview Planner Parity

- Manual / Auto full Build preview now uses the same full-detail planner path as final Draw.
- Auto light remains the explicit fast approximation.
- Full-detail preview can use up to four bounded CPU workers instead of always one.

# Image Draw Bot v1.0.145-rc15 — CPU/GPU Performance Engine

- CUDA Pixel Accurate simulation now retries smaller VRAM work units before CPU fallback.
- Accuracy scoring uses bounded GPU row tiles rather than requiring full-frame score masks.
- Transient OOM no longer permanently quarantines an otherwise healthy GPU workload route.
- Auto CPU scheduling reacts to live RAM pressure by reducing concurrency and chunk size.

# Image Draw Bot v1.0.145-rc14 — Resume & Checkpoints

- Progressive and Pixel Accurate execution sequences can now resume safely.
- Dynamic Replanner order changes no longer invalidate completed-work checkpoints.
- Sequence checkpoints store compact execution coverage and remaining-work identity without restoring armed input state.
- Temporary browser disappearance can preserve progress for the next explicitly started, recalibrated run.

# Image Draw Bot v1.0.145-rc13 — Calibration & Recovery

- Calibration state now exposes component confidence and an overall safety-weighted health score.
- Cached browser palettes can survive a small canvas-only drift, avoiding unnecessary full palette recalibration.
- Large layout/DPI changes still force full recalibration before mouse input.
- Transient read-only calibration failures receive bounded adaptive retries.

# Image Draw Bot v1.0.145-rc12 — ETA Calibration 2.0

- Learned operation timing now uses stable per-operation EMAs instead of only the latest completed draw.
- ETA calibration measures how much of the current operation mix is covered by real timing evidence.
- Typed runtime evidence can correct cold operation costs both downward and upward.
- The global completed-draw ratio is blended only for residual error, avoiding double-counting operation timing.
- ETA uncertainty narrows only when repeated operation evidence covers the current plan.

# Image Draw Bot v1.0.145-rc11 — Smart Color Engine

- Added local spatial dominance and perceptual uniqueness to palette importance scoring.
- Small locally authoritative accents can keep a palette slot without overpowering broad coverage.
- Colour-switch cost now participates in the stop decision for low-value extra palette colours.
- Existing dominant-hue, tone-ladder and region-detail protections remain authoritative.

# Image Draw Bot v1.0.145-rc10 — Pixel Accuracy 2.0

- Added per-connected-region accuracy scoring across color, coverage, edges and protected detail.
- Pixel correction passes now report marginal accuracy gain and repaired pixels per correction path.
- Later correction passes can stop when simulated marginal repair efficiency becomes negligible.
- Existing coverage maps, pixel error maps, CPU/GPU simulation and correction safety remain authoritative.

# Image Draw Bot v1.0.145-rc9 — Progressive Drawing 2.0

- Progressive passes now seed broad forms and contours across a bounded 4x4 spatial grid before local refinement.
- The renderer keeps phase barriers and source geometry unchanged while making the whole subject recognizable earlier.
- Progressive entries now carry bounded importance, structural score and optional-detail metadata for runtime deadline decisions.

# Image Draw Bot v1.0.145-rc8 — Dynamic Replanner

- Added live runtime replanning on top of the existing DeadlineScheduler.
- CATCH_UP/PANIC can reorder only remaining already-safe stroke paths inside contiguous phase barriers; geometry, colors and brush widths are never rewritten.
- Non-stroke operations remain hard barriers and candidate replans are rejected if they increase color/brush transitions.
- Replanning is throttled by measured runtime samples and exposed through deadline telemetry.

# Image Draw Bot v1.0.145-rc6 — Region Brush Packing

- Added exact multi-brush region packing for verified browser brush ladders such as Gartic 2 / 4 / 8 / 16 / 28 px.
- Large safe interiors are packed largest-first, then smaller verified brushes repair remaining pixels.
- Every emitted brush footprint is simulated against the exact connected component; unsafe or incomplete candidates fall back to connected runs.
- Fixed even-sized brush erosion so planner safety matches the real 2/4/8/16/28 px execution footprint.
- Removed the old 1 px brush requirement and stopped isolated hybrid paths from requesting a brush control that the target does not expose.

# Image Draw Bot v1.0.145-rc5 — Smart Fill Engine

- Added conservative Fill escape prediction and planner-proven contour sealing.
- Seal strokes are restricted to pixels inside the connected region and are included in real execution cost.
- Existing Fill hard blockers and runtime guard verification remain authoritative.

# Image Draw Bot v1.0.145-rc4 — Gartic Five-Brush CanvasGuard

- Verified Gartic controls can use 2 / 4 / 8 / 16 / 28 px with a brush-specific CanvasGuard.
- A broad brush no longer forces its safety inset onto every path in the render.
- Legacy/unverified controls retain the conservative global guard fallback.

# Image Draw Bot v1.0.145-rc3 — Fill, Brush and ETA Reliability

- Bound stateful Fill safety simulation to local ROIs while preserving global coverage state, reducing repeated full-canvas allocations.
- Make Extra Fast and RegionFill economics batch-aware so same-color Fill candidates are not penalized by duplicated tool-switch overhead.
- Improve adaptive brush planning with geometry-aware brush selection and collapse transient speed-only upshifts that would cost more UI switching than they save.
- Estimate draw time from the final execution sequence, including actual color, brush, Fill, verification and tool transitions instead of relying only on planner summary estimates.
- Keep existing browser CanvasGuard limits authoritative; full Gartic 5-brush CanvasGuard support remains follow-up work rather than being claimed complete in this RC.
- Include regression coverage for the Fill ROI allocation and batch/sequence cost-model fixes.

# Image Draw Bot v1.0.145-rc2 — Gartic Auto Tools

- Add conservative automatic Brush, Fill, Eraser and Clear selection for verified Gartic Phone layouts.
- Extend the same fail-closed tool-layout path and automatic brush-size presets to Gartic.io.
- Prefer manual anchored tool calibration when present, then fall back to visually verified browser-tool inference.
- Restore Brush automatically after Fill and Eraser-based canvas clearing.
- Keep multi-size Auto Brush bounded by BrowserBrushSize and CanvasGuard.
- Refuse guessed tool clicks when browser-layout confidence is low.
- Preserve the rc1 Total Draw Timer, automatic pixel brush width, Paint UI Automation sizing, profile isolation and ETA calibration.

# Image Draw Bot v1.0.145-rc1 — Verified Drawing Baseline

- Begin the 1.0.145 release-candidate line from the verified rc14 runtime.
- Retain Total Draw Timer, Automatic Pixel Brush, Paint UI Automation sizing and profile-isolated ETA calibration.
- Preserve existing drawing-engine, calibration, preview, profile and cancellation behavior.

# Image Draw Bot v1.0.144-rc14 — Total Draw Timer & Automatic Pixel Brush

- Add a visible live drawing timer with elapsed time, estimated remaining time and projected total while a real drawing is running.
- Show the exact measured **Total draw time** after a completed drawing and keep it visible in Safety & draw and the preview workspace.
- Make Brush width support **Auto** as the default while preserving manual 1–50 px input and old saved numeric settings.
- Select the automatic baseline from target canvas size plus image edge/color complexity, with 1 px retained for Pixel Accurate and protected-detail workflows.
- Microsoft Paint preparation now sets the requested/automatic Pencil pixel size through verified UI Automation RangeValuePattern instead of always forcing 1 px.
- Keep browser adaptive brush switching safe: only verified controls are used, with smallest verified brushes reserved for fine details/corrections.
- Isolate learned ETA calibration by rendering mode, preset, draw quality and render style in addition to profile/tool/brush/color workflow.
- Existing CanvasGuard, calibration, cancellation and manual brush fallbacks remain mandatory.

# Image Draw Bot v1.0.144-rc13 — Automatic Image-Aware Brush Selection

- Analyze the actual planned image geometry and classify it as detail-heavy, balanced or flat-shape before assigning brush widths.
- Automatically use a broader verified brush for large flat regions when that reduces work without weakening CanvasGuard.
- Automatically downshift to smaller verified brushes for contours, narrow components, protected details, cleanup and accuracy corrections.
- Let supported browser targets reserve a bounded safety inset for one verified automatic brush upshift; very large brush presets are never selected just because they exist.
- Keep low-confidence or incomplete brush-control detection fail-closed: no guessed control clicks and no invented dynamic brush sizes.
- Preserve the existing fixed brush behavior on targets that do not expose verified multi-size controls.
- Add deterministic Auto Brush diagnostics with image classification, selected base/detail/mid sizes, reasons and planned brush-switch counts.
- Update the Brush width help so the value is clearly a baseline for automatic selection rather than a required single fixed width.

This release keeps the existing drawing geometry authoritative. Automatic brush choices are constrained by verified target controls, per-path detail protection and CanvasGuard, and the release remains gated by the complete Windows regression suite, self-test, package validation and silent installer round-trip.

# Image Draw Bot v1.0.144-rc12 — Paint palette transaction stability

- Harden Microsoft Paint picture-palette preparation with explicit OPEN → WRITE → VERIFY → COMMIT → VERIFY transaction states.
- Retry transient Paint RGB-entry failures up to three bounded attempts with adaptive backoff instead of continuing with stale UI state.
- Re-read calibrated Edit colors controls during recovery and after every committed custom color before moving to the next RGB value.
- Never click + / Add to custom colors until the live R/G/B fields have been verified for the requested color.
- On cancellation or final failure, safely escape the Paint modal and always release native input ownership.
- Preserve the existing picture-palette planner, perceptual refinement, cache, CanvasGuard, render-resume and anchor-safety behavior.
- Keep possible Fill leaks as a hard stop; regions rejected before Fill continue to use the existing safe stroke/scanline fallback.
- Add focused regression coverage for retry bounds, transient recovery, exception preservation and no premature Add-to-custom-colors click.

The release remains protected by source-package checks, portable raster/planner regressions, the complete Windows regression suite, ImageDrawBot self-test, packaged-release validation and silent installer install/uninstall verification before publication.

# Image Draw Bot v1.0.144-rc11 — Shutdown stability fix

- Fix a Windows shutdown crash where CustomTkinter/Tk could receive a second destroy call after the Tcl application had already been destroyed.
- Make branded root destruction idempotent so converging close/startup-error/teardown paths safely become a no-op after the first shutdown.
- Ignore only the specific TclError that means the application is already destroyed; unrelated Tcl errors still surface normally.
- Install the shutdown guard before optional icon/branding setup so teardown remains protected even if decorative branding cannot load.
- Add regression coverage for the exact "can't invoke destroy command: application has been destroyed" failure and repeated root.destroy() calls.
- Keep the compact UI and all rc10 drawing/rendering behavior unchanged.

The release remains protected by source-package checks, the complete Windows regression suite, ImageDrawBot self-test, packaged-release validation and silent installer install/uninstall verification before publication.

# Image Draw Bot v1.0.144-rc10 — Compact UI and release update fix

- Reduce the default sidebar density with progressive-disclosure sections while keeping the five-step workflow and all existing controls.
- Keep target selection, image loading, one-click setup, core drawing preset and preview/draw actions visible first.
- Move profile/ink extras, image automation, manual calibration, fine tuning, preview options and duplicate safety shortcuts behind clear expandable sections.
- Keep Advanced and Developer controls available, but start the largest groups collapsed so the settings panel is easier to scan.
- Preserve the existing Tk variables, callbacks, saved profile values and profile-scoped visibility; the compact layer only changes presentation.
- Add regression coverage for compact UI structure, compatibility markers and profile-aware visibility.
- Publish this as a new rc10 installer so rc9 installations can detect the update through the existing verified GitHub Releases updater.

The updater security model is unchanged: automatic installation still requires a versioned GitHub Release, the expected installer filename, published SHA-256 digest and size checks before launch.

# Image Draw Bot v1.0.144-rc9 — Refine picture colors and simplify Paint setup

- Remove the separate Smart custom palette / exact color button and its help block. Use the existing Custom color palette for picture or automatic Paint preparation.
- Refine the image palette using bounded OKLab source-color sampling, fill unused color slots, and preserve small color accents.
- Accept refinement steps only when sample squared color error improves without increasing the sample 95th-percentile error.
- Match image-palette colors by nearest OKLab distance, avoiding the standard-palette brightness bias in this workflow.
- Keep the same palette in preview and drawing. Keep the Paint + batch, 24-slot preparation limit, cancellation and 750 ms pauses.

The analysis uses at most 16,384 samples, eight refinement iterations and small distance chunks. Existing analysis caches are invalidated. After updating, rerun Custom color palette for picture and Build preview to use the refined palette. Photographic gradients remain approximations with a limited color count.

Regression coverage checks tone gradients, small saturated accents, deterministic output, cancellation, shared preview/runtime colors and Pixel Accurate planning. Actual Paint drawing still depends on the target installation and calibration.

# Image Draw Bot v1.0.144-rc8 — Use the prepared image colors

Pixel Accurate previously bypassed the image-specific RGB palette and mapped the image to the standard toolbar palette. Saving a picture palette also left the old preview and exact-color status on screen.

- Use one ordered image RGB palette for Pixel Accurate mapping, correction simulation, previews and runtime color selectors.
- Use the prepared palette in the normal color-run planner too; keep it isolated to the same image and Microsoft Paint profile.
- Build picture colors from measured source clusters without substituting standard palette colors. Invalidate older picture-palette analysis caches.
- Refresh RGB calibration status and invalidate the old preview after picture-palette preparation.
- Stop if an exact image color cannot be selected instead of silently substituting a standard palette color.
- Retain + saving, one open dialog for the batch and at least 750 ms between additions.

After updating: select Microsoft Paint, run Custom color palette for picture again, then Build preview. The custom palette is still a limited-color approximation of a photograph. Native Paint behavior and swatch insertion require a real run on the target Paint version.

Regression coverage checks source-to-input RGB values, both rendering paths, runtime selectors, missing calibration, stale preview invalidation and image/profile isolation.

# Image Draw Bot v1.0.144-rc7 — Save picture colors in Paint

- Custom color palette for picture now presses Paint's + / Add to custom colors for each selected image color. OK alone did not save custom slots.
- Keep Edit colors open for the batch and press OK once at the end.
- Allow at least 750 ms after each Add action; preserve cancellation between colors.
- Identify the Add control and verify the entered RGB values before saving. Stop if controls or values cannot be verified.
- Bound picture-palette preparation to 24 colors for the modern Paint layout shown in the report.

Includes rc5/rc6 calibration and readiness fixes. Automated tests cover sequence, pacing and fail-closed behavior; a real run on the user's Paint version is still needed to confirm slot insertion and crash resolution.

# Image Draw Bot v1.0.144-rc6 — Picture palette stability

- Calibrate only RGB controls for Custom color palette for picture; do not change Pencil/size as part of this action.
- Wait for identifiable RGB fields before typing, and use their current positions.
- Verify Edit colors has closed before preparing the next color; foreground ownership alone is insufficient.
- Stop the sequence on a readiness failure instead of continuing with keyboard input or subsequent colors.

Includes the rc5 modal UI Automation timeout and interrupted-dialog recovery fixes. These changes address unsafe timing and unnecessary tool preparation. They do not establish the cause of a particular Paint process crash; real Paint-version testing is still needed.

## v1.0.144-rc5 — Paint color-dialog responsiveness

- Bound modal Invoke/Legacy actions on an MTA helper thread, then verify actual controls.
- Recover calibration when the RGB dialog is already open.
- Read values only from edit fields and pace RGB readiness scans.

## v1.0.144-rc4 — Getting started and contextual help

- Six-section guide with target-specific setup, modes, preview and troubleshooting.
- Clickable setting help and improved tooltip placement and lifecycle.

## v1.0.144-rc3 — Windows taskbar identity

- Set the taskbar group icon and relaunch metadata on the native app window.
- Restore branding on remap and theme changes.
- Use the bundled icon file for installer shortcuts.
- Verify Windows shell properties through the real app root and release them on close.

# v1.0.144-rc2

- Unified application, window, header, taskbar, installer and shortcut icons.
- Multi-resolution Windows ICO and a shared 512-pixel UI master from the same SVG artwork.
- Stable Windows taskbar application identity.

# v1.0.144-rc1

- Image Draw Bot — Automatic Image Drawing public release candidate.
- GitHub repository, UI titles, Windows metadata, installer, EXE and release artifacts use the Image Draw Bot identity.
- Frozen installs use `%LOCALAPPDATA%\ImageDrawBot`.
- Installer, updater and portable ZIP use `ImageDrawBot.exe` and `ImageDrawBot-...` release files.
- Sketch/single-color Paint modes continue to bypass Edit colors.


# v1.0.143-rc4

- Fix Paint drawing startup when the automatic RGB calibration opens **Edit colors** over the canvas.
- Require the Edit colors modal to be fully closed before canvas/ribbon verification or drawing preparation can continue.
- Re-scan the Paint UI after Cancel/OK and retry only the already identified modal control when current XAML Paint closes asynchronously.
- Reactivate and re-probe the Paint document after RGB calibration before taking any canvas screenshot.
- Apply the same modal-closure invariant to **Custom color palette for picture**, including a bounded foreground grace period and UIA-confirm fallback only when the Paint modal persists.
- Never report Paint preparation as ready while Edit colors RGB controls are still visible.
- Add Windows regressions for delayed modal dismissal, stuck-modal rejection, confirm closure, and Paint reactivation.

# v1.0.143-rc3

- Fix false `Paint canvas border is ambiguous or covered` failures in modern Microsoft Paint.
- Treat an explicit user-selected Paint drawing area as the authoritative CanvasGuard boundary during Prepare Paint & draw.
- Reuse that selection only for the same Paint window and same client size; pure window moves are rebased, while resize/target changes fall back to automatic detection.
- Keep palette, Pencil/Fill/Eraser and Edit colors RGB calibration automatic even when visual canvas-border detection is unreliable.
- Preserve the full auto-detected canvas envelope around interior obstructions so a covered canvas cannot be silently reduced to a smaller white sub-area.
- Add a conservative inward safety margin for auto-detected visible Paint borders whose pale shadow/resize chrome is visually indistinguishable from pure white canvas.
- Add regressions for manual canvas authority, moved-window rebasing, resize rejection, white border halos, compact/clipped canvases and covered-canvas rejection.

# v1.0.143-rc2

- Fix false `Paint canvas visible area is too small` failures on modern Paint.
- Replace the fixed 35% Paint-window width rule with a DPI-scaled minimum drawable size.
- Detect compact blank canvases safely even when Paint is maximized and the document occupies only part of the window.
- Ignore thin Paint resize-handle/edge chrome while finding the blank canvas rectangle, while still rejecting covered or non-blank interiors.
- Preserve clipped-canvas safety insets and manual fallback for genuinely tiny or ambiguous areas.
- Add compact-canvas, resize-handle and tiny-area regression coverage.

# v1.0.143-rc1

- Fix Microsoft Paint auto calibration when the blank document canvas extends beyond the visible window.
- Accept a large verified blank visible canvas viewport instead of requiring every document edge to be on-screen.
- Keep strict rejection for genuinely small, covered or ambiguous drawing areas.
- Inset clipped client edges more aggressively so automatic drawing stays away from window boundaries and scroll/clipping edges.
- Preserve full-canvas behavior and existing palette/tool verification when all Paint canvas borders are visible.
- Add regression coverage for left/right/bottom clipped Paint documents and keep Windows/Linux CI plus DrawBot self-test as release gates.

# v1.0.142-rc1

- Add **Custom color palette for picture** to the Microsoft Paint color-calibration workflow.
- Analyze the loaded image with the production DynamicColors/OKLab planner and prepare a bounded set of important exact RGB colors, including protected edge/detail colors.
- Automatically calibrate Edit colors R/G/B controls when needed and save that calibration independently from full canvas detection.
- Persist picture palettes by image + Paint calibration fingerprint and seed numeric selection without bypassing normal rendered-color verification.
- Keep palette preparation explicit, cancel-safe and guaranteed to disarm native input after the UI sequence.

# v1.0.141-rc1

- Fix Microsoft Paint automatic Edit colors discovery/activation on modern Windows 11 Paint.
- Automatically calibrate numeric RGB fields so image colors can be typed, verified and cached persistently.

# v1.0.140-rc1

- Merge the v1.0.134–v1.0.140 drawing-engine correctness, travel, semantic-barrier and Cost Model v2 work.
- Installed Windows builds can download a verified GitHub Release installer, update the same installation in place, and relaunch Image Draw Bot automatically.
- Version bumps on `main` trigger the verified Windows release workflow so Update Center can discover newly published installers.
- Keep SHA-256, size, redirect-host and PE-header verification before any downloaded installer is started.

# v1.0.133-rc3

- Gartic Phone auto calibration checks visible edges before planning and conservatively shrinks detected paper bounds.
- Invalidate older layout fingerprints so automatic setup recalculates bounds.
- Keep execution boundary verification active.

v1.0.133-rc2: In-app updates download and verify versioned Windows installers, then launch the normal installer. GitHub release publishing follows successful Windows tests and installer validation. Includes automatic Paint RGB preparation and Extra Fast improvements.

v1.0.133-rc1: 100 maintenance improvements across preview, color cache, budgets, resume, profiles, precision, scheduling and UI diagnostics. See docs/100-UPPDATERINGAR-v1.0.133-rc1.md. Windows/GPU validation pending.

# v1.0.132-rc1 — final engine integration

- Faster exact run extraction and bounded component scheduling.
- Preserve collinear reversals; retain path coverage through deadline splitting.
- Account for canvas scale, cursor travel and color selections in hybrid costs.
- Exclude pauses from runtime speed learning; expose a labeled timing envelope.
- Reject non-improving or brush-unsafe corrections.
- Fingerprint geometry and target/tool context before render recovery.
- Release/disarm input before writing diagnostics.
- Normal startup no longer installs optional GPU packages.
- Source candidate only: Windows/EXE and physical GPU validation still pending.

v1.0.131-beta Sketch 2.0 + Auto Fill improves Paint sketch structure with color-boundary edges and adds a strict Sketch -> Color Fill -> Re-outline renderer that reuses calibrated custom RGB while leaving browser/Gartic execution unchanged.
v1.0.130-rc2 Release Candidate Hardening II removes leftover one-shot integration files, adds permanent source-tree hygiene enforcement, adopts version-only current release-note naming, and strengthens release-manifest version/channel/hash/size validation while keeping the RC feature freeze.

v1.0.129-rc1 Step 30: Release Candidate Hardening freezes the numbered feature roadmap, adds executable source/artifact release gates, 5,000-cycle lifecycle and profile-isolation soak checks, fixes Update Center repository/channel handling, validates Windows ZIP/installer/checksums/manifests, and requires a silent install/self-test/uninstall round trip before RC publication.
v1.0.128-beta Step 29: Hybrid Renderer 3.0 adds deterministic Auto Hybrid plus Pixel Art, Icon / Logo, Line Art, Portrait, Shaded Object and Deadline Silhouette modes; it reuses the existing Pixel Accurate, Quick Sketch, Shape Paths and PortraitPlanner engines while preserving CanvasGuard, calibration and profile isolation.
v1.0.127-beta Step 28: More Drawing Targets adds the TargetCapabilities registry plus isolated Kleki and Magma profiles; unverified browser targets remain manual by design and cannot inherit verified auto-setup semantics.
v1.0.124-beta Step 21: Build / Publisher / GitHub Release Clean-up adds deterministic source release validation, clean source ZIP creation, release manifests, GitHub release template, publishing docs and stronger checks that logs/safety reports/build artifacts are not accidentally shipped.
v1.0.124-beta Step 19/20: Final Profile Polish + Beginner Setup Wizard centralizes Paint/Gartic/Skribbl release presets, target-specific warnings/calibration flows, clearer Start-blocking status, setup wizard dialog and friendlier recovery/error actions.
v1.0.123-beta: Adaptive Palette Fidelity & Anti-Posterization Engine replaces fixed browser 4/6/8-colour reduction with fidelity/deadline-aware palette capacity, tone/hue/spatial anchors, visual-gain-per-switch selection, palette coverage and posterization diagnostics.
v1.0.122-beta: Exact Color Engine + Paint Color Verification adds CIEDE2000-based Faithful/Exact matching, source-backed color representatives, stronger bright-tone protection, Paint exact-RGB recovery after palette mismatches, per-profile verified color caching, and richer preview color diagnostics.
v1.0.121-beta: Direct Game Canvas Web Drop adds a canvas-only 60-second drop target for supported browser games, accepts Google Images/Chrome/Edge file+URL+HTML drag payloads, unwraps Google imgres links, and uses the dropped image as one-shot authorization for Browser One-Click verification and automatic drawing start.
v1.0.120-beta: Color Fidelity & Preview Tone Fix adds sRGB/Lab-aware palette matching, Faithful lightness/saturation preservation, bright-anchor retention in game turbo palettes, GPU parity and removes the artificial 0.68 Fill Preview darkening.
v1.0.119-beta: Deadline Reliability & Runtime Optimizer fixes safety reserves for legacy timers, adds conservative cold-start timing, typed-operation runtime learning, Normal/Catch-up/Panic scheduling, workload-aware CPU workers, verified GPU diagnostics, smarter browser candidate ranking, Start Drawing state tracking, structural-coverage gating and fill value-per-error scoring.
v1.0.118-beta: Adaptive Deadline Renderer adds named Gartic/Skribbl time presets, safety reserves, visual-importance budgeting, progressive deadline-aware scheduling, Panic Mode, local timing calibration and weighted preview accuracy metrics.
v1.0.117-beta: Region Fill Engine adds connected-region planning, conservative outline+fill substitution, leak-risk/cost analysis, stroke fallback, and locally learned draw-time calibration based on completed real drawings.
v1.0.116-beta: 4K + Automatic DPI Recognition Fix centralizes per-monitor DPI detection, adds monitor/system fallbacks, logs effective monitor/DPI metadata, and maps plausible high-DPI selection mismatches back to physical pixels.
v1.0.115-beta: High-DPI Browser Auto Setup Fix scans oversized browser palette ROIs in bounded overlapping tiles, preserving the 1M-pixel per-scan safety limit while supporting 144-DPI/4K Gartic layouts.
v1.0.114-beta: Automatic Canvas Clear adds an opt-in full-draw prelude: Paint Select All/Delete, calibrated browser Clear control, or CanvasGuard-bounded Eraser sweep with Brush restore. Small Test/Dry Run/resume remain protected.
v1.0.113-beta: Detail-Aware Preview adds adaptive oversampled preview resampling, edge-priority micro-detail recovery, and Fast/Balanced/Detailed/Micro detail controls so eyes, pupils and thin contours survive preview downscaling more reliably.
v1.0.112-beta: Contour & Detailed Shadow Rendering adds local shadow analysis, palette-aware contour detection, detailed-shadow protection and post-processing priority while preserving the lossless PixelMap.
v1.0.111-beta: Smart Drop-In Canvas Targeting (EXPERIMENTAL / very early stage) can detect a supported browser game canvas and open a temporary drag/drop overlay; drops outside the drawable canvas are rejected and the normal CanvasGuard/One-Click safety chain remains mandatory.
v1.0.110-beta: Preview Draw Time Estimate shows an estimated final drawing duration directly after Build preview, including projected range when safe preview is smaller than the target canvas.
v1.0.109-beta: Advanced Color Matching measures source mean/median/dominant RGB, prefers exact numeric Paint RGB entry, verifies the selected-color preview, and falls back safely instead of confirming a known-wrong custom color.
v1.0.108-beta: Fix Paint color verification and enable spectrum-only custom palette selection during real drawing.
v1.0.107-beta: Reset all drawing settings before profile load; show only matching Paint/Gartic/browser controls.

v1.0.106-beta: Verified modern Paint automatic canvas, palette and Pencil/Fill setup.

v1.0.105-beta: Extra fast preset uses cost-selected closed contours and bucket fills, with stroke fallback.

v1.0.104-beta: Native-resolution preview, bounded viewport zoom, visible-tab rendering and actual planned colour map.

v1.0.103-beta: Human mode removed from UI; application always plans with it Off.

v1.0.102-beta: Clear image/cache, full Gartic setup, Auto engine and Masterpiece/Unlimited.

v1.0.101-beta: Visual Gartic pie timer observation and conservative drawing deadline.

v1.0.100-beta: Auto sketch detail using configured time budget.

v1.0.99-beta: Adjustable sketch detail, Simple default.

v1.0.98-beta: Gartic connected contour engine.

v1.0.97-beta: Single-color sketch for games, including Gartic.

v1.0.96-beta: sketch/subject-focus conflict no longer blocks drawing.

# Image Draw Bot Version History

This file is the quick answer to “what changed?” for each beta/source ZIP. It is shipped in the source package and bundled into the Windows build from v1.0.68 onward.

## Current release

| Version | Name | What changed |
|---|---|---|
| 1.0.126-beta Step 27.5 | One-click Setup + Automatic Canvas/Palette Verification | Unified Paint/browser setup, second live canvas/palette verification, fail-closed confidence checks and no drawing authorization. |
| 1.0.124-beta Step 24 | Adaptive Detail Zoom Pass | Re-analyzes bounded source ROIs at 2x/4x, restores palette-safe micro details, adds a Detail zoom preview, and keeps all target-app zoom/calibration coordinates unchanged. |
| 1.0.124-beta Step 19/20 | Profile Polish + Beginner Setup Wizard | Centralizes release presets for Paint/Gartic/Skribbl, applies game time presets in Auto mode, shows what blocks Start, and adds a full setup wizard with target warnings. |
| 1.0.124-beta | Paint Color Selection Recovery & Exact Swatch Verification | Fixes Paint palette→exact recovery, adds optional Active Color 1 swatch verification before strokes, and expands Faithful custom-RGB use for poor palette matches. |
| 1.0.123-beta | Adaptive Palette Fidelity & Anti-Posterization Engine | Replaces fixed 4/6/8-colour browser reduction with adaptive Faithful palette capacity, tone/hue/spatial anchors, weighted DeltaE2000 coverage, midtone protection and posterization diagnostics. |
| 1.0.122-beta | Exact Color Engine + Paint Color Verification | CIEDE2000 palette fidelity, source-backed representative colors, stronger lightness protection, Paint custom-RGB verification/recovery, verified color cache and richer preview color diagnostics. |
| 1.0.121-beta | Direct Game Canvas Web Drop | Drag a Google/Chrome/Edge image directly onto the detected game canvas; file/URL/HTML payloads are normalized, the canvas/palette is re-verified, then the drawing starts automatically through the existing safe browser pipeline. |
| 1.0.120-beta | Color Fidelity & Preview Tone Fix | Faithful sRGB/Lab palette matching, lightness/saturation preservation, bright turbo anchors, GPU fidelity parity and neutral preview tone. |
| 1.0.119-beta | Deadline Reliability & Runtime Optimizer | Fixes automatic timer reserve, conservative cold-start timing, typed-operation learning, Normal/Catch-up/Panic scheduling, workload-aware CPU/GPU diagnostics, browser candidate ranking, Start Drawing state tracking and deadline-aware Region Fill value scoring. |
| 1.0.118-beta | Adaptive Deadline Renderer | Adds real game-time budgets, importance-weighted plan reduction, progressive deadline scheduling, Panic Mode and locally calibrated estimated-vs-actual timing. |
| 1.0.117-beta | Region Fill Engine | Adds connected-region outline+fill planning with hard fill safety gates, cost-based fallback and locally learned final draw-time calibration from completed drawings. |
| 1.0.116-beta | 4K + Automatic DPI Recognition Fix | Centralized automatic target DPI detection, stronger per-monitor awareness, 4K/high-scaling coordinate mapping, monitor diagnostics and safe physical-pixel selection fallback. |
| 1.0.115-beta | High-DPI Browser Auto Setup Fix | Keeps browser palette scanning bounded while supporting oversized 144-DPI/4K palette ROIs. |
| 1.0.114-beta | Automatic Canvas Clear | Opt-in pre-draw clear using Paint shortcut, anchored Clear control, or guarded Eraser sweep; never destroys Small Test/Dry Run/resume state. |
| 1.0.113-beta | Detail-Aware Preview | Preserves eyes, pupils, thin contours, fine facial lines and tiny shadow edges in bounded UI previews using deterministic oversampling and micro-detail recovery. |
| 1.0.112-beta | Contour & Detailed Shadow Rendering | Adds local shadow analysis, contour maps, detailed-shadow protection and post-processing priority while preserving the lossless PixelMap. |
| 1.0.111-beta | Smart Drop-In Canvas Targeting | Experimental early-stage drop-on-canvas targeting for supported browser drawing games with safety fallback. |
| 1.0.110-beta | Preview Draw Time Estimate | Shows projected final drawing time after Build preview. |
| 1.0.109-beta | Advanced Color Matching | Measures real source RGB statistics, enters image-derived R/G/B automatically in Paint, verifies the custom-color preview before OK, and uses spectrum/palette fallbacks when needed. |
| 1.0.96-beta | Sketch start fix | Sketch takes priority over conflicting subject focus; GUI prevents this conflict. |
| 1.0.95-beta | Black contour sketch | Simple black-only contour planner; smoothing, edge thinning, speck removal and no colour fills. |
| 1.0.94-beta | Restore original UI | Restores the v1.0.91 layout/theme and preview tabs; keeps update actions, calibration hiding, startup fix and scroll handling. |
| 1.0.93-beta | Startup hotfix | Fixes undefined release_page_btn reference during UI creation and adds UI name-binding regression check. |
| 1.0.92-beta | Compact workspace | Section navigation, preview selector, wrapped tools, pointer-local scrolling, GitHub update actions and automatic hiding during calibration. |
| 1.0.91-beta | Unified release | Adaptive Brush Draw Motor merged with review/crash diagnostics, Subject Focus, image format detection and upscaling. |
| 1.0.90-beta (Adaptive Brush branch) | Adaptive brush motor | Per-path brush widths, verified browser switching and brush-aware CPU/CUDA simulation; merged into 1.0.91. |
| 1.0.90-beta | Review and crash diagnostics | Correct Windows dump setup, reliable mouse probe output, fill correction scope, order-preserving checkpoints and bounded CUDA launch work. |
| 1.0.89-beta | Pixel Accurate Planner — Block D | CUDA planned-stroke simulation and score reduction, VRAM-aware tiles/batches, parallel CPU region processing, protected progressive time budgets and phase accuracy checkpoints. |
| 1.0.88-beta | Pixel Accurate Planner — Block C | Brush-aware coverage map, executable stroke simulation, categorical pixel error map, improvement-gated correction passes, and measurable pixel/coverage/edge/protected-feature accuracy scores. |
| 1.0.87-beta | Pixel Accurate Planner — Block B | Exact 4-connected regions, local H/V lossless runs, component-safe merge + coverage verification, CPU component scheduling, and four-pass fill/mid/fine/cleanup execution. |
| 1.0.86-beta | Pixel Accurate Planner — Block A | Full fitted-resolution PixelMap, CUDA palette + Sobel analysis, perceptual palette mapping, importance/tiny-feature protection, and quality-first bypass of destructive browser turbo/simplification. |
| 1.0.85-rc1 | Automatic NVIDIA CUDA setup | Start.bat now detects NVIDIA hardware, automatically installs/repairs the CuPy + matched CUDA runtime inside .venv, removes conflicting CuPy families, validates a real CUDA kernel, and keeps CPU fallback if setup fails. |
| 1.0.84-rc1 | Browser palette guard hotfix | Prevent browser drawing from being falsely blocked by Paint palette validation; expose NVIDIA benchmark in GPU settings and show effective planner backend. |
| 1.0.83-rc3 | NVIDIA discovery + canvas drop-to-draw | Detect NVIDIA hardware independently of CuPy, auto-prepare CUDA on NVIDIA systems, real CUDA smoke/benchmark diagnostics, and direct preview-canvas drop-to-draw when setup is ready. |
| 1.0.82-rc2 | RC1 field-log fixes | Gartic conservative-edge handling, CTk scroll guard, Stop log-spam fix and One-Click callback recovery. |
| 1.0.81-rc1 | Stability / Release Candidate | No major renderer features: stress/race cleanup, guaranteed mouse release/disarm, stale callback/worker containment, and settings/cache migration validation. |

## Recent releases

| Version | Name | What changed |
|---|---|---|
| 1.0.80-beta | Browser One-Click Mode | Choose a supported browser game and add an image; Image Draw Bot discovers/reuses the game window, auto-detects canvas/palette, runs auto brush + visual preflight, then starts without manual calibration. |
| 1.0.79-beta | Smart Recovery / Resume | Saves active color + exact unfinished path on recoverable browser stops; next explicit Start recalibrates/preflights and resumes without redrawing completed paths. |
| 1.0.78-beta | Stroke Delivery Verification | Verifies browser strokes after delivery and retries only a suspected missed/partial stroke once with safer spacing. |
| 1.0.77-beta | Real-Speed Time Budget | Learns completed browser paths/second and adapts 30/60/90-second path, color and detail budgets while prioritizing large outlines/forms. |
| 1.0.76-beta | Layout Fingerprint v2 | Caches browser canvas/palette geometry, client size, DPI and zoom/reflow signatures for near-instant repeated Auto Setup. |
| 1.0.75-beta | Per-Game Input Engine | Separate Gartic/Skribbl/SketchHeads interpolation, stroke spacing, press/release timing and palette-click delays; includes v1.0.74 Automatic Brush Size. |
| 1.0.74-beta | Automatic Brush Size | Auto-detects and safely selects browser brush-size presets for Gartic Phone, Skribbl and SketchHeads; low-confidence layouts use a conservative no-click fallback. |
| 1.0.73-beta | Drop-In Synchronization | Queues a manually armed browser image while Auto Setup/Recalibration/Visual Preflight is running, resumes automatically, keeps only the latest image and cancels on target/profile change. |
| 1.0.72-beta | Browser Visual Preflight | Verifies the visible canvas and representative palette swatches immediately before every browser drawing; retries Auto-Recalibration once and blocks persistent visual mismatches before mouse input. |
| 1.0.71-beta | Browser Auto-Recalibration | Read-only pre-input rescans automatically refresh browser canvas/palette after Chrome zoom, resize, window movement or DPI changes. |
| 1.0.70-beta | Browser Auto Calibration | Auto-detects/anchors browser palettes and safe canvases for Gartic Phone, Skribbl and SketchHeads; manual calibration becomes fallback-only. |
| 1.0.124-beta Step 25 | Quick Sketch Fill + Contour | Adds a recognition-first short-round renderer using verified closed-region OUTLINE_FILL, simplified visible contours, connected scanline fallback and Auto Tuner selection. |
| 1.0.124-beta Step 24 | Adaptive Detail Zoom Pass | Re-analyzes high-value source regions internally at 2x/4x, recovers bounded micro-details and never changes target-app/browser zoom or calibration geometry. |
| 1.0.124-beta Step 23 | Universal GPU Acceleration Engine | Routes real OKLab, palette, DeltaE, quantization, edge and pixel workloads through the fastest Step-22-measured CUDA/OpenCL/CPU backend with per-workload fallback. |
| 1.0.124-beta Step 22 | Universal Hardware Auto Benchmark | Adds NVIDIA/AMD/Intel detection, CUDA/OpenCL/CPU microbenchmarks, per-workload backend selection and a local per-machine adaptive hardware profile. |
| 1.0.69-beta | Mobile Preview Live | Adds an opt-in local Wi-Fi/LAN preview page with Original, Drawing Preview, Safety Map, live refresh and QR/address sharing. |
| 1.0.68-beta | Version History & README Index | Adds VERSION-HISTORY, README-INDEX, docs indexes and an in-app Version history viewer. |
| 1.0.67-beta | Manual Drop-In Start | One-shot browser/game workflow that starts drawing after the next image import when manually armed. |
| 1.0.66-beta | Gartic Engine v2 | Dedicated Gartic layout validation, 72-color palette support, StrokeGraph travel optimization and timer-aware runtime settings. |
| 1.0.65-beta | Gartic Phone Turbo Renderer | Fast Gartic renderer with color batching, horizontal/vertical run selection and fixed-palette drawing. |
| 1.0.64-beta | Skribbl Turbo Renderer | Skribbl.io Fast uses palette reduction, color batching and continuous raster-run compression. |
| 1.0.63-beta | Adaptive Stroke & Input Ownership Fix | Rolls back overly aggressive Paint delivery defaults and reduces false manual-mouse stops. |
| 1.0.62-beta | Paint Stroke Delivery Fix | Adds denser Paint drag delivery and timing fixes for missing mouse-down segments. |
| 1.0.61-beta | Fast Dry Run Completion Fix | Clean Fast Dry Run budget expiry is treated as pass rather than a hard timeout error. |
| 1.0.60-beta | Performance Auto Tuner | Local benchmark for CPU workers, RAM budget, GPU/VRAM policy and planning resolution. |
| 1.0.59-beta | GitHub Update Center | Manual update checker for GitHub Releases with no background checks or automatic downloads. |
| 1.0.58-beta | Runtime Safety UI + Release Prep | Visible runtime safety counters, release packaging and local-only diagnostics cleanup. |

## Earlier development history

These entries are generated from the historical markdown notes in `docs/history/`.

| Version | Note | File |
|---|---|---|
| 1.0.57 | v1.0.57-beta – Runtime Safety Report Step 11 | `docs/history/RUNTIME-SAFETY-REPORT-v1.0.57.md` |
| 1.0.56 | v1.0.56-beta – Safety Debug Overlay Step 10 | `docs/history/SAFETY-DEBUG-OVERLAY-v1.0.56.md` |
| 1.0.55 | v1.0.55-beta – Smart Preview Safety Step 9 | `docs/history/SMART-PREVIEW-SAFETY-v1.0.55.md` |
| 1.0.54 | v1.0.54-beta – Edge Behavior Step 8 | `docs/history/EDGE-BEHAVIOR-v1.0.54.md` |
| 1.0.53 | v1.0.53-beta – Stroke Clip Step 7 | `docs/history/STROKE-CLIP-v1.0.53.md` |
| 1.0.52 | v1.0.52-beta – Safe Fill Mask Step 6 | `docs/history/SAFE-FILL-MASK-v1.0.52.md` |
| 1.0.51 | Image Draw Bot v1.0.51-beta – Edge Detection Step 5 | `docs/history/CANVAS-EDGE-DETECTION-v1.0.51.md` |
| 1.0.50 | v1.0.50-beta — Anchor Transform Step 4 | `docs/history/ANCHOR-TRANSFORM-v1.0.50.md` |
| 1.0.49 | Canvas Anchor Detection — v1.0.49 | `docs/history/CANVAS-ANCHORS-v1.0.49.md` |
| 1.0.48 | Canvas Polygon — v1.0.48 | `docs/history/CANVAS-POLYGON-v1.0.48.md` |
| 1.0.47 | Canvas Guard — v1.0.47 | `docs/history/CANVAS-GUARD-v1.0.47.md` |
| 1.0.46 | Fast Calibrated Dry Run — v1.0.46 | `docs/history/FAST-DRY-RUN-v1.0.46.md` |
| 1.0.45 | Profile Engine v2 — v1.0.45 | `docs/history/PROFILE-ENGINE-v1.0.45.md` |
| 1.0.44 | Resource Scheduler v2 — v1.0.44 | `docs/history/RESOURCE-SCHEDULER-v1.0.44.md` |
| 1.0.43 | Visual Verification — v1.0.43 | `docs/history/VISUAL-VERIFICATION-v1.0.43.md` |
| 1.0.42 | Render Resume + Color Checkpoints — v1.0.42 | `docs/history/RENDER-RESUME-v1.0.42.md` |
| 1.0.41 | Color Engine v3 — v1.0.41 | `docs/history/COLOR-ENGINE-v1.0.41.md` |
| 1.0.40 | Auto Paint Calibration — v1.0.40 | `docs/history/AUTO-PAINT-CALIBRATION-v1.0.40.md` |
| 1.0.39 | Better Fill Engine v1.0.39 | `docs/history/BETTER-FILL-v1.0.39.md` |
| 1.0.38 | Adaptive Detail Engine — v1.0.38-beta | `docs/history/ADAPTIVE-DETAIL-v1.0.38.md` |
| 1.0.37 | Image Draw Bot v1.0.37-beta – Smart Stroke Optimizer | `docs/history/STROKE-OPTIMIZER-v1.0.37.md` |
| 1.0.35 | Image Draw Bot v1.0.35-beta – Adaptive Color Verification + Auto-Recovery | `docs/history/ADAPTIVE-COLOR-v1.0.35.md` |
| 1.0.34 | Image Draw Bot v1.0.34-beta – Smart Custom Palette + Color Batching | `docs/history/CUSTOM-PALETTE-v1.0.34.md` |
| 1.0.33 | Image Draw Bot v1.0.33-beta – Color Engine v2 | `docs/history/COLOR-ENGINE-v1.0.33.md` |
| 1.0.32 | Image Draw Bot v1.0.32-beta — Paint Pencil / opacity safety | `docs/history/PAINT-PENCIL-OPACITY-FIX-v1.0.32.md` |
| 1.0.31 | Image Draw Bot v1.0.31-beta — Color Calibration Stability | `docs/history/COLOR-CALIBRATION-STABILITY-v1.0.31.md` |
| 1.0.30 | Image Draw Bot v1.0.30-beta — Preview Stability Fix | `docs/history/PREVIEW-STABILITY-v1.0.30.md` |
| 1.0.29 | Image Draw Bot v1.0.29-beta — Step 11 UI Icons + Profile Experience | `docs/history/UI-PROFILES-v1.0.29.md` |
| 1.0.28 | Image Draw Bot v1.0.28-beta — Step 10 Safe Recovery + Diagnostics | `docs/history/SAFE-RECOVERY-DIAGNOSTICS-v1.0.28.md` |
| 1.0.27 | Image Draw Bot v1.0.27-beta — Step 9 Performance Profiler + Benchmark | `docs/history/PERFORMANCE-PROFILER-v1.0.27.md` |
| 1.0.26 | Image Draw Bot v1.0.26-beta — Step 8: Renderer v2 / Better Shapes | `docs/history/BETTER-SHAPES-v1.0.26.md` |
| 1.0.25 | Image Draw Bot v1.0.25-beta — Step 7: Live Target Monitoring | `docs/history/LIVE-TARGET-MONITORING-v1.0.25.md` |
| 1.0.24 | Image Draw Bot v1.0.24-beta — Step 6: Target Lock + Calibration Fingerprint | `docs/history/TARGET-LOCK-v1.0.24.md` |
| 1.0.23 | Image Draw Bot v1.0.23-beta — Step 5: Dry Run / No-click Plan Test | `docs/history/DRY-RUN-v1.0.23.md` |
| 1.0.22 | Image Draw Bot v1.0.22-beta — Step 4: Planning Watchdog + Fallback | `docs/history/PLANNING-WATCHDOG-v1.0.22.md` |
| 1.0.21 | Image Draw Bot v1.0.21-beta — Step 3: Progressive Renderer | `docs/history/PROGRESSIVE-RENDERER-v1.0.21.md` |
| 1.0.20 | Image Draw Bot v1.0.20 beta — Step 2: Time Budget + Target Stroke Count | `docs/history/TIME-BUDGET-TARGET-STROKES-v1.0.20.md` |
| 1.0.19 | Image Draw Bot v1.0.19 beta — Step 1: Preflight Lock | `docs/history/PREFLIGHT-LOCK-v1.0.19.md` |
| 1.0.18 | Image Draw Bot v1.0.18-beta — Start Failsafe | `docs/history/START-FAILSAFE-v1.0.18.md` |
| 1.0.17 | Image Draw Bot v1.0.17 beta – Skribbl Fast Renderer | `docs/history/SKRIBBL-FAST-RENDERER-v1.0.17.md` |
| 1.0.16 | Image Draw Bot v1.0.16 beta – Manual Preview and Start Guard | `docs/history/PREVIEW-START-SAFETY-v1.0.16.md` |
| 1.0.15 | Image Draw Bot v1.0.15 – Drawing Start Diagnostics | `docs/history/DRAW-START-DIAGNOSTICS-v1.0.15.md` |
| 1.0.14 | Image Draw Bot v1.0.14 – Real CPU/GPU/RAM Workload Allocation | `docs/history/RESOURCE-ALLOCATION-v1.0.14.md` |
| 1.0.13 | Image Draw Bot v1.0.13 — CPU / GPU / RAM Allocation | `docs/history/RESOURCE-ALLOCATION-v1.0.13.md` |
| 1.0.12 | Image Draw Bot v1.0.12 — Smart Continuous Paths | `docs/history/SMART-PATHS-v1.0.12.md` |
| 1.0.11 | Image Draw Bot v1.0.11 — Manual Preview + Stability Defaults | `docs/history/MANUAL-PREVIEW-PERFORMANCE-v1.0.11.md` |
| 1.0.10 | Image Draw Bot v1.0.11 — Preview Planning Fix | `docs/history/PREVIEW-PLANNING-v1.0.10.md` |
| 1.0.9 | Image Draw Bot 1.0.9 beta — Modern UI / UX Redesign | `docs/history/MODERN-UI-v1.0.9.md` |
| 1.0.8 | Image Draw Bot v1.0.8 — Advanced Color Rendering | `docs/history/ADVANCED-COLOR-v1.0.8.md` |
| 1.0.7 | Image Draw Bot v1.0.7 — Auto Fill + Smart Tool Control | `docs/history/AUTO-FILL-SMART-TOOLS-v1.0.7.md` |
| 1.0.6 | Image Draw Bot v1.0.6 — GPU Acceleration | `docs/history/GPU-ACCELERATION-v1.0.6.md` |
| 1.0.6 | Image Draw Bot v1.0.6 — Tool capabilities and Background Fill | `docs/history/TOOLS-AND-AUTOFILL-v1.0.6.md` |
| 1.0.5 | Speed Optimization — v1.0.5 beta | `docs/history/SPEED-OPTIMIZATION-v1.0.5.md` |
| 1.0.4 | Human Mode — v1.0.4 beta | `docs/history/HUMAN-MODE-v1.0.4.md` |
| 1.0.3 | Draw Quality Upgrade — v1.0.3 beta | `docs/history/DRAW-QUALITY-v1.0.3.md` |
| 1.0.2 | Precision Upgrade — v1.0.2 beta | `docs/history/PRECISION-v1.0.2.md` |
| 0.9.3 | Image Draw Bot 0.9.3 — Stability Code Audit | `docs/history/CODE-AUDIT-v0.9.3.md` |

## Safety note

Version history is documentation only. Renderer/profile settings cannot disable CanvasGuard, FinalMouseGuard, target monitoring or the no-click safety preflight chain.
