"""Versioned source palette plus conservative, click-free screen matching."""
from dataclasses import dataclass


class NoColorSwatchesError(ValueError):
    """A valid sampling region contained no eligible solid swatches."""

@dataclass(frozen=True)
class Palette:
    source: str
    checked: str
    names: tuple
    colors: tuple

# Index order from the public game's kt/wt arrays. Rows in the UI alternate
# even and odd indices; do not reorder this table into screen reading order.
SKRIBBL = Palette(
    'https://skribbl.io/js/game.js', '2026-09-05',
    ('White','Black','Light Gray','Gray','Red','Dark Red','Orange','Dark Orange',
     'Yellow','Dark Yellow','Green','Dark Green','Mint','Dark Mint','Skyblue',
     'Dark Skyblue','Seablue','Dark Seablue','Purple','Dark Purple','Pink',
     'Dark Pink','Beige','Dark Beige','Brown','Dark Brown'),
    ((255,255,255),(0,0,0),(193,193,193),(80,80,80),(239,19,11),(116,11,7),
     (255,113,0),(194,56,0),(255,228,0),(232,162,0),(0,204,0),(0,70,25),
     (0,255,145),(0,120,93),(0,178,255),(0,86,158),(35,31,211),(14,8,101),
     (163,0,186),(85,0,105),(223,105,167),(135,53,84),(255,172,142),
     (204,119,77),(160,82,45),(99,48,13)))
# Gartic Phone reference palette from the current 6-column x 12-row UI.
# The calibration UI still samples the RGB actually rendered on screen after a
# successful match; this table is only a deterministic geometry/color reference.
GARTIC_PHONE = Palette(
    'Gartic Phone 6x12 palette reference', '2026-09-06',
    ('R1C1', 'R1C2', 'R1C3', 'R1C4', 'R1C5', 'R1C6', 'R2C1', 'R2C2', 'R2C3', 'R2C4', 'R2C5', 'R2C6', 'R3C1', 'R3C2', 'R3C3', 'R3C4', 'R3C5', 'R3C6', 'R4C1', 'R4C2', 'R4C3', 'R4C4', 'R4C5', 'R4C6', 'R5C1', 'R5C2', 'R5C3', 'R5C4', 'R5C5', 'R5C6', 'R6C1', 'R6C2', 'R6C3', 'R6C4', 'R6C5', 'R6C6', 'R7C1', 'R7C2', 'R7C3', 'R7C4', 'R7C5', 'R7C6', 'R8C1', 'R8C2', 'R8C3', 'R8C4', 'R8C5', 'R8C6', 'R9C1', 'R9C2', 'R9C3', 'R9C4', 'R9C5', 'R9C6', 'R10C1', 'R10C2', 'R10C3', 'R10C4', 'R10C5', 'R10C6', 'R11C1', 'R11C2', 'R11C3', 'R11C4', 'R11C5', 'R11C6', 'R12C1', 'R12C2', 'R12C3', 'R12C4', 'R12C5', 'R12C6'),
    ((0, 0, 0), (48, 48, 48), (68, 68, 68), (119, 119, 119), (170, 170, 170), (255, 255, 255), (1, 20, 11), (0, 76, 36), (0, 128, 0), (15, 177, 62), (102, 255, 102), (170, 255, 170), (0, 59, 59), (0, 102, 102), (0, 128, 128), (0, 179, 179), (64, 224, 208), (192, 255, 238), (0, 0, 102), (0, 0, 253), (0, 99, 214), (0, 122, 255), (50, 151, 255), (102, 177, 255), (29, 8, 91), (58, 30, 117), (78, 21, 192), (90, 58, 204), (95, 80, 194), (152, 118, 221), (76, 0, 39), (153, 0, 78), (188, 0, 97), (204, 0, 118), (255, 0, 143), (255, 135, 203), (51, 0, 0), (102, 0, 0), (153, 0, 0), (204, 0, 0), (255, 0, 0), (255, 135, 135), (40, 16, 4), (71, 36, 0), (140, 60, 14), (255, 88, 2), (255, 120, 41), (255, 164, 112), (135, 85, 21), (176, 112, 28), (211, 157, 31), (255, 193, 38), (255, 255, 0), (253, 241, 216), (141, 92, 70), (189, 129, 103), (200, 142, 116), (254, 204, 175), (255, 220, 200), (254, 230, 220), (132, 58, 57), (203, 90, 86), (219, 116, 113), (235, 143, 138), (254, 175, 168), (252, 224, 222), (27, 0, 0), (63, 24, 0), (66, 39, 35), (78, 42, 12), (96, 57, 46), (135, 96, 63)))

PRESETS = {'skribbl': SKRIBBL, 'skribbl-fast': SKRIBBL, 'gartic-phone': GARTIC_PHONE}


