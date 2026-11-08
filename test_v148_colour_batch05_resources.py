"""Independent component/pixel oracles for the two memory optimizations."""
from contextlib import ExitStack, closing
import math
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import AccuracyEvaluator as accuracy
from ColorFidelity import rgb_to_oklab
from PixelAccuratePlanner import PixelMap
from PixelStrokeEngine import connected_components, build_pixel_stroke_plan


def component_oracle(pixel_map):
    height, width = pixel_map.palette_index.shape
    labels = np.full((height, width), -1, np.int32)
    components = []
    for y in range(height):
        for x in range(width):
            if not pixel_map.drawable_mask[y, x] or labels[y, x] >= 0:
                continue
            color = int(pixel_map.palette_index[y, x])
            cid = len(components)
            labels[y, x] = cid
            frontier = [(x, y)]
            members = []
            while frontier:
                cx, cy = frontier.pop()
                members.append((cx, cy))
                for nx, ny in ((cx-1,cy), (cx+1,cy), (cx,cy-1), (cx,cy+1)):
                    if (0 <= nx < width and 0 <= ny < height and labels[ny, nx] < 0
                            and pixel_map.drawable_mask[ny, nx] and pixel_map.palette_index[ny, nx] == color):
                        labels[ny, nx] = cid
                        frontier.append((nx, ny))
            members.sort(key=lambda p: (p[1], p[0]))
            def mean(plane):
                return 0.0 if plane is None else sum(float(plane[py, px]) for px, py in members) / len(members)
            components.append(dict(component_id=cid, color_index=color, area=len(members),
                bbox=(min(p[0] for p in members), min(p[1] for p in members),
                      max(p[0] for p in members), max(p[1] for p in members)),
                importance_mean=mean(pixel_map.importance_map),
                importance_max=max(float(pixel_map.importance_map[py, px]) for px, py in members),
                edge_mean=mean(pixel_map.edge_map),
                contour_mean=mean(pixel_map.contour_map if pixel_map.contour_map is not None else pixel_map.edge_map),
                shadow_mean=mean(pixel_map.shadow_map), shadow_detail_mean=mean(pixel_map.shadow_detail_map),
                protected_pixels=sum(bool(pixel_map.protected_mask[py, px]) for px, py in members)))
    return components, labels


class ComponentReductionTests(unittest.TestCase):
    def test_numeric_protected_masks_count_pixels_across_reduction_threshold(self):
        for width in (7, 8, 16):
            for values in (np.array([0, 255, 255], np.uint8),
                           np.array([.5, 0, -1.5], np.float32)):
                with self.subTest(width=width, dtype=values.dtype):
                    shape = (1, width)
                    index = (np.arange(width) % 2).astype(np.int16).reshape(shape)
                    plane = np.ones(shape, np.float32)
                    protected = np.resize(values, shape)
                    source = PixelMap(width, 1, np.zeros((*shape, 3), np.uint8), index,
                        np.ones(shape, bool), plane, plane, protected, {})
                    expected, labels = component_oracle(source)
                    actual, actual_labels, _ = connected_components(source)
                    np.testing.assert_array_equal(actual_labels, labels)
                    self.assertEqual([row.protected_pixels for row in actual],
                                     [row['protected_pixels'] for row in expected])
                    self.assertTrue(all(0 <= row.protected_pixels <= row.area for row in actual))

    def test_components_match_independent_pixel_flood_fill_with_gaps_and_optional_maps(self):
        rng = np.random.default_rng(148052)
        for shape in ((13,17), (1,23), (19,1), (1,1)):
            for optional in (False, True):
                idx = rng.integers(0, 3, shape, dtype=np.int16)
                draw = rng.random(shape) > .25
                planes = [rng.random(shape, dtype=np.float32) for _ in range(5)]
                pm = PixelMap(shape[1], shape[0], np.zeros((*shape,3), np.uint8), idx,
                    draw, planes[0], planes[1], rng.random(shape) > .7, {},
                    *(planes[2:] if optional else (None,None,None)))
                expected, expected_map = component_oracle(pm)
                for workers in (1, 3):
                    with self.subTest(shape=shape, optional=optional, workers=workers):
                        actual, actual_map, _meta = connected_components(pm, cpu_workers=workers)
                        np.testing.assert_array_equal(actual_map, expected_map)
                        self.assertEqual(len(actual), len(expected))
                        for component, row in zip(actual, expected):
                            for key, value in row.items():
                                self.assertEqual(getattr(component, key), value, key)

    def test_complete_planner_paths_reproduce_only_source_pixels(self):
        rng = np.random.default_rng(148053)
        shape = (19, 23)
        idx = rng.integers(0, 4, shape, dtype=np.int16)
        draw = rng.random(shape) > .22
        planes = [rng.random(shape, dtype=np.float32) for _ in range(5)]
        pm = PixelMap(shape[1], shape[0], np.zeros((*shape,3), np.uint8), idx,
            draw, planes[0], planes[1], planes[0] > .7, {}, *planes[2:])
        plan = build_pixel_stroke_plan(pm, 4, options={'adaptive_hybrid_cost': 'Off'})
        painted = np.full(shape, -1, np.int16)
        for entry in plan['execution_sequence']:
            path, color = entry['path'], entry['color_index']
            if len(path) == 1:
                x, y = path[0]
                painted[y, x] = color
            for (x0,y0),(x1,y1) in zip(path,path[1:]):
                self.assertTrue(x0 == x1 or y0 == y1)
                for y in range(min(y0,y1),max(y0,y1)+1):
                    for x in range(min(x0,x1),max(x0,x1)+1):
                        painted[y,x] = color
        np.testing.assert_array_equal(painted, np.where(draw, idx, -1))


