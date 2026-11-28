"""Identify Sketchful's three rows of thirteen shaded colors in a side toolbar."""

from statistics import median


def find_sketchful_grid(positions, rgbs):
    """Return observed swatches in visual order and their column spacing."""
    rows = []
    for (x, y), rgb in sorted(zip(positions, rgbs), key=lambda item: item[0][1]):
        if not rows or y - rows[-1][0][1] > 2:
            rows.append([])
        rows[-1].append((x, y, rgb))
    rows = [sorted(row) for row in rows if len(row) >= 10]
    for first, middle, last in zip(rows, rows[1:], rows[2:]):
        ys = [median(y for x, y, rgb in row) for row in (first, middle, last)]
        vertical_pitch = (ys[2] - ys[0]) / 2
        if vertical_pitch < 7 or abs(ys[1] - ys[0] - vertical_pitch) > max(2, vertical_pitch*.12):
            continue
        for reference in (first, middle, last):
            for start in range(len(reference)-12):
                centers = [x for x, y, rgb in reference[start:start+13]]
                pitch = (centers[-1]-centers[0]) / 12
                tolerance = max(2, pitch*.12)
                if abs(pitch - vertical_pitch) > max(2, pitch*.22):
                    continue
                if any(abs(x - centers[0] - i*pitch) > tolerance for i, x in enumerate(centers)):
                    continue
                grid = {}
                for row_id, row in enumerate((first, middle, last)):
                    for x, y, rgb in row:
                        col = round((x-centers[0])/pitch)
                        if 0 <= col < 13 and abs(x - centers[col]) <= tolerance:
                            grid[row_id, col] = (x, y, rgb)
                # The bottom two swatches of a column are progressively darker
                # versions of the top one. A regular grid of toolbar icons or
                # arbitrary artwork is insufficient evidence of drawing colors.
                shaded = sum(sum(grid[0, c][2]) > sum(grid[1, c][2]) > sum(grid[2, c][2])
                             for c in range(13) if all((row, c) in grid for row in range(3)))
                vivid = sum(max(rgb)-min(rgb) >= 55 for (r, c), (x, y, rgb) in grid.items() if r == 0)
                if len(grid) >= 34 and shaded >= 9 and vivid >= 7:
                    return grid, centers, ys, pitch
    return None


def recover_sketchful_black(image, grid, centers, ys, pitch, origin):
    """Recover only the known black cell if global RGB deduplication selected a tool."""
    if (2, 0) in grid:
        return
    x, y = centers[0], round(ys[2])
    lx, ly = x-origin[0], y-origin[1]
    # A solid black center with a surrounding lighter toolbar distinguishes the
    # actual round swatch from empty space or the slider's black knob above it.
    rim = max(4, round(pitch*.55))
    if not (rim <= lx < image.width-rim and 2 <= ly < image.height-2):
        return
    black = (0, 0, 0)
    if (all(image.getpixel((lx+dx, ly+dy)) == black for dx in (-2, 0, 2) for dy in (-2, 0, 2))
            and image.getpixel((lx-rim, ly)) != black and image.getpixel((lx+rim, ly)) != black):
        grid[2, 0] = (x, y, black)
