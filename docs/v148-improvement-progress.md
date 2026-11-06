# Image Draw Bot 1.0.148 improvement progress

## Requested result

Continue application-wide correctness, performance and security improvements, with a target of **1,000 distinct improvements**, then release **1.0.148**. The 100 already reviewed and merged improvements form the starting point; formatting, tests, documentation and version bumps do not count as additional product improvements.

## Current state

- The first 100 improvements are merged on `main` at `eb9804560c8648a92aabe2688e362a6b4a1d28b5`; Windows and Linux CI passed for their reviewed source head.
- Version 1.0.147's promotion PR was closed unmerged after the target changed. The RC4 release run was cancelled before publication.
- Development continues on `improve/v1.0.148`, based on `94a748ec7690eebb542c70311c594aa835434a98`. No 1.0.148 release has been published.
- Batch 01 adds 162 distinct changes: colour/GPU 40, planning/geometry 40, storage/resources 41 and UI/input 41. All four areas received independent source review; whole-program local integration passed 2,202 tests with 19 platform/hardware skips. Draft [PR46](https://github.com/Vxiey/Image-Draw-Bot/pull/46) publishes checkpoint `1c09774ad22088c5c30a8f8220b6b451fdee9659`.
- The checkpoint's Linux, dependency and CodeQL checks passed. Its Windows test job exposed a concurrent atomic-publication sharing failure. Batch 02 serializes publication and retries the bounded Windows sharing errors; Windows CI verified the correction. It is not counted again as a new improvement.
- Batch 02 adds 236 independently reviewed changes: calibration 69, delivery/planning 73, storage/resources 38 and UI/input 56. Whole-program local integration passed 2,557 tests (22 platform/hardware skips), the 5,000-cycle source gate, source-package hygiene and eight exact-raster engine fixtures. Published head `2fb7abf470a4ef498df9c53f42cddda62d8b652b` passed the Windows/Linux regression, dependency, CodeQL and packaged Windows GUI/native drag-and-drop checks in [run 42260646614](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42260646614). Windows first hit three subprocess startup timeouts; one rerun passed with unchanged source and unchanged test timeouts. At that checkpoint the combined implemented count was 498, with 502 remaining before the requested release target.
- The requested count of 1,000 has **not** been reached. No release claims, antivirus verdicts or signing status should be inferred from source improvements or old binary scans.

Batch 03 adds 116 distinct changes: colour quality 16, rendering/planning 38,
GPU/platform 22 and image workflow/UI 40. The implemented total is **614**;
**386 remain**. Final frozen-source integration passed 2,800 tests in 70.634 seconds
with 22 platform/hardware skips and unchanged source hashes. All four independent
area reviews are closed. The 5,000-cycle source gate, source-package hygiene for
860 files and eight exact-raster fixtures also passed. This checkpoint has not yet
passed its own Windows CI.

## Review method

1. Reproduce a concrete incorrect behavior, avoidable allocation, measured hotspot or unsafe failure mode.
2. Apply one focused correction and verify valid existing behavior remains compatible.
3. Add meaningful regression coverage for the failure or an independent correctness oracle for an optimization.
4. Count the product change once, grouping repeated call sites and related validation branches.
5. Compare performance to the unchanged source reference with identical inputs; disclose unchanged or slower results.
6. Integrate full tests, source gates, dependency review and Windows package checks before release.

## Baselines and ledgers

- [Original 100 improvements](100-IMPROVEMENTS-v1.0.148.md).
- [Batch 01 UI/input](v148-batch01-ui-input.md).
- [Batch 01 planning/geometry](v148-batch01-planning.md).
- [Batch 01 colour/GPU](v148-batch01-colour-gpu.md).
- [Batch 01 storage/resources](v148-batch01-storage-security.md).
- [Batch 02 calibration](v148-batch02-calibration.md), [delivery/planning](v148-batch02-delivery-planning.md), [storage/resources](v148-batch02-storage-runtime.md), and [UI/input](v148-batch02-ui-input.md).
- Batch 03: [colour quality](v148-batch03-colour-quality.md), [rendering/planning](v148-batch03-rendering-planning.md), [GPU/platform](v148-batch03-gpu-platform.md), and [image workflow/UI](v148-batch03-image-workflow.md).
- [Combined numbered index](IMPROVEMENTS-v1.0.148.md) and [machine-readable registry](v148-improvements.json).
- `benchmark_engine.py` validates eight deterministic planning fixtures against quantized target geometry. The saved reference has zero mismatched pixels in all eight fixtures.
- `benchmark_v148_ui.py` reproduces UI helper workload comparisons. It does not exercise real Windows input or physical GPU hardware.

## Release condition

Keep publication paused while the requested work and integration verification are incomplete. Do not manufacture a count of 1,000 by counting assertions, affected lines, repeated options, documentation or metadata edits as independent improvements.

## Repository security observations — 2026-11-06 UTC

The signed-in GitHub security pages showed:

- [Dependabot vulnerabilities](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot): **0 open**, 26 closed; dependency files last checked 2026-11-05.
- [Dependency malware alerts](https://github.com/Vxiey/Image-Draw-Bot/security/malware): **0 open**, 0 closed.
- [Code scanning](https://github.com/Vxiey/Image-Draw-Bot/security/code-scanning): **0 open**, 2 closed; all listed alerts resolved.

These are observations of the repository dashboards, not antivirus results for
a new installer and not proof that every possible vulnerability is absent.
The new source checkpoint must still pass its own dependency and CodeQL checks.
