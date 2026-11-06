# Image Draw Bot 1.0.148 improvement progress

## Requested result

Continue application-wide correctness, performance and security improvements, with a target of **1,000 distinct improvements**, then release **1.0.148**. The 100 already reviewed and merged improvements form the starting point; formatting, tests, documentation and version bumps do not count as additional product improvements.

## Current state

- The first 100 improvements are merged on `main` at `eb9804560c8648a92aabe2688e362a6b4a1d28b5`; Windows and Linux CI passed for their reviewed source head.
- Version 1.0.147's promotion PR was closed unmerged after the target changed. The RC4 release run was cancelled before publication.
- Development continues on `improve/v1.0.148`, based on `94a748ec7690eebb542c70311c594aa835434a98`. No 1.0.148 release has been published.
- Batch 01 adds 162 distinct changes: colour/GPU 40, planning/geometry 40, storage/resources 41 and UI/input 41. All four areas received independent source review; whole-program local integration passed 2,202 tests with 19 platform/hardware skips. Windows CI remains pending.
- The requested count of 1,000 has **not** been reached. No release claims, antivirus verdicts or signing status should be inferred from source improvements or old binary scans.

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
- [Combined numbered index](IMPROVEMENTS-v1.0.148.md) and [machine-readable registry](v148-improvements.json).
- `benchmark_engine.py` validates eight deterministic planning fixtures against quantized target geometry. The saved reference has zero mismatched pixels in all eight fixtures.
- `benchmark_v148_ui.py` reproduces UI helper workload comparisons. It does not exercise real Windows input or physical GPU hardware.

## Release condition

Keep publication paused while the requested work and integration verification are incomplete. Do not manufacture a count of 1,000 by counting assertions, affected lines, repeated options, documentation or metadata edits as independent improvements.
