"""Verify exact one-pixel plans using eight existing, tracked image assets.

Writes numeric JSON only. No fixture factory or image export is used. This is
a quality regression gate; its single planning duration is not a speed claim.
"""
from contextlib import closing
import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
from PIL import Image, ImageDraw, __version__ as pillow_version

from PixelAccuratePlanner import build_pixel_map
from PixelStrokeEngine import build_pixel_stroke_plan
from Version import APP_VERSION


ROOT = Path(__file__).resolve().parent
CASES = (
    ('red-bananas', 'golden-regression/red-bananas-texture.png', None),
    ('yellow-banana', 'golden-regression/yellow-banana-hue-guard.png', None),
    ('small-details', 'golden-regression/small-detail-preservation.png', None),
    ('dominant-hues', 'golden-regression/dominant-hue-four-color.png', None),
    ('icon-crop', 'assets/image-draw-bot-icon.png', (128, 128, 384, 384)),
    ('paint-reference', 'assets/paint-tools-reference.png', None),
    ('application-webp', 'assets/image-draw-bot-app-screenshot.webp', None),
    ('application-png-crop', 'assets/image-draw-bot-app-screenshot.png', (320, 200, 640, 440)),
)
PALETTE = ((255, 255, 255), (0, 0, 0), (255, 0, 0), (0, 0, 255),
           (255, 204, 64), (54, 160, 92), (70, 145, 225), (128, 128, 128))
OPTIONS = dict(profile_key='isolated-benchmark', gpu_mode='CPU',
               speed='Balanced', precision='High', delay=.006, brush_px=1,
               adaptive_hybrid_cost='Auto')


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    before = source_hashes()
    rows = []
    for name, relative, crop in CASES:
        path = ROOT / relative
        with closing(Image.open(path)) as original:
            with closing(original.crop(crop) if crop else original.copy()) as image:
                pixel_map = build_pixel_map(image, PALETTE, gpu_mode='CPU', skip_white=True)
                started = time.perf_counter()
                plan = build_pixel_stroke_plan(pixel_map, len(PALETTE),
                                              options=OPTIONS, cpu_workers=1)
                elapsed = time.perf_counter() - started
                # Independent Pillow replay of the actual ordered plan, kept
                # in memory and never exported as an image asset.
                with closing(Image.new('I', image.size, -1)) as rendered:
                    draw = ImageDraw.Draw(rendered)
                    for entry in plan['execution_sequence']:
                        points = entry['path']
                        color = int(entry['color_index'])
                        if len(points) == 1:
                            draw.point(points[0], fill=color)
                        else:
                            draw.line(points, fill=color, width=1)
                    actual = np.asarray(rendered)
                    expected = np.where(pixel_map.drawable_mask, pixel_map.palette_index, -1)
                    wrong = int(np.count_nonzero(actual != expected))
                    del draw, actual, expected
                rows.append(dict(case=name, source=relative, crop=crop,
                    file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    input_pixel_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
                    size=image.size, planning_seconds=elapsed,
                    operations=len(plan['execution_sequence']),
                    mismatched_plan_pixels=wrong, exact_palette_geometry=wrong == 0))
                print(f'{name}: {wrong} mismatched pixels', flush=True)
    after = source_hashes()
    result = dict(schema=1, app_version=APP_VERSION, python=platform.python_version(),
        platform=platform.platform(), numpy=np.__version__, pillow=pillow_version,
        palette=PALETTE, options=OPTIONS, cases=rows, source_hashes=before,
        source_unchanged=before == after, real_windows_input_verified=False,
        physical_gpu_verified=False, image_assets_created=False,
        quality_scope='Ordered 1 px plans against quantized PixelMap; not original-image perceptual fidelity.',
        timing_scope='One planning invocation per existing asset; no comparative performance claim.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return 0 if before == after and all(row['exact_palette_geometry'] for row in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
