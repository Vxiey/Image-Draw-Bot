"""Auxiliary preview work owns its failures and skips unused color rasters."""
from contextlib import closing
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import PreviewLayers
from DrawBot import make_plan
from test_pixel_accuracy_engine_v1088 import options
from test_v148_rendering_batch06_canvas import close_plan


def captured_bitmaps(error):
    images = {}
    trace = error.__traceback__
    while trace is not None:
        if Path(trace.tb_frame.f_code.co_filename).name == 'PreviewLayers.py':
            for value in trace.tb_frame.f_locals.values():
                if isinstance(value, Image.Image):
                    images[id(value)] = value
        trace = trace.tb_next
    return tuple(images.values())


def captured_draw_handles(error):
    handles = {}
    trace = error.__traceback__
    while trace is not None:
        for value in trace.tb_frame.f_locals.values():
            if isinstance(value, ImageDraw.ImageDraw):
                handles[id(value)] = value
        trace = trace.tb_next
    return tuple(handles.values())


class AuxiliaryLayerOwnershipTests(unittest.TestCase):
    def assert_closed(self, image):
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def assert_draw_handles_released(self, error):
        handles = captured_draw_handles(error)
        self.assertTrue(handles)
        for handle in handles:
            self.assertIsNone(handle.im)
            self.assertIsNone(handle.draw)
            self.assertIsNone(handle._image)

    def test_partial_stroke_and_fill_failure_release_traceback_owned_pixels(self):
        for fail_in_fill in (False, True):
            with self.subTest(fill=fail_in_fill), closing(Image.new('RGBA', (8, 6), (20, 40, 60, 128))) as source:
                error = None
                def fail_point(*_args):
                    raise RuntimeError('mapping failed')
                try:
                    PreviewLayers.build_auxiliary_previews(source, (8, 6),
                        [[]] if fail_in_fill else [[(1, 1, 4, 1)]], [(0, 0, 0)], fail_point, 1,
                        {'fill_regions': [{'bbox': (1, 1, 4, 3), 'color_index': 0}]} if fail_in_fill else {})
                except RuntimeError as caught:
                    error = caught
                self.assertIsNotNone(error)
                retained = [image for image in captured_bitmaps(error) if image is not source]
                self.assertGreaterEqual(len(retained), 4 if fail_in_fill else 1)
                for image in retained:
                    self.assert_closed(image)
                self.assert_draw_handles_released(error)
                self.assertEqual(source.getpixel((0, 0)), (20, 40, 60, 128))

    def test_late_stop_closes_completed_layers_without_closing_borrowed_source(self):
        with closing(Image.new('RGBA', (8, 6), (10, 20, 30, 128))) as source:
            checks = 0
            def cancelled():
                nonlocal checks
                checks += 1
                return checks == 3  # Entry, post-strokes, then complete layers.
            error = None
            try:
                PreviewLayers.build_auxiliary_previews(source, (16, 12), [], [],
                    lambda x, y: (x, y), 1, {}, cancelled)
            except InterruptedError as caught:
                error = caught
            self.assertIsNotNone(error)
            retained = [image for image in captured_bitmaps(error) if image is not source]
            self.assertGreaterEqual(len(retained), 4)
            for image in retained:
                self.assert_closed(image)
            self.assert_draw_handles_released(error)
            self.assertEqual(source.getpixel((0, 0)), (10, 20, 30, 128))

    def test_native_pillow_drawing_failure_cannot_keep_the_image_core_in_its_traceback(self):
        with closing(Image.new('RGB', (8, 6), 'white')) as source:
            error = None
            try:
                PreviewLayers.build_auxiliary_previews(source, (8, 6), [[(1, 1, 4, 1)]],
                    [(0, 0, 0)], lambda x, y: ('bad coordinate', y), 1, {})
            except (TypeError, ValueError) as caught:
                error = caught
            self.assertIsNotNone(error)
            self.assert_draw_handles_released(error)
            for image in captured_bitmaps(error):
                if image is not source: self.assert_closed(image)
            self.assertEqual(source.getpixel((0, 0)), (255, 255, 255))

    def test_omitting_color_map_keeps_exact_stroke_fill_pixels_and_avoids_nearest_resize(self):
        for size in ((8, 6), (16, 12)):
            with self.subTest(size=size), closing(Image.new('RGBA', (8, 6), (20, 40, 60, 128))) as source:
                source.putpixel((2, 2), (200, 10, 20, 255))
                inputs = (source, size, [[(1, 1, 4, 1)]], [(0, 0, 0)],
                          lambda x, y: (x * size[0] / 8, y * size[1] / 6), 1,
                          {'fill_regions': [{'bbox': (1, 1, 4, 3), 'color_index': 0}]})
                ordinary = PreviewLayers.build_auxiliary_previews(*inputs)
                calls = []
                resize = Image.Image.resize
                def measured(image, target, resample=None, *args, **kwargs):
                    calls.append(resample)
                    return resize(image, target, resample, *args, **kwargs)
                try:
                    with patch.object(Image.Image, 'resize', measured):
                        reduced = PreviewLayers.build_auxiliary_previews(*inputs, include_color_map=False)
                    try:
                        self.assertEqual(set(ordinary), {'stroke', 'fill', 'color'})
                        self.assertEqual(set(reduced), {'stroke', 'fill'})
                        self.assertNotIn(Image.Resampling.NEAREST, calls)
                        for name in reduced:
                            self.assertEqual(reduced[name].mode, ordinary[name].mode)
                            self.assertEqual(reduced[name].size, ordinary[name].size)
                            self.assertEqual(reduced[name].tobytes(), ordinary[name].tobytes())
                        self.assertEqual(source.getpixel((2, 2)), (200, 10, 20, 255))
                    finally:
                        for image in reduced.values(): image.close()
                finally:
                    for image in ordinary.values(): image.close()

    def test_public_plan_uses_its_executed_color_map_without_constructing_a_discarded_one(self):
        with closing(Image.new('RGB', (24, 16), (0, 80, 205))) as source:
            produced = []
            build = PreviewLayers.build_auxiliary_previews
            def record(*args, **kwargs):
                layers = build(*args, **kwargs)
                produced.append((kwargs, set(layers)))
                return layers
            with patch.object(PreviewLayers, 'build_auxiliary_previews', record):
                plan = make_plan(source, (24, 16), options(render_preset='Manual',
                    auto_engine_resolved=True, time_budget_mode='Unlimited', unlimited_time=True,
                    brush_px=1, detail_zoom='Off', _execution_cost_calibration_override={}))
            try:
                self.assertEqual(len(produced), 1)
                self.assertIs(produced[0][0].get('include_color_map'), False)
                self.assertEqual(produced[0][1], {'stroke', 'fill'})
                self.assertIs(plan['ui_previews']['color'], plan['preview'])
                self.assertEqual(plan['ui_previews']['color'].size, plan['preview'].size)
            finally:
                close_plan(plan, source)


if __name__ == '__main__':
    unittest.main()
