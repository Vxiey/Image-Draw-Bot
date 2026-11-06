"""CPU/reference comparisons for the color analysis working set and Stop flow."""
from contextlib import closing
import math
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image


def scalar_cells(groups, active, grid, *, legacy_sqrt_mass=False):
    records = []
    for color in active:
        for stroke in groups[color]:
            x1, y1, x2, y2 = map(float, stroke)
            length = (math.sqrt((x2-x1)**2 + (y2-y1)**2) if legacy_sqrt_mass
                      else math.hypot(x2-x1, y2-y1))
            records.append((color, (x1+x2)*.5, (y1+y2)*.5, max(1.0, length)))
    if not records:
        return {}
    xmin = min(row[1] for row in records)
    xmax = max(row[1] for row in records)
    ymin = min(row[2] for row in records)
    ymax = max(row[2] for row in records)
    cells = {}
    for color, x, y, mass in records:
        gx = min(grid-1, max(0, int((x-xmin)/max(1.0, xmax-xmin)*grid)))
        gy = min(grid-1, max(0, int((y-ymin)/max(1.0, ymax-ymin)*grid)))
        bucket = cells.setdefault((gx, gy), {})
        bucket[color] = bucket.get(color, 0.0) + mass
    return cells


def scalar_edge_colors(image, count):
    import PictureCustomPaletteLegacy as legacy
    with closing(legacy._analysis_image(image)) as source:
        # Batch05 corrects the edge definition. Keep this allocation regression
        # independent: inspect each real 4-neighbor directly in source order.
        pixels = source.load()
        candidates = []
        for y in range(source.height):
            for x in range(source.width):
                rgb = pixels[x, y]
                if any(max(abs(rgb[c]-pixels[nx, ny][c]) for c in range(3)) >= 32
                       for nx, ny in ((x-1,y), (x+1,y), (x,y-1), (x,y+1))
                       if 0 <= nx < source.width and 0 <= ny < source.height):
                    candidates.append(rgb)
    if not candidates:
        return []
    step = max(1, math.ceil(len(candidates)/legacy.MAX_EDGE_SAMPLES))
    candidates = candidates[::step][:legacy.MAX_EDGE_SAMPLES]
    with closing(Image.new('RGB', (len(candidates), 1))) as sample:
        sample.putdata(candidates)
        with closing(sample.quantize(colors=max(1, min(count, 16)),
                                     method=Image.Quantize.MEDIANCUT,
                                     dither=Image.Dither.NONE)) as quantized:
            palette = quantized.getpalette()
            rows = sorted(quantized.getcolors(), reverse=True)
    return legacy._dedupe([tuple(palette[index*3:index*3+3]) for _mass, index in rows])


def importance_reference(rgb):
    """Original allocation-heavy formula, with the shared corrected gradient."""
    from VisualImportanceMap import _normalize
    from ImageGradients import luminance_edges
    pixels = rgb.astype(np.float32)/255.0
    luminance = pixels[..., 0]*.2126 + pixels[..., 1]*.7152 + pixels[..., 2]*.0722
    edges = luminance_edges(luminance)
    contrast = np.zeros_like(luminance)
    contrast[1:-1, 1:-1] = (
        np.abs(luminance[1:-1, 1:-1]-luminance[:-2, 1:-1]) +
        np.abs(luminance[1:-1, 1:-1]-luminance[2:, 1:-1]) +
        np.abs(luminance[1:-1, 1:-1]-luminance[1:-1, :-2]) +
        np.abs(luminance[1:-1, 1:-1]-luminance[1:-1, 2:]))*.25
    border = np.concatenate((pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]), axis=0)
    median = np.median(border, axis=0)
    foreground = np.sqrt(np.sum((pixels-median[None, None, :])**2, axis=2))
    dark = np.clip((.48-luminance)*2., 0., 1.)*np.clip(contrast*6., 0., 1.)
    en, cn, fn = map(_normalize, (edges, contrast, foreground))
    result = np.clip(.48*en + .22*cn + .20*fn + .10*dark, 0., 1.)
    height, width = luminance.shape
    yy, xx = np.ogrid[:height, :width]
    nx = (xx-(width-1)*.5)/max(1., width*.5)
    ny = (yy-(height-1)*.5)/max(1., height*.5)
    center = np.clip(1.-np.sqrt(nx*nx+ny*ny), 0., 1.)
    result = np.clip(result + center.astype(np.float32)*.05, 0., 1.)
    return result, {
        'backend': 'cpu-numpy', 'edge_mean': float(en.mean()),
        'contrast_mean': float(cn.mean()), 'foreground_mean': float(fn.mean()),
        'protected_percent': float((result >= .62).mean()*100.),
        'border_rgb': tuple(int(round(v*255)) for v in median),
    }


