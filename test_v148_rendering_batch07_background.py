from __future__ import annotations

from contextlib import closing
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import FillOptimizer as fill


def connected_border_pixels(image, tolerance):
    """Set/frontier oracle independent of the production byte mask and queue."""
    width, height = image.size
    eligible = {(x, y) for y in range(height) for x in range(width)
                if sum((value - 240) ** 2 for value in image.getpixel((x, y))[:3]) <= tolerance ** 2}
    reached = {point for point in eligible if point[0] in (0, width - 1) or point[1] in (0, height - 1)}
    frontier = set(reached)
    while frontier:
        x, y = frontier.pop()
        for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if point in eligible and point not in reached:
                reached.add(point)
                frontier.add(point)
    return reached


class BackgroundStorageTests(unittest.TestCase):
    def test_full_raster_matches_independent_components_including_enclosed_islands(self):
        rng = np.random.default_rng(7705)
        for mode, tolerance in (('Conservative', 26), ('Balanced', 38), ('Strong', 54)):
            rgb = rng.integers(225, 256, (29, 31, 3), dtype=np.uint8)
            rgb[0] = rgb[-1] = 240
            rgb[:, 0] = rgb[:, -1] = 240
            with self.subTest(mode=mode), closing(Image.fromarray(rgb)) as image:
                ImageDraw.Draw(image).rectangle((8, 7, 22, 21), outline='black', width=1)
                image.putpixel((1, 1), (255, 255, 255))
                original = image.tobytes()
                expected_pixels = connected_border_pixels(image, tolerance)
                expected_changed = sum(image.getpixel(point) != (255, 255, 255) for point in expected_pixels)
                with closing(image.copy()) as expected:
                    for point in expected_pixels:
                        expected.putpixel(point, (255, 255, 255))
                    result, meta = fill.simplify_background(image, mode)
                    with closing(result):
                        self.assertEqual(result.tobytes(), expected.tobytes())
                        self.assertTrue(meta.enabled)
                        self.assertEqual(meta.rgb, (255, 255, 255))
                        self.assertEqual(meta.changed_pixels, expected_changed)
                        self.assertEqual(meta.coverage, len(expected_pixels) / (31 * 29))
                        self.assertEqual(meta.border_confidence, 1)
                        self.assertEqual(result.getpixel((15, 15)), image.getpixel((15, 15)))
                self.assertEqual(image.tobytes(), original)

    def test_coverage_thresholds_keep_rejected_pixels_and_accept_exact_boundary(self):
        for mode, target in (('Conservative', 400), ('Balanced', 300), ('Strong', 200)):
            for count in (target - 1, target):
                with self.subTest(mode=mode, count=count), closing(Image.new('RGB', (50, 50), 'black')) as image:
                    pixels = {(x, y) for y in range(50) for x in range(50)
                              if x in (0, 49) or y in (0, 49)}
                    for y in range(1, 49):
                        for x in range(1, 49):
                            if len(pixels) < count:
                                pixels.add((x, y))
                    self.assertEqual(len(pixels), count)
                    for point in pixels:
                        image.putpixel(point, (240, 240, 240))
                    original = image.tobytes()
                    result, meta = fill.simplify_background(image, mode)
                    with closing(result):
                        self.assertEqual(meta.enabled, count == target)
                        self.assertEqual(meta.coverage, count / 2500)
                        self.assertEqual(meta.changed_pixels, count if count == target else 0)
                        if count < target:
                            self.assertEqual(result.tobytes(), original)
                        else:
                            self.assertEqual(sum(result.getpixel((x, y)) == (255, 255, 255)
                                                 for y in range(50) for x in range(50)), count)
                    self.assertEqual(image.tobytes(), original)

    def test_owned_conversion_is_published_without_second_full_image_copy(self):
        converted = []
        convert = Image.Image.convert
        def capture(image, *args, **kwargs):
            result = convert(image, *args, **kwargs)
            converted.append(result)
            return result
        with closing(Image.new('RGB', (16, 16), (240, 240, 240))) as image, \
                patch.object(Image.Image, 'convert', capture):
            result, meta = fill.simplify_background(image, 'Balanced')
            with closing(result):
                self.assertTrue(meta.enabled)
                self.assertIs(result, converted[0])
                self.assertIsNot(result, image)
                self.assertEqual(image.getpixel((0, 0)), (240, 240, 240))

    def test_stop_before_conversion_and_during_publication_preserves_source(self):
        with closing(Image.new('RGB', (32, 32), (240, 240, 240))) as image:
            with patch.object(Image.Image, 'convert') as convert:
                with self.assertRaises(InterruptedError):
                    fill.simplify_background(image, cancelled=lambda: True)
                convert.assert_not_called()
            converted = []
            convert = Image.Image.convert
            def capture(source, *args, **kwargs):
                result = convert(source, *args, **kwargs)
                converted.append(result)
                return result
            with patch.object(Image.Image, 'convert', capture):
                with self.assertRaises(InterruptedError):
                    fill.simplify_background(image, cancelled=lambda:
                        bool(converted) and converted[0].getpixel((0, 0)) == (255, 255, 255))
            self.assertEqual(len(converted), 1)
            with self.assertRaises(ValueError):
                converted[0].getpixel((0, 0))
            self.assertEqual(image.getpixel((0, 0)), (240, 240, 240))

    def test_actual_make_plan_uses_the_same_simplified_rgba_source(self):
        import DrawBot
        from test_pixel_accurate_v1086 import opts
        from test_v148_rendering_batch06_canvas import close_plan
        saved = {}
        def observe(image, *args, **kwargs):
            result, meta = fill.simplify_background(image, *args, **kwargs)
            saved.update(rgb=result.tobytes(), metadata=meta.as_dict())
            return result, meta
        options = opts(render_preset='Manual', draw_quality='High likeness', planning_resolution='Standard',
            background_simplification='Balanced', adaptive_detail='Off', detail_zoom='Off',
            background_fill='Off', use_region_fill_engine=False, color_rendering='RGB nearest',
            color_fidelity='Fast', time_budget_mode='Unlimited', unlimited_time=True)
        with closing(Image.new('RGBA', (48, 40), (240, 240, 240, 255))) as image:
            draw = ImageDraw.Draw(image)
            draw.rectangle((14, 10, 33, 29), fill=(80, 20, 140, 128))
            draw.rectangle((20, 16, 27, 23), fill=(220, 10, 50, 0))
            original = image.tobytes()
            with patch.object(DrawBot, 'simplify_background', side_effect=observe) as operation:
                plan = DrawBot.make_plan(image, image.size, options)
            try:
                operation.assert_called_once()
                self.assertTrue(saved['metadata']['enabled'])
                self.assertEqual(plan['options']['background_simplification_meta'], saved['metadata'])
                with closing(plan['image'].convert('RGB')) as planned_rgb:
                    self.assertEqual(planned_rgb.tobytes(), saved['rgb'])
                self.assertEqual(image.tobytes(), original)
                self.assertGreater(plan['count'], 0)
            finally:
                close_plan(plan, image)


if __name__ == '__main__':
    unittest.main()
