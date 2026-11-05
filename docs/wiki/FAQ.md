# Frequently asked questions

## Does it generate AI images?

No. It processes an existing picture into drawing actions. Image processing runs locally.

## Do I need Python or a GPU?

Packaged Windows Setup and ZIP include Python. Source use needs Python 3.11+. GPU acceleration is optional; CPU fallback is available.

## Where is the new guide?

Open **Get started** in the app header. It stays open beside the main window. Click **?** beside a setting for explanations or hover for a tooltip. **Setup wizard** checks the current profile's requirements.

## Do I need to run every diagnostic before drawing?

Paint uses **Prepare Paint & draw**, with automatic preparation before drawing. Tests and preview are optional. Manual browser/game starts normally use **Unlock full drawing → Start drawing** after setup. Follow the actual status message; do not assume all profiles share one start sequence.

## Why did importing an image start drawing?

Browser One-Click or an armed drop-start mode can start supported targets after import. For a manual first attempt, disable Browser One-Click and leave drop modes unarmed before importing.

## Does Gartic Phone need anything extra?

The supported workflow uses Google Chrome with Artist Tools for Gartic Phone enabled. See [Gartic Phone](Gartic-Phone).

## Does preview guarantee identical results?

No. It estimates the plan. Actual brush behavior, colors, calibration and timing affect the drawing.

## Does Clear image erase my target canvas?

Clearing the loaded source and clearing the target are different actions. **Auto clear target canvas before full drawing** can erase target artwork; keep it off unless intended.

## Can I move the target while drawing?

Avoid moving, resizing or zooming the target. These can invalidate setup. Esc stops; F6 pauses/resumes.

## Are downloads signed?

Published packages are unsigned. See [Installation](Installation) for downloads and integrity checks.
