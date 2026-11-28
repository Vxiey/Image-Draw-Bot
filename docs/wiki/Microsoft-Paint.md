# Microsoft Paint setup

## Automatic workflow

Open one Paint window with a blank, fully visible canvas. Select **Microsoft Paint**, load an image and press **Prepare Paint & draw**. The app prepares the canvas, Pencil size, palette and RGB controls before drawing. Tests and previews are optional.

In Simple, **Find canvas** can recognize the blank page by its surrounding workspace and the resize handles halfway down the right side, halfway across the bottom and at the lower-right corner. Use **Show canvas** to inspect the inset. If the page is clipped or the handles are hidden, show the full page, expand the ribbon, or choose **Select canvas manually…**. Choosing the area leaves pencil and palette setup to **Prepare Paint & draw**.

Keep Paint and Image Draw Bot at the same Windows privilege level, normally without administrator rights. Preparation can stop when multiple Paint windows, covered controls or ambiguous fields make detection unreliable.

## Custom color palette for picture

This is the existing picture-color setup action. From rc9, the separate **Smart custom palette / exact color** button and help block are removed. RGB calibration runs through this action or automatic Paint preparation.

With an image loaded, this action selects up to 24 representative image colors and calibrates Edit colors R/G/B controls when needed. From rc7, it keeps the dialog open, enters each RGB value, checks that Paint accepted it, and presses **+ / Add to custom colors**. It waits at least **750 ms after each addition**, then proceeds to the next color. It presses OK once at the end. OK alone only selects the current color; it is not the save-to-custom-palette action.

Leave the mouse alone during preparation. If the Add button or RGB fields cannot be identified, preparation stops. Inspect the slots under **Custom colors / Anpassade färger** after the first run on your Paint version. This action does not clear existing custom colors, and should not be treated as a guarantee that Paint preserves them across restarts.

RGB calibration is saved separately from canvas detection. From rc8, the completed picture palette is used in both Pixel Accurate and normal color planning for the same loaded image. After preparation, press **Build preview**; the old plan is invalidated. Older palette analysis caches are rebuilt after updating. If exact colors become unavailable, the prepared palette stops with an error instead of substituting standard toolbar colors. The limited palette still cannot preserve every original photo shade. See [Color Engine](Color-Engine).

## When setup fails

Read the status message. Make the full blank canvas and toolbar visible, close extra Paint windows and check the selected profile. Changes to zoom, scaling and tool layout can require recalibration. Manual calibration is available, but the automatic Start path still requires successful fresh preparation.

Automatic accessible-control matching covers Swedish and English names in supported modern Paint layouts. Other versions or layouts may need manual setup. Passing automated tests does not guarantee compatibility with every Paint installation.

[Detailed automatic preparation and validation scope](https://github.com/Vxiey/Image-Draw-Bot/blob/main/docs/PAINT-AUTOMATIC-PREPARATION.md) · [Troubleshooting](Troubleshooting)
