# Image Draw Bot v1.0.149

The **Simple** workspace shows the next action for your picture and target. Open Paint or a supported drawing game, choose the target, and load your image. The app looks for the canvas. Confirm the detected area or select it manually, build a preview if desired, and start drawing when ready. Use **Advanced controls** to reach the full workspace.

## Setup and canvas detection

- The setup panel keeps the selected target, picture, canvas and palette status together. It exposes the current image style, background removal and Undo.
- Canvas discovery reads the visible window. Confirmation checks the window owner, current screen rectangle, DPI and detected canvas again. **Show canvas** briefly outlines a visible suggestion on Windows. Paint can locate the canvas independently of full color and tool calibration.
- The browser detector collects connected light areas in runs. A plain white window without canvas boundaries is rejected. When detection is inconclusive, the guide offers manual selection.

## Image processing

- Automatic background removal preserves existing cutout transparency. Light and Dark removal respect the selected brightness range during expansion. Edge refinement preserves partially transparent subject pixels, and Undo restores the original source.
- Image style choices are available in Simple mode. The Auto engine distinguishes sparse colored artwork on white paper from a monochrome sketch.

## Drawing and performance

- Adaptive Detail computes local contrast in small strips and reuses the results across each 5 × 5 neighborhood. On the original 1,920 × 1,048 application screenshot, the complete Preserve detail image-processing step fell from about 883 to 268 ms. It produced identical RGBA pixels, protection masks and detail statistics. The equivalent times were 126 to 50 ms on the icon in Auto and 39 to 24 ms on the texture in Strong simplify. In separate complete planner runs the icon went from 205 to 179 ms and the texture from 120 to 108 ms.

- Gartic outline mode can join opaque strokes that meet at exactly the same endpoint. It keeps gaps, direction and the original coverage. The planner checks the profile’s timing before accepting a join.
- On the existing 800 × 600 detail fixture, the production executor issued 39 mouse presses, down from 62. On the application screenshot it issued 567, down from 618 with the normal outline edge guard, and 562, down from 613 with hard clipping. The simulated output was identical. Input was recorded locally, so these figures do not measure elapsed time in a live game.
- On the project's existing reference cases, median canvas analysis decreased from about 89 to 16 ms for Paint at 100% scaling, 40 to 2 ms for Skribbl and 1,072 to 57 ms for Gartic. These benchmarks exclude screen capture and tool preparation.

## Windows download

Use the installer for 64-bit Windows 10 or 11, or extract the complete portable ZIP. Both packages include Python. The default installation is for the current user. All-users installation uses the dedicated Image Draw Bot directory under Program Files. Setup rejects an unsuitable machine-wide destination before replacing files. The installer is unsigned. The accompanying SHA-256 file covers the installer and the ZIP.

[First drawing](https://github.com/Vxiey/Image-Draw-Bot/blob/v1.0.149/docs/GETTING-STARTED.md) · [Drawing approaches and experiments](https://github.com/Vxiey/Image-Draw-Bot/blob/v1.0.149/docs/DRAWING-APPROACHES-v1.0.149.md)