def detect_preset(image, preset, offset=(0,0)):
    """Find one solid rectangular component per exact RGB, or reject.

    Input must be a tightly selected palette region, never an entire game.
    No guessed coordinates, tolerance, missing-color substitution, or clicks.
    """
    image=image.convert('RGB');w,h=image.size
    if not (6<=w<=2000 and 6<=h<=1000) or w*h>1000000:
        raise ValueError('Select only the color palette, up to 1 million pixels.')
    pixels=image.load();wanted=set(preset.colors);visited=bytearray(w*h)
    candidates={rgb:[] for rgb in preset.colors}
    for y in range(h):
        for x in range(w):
            index=y*w+x;rgb=pixels[x,y]
            if visited[index] or rgb not in wanted:continue
            visited[index]=1;stack=[(x,y)];count=0
            left=right=x;top=bottom=y
            while stack:
                a,b=stack.pop();count+=1
                if a<left:left=a
                elif a>right:right=a
                if b<top:top=b
                elif b>bottom:bottom=b
                for nx,ny in ((a-1,b),(a+1,b),(a,b-1),(a,b+1)):
                    if 0<=nx<w and 0<=ny<h:
                        ni=ny*w+nx
                        if not visited[ni] and pixels[nx,ny]==rgb:
                            visited[ni]=1;stack.append((nx,ny))
            cw,ch=right-left+1,bottom-top+1
            if not (6<=cw<=100 and 6<=ch<=100 and .6<=cw/ch<=1.7):continue
            if count<cw*ch*.85:continue
            cx,cy=(left+right)//2,(top+bottom)//2
            if all(pixels[a,b]==rgb for a in range(cx-2,cx+3) for b in range(cy-2,cy+3)):
                candidates[rgb].append((cx+offset[0],cy+offset[1],cw,ch))
    bad=[preset.names[i] for i,rgb in enumerate(preset.colors) if len(candidates[rgb])!=1]
    if bad:raise ValueError('Could not identify all colors unambiguously: '+', '.join(bad)+'. Select more tightly or use manual capture.')
    matches=[candidates[rgb][0] for rgb in preset.colors]
    widths=[m[2] for m in matches];heights=[m[3] for m in matches]
    if max(widths)>min(widths)*1.5 or max(heights)>min(heights)*1.5:
        raise ValueError('Color swatches have different sizes. Check the selection.')
    return [(m[0],m[1]) for m in matches]


def sample_grid(image, rows, columns, offset=(0,0)):
    """Read equal-sized grid cells. App indices are row-major, NOT game IDs."""
    if type(rows) is not int or type(columns) is not int or not 1<=rows*columns<=96 or min(rows,columns)<1:
        raise ValueError('The grid must contain 1–96 colors.')
    image=image.convert('RGB');w,h=image.size
    if w<columns*8 or h<rows*8 or w*h>1000000:
        raise ValueError('Select a clear color palette with equally sized swatches.')
    positions=[];colors=[]
    for row in range(rows):
        for col in range(columns):
            x=int((col+.5)*w/columns);y=int((row+.5)*h/rows)
            rgb=image.getpixel((x,y))
            if any(image.getpixel((a,b))!=rgb for a in range(x-2,x+3) for b in range(y-2,y+3)):
                raise ValueError('A color swatch is not solid in the center. Check the grid and selection.')
            positions.append((x+offset[0],y+offset[1]));colors.append(rgb)
    if len(set(colors))!=len(colors):
        raise ValueError('Duplicate colors were detected. Check row/column counts or capture manually.')
    return positions,colors


def sample_paint_grid(image, rows, columns, offset=(0,0)):
    """Sample spaced Paint swatches; deduplicate exact RGBs, never near colors.

    Contrast against cell corners excludes likely empty/custom slots. Ambiguous
    background-colored swatches must be captured manually. This is a screenshot
    heuristic, not knowledge of which Paint controls are actually clickable.
    """
    from statistics import median
    if type(rows) is not int or type(columns) is not int or min(rows,columns)<1 or not 1<=rows*columns<=64:
        raise ValueError('Enter 1–64 color swatches in total.')
    image=image.convert('RGB');w,h=image.size
    if w<columns*10 or h<rows*10 or w*h>1000000:
        raise ValueError("Select only Paint's palette with clear color swatches.")
    positions=[];colors=[];duplicates=0;skipped=0
    for row in range(rows):
        for col in range(columns):
            left,right=int(col*w/columns),int((col+1)*w/columns)
            top,bottom=int(row*h/rows),int((row+1)*h/rows)
            cx,cy=(left+right)//2,(top+bottom)//2
            samples=[image.getpixel((x,y)) for y in range(cy-2,cy+3) for x in range(cx-2,cx+3)]
            rgb=tuple(int(median(p[i] for p in samples)) for i in range(3))
            # Tolerate a few edge/selection pixels, but not gradients or icons.
            if sum(max(abs(p[i]-rgb[i]) for i in range(3))<=3 for p in samples)<22:
                skipped+=1;continue
            corners=[image.getpixel(p) for p in ((left,top),(right-1,top),(left,bottom-1),(right-1,bottom-1))]
            if sum(max(abs(p[i]-rgb[i]) for i in range(3))>8 for p in corners)<3:
                skipped+=1;continue
            # Choose an actual pixel of the sampled color nearest the center.
            choices=[(x,y) for y in range(cy-2,cy+3) for x in range(cx-2,cx+3) if image.getpixel((x,y))==rgb]
            if not choices:skipped+=1;continue
            x,y=min(choices,key=lambda p:(p[0]-cx)**2+(p[1]-cy)**2)
            if rgb in colors:duplicates+=1;continue
            colors.append(rgb);positions.append((x+offset[0],y+offset[1]))
    if not colors:
        raise ValueError('No clear Paint colors were found. Check rows, columns and selection, or capture colors manually.')
    return positions,colors,{'duplicates':duplicates,'skipped':skipped}


