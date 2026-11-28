# Settings and tooltips

Click **?** next to a setting for help that stays open while you read, or hover for a tooltip. Start with defaults, change one setting at a time and build a fresh preview.

## Background removal

Choose **Adjust…** beside the background-removal button. **Auto** samples the image border. **Light background** and **Dark background** restrict removal to light or dark areas. **Corner color** uses the dominant color at the image corners. Start with **Balanced** strength. Use **Conservative** if a fine outline disappears, or **Aggressive** if too much of the background remains.

Choose **Apply** for the first cutout or **Replace cutout** to try another setting on the original. **Cancel** dismisses the controls. **Undo** restores the original image.

## Quality preset

Start with Balanced or the default. Extra Fast suits short rounds and simple shapes. Pixel Accurate emphasizes detail and can take longer. Build a new preview after changing the preset.

## Brush width (px)

This is the Auto Brush baseline. On supported targets, Image Draw Bot verifies available brush sizes and automatically uses broader brushes for large flat regions and smaller brushes for contours, protected details and corrections. Low-confidence layouts keep the fixed baseline and never guess brush-control clicks.

## Rendering style

Start with Auto. Portrait / shaded suits faces and gradients; Standard / pixel suits flat artwork. Quick Sketch prioritizes recognizable outlines when time is short.

## Drawing mode

Smart paths connects nearby pixels to reduce mouse actions. Lines draws runs; Dots places individual marks and can be much slower. Start with Smart paths.

## GPU acceleration

Auto uses a supported backend when available and falls back to CPU. GPU acceleration helps supported image-processing work; it does not make the target accept unlimited mouse input.

## VRAM budget

Leave Auto initially. A larger budget can help large images but leaves less graphics memory for other apps. More allocated memory is not always faster.

## Draw quality

Higher quality can preserve small features but adds planning work and strokes. Begin with the default; increase quality when a fresh preview loses important details.

## Precision

Higher precision can retain fine edges but usually adds work and strokes. Start with the default and compare a fresh preview.

## Speed

Higher speed only helps when the target app keeps up. If lines have gaps, colors are skipped or controls miss clicks, lower speed and repeat a small test.

## Time target

Choose a budget shorter than the remaining round so setup and finishing have time. A tight budget may omit small details. Check the preview and estimate.

## Manual time limit (seconds)

Leave time for setup and finishing before the round ends. Short budgets can omit small details. Compare estimated time and preview after changes.

## Edge behavior

Controls strokes near the selected canvas boundary. Keep the default at first. If edges are missing, check the real canvas bounds before changing this setting.

## Color rendering

The target may offer fewer colors than the source. Perceptual matching chooses visually similar available colors. Paint custom RGB colors can improve the match, but color switching adds time.

## Preview mode

Build preview calculates a plan without drawing. Rebuild after changing the image, area or settings. The simulation estimates the result; calibration, brush behavior and timing still matter.

## CPU workers

Auto is a good starting point. More workers can help preparation but compete with the target app. A larger number is not always faster.

## RAM budget

Auto balances available memory. Large pictures and detailed plans need more RAM. If preparation struggles, reduce planning resolution rather than allocating all memory.

## Planning resolution

Higher resolution can retain detail but increases memory use, planning time and possible stroke count. Lower it for quicker results or large-image problems.

## Fill aggressiveness

Fill can color closed areas quickly, but an open outline can leak into the background. Start conservatively; verify the target tools and preview before increasing this.

## Terms

| Term | Meaning |
| --- | --- |
| Canvas | The drawable area in the target app |
| Palette | Available colors |
| Calibration | Saved positions of tools, colors and canvas |
| Stroke | A mouse-drawn line or mark |
| Fill | Coloring a closed region |
| VRAM | Graphics-card memory |
| Time budget | Time available for drawing |
