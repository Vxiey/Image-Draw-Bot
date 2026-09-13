# Image Draw Bot — AutoDraw & Drawing Bot for Windows

## See Image Draw Bot draw in real time

<video src="https://raw.githubusercontent.com/Vxiey/Image-Draw-Bot/main/assets/0912.mp4" controls muted loop playsinline width="100%"></video>

If the inline player is not available in your GitHub client, click the animated preview below to open the MP4 demo:

[![Image Draw Bot drawing automatically in Microsoft Paint, Gartic Phone and Skribbl.io](assets/0912.gif)](assets/0912.mp4)

[Open the full MP4 demo](assets/0912.mp4)

[![Image Draw Bot CI](https://github.com/Vxiey/Image-Draw-Bot/actions/workflows/ci.yml/badge.svg)](https://github.com/Vxiey/Image-Draw-Bot/actions/workflows/ci.yml)
![Windows 10/11](https://img.shields.io/badge/platform-Windows%2010%2F11-informational)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-informational)
![Local processing](https://img.shields.io/badge/processing-local-informational)
[![GitHub stars](https://img.shields.io/github/stars/Vxiey/Image-Draw-Bot?style=social)](https://github.com/Vxiey/Image-Draw-Bot/stargazers)

**Image Draw Bot is a Windows AutoDraw and drawing-bot app that converts images into real mouse strokes, fills, contours and pixel-accurate drawing plans for Microsoft Paint, Gartic Phone, Skribbl.io and similar canvases.**

It uses local image processing, deterministic render planning and safe mouse automation instead of generating a replacement image. Load a picture, calibrate the target canvas, preview the plan and draw it using the target application's real tools.

> If Image Draw Bot is useful to you, **star the repository** so you can find it again and help other people discover the project. Bug reports, real drawing results and target-compatibility feedback are also valuable.

## Download Image Draw Bot for Windows

Download **Image Draw Bot v1.0.146-rc2** for Windows 10/11 x64. The installer and portable ZIP include Python.

| Download | How to use it |
| --- | --- |
| [Windows installer — recommended](https://github.com/Vxiey/Image-Draw-Bot/releases/download/v1.0.146-rc2/ImageDrawBot-1.0.146-rc2-Windows-x64-Setup.exe) | Run Setup, then open Image Draw Bot. |
| [Portable Windows ZIP](https://github.com/Vxiey/Image-Draw-Bot/releases/download/v1.0.146-rc2/ImageDrawBot-1.0.146-rc2-Windows-x64.zip) | Extract the complete ZIP and run `ImageDrawBot/ImageDrawBot.exe`. |
| [SHA-256 checksums](https://github.com/Vxiey/Image-Draw-Bot/releases/download/v1.0.146-rc2/ImageDrawBot-1.0.146-rc2-SHA256.txt) | Verify the published files. |

[All releases](https://github.com/Vxiey/Image-Draw-Bot/releases) · [Release notes](RELEASE-NOTES-v1.0.146-rc2.md) · [Getting started](docs/GETTING-STARTED.md) · [FAQ](docs/FAQ.md) · [Wiki](https://github.com/Vxiey/Image-Draw-Bot/wiki)

## AutoDraw for Microsoft Paint, Gartic Phone and Skribbl.io

| Use case | What Image Draw Bot does |
| --- | --- |
| **Microsoft Paint AutoDraw** | Detects the Paint canvas, prepares Pencil/Fill, calibrates RGB controls and draws with exact colors where possible. |
| **Gartic Phone drawing bot** | Uses calibrated browser-canvas controls, dynamic brush sizes and optimized drawing paths. |
| **Skribbl.io drawing bot** | Supports isolated profile settings and calibrated browser-canvas workflows. |
| **Image-to-mouse drawing** | Converts pictures into connected runs, contours, fill regions, correction strokes and ordered mouse paths. |
| **Fast AutoDraw** | Extra Fast prioritizes Fill, large safe regions, region strokes, contours and detail correction. |
| **Pixel Accurate drawing** | Uses full-resolution pixel planning, coverage tracking, error analysis and correction passes for higher fidelity. |
| **Local Windows automation** | Processes images locally and controls real target-app tools instead of uploading artwork to a cloud renderer. |

## AutoDraw and drawing-bot features

- **Extra Fast** rendering for time-limited drawing rounds.
- **Pixel Accurate** rendering for high-fidelity image recreation.
- Connected color regions, safe Fill decisions, contours and horizontal/vertical runs.
- Dynamic brush sizes instead of forcing the smallest brush for every region.
- Adaptive detail protection for eyes, faces, text-like shapes, thin outlines and small objects.
- Exact/custom RGB color workflows for Microsoft Paint.
- Preview planning based on the same or nearly the same planner used for real drawing.
- Estimated drawing time based on modeled execution cost, including mouse travel and tool/color/brush changes.
- Automatic Paint preparation and calibration with manual fallback.
- Separate profiles for Paint, Gartic Phone, Skribbl.io and other targets.
- Optional CUDA/OpenCL acceleration with CPU fallback.
- Cancel-safe preview, planning, calibration and drawing jobs.

### Picture custom palette for Microsoft Paint

After loading an image and calibrating Paint, use **Custom color palette for picture** to analyze the current picture and prepare important exact RGB colors through **Edit colors**. Exact RGB control calibration is stored independently from canvas detection.

Requires **Windows 10/11, 64-bit**. Run Image Draw Bot and the target application at the same privilege level, normally without administrator rights.

**Published Windows builds are unsigned.** Windows may display “Unknown publisher” or SmartScreen warnings, and Smart App Control can block execution. Code signing has not been activated.

## Microsoft Paint AutoDraw quick start

1. Open Image Draw Bot and choose **Microsoft Paint**.
2. Load, paste or drop an image.
3. Keep one Paint window with a blank, fully visible canvas.
4. Press **Prepare Paint & draw**.

Before drawing, Image Draw Bot prepares the drawing tool, detects the canvas and palette, and calibrates Paint's RGB controls. Use **Prepare Paint automatically** if you want to prepare the target without starting a draw.

Automatic preparation currently targets supported Swedish/English modern Paint layouts and stops instead of guessing when the canvas or controls cannot be verified. [Paint setup details](docs/PAINT-AUTOMATIC-PREPARATION.md)

## Gartic Phone and Skribbl.io drawing-bot quick start

1. Open the target and choose its matching Image Draw Bot profile.
2. Load an image and run automatic setup or manual calibration.
3. Select only the drawable canvas and keep toolbars outside the area.
4. Choose a drawing mode and time budget.
5. Start the draw and keep browser zoom/window geometry unchanged.

**Gartic Phone:** the supported workflow requires Google Chrome with **Artist Tools for Gartic Phone** installed and enabled.

## Drawing modes: Extra Fast, Balanced and Pixel Accurate

| Mode or feature | Purpose |
| --- | --- |
| **Extra Fast** | Prioritizes safe Fill, large regions, region strokes, contours and detail correction for lower real execution time. |
| **Balanced** | General-purpose balance between speed and detail. |
| **Pixel Accurate** | Prioritizes source coverage, small details and correction passes for higher fidelity. |
| **Auto Hybrid** | Selects specialized deterministic renderers for different image structures. |
| **Adaptive Exact colors** | Uses calibrated custom RGB controls when the normal palette is not close enough. |
| **Manual previews** | Shows the planned result without rebuilding a heavy preview after every small setting change. |

Extra Fast's synthetic comparison suite preserves source-raster coverage for tested cases; real target-app speed also depends on UI delays, Fill operations, color changes, brush changes and mouse travel. [Benchmark and limitations](docs/EXTRA-FAST-REVIEW.md)

## Why this project is different from simple AutoDraw scripts

Many drawing scripts replay pixels or use one brush size everywhere. Image Draw Bot instead plans around the actual target application: connected regions, safe fills, brush sizes, contours, color changes, UI delays, cursor travel and correction passes all contribute to the final plan. The goal is recognizable image quality at the lowest practical **real drawing time**, not just the lowest stroke count.

## Guides and help

- [First drawing](docs/GETTING-STARTED.md)
- [Setup and troubleshooting](README-INDEX.md)
- [Frequently asked questions](docs/FAQ.md)
- [Wiki: installation, target setup and troubleshooting](https://github.com/Vxiey/Image-Draw-Bot/wiki)
- [Setting explanations and glossary](https://github.com/Vxiey/Image-Draw-Bot/wiki/Settings-and-Tooltips)

Inside the app, open **Get started** for the built-in guide or click **?** beside a setting.

## Controls

- **Esc:** stop drawing.
- **F6:** pause or resume.
- Stop or pause before manually moving the mouse.

## Updates

Installed Windows builds can use **Check updates / install** while the app is idle. Eligible published releases are downloaded as complete installers, verified against the published SHA-256 digest and installed over the existing Image Draw Bot installation.

RC builds accept newer RC/stable releases; stable builds do not automatically switch to prereleases. [Update details](docs/IN-APP-UPDATES.md)

## Troubleshooting

- **Automatic Paint setup fails:** expose the whole blank canvas, close menus, use RGB mode in Edit colors and verify the supported layout.
- **Wrong position or colors:** stop, verify the selected profile and recalibrate after window, DPI or zoom changes.
- **Too slow:** try Extra Fast, crop unnecessary backgrounds or reduce detail.
- **No update appears:** only published GitHub Releases count, not arbitrary commits or Actions artifacts.
- **Download verification fails:** retry the update; a failed download does not replace the installed app.
- **Windows blocks the app:** published builds are unsigned; the project does not require disabling Windows protection.

## Run from source

Install Python 3.10+ on Windows, extract the complete source and run:

```bat
Start.bat
```

The source launcher creates a private Python environment and installs required packages. Packaged Windows downloads include Python. CPU operation is supported; optional GPU acceleration depends on compatible hardware and drivers.

## Contributing and community

Contributions, reproducible bug reports and real target-app test results are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

If you want to help the project grow:

- **Star** the repository if you want to follow or revisit it.
- Share a real drawing result or app screenshot with a link back to the repo.
- Report target compatibility problems with logs and reproduction steps.
- Suggest Paint, Gartic Phone or Skribbl.io workflow improvements through Issues or Discussions.

A ready-to-use organic launch/share kit is available in [docs/PROMOTION.md](docs/PROMOTION.md).

## Development and release validation

Built with Python, CustomTkinter/Tkinter, Pillow and NumPy; Windows packages use PyInstaller and Inno Setup.

```powershell
python ReleasePackage.py --check
python -m unittest discover -v
python DrawBot.py --self-test
python ReleaseCandidateHardening.py --source-gate --soak-cycles 5000
python build_release.py --installer
```

For a local Windows release build, you can also run `Build-Release.bat`.

Windows releases must pass tests, packaging and a silent install/self-test/uninstall round trip before publication. Real drawing speed, GPU behavior and compatibility with every target layout still require live testing.

[Publishing](docs/PUBLISHING.md) · [Package layout](docs/RELEASE-STRUCTURE.md) · [Version history](VERSION-HISTORY.md) · [GitHub SEO checklist](docs/GITHUB-SEO-CHECKLIST.md)

## Privacy

Image analysis and rendering are local. No telemetry is included. Explicit features such as checking updates, loading an image URL, source dependency installation or optional network preview can use the network. The updater uses public releases from **Vxiey/Image-Draw-Bot**.

### Image Draw Bot banner

![Image Draw Bot promotional banner for Windows automatic image drawing](assets/image-draw-bot-social-preview.png)