def _span_components(image, cancelled):
    """Label solid row spans; return None for noise that needs the bounded DFS."""
    import numpy as np
    a=np.asarray(image)
    breaks=np.any(a[:,1:] != a[:,:-1],axis=2)
    run_count=int(np.count_nonzero(breaks))+image.height
    if run_count>max(4096,min(50000,image.width*image.height//8)):
        # Every accepted swatch needs an exact 5×5 interior. If five horizontal
        # runs cannot overlap for five rows, the noisy image has no candidate;
        # avoid a Python component walk over thousands of isolated pixels.
        same=~breaks
        row_solid=same[:,:-3]&same[:,1:-2]&same[:,2:-1]&same[:,3:]
        possible=row_solid[:-4]&row_solid[1:-3]&row_solid[2:-2]&row_solid[3:-1]&row_solid[4:]
        if not bool(np.any(possible)):return []
        return None
    pixels=image.load();parents=[];stats=[];colors=[];previous=[]
    def root(index):
        while parents[index]!=index:
            parents[index]=parents[parents[index]];index=parents[index]
        return index
    def merge(left,right):
        left,right=root(left),root(right)
        if left==right:return left
        if right<left:left,right=right,left
        parents[right]=left
        s,t=stats[left],stats[right]
        s[0]+=t[0];s[1]=min(s[1],t[1]);s[2]=min(s[2],t[2]);s[3]=max(s[3],t[3]);s[4]=max(s[4],t[4])
        return left
    for y in range(image.height):
        if y%16==0 and cancelled():raise InterruptedError('Palette scan cancelled.')
        boundaries=[0,*((np.flatnonzero(breaks[y])+1).tolist()),image.width]
        current=[];first=0
        for x0,x1 in zip(boundaries,boundaries[1:]):
            rgb=pixels[x0,y]
            while first<len(previous) and previous[first][1]<=x0:first+=1
            neighbor=first;matches=[]
            while neighbor<len(previous) and previous[neighbor][0]<x1:
                if previous[neighbor][3]==rgb:matches.append(root(previous[neighbor][2]))
                neighbor+=1
            if not matches:
                label=len(parents);parents.append(label);colors.append(rgb)
                stats.append([x1-x0,x0,y,x1-1,y])
            else:
                label=matches[0]
                for other in matches[1:]:label=merge(label,other)
                s=stats[label];s[0]+=x1-x0;s[1]=min(s[1],x0);s[3]=max(s[3],x1-1);s[4]=y
            current.append((x0,x1,label,rgb))
        previous=current
    return [(colors[i],*stats[i]) for i in range(len(parents)) if parents[i]==i]


def _pixel_components(image, cancelled):
    """Exact four-connected fallback with one byte of visit state per pixel."""
    w,h=image.size;pixels=image.load();visited=bytearray(w*h)
    for sy in range(h):
        if sy%16==0 and cancelled():raise InterruptedError('Palette scan cancelled.')
        for sx in range(w):
            start_index=sy*w+sx
            if visited[start_index]:continue
            rgb=pixels[sx,sy];visited[start_index]=1;stack=[(sx,sy)]
            count=0;left=right=sx;top=bottom=sy
            while stack:
                x,y=stack.pop();count+=1
                if count%4096==0 and cancelled():raise InterruptedError('Palette scan cancelled.')
                if x<left:left=x
                elif x>right:right=x
                if y<top:top=y
                elif y>bottom:bottom=y
                if x:
                    ni=y*w+x-1
                    if not visited[ni] and pixels[x-1,y]==rgb:visited[ni]=1;stack.append((x-1,y))
                if x+1<w:
                    ni=y*w+x+1
                    if not visited[ni] and pixels[x+1,y]==rgb:visited[ni]=1;stack.append((x+1,y))
                if y:
                    ni=(y-1)*w+x
                    if not visited[ni] and pixels[x,y-1]==rgb:visited[ni]=1;stack.append((x,y-1))
                if y+1<h:
                    ni=(y+1)*w+x
                    if not visited[ni] and pixels[x,y+1]==rgb:visited[ni]=1;stack.append((x,y+1))
            yield rgb,count,left,top,right,bottom


def detect_color_swatches(image, offset=(0, 0), max_colors=96, *, cancelled=lambda:False):
    """Find solid color swatches inside a user-selected screen region.

    This intentionally works only inside the selected region and never scans the
    full desktop.  Exact-color connected components are used so labels, icons,
    gradients and antialiased controls are rejected rather than guessed as
    clickable colors.  The returned position is inside the solid component.
    """
    if cancelled():raise InterruptedError('Palette scan cancelled.')
    image = image if image.mode=='RGB' else image.convert('RGB')
    w, h = image.size
    area = w * h
    if w < 8 or h < 8 or area > 1_000_000:
        raise ValueError('Select a color sampling area between 8 px and 1 million pixels.')
    if type(max_colors) is not int or not 1 <= max_colors <= 96:
        raise ValueError('Maximum color count must be between 1 and 96.')

    pixels = image.load()
    found = []
    rejected = 0

    def solid_point(rgb, box):
        left, top, right, bottom = box
        cx, cy = (left + right) // 2, (top + bottom) // 2
        # Prefer points near the component center with a 5x5 solid neighborhood.
        candidates = []
        for radius in range(0, max(right-left, bottom-top) + 1):
            for x, y in ((cx-radius, cy), (cx+radius, cy), (cx, cy-radius), (cx, cy+radius)):
                if left + 2 <= x <= right - 2 and top + 2 <= y <= bottom - 2:
                    candidates.append((x, y))
            if len(candidates) > 200:
                break
        # Add a coarse interior sweep in case the shape is not center-filled.
        step = max(1, min(right-left+1, bottom-top+1) // 8)
        for y in range(top+2, bottom-1, step):
            for x in range(left+2, right-1, step):
                candidates.append((x, y))
        seen = set()
        for x, y in candidates:
            if (x, y) in seen:
                continue
            seen.add((x, y))
            if all(pixels[xx, yy] == rgb
                   for yy in range(y-2, y+3)
                   for xx in range(x-2, x+3)):
                return x, y
        return None

    components=_span_components(image,cancelled)
    if components is None:components=_pixel_components(image,cancelled)
    for rgb,count,left,top,right,bottom in components:
            cw, ch = right-left+1, bottom-top+1
            bbox_area = cw * ch
            touches = sum((left == 0, top == 0, right == w-1, bottom == h-1))
            # Solid swatch interiors are compact rectangles. Reject text,
            # borders, thin separators, huge backgrounds and tiny noise. A
            # dominant component touching multiple selection edges is almost
            # certainly the palette/toolbar background, not a swatch.
            if (cw < 6 or ch < 6 or cw > 180 or ch > 180 or
                    bbox_area < 36 or bbox_area > area * .35 or
                    count > area * .35 or
                    (touches >= 2 and count > area * .08) or
                    count / bbox_area < .55 or not .35 <= cw/ch <= 2.8):
                rejected += 1
                continue
            point = solid_point(rgb, (left, top, right, bottom))
            if point is None:
                rejected += 1
                continue
            found.append({
                'rgb': rgb,
                'position': (point[0] + offset[0], point[1] + offset[1]),
                'box': (left, top, right, bottom),
                'count': count,
            })

    # Duplicate RGB swatches do not add drawing capability. Keep the largest,
    # then return colors in visual row-major order for predictable UI output.
    by_rgb = {}
    duplicates = 0
    for item in found:
        old = by_rgb.get(item['rgb'])
        if old is None or item['count'] > old['count']:
            if old is not None: duplicates += 1
            by_rgb[item['rgb']] = item
        else:
            duplicates += 1
    unique = list(by_rgb.values())
    if cancelled():raise InterruptedError('Palette scan cancelled.')
    if not unique:
        raise NoColorSwatchesError('No solid color swatches were found in the selected area. Try a tighter selection or use Grid mode.')
    if len(unique) > max_colors:
        # Prefer the largest solid components if decorative UI colors were also
        # selected, then restore visual order.
        unique = sorted(unique, key=lambda item: item['count'], reverse=True)[:max_colors]
    unique.sort(key=lambda item: ((item['box'][1] + item['box'][3]) // 2,
                                  (item['box'][0] + item['box'][2]) // 2))
    return ([item['position'] for item in unique],
            [item['rgb'] for item in unique],
            {'found': len(unique), 'duplicates': duplicates, 'rejected': rejected})
