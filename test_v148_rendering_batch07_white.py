from __future__ import annotations

from contextlib import closing
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from GarticPhoneFastRenderer import optimize_gartic_phone_groups
from SkribblFastRenderer import optimize_skribbl_groups


def covered(group):
    pixels = set()
    for x0, y0, x1, y1 in group:
        if x0 == x1:
            pixels.update((x0, y) for y in range(min(y0, y1), max(y0, y1) + 1))
        elif y0 == y1:
            pixels.update((x, y0) for x in range(min(x0, x1), max(x0, x1) + 1))
        else:
            raise AssertionError('The source fixture only contains axis-aligned raster runs.')
    return pixels


class ExplicitWhiteTurboTests(unittest.TestCase):
    engines = (optimize_gartic_phone_groups, optimize_skribbl_groups)

    def test_white_dots_and_gaps_survive_both_fast_rasterizers(self):
        groups = [[(1, 2, 1, 2)], [(0, y, 8, y) for y in range(8, 13)],
                  [(0, 2, 0, 2), (2, 2, 2, 2)] + [(6, y, 6, y) for y in range(6)]]
        palette = [(0, 0, 0), (0, 80, 205), (255, 255, 255)]
        for engine in self.engines:
            with self.subTest(engine=engine.__name__):
                result, meta = engine(groups, palette, max_colors=3, gap_join=3, min_run=5)
                self.assertEqual(covered(result[2]), covered(groups[2]))
                self.assertNotIn((1, 2), covered(result[2]))
                self.assertEqual(covered(result[0]), {(1, 2)})
                self.assertEqual(meta['active_colors_before'], 3)
                self.assertEqual(meta['active_colors_after'], 3)
                self.assertEqual(meta['color_mapping']['2'], 2)

    def test_minimum_colour_ceiling_retains_black_and_white_anchors(self):
        groups = [[(0, 0, 0, 0)], [(0, 2, 19, 2)], [(0, 4, 19, 4)], [(5, 5, 5, 5)]]
        palette = [(0, 0, 0), (255, 0, 0), (0, 0, 255), (255, 255, 255)]
        for engine in self.engines:
            with self.subTest(engine=engine.__name__):
                result, meta = engine(groups, palette, max_colors=2, gap_join=0, min_run=1)
                self.assertIn((0, 0), covered(result[0]))
                self.assertIn((5, 5), covered(result[3]))
                self.assertLessEqual(meta['active_colors_after'], 2)
                self.assertEqual(set(meta['kept_color_indexes']), {0, 3})
                self.assertEqual(set().union(*(covered(group) for group in result)),
                                 set().union(*(covered(group) for group in groups)))
                self.assertTrue(set(meta['color_mapping'].values()) <= set(meta['kept_color_indexes']))

    def test_white_variants_reduce_to_white_and_white_only_counts_are_honest(self):
        for engine in self.engines:
            with self.subTest(engine=engine.__name__):
                groups = [[(0, 0, 0, 0)], [(1, 1, 1, 1)], [(3, 1, 3, 1)], [(0, 4, 9, 4)]]
                palette = [(0, 0, 0), (245, 245, 245), (255, 255, 255), (200, 30, 50)]
                result, meta = engine(groups, palette, max_colors=2, gap_join=0, min_run=1)
                self.assertTrue({(1, 1), (3, 1)} <= covered(result[2]))
                self.assertEqual(meta['color_mapping']['1'], 2)
                result, meta = engine([[], [(0, 0, 0, 0)]], palette[:2], gap_join=2, min_run=5)
                self.assertEqual(covered(result[1]), {(0, 0)})
                self.assertEqual(meta['active_colors_before'], 1)
                self.assertEqual(meta['active_colors_after'], 1)

    def test_actual_profile_policies_keep_explicit_white_and_respect_skip_white(self):
        import DrawBot
        from Colors import allColors
        from ProfileEngine import resolve_profile_policy
        from ProfilePolish import apply_profile_polish
        from test_pixel_accurate_v1086 import opts
        from test_v148_rendering_batch06_canvas import close_plan
        white = next(i for i, color in enumerate(allColors) if color.RGB == (255, 255, 255))
        for profile, key, function in (
                ('Gartic Phone', 'gartic-phone', 'optimize_gartic_phone_groups'),
                ('Skribbl.io Fast', 'skribbl-fast', 'optimize_skribbl_groups')):
            for skip_white in (False, True):
                with self.subTest(profile=profile, skip_white=skip_white), \
                        closing(Image.new('RGBA', (48, 40), 'white')) as image:
                    draw = ImageDraw.Draw(image)
                    draw.rectangle((5, 5, 17, 30), fill=(0, 80, 205, 255))
                    draw.rectangle((28, 10, 42, 32), fill='black')
                    requested = opts(render_preset='Manual', skip_white=skip_white, time_budget_mode='Unlimited',
                        unlimited_time=True, draw_quality='High likeness', profile_engine='Auto',
                        profile_name=profile, profile_key=key, detail_zoom='Off', use_region_fill_engine=False)
                    effective, _ = resolve_profile_policy(profile, requested, mode='Auto')
                    effective, _ = apply_profile_polish(profile, effective)
                    effective['drawing_mode'] = effective['mode']
                    self.assertEqual(effective['skip_white'], skip_white)
                    with patch.object(DrawBot, function, wraps=getattr(DrawBot, function)) as turbo:
                        plan = DrawBot.make_plan(image, (96, 80), effective)
                    try:
                        turbo.assert_called_once()
                        supplied_white = covered(turbo.call_args.args[0][white])
                        # skip_white applies to source pixels before matching.
                        # Nonwhite antialiasing can legitimately map to a white
                        # swatch even when the white source background is skipped.
                        self.assertEqual((0, 0) in supplied_white, not skip_white)
                        self.assertTrue(supplied_white <= covered(plan['groups'][white]))
                        self.assertTrue(plan['execution_groups'][white])
                        self.assertEqual(bool(plan['options']['advanced_color_meta']['white_skipped']), skip_white)
                    finally:
                        close_plan(plan, image)


if __name__ == '__main__':
    unittest.main()
