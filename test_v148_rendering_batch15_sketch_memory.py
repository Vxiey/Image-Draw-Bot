"""Sketch gradient lifetimes preserve masks and real Paint/Sketch Fill plans."""
from contextlib import ExitStack, closing, contextmanager
import hashlib
import sys
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import DrawBot
import Sketch2Planner as sketch
from test_pixel_accurate_v1086 import opts
from test_v148_planning_batch04_resources import connected_components
from test_v148_rendering_batch06_canvas import close_plan


PROFILES = {
    'Simple': (1.8, 82.0, 34.0, 10, 1.75),
    'Balanced': (1.25, 77.0, 27.0, 6, 1.60),
    'Detailed': (.85, 72.0, 20.0, 3, 1.45),
}
VOLATILE_PATHS = {
    ('performance_profile',), ('options', '_performance_profile'),
    ('preview_diagnostics', 'performance', 'planning_seconds'),
    ('preview_diagnostics', 'performance', 'slowest_planning_phase'),
    ('options', 'preview_diagnostics_meta', 'performance', 'planning_seconds'),
    ('options', 'preview_diagnostics_meta', 'performance', 'slowest_planning_phase'),
    ('options', 'pixel_stroke_meta', 'planning_stage_seconds'),
}


def reference_structure(image, cancelled=lambda: False, detail='Detailed'):
    """Original float32 expressions, then an independent union/find filter.

    NMS is unchanged by this optimization. The baseline benchmark additionally
    loads the complete historical module, including its own NMS and flood.
    """
    blur, percentile, floor, minimum, factor = PROFILES[detail]
    with closing(image.convert('RGBA')) as rgba, \
            closing(Image.new('RGBA', image.size, 'white')) as composite:
        composite.alpha_composite(rgba)
        with closing(composite.convert('RGB')) as flat, \
                closing(flat.filter(ImageFilter.GaussianBlur(blur))) as smooth:
            arr = np.asarray(smooth, dtype=np.float32)
            lum = arr[:, :, 0]*.2126 + arr[:, :, 1]*.7152 + arr[:, :, 2]*.0722
            lx = np.zeros_like(lum); ly = np.zeros_like(lum)
            lx[:, 1:-1] = lum[:, 2:]-lum[:, :-2]
            ly[1:-1, :] = lum[2:, :]-lum[:-2, :]
            lum_mag = np.hypot(lx, ly)
            cx = np.zeros_like(arr); cy = np.zeros_like(arr)
            cx[:, 1:-1, :] = arr[:, 2:, :]-arr[:, :-2, :]
            cy[1:-1, :, :] = arr[2:, :, :]-arr[:-2, :, :]
            color_mag = np.sqrt(np.max(cx*cx+cy*cy, axis=2))
            combined = lum_mag*.78 + color_mag*.46
            gx = lx + (cx[:, :, 0]-cx[:, :, 2])*.10
            gy = ly + (cy[:, :, 0]-cy[:, :, 2])*.10
            thin = sketch._nms(combined, gx, gy)
            active = thin[thin > 0]
            threshold = max(floor, float(np.percentile(active, percentile)) if active.size else 255.0)
            mask = thin >= threshold
            raw = np.asarray(flat, dtype=np.float32)
            raw_lum = raw[:, :, 0]*.2126 + raw[:, :, 1]*.7152 + raw[:, :, 2]*.0722
            rgx = np.zeros_like(raw_lum); rgy = np.zeros_like(raw_lum)
            rgx[:, 1:-1] = raw_lum[:, 2:]-raw_lum[:, :-2]
            rgy[1:-1, :] = raw_lum[2:, :]-raw_lum[:-2, :]
            rcx = np.zeros_like(raw); rcy = np.zeros_like(raw)
            rcx[:, 1:-1, :] = raw[:, 2:, :]-raw[:, :-2, :]
            rcy[1:-1, :, :] = raw[2:, :, :]-raw[:-2, :, :]
            raw_strength = np.hypot(rgx, rgy)*.72 + np.sqrt(np.max(rcx*rcx+rcy*rcy, axis=2))*.40
            micro = raw_strength >= max(88.0, threshold*1.18)
            micro[[0, -1], :] = False; micro[:, [0, -1]] = False
            mask |= micro
            strength = np.maximum(thin, raw_strength)
    removed = protected = 0
    for component in connected_components(mask):
        if len(component) >= minimum:
            continue
        peak = max(float(strength[y, x]) for y, x in component)
        if len(component) >= 2 and peak >= threshold*factor:
            protected += 1
        else:
            removed += 1
            for y, x in component:
                mask[y, x] = False
    lum_only = lum_mag >= threshold
    color_only = (color_mag*.46 >= threshold*.55) & (~lum_only) & mask
    return mask, {
        'engine': 'Sketch 2.0', 'detail': detail, 'threshold': round(threshold, 3),
        'ink_pixels': int(mask.sum()), 'luminance_edge_pixels': int((mask & lum_only).sum()),
        'color_boundary_pixels': int(color_only.sum()), 'removed_noise_components': removed,
        'protected_small_components': protected, 'ai_ml_ocr': False,
    }


