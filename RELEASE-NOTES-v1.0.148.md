# Image Draw Bot v1.0.148

Download `ImageDrawBot-1.0.148-Windows-x64-Setup.exe` for Windows 10 or 11, or extract the entire portable ZIP and run `ImageDrawBot/ImageDrawBot.exe`. Both packages include Python. A GPU is optional. The accompanying SHA-256 file covers the installer and the ZIP. This build is unsigned.

## Drawing and preview

- In **Pixel Accurate → Build preview → Missed details**, select one of up to three protected areas with missing or incorrectly colored pixels. The palette target and simulated result show the same area at the same scale.
- In **Correction Review → Correction time**, set a per-profile limit of 5, 10 or 20 seconds. Corrections account for color selection, verification, travel and stroke time. Auto retains the default behavior and Off skips corrections. The review shows estimated gain and measured results separately.
- Extra Fast keeps safe scanlines when the target cannot use Fill. Pixel Accurate uses the calibrated brush footprint and time budget when deciding how much detail to retain.
- Pixel Accurate collects remaining errors into same-color runs in bounded tiles. Protected details and their drawing order are preserved across tile boundaries.
- Panning or zooming an image with an alpha channel can process just the visible area and the neighboring pixels needed for filtering. Large transparent images benefit most when only a small part is visible.

## Reliability and packaging

- Corrections now retain their full pixel allowance when many errors are tied, including on transposed arrays. Large correction masks are processed in bounded blocks, and runs for all colors are collected in one pass.
- A native input failure during correction stops delivery, releases the mouse and preserves the number of completed strokes. A new canvas check is required before retrying.
- Profile settings and recovery remain separate for each target. Mobile Preview asks before sharing on the local network, and update download and installer launch have separate confirmation steps.
- Windows input and window-monitor components load system DLLs through System32. Session recovery accepts PNG and checks the open file before decoding. The release builder checks for misplaced credentials and private signing keys.
- Publication checks the exact four Windows release files and compares their uploaded sizes and SHA-256 hashes to the local build.
- Windows release verification covers packaged startup, native drag and drop, silent installation and removal, and an upgrade from an earlier 1.0.148 test build that preserves profile settings.

[Getting started](https://github.com/Vxiey/Image-Draw-Bot/blob/v1.0.148/docs/GETTING-STARTED.md) · [Improvement registry and evidence](https://github.com/Vxiey/Image-Draw-Bot/blob/v1.0.148/docs/IMPROVEMENTS-v1.0.148.md) · [Development history](https://github.com/Vxiey/Image-Draw-Bot/blob/bed607ea364149138d77775db558c23519adcf8b/RELEASE-NOTES-v1.0.148.md)
