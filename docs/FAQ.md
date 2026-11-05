# Image Draw Bot: frequently asked questions

## What does Image Draw Bot do?

It turns an existing picture into mouse strokes, contours and fills, then executes that plan in a calibrated drawing canvas. The Windows app includes profiles for Microsoft Paint, Gartic Phone and Skribbl.io. See [supported workflows and quick start](../README.md#quick-start-microsoft-paint).

## Does it generate AI images or upload my pictures?

Image processing and drawing plans run locally. It does not generate new AI artwork or upload your images. Explicit features such as loading an image URL, installing dependencies and checking updates can use the network.

## Do I need Python or an NVIDIA GPU?

Packaged Windows downloads include Python. Running the source requires Python 3.11+ on Windows. A GPU is optional: CPU processing remains available, with CUDA/OpenCL acceleration where the hardware and installed backend support it. See [running from source](../README.md#run-from-source).

## How do I draw a picture in Microsoft Paint?

Open a blank Paint canvas, select the Paint profile, load a picture and press **Prepare Paint & draw**. This prepares Paint and then draws. Preview and small tests are optional. Window size, zoom and display scaling can affect calibration. Follow the [Paint setup guide](PAINT-AUTOMATIC-PREPARATION.md).

## Which drawing mode should I use?

Extra Fast reduces input overhead with connected paths and suitable fill regions. Pixel Accurate prioritizes coverage and detail. Results and timing also depend on the target canvas, palette, brush settings and available drawing time. See [rendering features](../README.md#core-features) and [Extra Fast benchmarks](EXTRA-FAST-REVIEW.md).

## Why does a downloaded build still show the previous name?

The repository and current source use Image Draw Bot. Older published packages retain the identity and filenames they were built with. Check the [download section](../README.md#download-for-windows) for the available release and the [update guide](IN-APP-UPDATES.md) for how published updates are selected.

## Is the Windows download signed?

Published downloads are unsigned. Windows may show an unknown-publisher warning or block execution. SHA-256 checks verify file integrity, not a trusted publisher signature. See [package verification](RELEASE-STRUCTURE.md#verification-files).

## Where can I learn the controls?

Open **Get started** in the app header for the step-by-step guide. Click **?** beside a setting for an explanation. **Setup wizard** checks the current profile requirements. See [First drawing](GETTING-STARTED.md) and the [Wiki](https://github.com/Vxiey/Image-Draw-Bot/wiki).
