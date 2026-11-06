# Image Draw Bot {{VERSION}}

Image Draw Bot is a Windows automatic image drawing app that converts pictures into mouse strokes, contours, fill regions and exact RGB colors for Microsoft Paint and calibrated drawing canvases.

## Download

Use the Windows x64 installer for the normal installation path, or the portable Windows x64 ZIP when you do not want to install the application.

Verify downloaded artifacts against the accompanying `SHA256.txt` file before use.

## What this release is useful for

- Microsoft Paint automation with canvas setup and RGB calibration.
- Image-to-strokes rendering for automatic drawing workflows.
- Extra Fast, Balanced, Pixel Accurate and Auto Hybrid drawing modes.
- Contours, connected regions, safe fills, palette matching and exact custom colors.
- Local image processing with no telemetry.

## Release verification

Before publication, the release workflow must pass:

- release source gate
- complete regression discovery
- Image Draw Bot self-test
- PyInstaller build validation
- Windows ZIP integrity validation
- Inno Setup build validation
- SHA-256 + manifest validation
- silent installer → installed EXE self-test → silent uninstall

## Requirements

- Windows 10/11 x64
- Same privilege level for Image Draw Bot and the target application; normally both non-admin
- For Gartic Phone: Google Chrome with **Artist Tools for Gartic Phone** installed and enabled

## Safety

CanvasGuard, calibration, target verification, small test, Safety Preflight and Fast Dry Run remain authoritative. Release hardening does not bypass native-input safety gates.

## Known release status

The Windows binaries remain unsigned until Authenticode code signing is configured, so Windows SmartScreen may show a warning.

## Discovery terms

Automatic image drawing, image drawing bot, Microsoft Paint automation, Paint drawing bot, image-to-strokes, safe mouse automation, contour fill renderer, exact RGB color calibration, local image processing, Windows drawing automation.
