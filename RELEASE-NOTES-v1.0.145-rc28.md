# Image Draw Bot v1.0.145-rc28 — Background Remover & PNG Workflow

- Add **Remove BG** beside image import. It converts only border-connected background pixels to transparent alpha instead of deleting same-colour details inside the subject.
- Transparent pixels are passed directly into the existing planners as empty canvas, so they produce no strokes and can materially reduce real drawing time.
- Add **Undo** for the background-removal edit without interfering with the existing upscale restore path.
- Add **PNG** export for the current RGBA image, preserving transparency.
- Run removal and PNG encoding in cancellable workers so large source images do not freeze the UI.
- Report removed area and approximate drawable-pixel work reduction immediately; final stroke count and ETA remain authoritative after Build preview.
- Fail closed when the detected background would consume more than 98.5% of the image.