def scalar_preview_metrics(source, preview, importance):
    """Small-image source metric oracle using independent double scalar OKLab."""
    src, dst = np.asarray(source), np.asarray(preview)
    height, width = src.shape[:2]
    source_labs = [[rgb_to_oklab(tuple(map(int, src[y,x]))) for x in range(width)] for y in range(height)]
    target_labs = [[rgb_to_oklab(tuple(map(int, dst[y,x]))) for x in range(width)] for y in range(height)]
    pixel, color, light, hue = [], [], [], []
    weighted = []
    for y in range(height):
        for x in range(width):
            a, b = source_labs[y][x], target_labs[y][x]
            pixel.append(1-sum(abs(int(src[y,x,c])-int(dst[y,x,c])) for c in range(3))/765)
            similarity = max(0, 1-math.dist(a,b)/.45)
            color.append(similarity)
            light.append(1-abs(a[0]-b[0]))
            chroma = math.hypot(a[1],a[2])
            if chroma >= .025:
                if math.hypot(b[1],b[2]) < .025:
                    hue.append(0)
                else:
                    delta = math.atan2(a[2],a[1])-math.atan2(b[2],b[1])
                    hue.append(1-abs(math.atan2(math.sin(delta),math.cos(delta)))/math.pi)
            weighted.append((similarity, float(importance[y,x])))
    def edges(labs):
        rows = []
        for y in range(height):
            row = []
            for x in range(width):
                left, right = max(0,x-1), min(width-1,x+1)
                top, bottom = max(0,y-1), min(height-1,y+1)
                gx = (labs[y][right][0]-labs[y][left][0])/max(1,right-left)
                gy = (labs[bottom][x][0]-labs[top][x][0])/max(1,bottom-top)
                row.append(math.hypot(gx,gy))
            rows.append(row)
        return np.asarray(rows)
    se, de = edges(source_labs), edges(target_labs)
    threshold = max(.02, float(np.percentile(se,70)))
    selected = []
    all_similarity = []
    for a,b in zip(se.ravel(),de.ravel()):
        similarity = 1-min(1,abs(a-b)/max(.04,a+b))
        all_similarity.append(similarity)
        if max(a,b) >= threshold:selected.append(similarity)
    selected = selected or all_similarity
    chosen = [(value, .25+.75*weight) for value,weight in weighted if weight >= .62]
    chosen = chosen or [(value, .25+.75*weight) for value,weight in weighted]
    mean = lambda values: sum(values)/len(values)*100
    return {'source_pixel_accuracy_percent': mean(pixel),
        'perceptual_color_accuracy_percent': mean(color),
        'luminance_accuracy_percent': mean(light),
        'hue_accuracy_percent': mean(hue) if hue else 100,
        'edge_accuracy_percent': mean(selected),
        'important_feature_accuracy_percent': sum(v*w for v,w in chosen)/sum(w for _,w in chosen)*100}


