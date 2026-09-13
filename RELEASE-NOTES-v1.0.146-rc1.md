# Image Draw Bot v1.0.146-rc1 — Release Build Recovery

- Start the 1.0.146 release-candidate line from the merged 1.0.145-rc29 stability/planner baseline.
- Fix the Windows PyInstaller release command so `DrawingStyleProfiles` is passed as its own explicit hidden import instead of a stray positional script argument.
- Keep the rc29 Preview/Draw generation guard, trusted completed-drawing ETA learning, background removal, drawing-style profiles, Extra Fast cost planning, Pixel Accurate correction pipeline and profile isolation unchanged.
- Add regression coverage for the PyInstaller hidden-import list so the Windows release build cannot regress in the same way silently.
- Validate source hygiene, release metadata, the complete unit-regression suite, self-test and Windows installer build before merging.
