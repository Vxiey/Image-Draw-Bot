from __future__ import annotations

from collections import defaultdict
from contextlib import closing
import random
import unittest

from PIL import Image, ImageDraw

from GarticPhoneFastRenderer import optimize_gartic_phone_groups
from test_v148_rendering_batch07_white import covered


def axis_runs(pixels, *, vertical=False, minimum=1):
    rows = defaultdict(set)
    for x, y in pixels:
        rows[x if vertical else y].add(y if vertical else x)
    result = []
    for fixed, coordinates in sorted(rows.items()):
        parts = []
        for coordinate in sorted(coordinates):
            if not parts or coordinate != parts[-1][-1] + 1:
                parts.append([coordinate])
            else:
                parts[-1].append(coordinate)
        for part in parts:
            if len(part) >= minimum:
                result.append((fixed, part[0], fixed, part[-1]) if vertical else
                              (part[0], fixed, part[-1], fixed))
    return result


class RetainedOrientationTests(unittest.TestCase):
    palette = ((0, 0, 0), (0, 80, 205), (255, 255, 255))

    def optimize(self, pixels, **options):
        return optimize_gartic_phone_groups([[(-2, -2, -2, -2)], axis_runs(pixels), []],
            self.palette, max_colors=3, **options)

    def test_horizontal_and_vertical_thin_colour_lines_do_not_choose_empty_candidate(self):
        for minimum in (2, 5):
            for vertical in (False, True):
                pixels = {(4, coordinate) if vertical else (coordinate, 4) for coordinate in range(10)}
                with self.subTest(minimum=minimum, vertical=vertical):
                    result, meta = self.optimize(pixels, min_run=minimum, gap_join=0)
                    self.assertEqual(covered(result[1]), pixels)
                    self.assertEqual(meta['orientations']['1'], 'vertical' if vertical else 'horizontal')

    def test_candidate_choice_matches_independent_retained_raster_oracle(self):
        randomizer = random.Random(7706)
        for minimum in (2, 3, 5):
            for case in range(20):
                pixels = {(x, y) for y in range(12) for x in range(15) if randomizer.random() < .6}
                horizontal = axis_runs(pixels, minimum=minimum)
                vertical = axis_runs(pixels, vertical=True, minimum=minimum)
                hp, vp = covered(horizontal), covered(vertical)
                expected = vertical if (-len(vp), len(vertical), len(vp)) < (-len(hp), len(horizontal), len(hp)) else horizontal
                result, meta = self.optimize(pixels, min_run=minimum, gap_join=0)
                with self.subTest(minimum=minimum, case=case):
                    self.assertEqual(covered(result[1]), covered(expected))
                    self.assertEqual(len(covered(result[1])), max(len(hp), len(vp)))
                    self.assertEqual(meta['horizontal_retained_pixels']['1'], len(hp))
                    self.assertEqual(meta['vertical_retained_pixels']['1'], len(vp))

    def test_bridged_gap_pixels_do_not_inflate_source_coverage(self):
        pixels = {(0, y) for y in range(5)} | {(10, 0), (20, 0)}
        result, meta = self.optimize(pixels, min_run=2, gap_join=9)
        self.assertEqual(meta['horizontal_retained_pixels']['1'], 3)
        self.assertEqual(meta['vertical_retained_pixels']['1'], 5)
        self.assertEqual(covered(result[1]), {(0, y) for y in range(5)})

    def test_vertical_storage_limit_and_true_tiny_fragment_policy_are_preserved(self):
        pixels = {(x, 2) for x in range(10)}
        result, meta = self.optimize(pixels, min_run=2, gap_join=0, vertical_pixel_limit=8)
        self.assertEqual(covered(result[1]), pixels)
        self.assertEqual(meta['vertical_retained_pixels']['1'], -1)
        result, _ = self.optimize({(1, 1)}, min_run=2, gap_join=0)
        self.assertFalse(result[1])

    def test_actual_gartic_policy_plan_and_preview_retain_both_orientations(self):
        from DrawBot import make_plan
        from Colors import allColors
        from ProfileEngine import resolve_profile_policy
        from ProfilePolish import apply_profile_polish
        from test_pixel_accurate_v1086 import opts
        from test_v148_rendering_batch06_canvas import close_plan
        from test_v148_planning_batch03_geometry import pixels_in_paths
        blue = next(i for i, color in enumerate(allColors) if color.RGB == (0, 80, 205))
        for vertical in (False, True):
            with self.subTest(vertical=vertical), closing(Image.new('RGBA', (64, 64), 'white')) as image:
                draw = ImageDraw.Draw(image)
                draw.rectangle((5, 5, 8, 8), fill='black')
                draw.line((32, 15, 32, 50) if vertical else (15, 32, 50, 32), fill=self.palette[1], width=1)
                requested = opts(render_preset='Manual', skip_white=True, time_budget_mode='Unlimited',
                    unlimited_time=True, draw_quality='High likeness', profile_engine='Auto',
                    profile_name='Gartic Phone', profile_key='gartic-phone', detail_zoom='Off',
                    use_region_fill_engine=False, gartic_phone_min_run=2)
                effective, _ = resolve_profile_policy('Gartic Phone', requested, mode='Auto')
                effective, _ = apply_profile_polish('Gartic Phone', effective)
                effective['drawing_mode'] = effective['mode']
                plan = make_plan(image, image.size, effective)
                try:
                    expected = {(32, coordinate) if vertical else (coordinate, 32) for coordinate in range(15, 51)}
                    self.assertEqual(covered(plan['groups'][blue]), expected)
                    self.assertEqual(pixels_in_paths(plan['execution_groups'][blue]), expected)
                    self.assertTrue(all(plan['preview'].getpixel(point) == self.palette[1] for point in expected))
                finally:
                    close_plan(plan, image)


if __name__ == '__main__':
    unittest.main()