class PreviewWorkingSetTests(unittest.TestCase):
    def test_normalization_closes_owned_rasters_on_success_and_composite_failure(self):
        for fails in (False, True):
            with self.subTest(fails=fails), ExitStack() as stack:
                source = stack.enter_context(closing(Image.new('RGBA', (3, 2), (20, 40, 60, 128))))
                rgba = source.copy()
                resized = rgba.resize((5, 4))
                base = Image.new('RGBA', (5, 4), 'white')
                # Keep real images alive after the operation, so garbage
                # collection cannot conceal a missing explicit close().
                for owned in (rgba, resized, base):
                    stack.callback(owned.close)
                stack.enter_context(patch.object(source, 'convert', return_value=rgba))
                stack.enter_context(patch.object(rgba, 'resize', return_value=resized))
                stack.enter_context(patch.object(accuracy.Image, 'new', return_value=base))
                if fails:
                    stack.enter_context(patch.object(base, 'alpha_composite', side_effect=MemoryError('composite fixture')))
                    with self.assertRaisesRegex(MemoryError, 'composite fixture'):
                        accuracy.normalize_source(source, (5, 4))
                else:
                    with closing(accuracy.normalize_source(source, (5, 4))) as normalized:
                        self.assertEqual(normalized.size, (5, 4))
                        self.assertEqual(normalized.mode, 'RGB')
                        normalized.getpixel((0, 0))
                for owned in (rgba, resized, base):
                    with self.assertRaises(ValueError):
                        owned.getpixel((0, 0))
                self.assertEqual(source.getpixel((0, 0)), (20, 40, 60, 128))

    def test_evaluation_closes_normalized_images_before_metrics_and_after_partial_failure(self):
        from UniversalGpuAcceleration import pixel_channel_error
        normalize = accuracy.normalize_source
        for fail_second in (False, True):
            created = []
            closed_before_metrics = []
            def normalized(*args, **kwargs):
                if fail_second and created:
                    raise MemoryError('second normalization fixture')
                result = normalize(*args, **kwargs)
                created.append(result)
                return result
            def channel_error(*args, **kwargs):
                for owned in created:
                    try:
                        owned.getpixel((0, 0))
                    except ValueError:
                        closed_before_metrics.append(True)
                    else:
                        closed_before_metrics.append(False)
                return pixel_channel_error(*args, **kwargs)
            # RGBA still requires real normalization. Already prepared RGB is
            # borrowed by the evaluator and has separate caller-ownership tests.
            with self.subTest(fail_second=fail_second), closing(Image.new('RGBA', (12, 9), 'red')) as source, \
                 patch.object(accuracy, 'normalize_source', side_effect=normalized), \
                 patch('UniversalGpuAcceleration.pixel_channel_error', side_effect=channel_error) as metric:
                if fail_second:
                    with self.assertRaisesRegex(MemoryError, 'second normalization fixture'):
                        accuracy.evaluate_preview(source, source, gpu_mode='CPU')
                    metric.assert_not_called()
                else:
                    result = accuracy.evaluate_preview(source, source, gpu_mode='CPU')
                    self.assertEqual(result['source_pixel_accuracy_percent'], 100.0)
                    metric.assert_called_once()
                    self.assertEqual(closed_before_metrics, [True, True])
                for owned in created:
                    with self.assertRaises(ValueError):
                        owned.getpixel((0, 0))
                self.assertEqual(source.getpixel((0, 0)), (255, 0, 0, 255))

    def test_resized_importance_owns_no_live_pillow_buffer(self):
        raw = np.array([[0.0, 1.0], [1.0, 0.0]], np.float32)
        with closing(Image.fromarray(raw)) as source, \
             closing(source.resize((7, 5), Image.Resampling.BILINEAR)) as resized:
            expected = np.asarray(resized).copy()
            with patch.object(accuracy.Image, 'fromarray', return_value=source), \
                 patch.object(source, 'resize', return_value=resized):
                importance, weights = accuracy._importance_weights(raw, (7, 5))
            for owned in (source, resized):
                with self.assertRaises(ValueError):
                    owned.getpixel((0, 0))
            np.testing.assert_array_equal(importance, expected)
            np.testing.assert_array_equal(weights, .25 + .75 * expected)
            np.testing.assert_array_equal(raw, [[0.0, 1.0], [1.0, 0.0]])

    def test_full_metric_pipeline_matches_independent_scalar_oracle(self):
        rng = np.random.default_rng(148054)
        for shape in ((9,13), (1,11), (12,1), (1,1)):
            source_pixels = rng.integers(0,256,(*shape,3),dtype=np.uint8)
            target_pixels = rng.integers(0,256,(*shape,3),dtype=np.uint8)
            importance = rng.random(shape, dtype=np.float32)
            with Image.fromarray(source_pixels) as source, Image.fromarray(target_pixels) as preview:
                expected = scalar_preview_metrics(source, preview, importance)
                result = accuracy.evaluate_preview(source, preview, importance, gpu_mode='CPU',
                    return_error_map=True, return_delta_e_heatmap=True)
                try:
                    for key, value in expected.items():
                        self.assertAlmostEqual(result[key], value, delta=.011, msg=f'{shape}: {key}')
                    self.assertEqual(result['_error_map_image'].size, source.size)
                    self.assertEqual(result['_delta_e_heatmap_image'].size, source.size)
                finally:
                    result['_error_map_image'].close()
                    result['_delta_e_heatmap_image'].close()

    def test_failed_second_heatmap_closes_first_completed_image(self):
        created = []
        original = accuracy._error_preview
        def first(*args):
            result = original(*args)
            created.append(result)
            return result
        with Image.new('RGB',(12,9),'red') as source, \
             patch.object(accuracy, '_error_preview', side_effect=first), \
             patch.object(accuracy, '_delta_e_preview', side_effect=MemoryError('fixture')):
            with self.assertRaises(MemoryError):
                accuracy.evaluate_preview(source, source, gpu_mode='CPU',
                    return_error_map=True, return_delta_e_heatmap=True)
            self.assertEqual(source.getpixel((0,0)), (255,0,0))
        self.assertEqual(len(created), 1)
        with self.assertRaises(ValueError):
            created[0].getpixel((0,0))


if __name__ == '__main__':
    unittest.main()
