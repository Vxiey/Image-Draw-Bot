# Drawing modes and quality

Start with the default or **Balanced / Auto**, then compare a fresh preview after changing one setting.

| Goal | Starting choice | Tradeoff |
| --- | --- | --- |
| First attempt | Balanced / Auto | General balance of time and recognizable detail |
| Short drawing round | Extra Fast | Prioritizes shapes and speed; fine details may be omitted |
| More small detail | Pixel Accurate | More planning work and mouse actions; allow extra time |
| Clear simple contours | Quick Sketch | Emphasizes outlines rather than complete shading |

## Extra Fast

Uses connected paths and suitable outline/fill strategies to reduce drawing work. Fill is useful only with supported controls and suitably closed regions; unsafe or unsuitable fills fall back to strokes. It cannot guarantee a complex photo will finish within any chosen timer.

## Pixel Accurate

Prioritizes coverage and detail. Actual results still depend on palette, brush width, planning resolution, target canvas and timing. It is not a guarantee of exact source-pixel reproduction in every drawing app.

## Post-draw correction time

In **Correction Review → Correction time**, choose **5 s**, **10 s**, or **20 s** to give the bot a time budget for correcting a trusted canvas snapshot. It estimates the reduction in color error per second, accounting for mouse travel, strokes, and color changes. Snapshot capture, analysis, and planning happen before the input timer starts. If the target round has less time left, the shorter deadline applies.

**Auto** uses the existing correction policy. **Off** skips the correction pass. The choice is saved for each drawing profile. You can change it before a correction-only retry. The review shows the predicted improvement separately from any change measured on a fresh snapshot.

## Drawing mode versus quality preset

A quality preset changes the detail/speed balance. **Smart paths**, **Lines** and **Dots** describe how marks are delivered. Smart paths connects nearby pixels to reduce actions; dots can be much slower. Start with Smart paths unless the target needs another method.

[Preview](Preview) · [Settings and Tooltips](Settings-and-Tooltips) · [Performance and GPU](Performance-and-GPU)
