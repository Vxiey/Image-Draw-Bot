# Preview

**Build preview** calculates the planned result without drawing in the target app. Manual previews are rebuilt on request to avoid expensive work after every setting change.

1. Load an image and confirm the target/canvas setup.
2. Press **Build preview**.
3. Compare the original, reduced-color target and simulated result in the available preview views.
4. After changing the image, canvas, palette, mode or quality, build again before judging the new settings.

When Pixel Accurate finds missing or incorrectly colored pixels in a protected detail, **Missed details** appears under the preview. Choose a region to compare the quantized target with the final simulation at the same location and scale. Up to three regions are available. Opening a region uses the existing plan and takes no action on the target canvas.

## Interpreting problems

| What you see | What to check |
| --- | --- |
| Important shapes disappear | Detail/time budget; try a simpler source or more time |
| Wrong colors | Target profile, calibrated palette and color settings |
| Edges clipped | Real canvas bounds and brush width |
| Blank or unchanged preview | Loaded image, selected area, planning status; rebuild manually |
| Preview looks good, real drawing does not | Tool calibration, focus, brush behavior and mouse timing |

A preview estimates the result. It does not prove that the target app accepted every mouse action. A small test changes the real canvas and can help verify delivery.
