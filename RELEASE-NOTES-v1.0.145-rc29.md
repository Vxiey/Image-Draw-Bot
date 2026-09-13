# Image Draw Bot v1.0.145-rc29

## Stability & Planner Validation

- Added monotonic preview generation IDs so stale/cancelled preview workers cannot overwrite a newer plan or UI state.
- Routed centralized worker failures and worker-start failures into `ImageDrawBot-debug-errors.log` while preserving normal session logging.
- Added a completed-draw ETA learning gate. Incomplete draws, untrusted final-canvas measurements, accuracy below 82/100, or coverage below 94% no longer train profile-local timing estimates.
- Kept execution-only ETA learning for fully completed modes where a safe final-canvas quality snapshot is unavailable.
- Verified full-detail Preview keeps the final planner's drawing policy and real target geometry while retaining bounded preview resource controls.
- Preserved the existing Paint/browser target revalidation, auto-recalibration and CanvasGuard safety chain instead of introducing duplicate preflight logic.
- Fixed Manual preset isolation so Auto Drawing Style does not mutate explicitly manual settings unless a non-Auto style was selected.
- Preserved `Finished...` as the terminal successful execution status while Completed Drawing Analysis continues to save and log its telemetry in the background.
- Updated the README download and release-note references to the rc29 package metadata.
- Removed rc27/rc28 one-off integration triggers, scripts and workflows from the release branch.
- Synchronized application and Windows installer metadata to `1.0.145-rc29` / file version `1.0.145.0`.
