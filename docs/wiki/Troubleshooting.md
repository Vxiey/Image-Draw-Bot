# Troubleshooting

**Stop unexpected drawing with Esc before changing setup.**

| Problem | Next checks |
| --- | --- |
| Start unavailable | Open Setup wizard, load an image, check current operation; browser/manual start may require Unlock |
| Paint preparation fails | One visible Paint window, blank full canvas, visible toolbar and RGB controls; read status |
| Mouse draws in wrong place | Correct profile, canvas bounds, zoom and display scaling; recalibrate then test |
| Wrong colors or tools | Target palette/tool calibration and current brush; stop before another attempt |
| Gaps or missed actions | Lower input speed; verify target focus and brush behavior |
| Slow preparation | Reduce planning resolution/detail; start with Auto resource settings |
| Slow drawing | Fewer details/color switches, simpler source or Extra Fast; leave enough round time |
| Blank/old preview | Confirm loaded image and canvas, read status, press Build preview again |
| Old taskbar icon | Check version and executable path; see Updates |
| Python not found | Use packaged Setup/ZIP, or install 64-bit Python 3.11+ for source use |
| GPU unavailable | CPU fallback remains available; check compatible backend and graphics driver |

## Picture colors saved, but the preview still looks wrong

Update to rc8, run **Custom color palette for picture** again, then **Build preview**. rc7 and earlier could leave the old preview visible; Pixel Accurate also ignored image-specific colors. rc8 shares the prepared RGB palette with both the preview and runtime selection. Check Microsoft Paint is selected and RGB calibration is ready. A limited-color photo remains an approximation even after these fixes.

## Paint closes or stops responding during picture palette preparation

Use v1.0.144-rc7 or later. This release waits for RGB fields before typing and adds each color with +, waits at least 750 ms and closes Edit colors once after the batch. It also avoids Pencil/size preparation for the picture-palette button. These fixes address timing problems; they do not prove the cause of every Paint crash.

Distinguish **Paint controls did not respond** (Image Draw Bot stopped waiting for a control operation) from Paint itself disappearing or Windows reporting an application crash. If it persists, include both Image Draw Bot and Microsoft Paint versions and state whether Edit colors appeared or any RGB values were entered. A Windows application-error event for mspaint/PaintApp can identify a process crash more precisely.

## Report a reproducible problem

Use [GitHub Issues](https://github.com/Vxiey/Image-Draw-Bot/issues). Include app version, Windows version, target/profile, installer or portable/source launch, exact steps, expected/actual behavior and the status/error text. For icon issues include a screenshot and launch path. For drawing issues include a small example you can share.

Runtime safety reports and diagnostics are local. Review files for personal information before attaching them. Automated tests do not confirm compatibility with every Paint/browser layout.

[FAQ](FAQ) · [First Use](First-Use) · [Gartic Phone requirements](Gartic-Phone)