def graphic_source(size):
    image = Image.new('RGBA', size, 'white')
    draw = ImageDraw.Draw(image)
    def box(values):
        return tuple(value*size[index % 2]//(512 if index % 2 == 0 else 384)
                     for index, value in enumerate(values))
    draw.rectangle(box((32, 40, 240, 320)), fill=(235, 40, 40, 230),
                   outline='black', width=max(1, size[0]*3//512))
    draw.ellipse(box((270, 70, 470, 310)), fill=(30, 135, 225, 190),
                 outline='black', width=max(1, size[0]*3//512))
    draw.rectangle(box((137, 140, 141, 144)), fill='black')
    return image


def planner_options(style, detail='Detailed', quality='Pixel Accurate'):
    return opts(profile_name='Microsoft Paint', profile_key='microsoft-paint',
        render_preset='Manual', render_style=style, outline=style == 'Standard / pixel',
        sketch_detail=detail, draw_quality=quality, skip_white=True, detail_zoom='Off',
        time_budget_mode='Unlimited', unlimited_time=True, cpu_workers='1',
        cpu_workers_resolved=1, ram_budget_mb=2048, available_ram_mb=8192,
        logical_cpus=4, _execution_cost_calibration_override={})


def comparable_plan(value, path=()):
    if isinstance(value, dict):
        return {key: comparable_plan(item, (*path, key)) for key, item in value.items()
                if (*path, key) not in VOLATILE_PATHS}
    if isinstance(value, (list, tuple)):
        return [comparable_plan(item, path) for item in value]
    if isinstance(value, Image.Image):
        return value.mode, value.size, hashlib.sha256(value.tobytes()).hexdigest()
    if isinstance(value, np.ndarray):
        return str(value.dtype), value.shape, hashlib.sha256(value.tobytes()).hexdigest()
    if isinstance(value, np.generic):
        return value.item()
    return value


def sequence_raster(plan, phase=None):
    """Pillow paints public paths independently of the preview renderer."""
    raster = Image.new('RGB', plan['image'].size, 'white')
    drawing = ImageDraw.Draw(raster)
    entries = plan['execution_sequence'] or (
        {'color_index': index, 'path': path}
        for index in (plan['options'].get('color_order') or range(len(plan['colors'])))
        for path in plan['execution_groups'][index])
    for entry in entries:
        if phase is not None and entry.get('phase') != phase:
            continue
        path = entry['path']; color = tuple(plan['colors'][entry['color_index']])
        if len(path) == 1:
            drawing.point(path[0], fill=color)
        elif path:
            drawing.line(path, fill=color, width=1)
    return raster


@contextmanager
def tracked_images():
    created = []
    def record(function):
        def wrapped(*args, **kwargs):
            image = function(*args, **kwargs)
            # Pillow's frombuffer implementation also creates an empty wrapper
            # before mapping its actual image. It owns no pixel allocation.
            if isinstance(image, Image.Image) and all(image.size):
                created.append(image)
            return image
        return wrapped
    with ExitStack() as stack:
        for owner, name in ((Image.Image, 'convert'), (Image.Image, 'filter'),
                            (Image, 'new'), (Image, 'fromarray')):
            stack.enter_context(patch.object(owner, name, new=record(getattr(owner, name))))
        yield created


class SketchScratchLifetimeTests(unittest.TestCase):
    def assert_closed(self, images, retained=()):
        retained_ids = {id(image) for image in retained}
        for image in images:
            if id(image) not in retained_ids:
                with self.assertRaises(ValueError):
                    image.getpixel((0, 0))

    def test_masks_and_all_metadata_match_reference_across_modes_and_thin_axes(self):
        rng = np.random.default_rng(1481501)
        for size in ((1, 1), (1, 13), (17, 1), (2, 9), (11, 2), (3, 3), (23, 19), (48, 37)):
            rgba = rng.integers(0, 256, (size[1], size[0], 4), dtype=np.uint8)
            rgba.flags.writeable = False
            with closing(Image.fromarray(rgba)) as source:
                for mode in ('RGBA', 'RGB', 'L', 'LA', 'P'):
                    with closing(source.convert(mode)) as converted:
                        if mode == 'P':
                            converted.info['transparency'] = bytes(range(256))
                        before = converted.tobytes(), dict(converted.info)
                        for detail in PROFILES:
                            with self.subTest(size=size, mode=mode, detail=detail):
                                expected, meta = reference_structure(converted, detail=detail)
                                actual, actual_meta = sketch.structure_map(converted, detail=detail)
                                np.testing.assert_array_equal(actual, expected)
                                self.assertEqual(actual.dtype, np.bool_)
                                self.assertEqual(actual_meta, meta)
                                self.assertEqual((converted.tobytes(), converted.info), before)
                                self.assertFalse(np.shares_memory(actual, rgba))

    def test_component_filter_retains_only_required_planes_and_no_rgb_scratch(self):
        references = []; observed = []
        actual_filter = sketch._filter_components
        def record(function):
            def wrapped(*args, **kwargs):
                value = function(*args, **kwargs)
                if isinstance(value, np.ndarray) and value.ndim == 3:
                    references.append(weakref.ref(value))
                return value
            return wrapped
        def inspect_filter(*args, **kwargs):
            fields = sys._getframe(1).f_locals
            arrays = {id(value): value.nbytes for value in fields.values() if isinstance(value, np.ndarray)}
            observed.append(sum(arrays.values()))
            self.assertTrue(references)
            self.assertTrue(all(reference() is None for reference in references))
            # One float32 strength plane plus the mask and two metadata predicates.
            self.assertLessEqual(observed[-1], 7*args[0].size)
            return actual_filter(*args, **kwargs)
        with closing(graphic_source((96, 72))) as source, \
                patch.object(sketch.np, 'asarray', new=record(np.asarray)), \
                patch.object(sketch.np, 'zeros_like', new=record(np.zeros_like)), \
                patch.object(sketch, '_filter_components', new=inspect_filter):
            sketch.structure_map(source)
        self.assertEqual(len(observed), 1)

    def test_success_closes_private_images_and_returns_an_independent_live_contour(self):
        with closing(graphic_source((64, 48))) as source:
            before = source.tobytes()
            with tracked_images() as created:
                contour, meta = sketch.contour_image_v2(source)
            try:
                self.assert_closed(created, (contour,))
                self.assertEqual(contour.mode, 'RGBA')
                self.assertEqual(contour.size, source.size)
                self.assertGreater(meta['ink_pixels'], 0)
                self.assertEqual(set(map(tuple, np.asarray(contour).reshape(-1, 4))),
                                 {(0, 0, 0, 255), (255, 255, 255, 255)})
                contour.putpixel((0, 0), (12, 34, 56, 255))
                self.assertEqual(source.tobytes(), before)
            finally:
                contour.close()

    def test_stop_before_work_and_between_numeric_passes_closes_owned_images(self):
        with closing(graphic_source((64, 48))) as source:
            before = source.tobytes()
            with patch.object(sketch, '_flatten', side_effect=AssertionError('No allocation')):
                with self.assertRaises(InterruptedError):
                    sketch.structure_map(source, lambda: True)
                with closing(Image.new('RGB', (1501, 1))) as oversized:
                    with self.assertRaisesRegex(ValueError, 'too large'):
                        sketch.structure_map(oversized)
            for phase in ('_smoothed_edges', '_micro_strength'):
                cancelled = [False]; errors = []
                actual = getattr(sketch, phase)
                def stop_after(*args, **kwargs):
                    result = actual(*args, **kwargs)
                    cancelled[0] = True
                    return result
                with self.subTest(phase=phase), tracked_images() as created, \
                        patch.object(sketch, phase, new=stop_after), \
                        patch.object(sketch, '_filter_components', side_effect=AssertionError('Stopped before flood')):
                    try:
                        sketch.structure_map(source, lambda: cancelled[0])
                    except InterruptedError as error:
                        errors.append(error)  # Keep the traceback while inspecting ownership.
                    self.assertEqual(len(errors), 1)
                    self.assert_closed(created)
                self.assertEqual(source.tobytes(), before)

    def test_numeric_and_composite_failures_close_images_with_retained_tracebacks(self):
        with closing(graphic_source((64, 48))) as source:
            before = source.tobytes()
            for owner, name in ((Image.Image, 'alpha_composite'), (sketch, '_nms'),
                                (sketch, '_filter_components')):
                error = RuntimeError('injected analysis failure'); caught = []
                with self.subTest(stage=name), tracked_images() as created, \
                        patch.object(owner, name, side_effect=error):
                    try:
                        sketch.structure_map(source)
                    except RuntimeError as failure:
                        caught.append(failure)
                    self.assertEqual(caught, [error])
                    self.assert_closed(created)
                self.assertEqual(source.tobytes(), before)

    def test_actual_paint_outline_and_sketch_fill_keep_complete_plans_and_ink(self):
        for style in ('Standard / pixel', 'Sketch + Auto Fill'):
            for detail in ('Simple', 'Detailed'):
                with self.subTest(style=style, detail=detail), ExitStack() as stack:
                    source = stack.enter_context(closing(graphic_source((64, 48))))
                    original = source.tobytes()
                    stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
                    stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))
                    options = planner_options(style, detail)
                    with patch.object(sketch, 'structure_map', new=reference_structure):
                        expected = DrawBot.make_plan(source, source.size, dict(options))
                    stack.callback(close_plan, expected, source)
                    with patch.object(sketch, 'structure_map', wraps=sketch.structure_map) as reached:
                        actual = DrawBot.make_plan(source, source.size, dict(options))
                    stack.callback(close_plan, actual, source)
                    self.assertEqual(reached.call_count, 1)
                    self.assertEqual(comparable_plan(actual), comparable_plan(expected))
                    self.assertGreater(actual['count'], 0)
                    self.assertEqual(actual['options']['sketch2_meta']['detail'], detail)
                    with closing(sequence_raster(actual)) as raster:
                        np.testing.assert_array_equal(np.asarray(raster), np.asarray(actual['preview']))
                    if style == 'Standard / pixel':
                        with closing(sequence_raster(actual)) as raster:
                            np.testing.assert_array_equal(np.asarray(raster)[:, :, 0] == 0,
                                                          np.asarray(actual['image'])[:, :, 0] == 0)
                    else:
                        phases = [entry['phase'] for entry in actual['execution_sequence']]
                        self.assertEqual(set(phases), {'sketch', 'color_fill', 'reoutline'})
                        with closing(sequence_raster(actual, 'sketch')) as raster:
                            np.testing.assert_array_equal(np.asarray(raster), np.asarray(actual['ui_previews']['sketch2']))
                    self.assertEqual(source.tobytes(), original)


if __name__ == '__main__':
    unittest.main()
