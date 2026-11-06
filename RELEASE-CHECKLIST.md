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

16. Create a tag matching the app version exactly:

   ```powershell
   git tag v1.0.146-rc4
   git push origin v1.0.146-rc4
   ```

17. Attach or verify:
   - portable ZIP
   - installer, if built
   - source ZIP
   - SHA-256 file
   - release manifest

18. Add Authenticode signing before broad distribution when a code-signing certificate is available.
