# Drawing on different canvases

A native Windows drawing bot spends time selecting colors and tools, moving the pointer, pressing and releasing the button, and waiting for the target to accept input. Planning and actual drawing have different costs. A change that shortens the first stage can leave the second unchanged.

## Lessons from other drawing tools

- AutoDraw for skribbl.io lets the user drop a picture directly onto a known game canvas. Its Chrome Web Store listing calls out the speed advantage of simple clip art. For a desktop app serving several targets, the corresponding shortcut is to identify the window and display the proposed canvas as part of the initial setup. [Project](https://github.com/galehouse5/skribbl-io-autodraw) · [Chrome Web Store](https://chromewebstore.google.com/detail/autodraw-for-skribblio/bpnefockcbbpkbahgkkacjmebfheacjb)
- Dev-Zhao's Skribbl extension describes fitting the image to the canvas and matching the game's limited palette. Its README lists dithering as future work. In a mouse-driven app, assess dithering against both the improvement to shading and the extra small marks that it would require. [Project and approach](https://github.com/Dev-Zhao/skribbl.io-autodraw)
- Chrome content scripts can access the host page's DOM. A Java desktop bot using AWT Robot delivers native mouse events. These interfaces have different timing constraints. Benchmark the complete drawing in the target application before choosing an implementation language or comparing speeds. [Chrome documentation](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts) · [Java Robot documentation](https://docs.oracle.com/en/java/javase/21/docs/api/java.desktop/java/awt/Robot.html)
- The desktop project o7q/DrawBot exposes separate row-by-row and color-grouped methods and warns that high speed can cause missed input. For a general Windows app, verify delivered marks and reuse a calibrated palette, including when comparing a new path ordering. [DrawBot manual](https://github.com/o7q/DrawBot#interface)
- The plotter tool vpype sorts paths to reduce travel while the pen is raised. Its optional two-opt pass trades additional planning time for shorter travel. Image Draw Bot must also preserve the order of painting where paths overlap and include the cost of the target's controls. [vpype linesort](https://vpype.readthedocs.io/en/stable/reference.html#linesort)

## Experiments for a future release

| Image and target | Experiment | Decide using |
| --- | --- | --- |
| Flat icons on Paint | Compare a verified bucket fill with same-color runs on a known closed region. Include the cost of entering and leaving the Fill tool. | Measured input time, complete silhouette, and zero spill into neighboring regions |
| Text or pixel art on Skribbl | Compare horizontal and vertical runs on each connected component. Keep one-pixel gaps and thin stroke ends. | Exact simulated mask, physical button releases, and whether the browser displays each mark |
| Cartoon outlines on Gartic | Compare two calibrated brush widths on interior regions. Keep outlines and small features on the protected pass. | Within-round completion, boundary accuracy, and number of brush changes |
| Portraits on limited palettes | Compare two detail budgets on the same face and shadows. Spend spare time on high-contrast details. | Local weighted color error, recognition of fine features, elapsed drawing time |
| Repeated drawings in the same window | Use measured draw history to predict when tool/color changes dominate, then test whether reordering independent color batches helps. | Difference between estimated and actual time on the next run, with identical output |

Use the same input, canvas size, available colors, physical brush widths and cold/warm setup for each comparison. Report planning time and actual input time independently, including failures to verify the target or deliver a mark.
