# Image Draw Bot v1.0.146-rc2 — Background Removal & Recognition-First Extra Fast

- Promote the validated post-rc1 fixes into the next 1.0.146 release candidate.
- Replace the old single-reference Remove BG flood fill with fully local classical edge-aware segmentation: adaptive border-colour clusters, chromatic edge barriers, conservative region growth, connected-component safety and a bounded contour matte.
- Keep Remove BG completely non-AI: no neural model, cloud service, OpenCV runtime dependency or generated replacement image.
- Make Extra Fast target-profile aware instead of applying one generic scanline-heavy policy to Paint, Gartic and Skribbl targets.
- Bind Extra Fast to the deterministic Drawing Style profile so Pixel Art preserves exact pixel regions, Line Art prioritizes connected contours, flat art prioritizes large colour regions, and Portrait/Photo prioritize recognisable structure before texture.
- Keep Gartic's verified multi-brush regional planning and safe Fill path while exposing recognition-first strategy metadata in preview/session diagnostics.
- Keep Estimated Draw Time tied to the real final execution sequence: mouse travel, strokes, colour changes, brush changes, Fill, tool changes and verification are costed instead of applying a cosmetic speed multiplier.
- Synchronize Windows installer metadata to the 1.0.146 RC line (`VersionInfoVersion=1.0.146.0`).
- Preserve CanvasGuard, calibration, cancellation, profile isolation, CPU fallback and no-CUDA operation.

Release publication remains gated by source-package hygiene, full regression tests, Image Draw Bot self-test, Windows packaging validation and the silent install/self-test/uninstall round trip.
