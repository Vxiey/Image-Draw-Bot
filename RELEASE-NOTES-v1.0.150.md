# Image Draw Bot v1.0.150

## Confirm the drawing area

In Paint, **Find canvas** can identify a fully visible blank document from its edges, surrounding workspace and matching resize handles on the right edge, bottom edge and lower-right corner. It leaves the handles outside the drawing area. If they are hidden, expand the ribbon so the existing Paint detector can check the tools, or use **Select canvas manually…**.

On a partly drawn Skribbl.io board, the palette tells the detector where to look. Four visible edges must support the proposed frame before this fallback can offer it. Sketchful now recognizes the three-row palette to the right of the board. Tests on screenshots from two drawing rounds found all 39 swatches and the edges of both the blank and partly drawn boards. The guide declined the lobby and guesser views.

For SketchHeads, keep the drawing surface and its toolbar in view. Use **Show canvas** to inspect a suggestion, or **Select canvas manually…** to mark the corners when the guide cannot verify the edges.

## Adjust background removal

Choose **Adjust…** beside the background-removal button in Simple or Advanced. Select **Auto** for a varied border, **Light background** or **Dark background** to restrict removal by brightness, or **Corner color** when the corners represent the background. Start with **Balanced** strength and try **Conservative** if a fine edge disappears.

Choose **Apply** for the first cutout. **Replace cutout** applies your next settings to the original picture, so you can compare results without repeatedly trimming the same edge. **Undo** restores the original.

The remover now measures connected regions using horizontal spans. In six paired local CPU runs of the full **Auto / Balanced** operation, median time fell from 1,085 to 210 ms on the project's 1,920 × 1,048 app screenshot and from 105 to 47 ms on its 360 × 240 small-detail fixture. The new and previous versions produced identical RGBA pixels and removal metadata on both inputs.

## Fast browser drawing

The fast drawing planners for Skribbl.io and Gartic Phone now honor a configured gap-join value of zero on opaque sources. Runs can meet at neighboring pixels while a one-pixel opening stays open.

## Windows downloads

Run Setup on 64-bit Windows 10 or 11, or extract the entire portable ZIP and start `ImageDrawBot/ImageDrawBot.exe`. Both packages include Python. The release includes SHA-256 checksums for the installer and ZIP.

[First drawing](https://github.com/Vxiey/Image-Draw-Bot/blob/v1.0.150/docs/GETTING-STARTED.md) · [Windows downloads](https://github.com/Vxiey/Image-Draw-Bot/releases/tag/v1.0.150)