class AnalysisWorkingSetTests(unittest.TestCase):
    def test_spatial_stream_matches_materialized_reference(self):
        from ColorSpatialSummary import midpoint_color_cells
        rng = np.random.default_rng(194)
        groups = [[tuple(row) for row in rng.integers(-80, 240, (100, 4))/3.]
                  for _ in range(6)]
        groups[0].extend([(0, 0, 0, 0), (10, 2, 10, 9), (3, 1, 7, 1)])
        for grid in (3, 4, 8):
            for old_sqrt in (False, True):
                with self.subTest(grid=grid, old_sqrt=old_sqrt):
                    self.assertEqual(
                        midpoint_color_cells(groups, [0, 2, 4, 5], grid, legacy_sqrt_mass=old_sqrt),
                        scalar_cells(groups, [0, 2, 4, 5], grid, legacy_sqrt_mass=old_sqrt))

    def test_spatial_stream_preserves_one_shot_groups_and_empty_input(self):
        from ColorSpatialSummary import midpoint_color_cells
        groups = [[(0, 0, 3, 4), (20, 0, 24, 2)], [(2, 3, 5, 8)]]
        self.assertEqual(midpoint_color_cells([iter(g) for g in groups], [0, 1], 4),
                         scalar_cells(groups, [0, 1], 4))
        self.assertEqual(midpoint_color_cells([[]], [0], 3), {})

    def test_spatial_passes_skip_the_same_unrepresentable_geometry(self):
        from ColorSpatialSummary import midpoint_color_cells
        from RegionAwareQuantization import region_detail_anchor_candidates
        groups = [[(0, 0, 1e200, 0)], [(0, 0, 1, 1)]]
        self.assertEqual(region_detail_anchor_candidates(groups, [(0, 0, 0), (255, 255, 255)],
                                                        [0, 1], [1, 1], 8), [])
        self.assertEqual(midpoint_color_cells(groups, [0, 1], 4, legacy_sqrt_mass=True),
                         midpoint_color_cells([[], groups[1]], [0, 1], 4, legacy_sqrt_mass=True))
        # Finite inputs can also overflow while forming a midpoint or delta.
        invalid = [(1e308, 0, 1e308, 1), (-1e308, 0, 1e308, 1)]
        self.assertEqual(midpoint_color_cells([invalid, groups[1]], [0, 1], 4),
                         midpoint_color_cells([[], groups[1]], [0, 1], 4))

    def test_edge_rgb_sample_preserves_order_threshold_and_sample_cap(self):
        import PictureCustomPaletteLegacy as legacy
        rng = np.random.default_rng(195)
        with closing(Image.fromarray(rng.integers(0, 256, (224, 320, 3), dtype=np.uint8))) as image:
            for count in (1, 6, 16):
                self.assertEqual(legacy._edge_detail_colors(image, count), scalar_edge_colors(image, count))
        with closing(Image.new('RGB', (6, 7))) as black:
            self.assertEqual(legacy._edge_detail_colors(black, 4), [])

    def test_importance_working_set_reuse_is_bit_exact(self):
        from VisualImportanceMap import _cpu_map
        rng = np.random.default_rng(196)
        for shape in ((17, 31, 3), (1, 9, 3), (8, 1, 3), (1, 1, 3)):
            for rgb in (rng.integers(0, 256, shape, dtype=np.uint8), np.zeros(shape, np.uint8)):
                result, metadata = _cpu_map(rgb)
                expected, expected_metadata = importance_reference(rgb)
                np.testing.assert_array_equal(result, expected)
                self.assertEqual(metadata, expected_metadata)


class AnalysisStopTests(unittest.TestCase):
    def test_color_count_backend_interruption_never_falls_back(self):
        import AdaptiveColorCount as adaptive
        with patch('UniversalGpuAcceleration.pairwise_oklab_distance', side_effect=InterruptedError('stop')), \
             patch.object(adaptive, 'rgb_to_oklab', side_effect=AssertionError('no CPU fallback')):
            with self.assertRaises(InterruptedError):
                adaptive._distance_matrix([(1, 2, 3), (100, 50, 30)])

    def test_color_count_stop_after_edge_analysis_prevents_curve(self):
        import AdaptiveColorCount as adaptive
        stopped = [False]
        def edge(_sample):
            stopped[0] = True
            return .1
        with closing(Image.new('RGB', (8, 8), 'red')) as image:
            with patch.object(adaptive, '_edge_density', side_effect=edge), \
                 patch.object(adaptive, '_greedy_error_curve') as curve:
                with self.assertRaises(InterruptedError):
                    adaptive.recommend_adaptive_color_count(image, ceiling=8, cancelled=lambda: stopped[0])
                curve.assert_not_called()

    def test_prepared_map_forwards_the_same_stop_callback(self):
        from PicturePalettePlanning import build_prepared_color_strokes
        stopped = lambda: True
        with patch('PixelAccuratePlanner.exact_palette_map', side_effect=InterruptedError()) as map_pixels:
            with self.assertRaises(InterruptedError):
                build_prepared_color_strokes(None, [(1, 2, 3)], (), {}, skip_white=False, cancelled=stopped)
        self.assertIs(map_pixels.call_args.kwargs['cancelled'], stopped)

    def test_shadow_stop_after_blur_skips_further_feature_work(self):
        import ShadowDetailEngine as shadow
        stopped = [False]
        def blur(values, _radius):
            stopped[0] = True
            return values.copy()
        with patch.object(shadow, '_box_blur', side_effect=blur), \
             patch.object(shadow, '_palette_boundaries') as boundaries:
            with self.assertRaises(InterruptedError):
                shadow.analyze_shadow_contours(np.zeros((3, 3, 3), np.uint8),
                    np.zeros((3, 3), np.int32), np.ones((3, 3), bool),
                    np.zeros((3, 3), np.float32), cancelled=lambda: stopped[0])
        boundaries.assert_not_called()


if __name__ == '__main__':
    unittest.main()
