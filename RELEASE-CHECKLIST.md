# Image Draw Bot release checklist

## Before packaging

1. Confirm `Version.py` is the intended version source of truth.
2. Confirm `version_info.txt` matches `FILE_VERSION`.
3. Run source hygiene validation:

   ```powershell
   python ReleasePackage.py --check
   ```

4. Run tests:

   ```powershell
   python -m pip install -r requirements.txt -r requirements-dev.txt
   python -m unittest discover -v
   python DrawBot.py --self-test
   ```

5. Confirm no user/runtime artifacts are staged:
   - `logs/`
   - `safety-reports/`
   - `diagnostics/`
   - crash dumps
   - build folders
   - nested release ZIPs/EXEs

## Build Windows artifacts

6. Build on Windows x64:

   ```powershell
   Build-Release.bat
   ```

7. Confirm the builder ran the frozen `ImageDrawBot.exe --self-test`.
8. Confirm release folder contains:
   - `ImageDrawBot-<version>-Windows-x64.zip`
   - optional `ImageDrawBot-<version>-Windows-x64-Setup.exe`
   - `ImageDrawBot-<version>-SHA256.txt`
   - `ImageDrawBot-<version>-manifest.json`

## Manual smoke tests

9. Test on a clean Windows 10/11 x64 standard-user account.
10. Test Microsoft Paint setup: image → setup wizard → calibration → canvas → preview → dry run → unlock → start.
11. Test Gartic Phone setup with Fast deadline.
12. Test Skribbl.io setup with 80-second deadline.
13. Verify CanvasGuard, Esc stop, F6 pause/resume and Runtime Safety UI.
14. Verify Golden tests button runs local synthetic regressions.
15. Verify logs/safety reports stay local and are not bundled into source releases.

## GitHub release

16. Confirm the owner has explicitly approved publication, all readiness work is
    complete (the registry must contain all 900 distinct groups), and push/main
    CI passed for the exact commit on `main`. A normal main/tag
    push only builds and verifies artifacts; it does not publish a release.

    In GitHub Actions, manually run **Build, verify, and optionally publish Image
    Draw Bot Windows release** on `main` with **publish** enabled. The default is
    disabled, so ordinary manual verification runs are also build-only. The
    workflow verifies the exact commit and creates the version tag only during
    this explicit publication path. If CI is still pending, publication stops;
    rerun after CI passes. Do not create or move a tag to bypass that gate.

17. Attach or verify:
   - portable ZIP
   - installer, if built
   - source ZIP
   - SHA-256 file
   - release manifest

18. Add Authenticode signing before broad distribution when a code-signing certificate is available.

## Wiki publication

Wiki synchronization is manual-only through the Publish Image Draw Bot Wiki
workflow. A code push does not publish Wiki changes. Obtain explicit approval
before dispatching that separate publication workflow.
