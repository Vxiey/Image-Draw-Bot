"""CG04 caller completion: absent source pixels stay absent after RGB planning."""
from contextlib import closing
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import DrawBot
from SafeFillMask import filter_fill_regions_by_source_alpha
from test_pixel_accurate_v1086 import opts
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch07_white import covered


def standard_options(**changes):
    settings = opts(render_preset='Manual', draw_quality='High likeness',
        planning_resolution='Standard', background_fill='Off', use_region_fill_engine=False,
        background_simplification='Off', adaptive_detail='Off', detail_zoom='Off',
        color_rendering='RGB nearest', color_fidelity='Fast',
        time_budget_mode='Unlimited', unlimited_time=True)
    settings.update(changes)
    return settings


def group_pixels(groups):
    return set().union(*(covered(group) for group in groups))


class TransparentSourcePlanningTests(unittest.TestCase):
    def assert_execution_avoids_absent_pixels(self, plan, source):
        self.assertEqual(plan['image'].size, source.size)
        with closing(Image.new('1', source.size)) as raster, closing(source.getchannel('A')) as alpha:
            draw = ImageDraw.Draw(raster)
            for group in plan['execution_groups']:
                for path in group:
                    if len(path) == 1:
                        draw.point(path[0], fill=1)
                    elif path:
                        draw.line(path, fill=1, width=1)
            self.assertFalse(np.any(np.asarray(raster) & (np.asarray(alpha) == 0)))

    def test_standard_and_dynamic_colour_plans_exclude_hidden_source_rgb(self):
        for workflow in ('Calibrated palette', 'Exact custom + palette fallback'):
            for hidden in ((0, 0, 0), (240, 15, 130)):
                with self.subTest(workflow=workflow, hidden=hidden), \
                        closing(Image.new('RGBA', (24, 24), (*hidden, 0))) as image:
                    ImageDraw.Draw(image).rectangle((8, 8, 15, 15), fill=(0, 80, 205, 255))
                    original = image.tobytes()
                    plan = DrawBot.make_plan(image, image.size, standard_options(
                        skip_white=False, custom_color_workflow=workflow,
                        exact_color_available=True, exact_color_limit='8'))
                    try:
                        self.assertEqual(group_pixels(plan['groups']),
                                         {(x, y) for x in range(8, 16) for y in range(8, 16)})
                        self.assertTrue(plan['options']['source_transparency_meta']['zero_alpha_excluded'])
                        self.assertEqual(plan['image'].getpixel((0, 0))[3], 0)
                        self.assertEqual(image.tobytes(), original)
                        self.assert_execution_avoids_absent_pixels(plan, image)
                    finally:
                        close_plan(plan, image)

    def test_entirely_transparent_source_has_no_geometry_even_when_white_is_requested(self):
        for hidden in ((0, 0, 0), (200, 45, 170)):
            with self.subTest(hidden=hidden), closing(Image.new('RGBA', (24, 24), (*hidden, 0))) as image:
                plan = DrawBot.make_plan(image, image.size, standard_options(skip_white=False))
                try:
                    self.assertFalse(group_pixels(plan['groups']))
                    self.assertEqual(plan['count'], 0)
                    self.assertFalse(plan['options'].get('fill_regions'))
                finally:
                    close_plan(plan, image)

    def test_partial_alpha_is_composited_once_and_only_zero_alpha_is_reapplied(self):
        alphas = (0, 1, 64, 128, 254, 255)
        color = (24, 72, 160)
        with closing(Image.new('RGBA', (24, 24))) as image:
            for x in range(24):
                for y in range(24):
                    image.putpixel((x, y), (*color, alphas[x // 4]))
            plan = DrawBot.make_plan(image, image.size, standard_options(skip_white=False))
            try:
                for x in range(24):
                    alpha = alphas[x // 4]
                    # Independent integer source-over-white oracle.
                    expected = tuple((channel * alpha + 255 * (255 - alpha) + 127) // 255
                                     for channel in color)
                    self.assertEqual(plan['image'].getpixel((x, 12)), (*expected, 0 if alpha == 0 else 255))
                self.assertTrue(all(x >= 4 for x, _ in group_pixels(plan['groups'])))
            finally:
                close_plan(plan, image)

    def test_background_fill_is_disabled_for_a_transparent_hole(self):
        for alpha in (0, 255):
            with self.subTest(alpha=alpha), closing(Image.new('RGBA', (64, 64), (0, 80, 205, 255))) as image:
                image.putpixel((32, 32), (0, 80, 205, alpha))
                plan = DrawBot.make_plan(image, image.size, standard_options(
                    background_fill='Balanced', fill_tool_available=True,
                    fill_tool_actions=[('fill', (10, 10))], fill_restore_actions=[('brush', (20, 10))]))
                try:
                    self.assertEqual(bool(plan['options'].get('background_fill_plan', {}).get('enabled')), alpha == 255)
                    if alpha == 0:
                        self.assertNotIn((32, 32), group_pixels(plan['groups']))
                        self.assertGreater(plan['count'], 0)
                        self.assert_execution_avoids_absent_pixels(plan, image)
                finally:
                    close_plan(plan, image)

    def test_safe_rectangle_fill_keeps_opaque_neighbor_and_falls_back_around_absent_pixel(self):
        for alpha in (0, 255):
            with self.subTest(alpha=alpha), closing(Image.new('RGBA', (180, 120), 'white')) as image:
                draw = ImageDraw.Draw(image)
                draw.rectangle((15, 15, 89, 99), fill=(0, 80, 205, 255))
                draw.rectangle((110, 20, 164, 94), fill=(255, 120, 41, 255))
                image.putpixel((50, 50), (255, 255, 255, alpha))
                plan = DrawBot.make_plan(image, image.size, standard_options(
                    use_region_fill_engine=True, fill_tool_available=True, fill_engine='Safe rectangles',
                    fill_tool_actions=[('fill', (10, 10))], fill_restore_actions=[('brush', (20, 10))]))
                try:
                    regions = plan['options']['fill_regions']
                    self.assertEqual([tuple(region['rgb']) for region in regions],
                                     [(0, 80, 205), (255, 120, 41)] if alpha else [(255, 120, 41)])
                    self.assertEqual(plan['options']['region_fill_meta']['source_mask_rejections'], int(alpha == 0))
                    if alpha == 0:
                        pixels = group_pixels(plan['groups'])
                        self.assertNotIn((50, 50), pixels)
                        self.assertIn((49, 50), pixels)
                        self.assert_execution_avoids_absent_pixels(plan, image)
                finally:
                    close_plan(plan, image)

    def test_both_actual_turbo_policies_do_not_bridge_a_transparent_gap(self):
        from ProfileEngine import resolve_profile_policy
        from ProfilePolish import apply_profile_polish
        for profile, key, function in (
                ('Gartic Phone', 'gartic-phone', 'optimize_gartic_phone_groups'),
                ('Skribbl.io Fast', 'skribbl-fast', 'optimize_skribbl_groups')):
            with self.subTest(profile=profile), closing(Image.new('RGBA', (64, 64), (220, 20, 140, 0))) as image:
                draw = ImageDraw.Draw(image)
                draw.rectangle((5, 5, 8, 8), fill=(0, 0, 0, 255))
                draw.line((15, 32, 50, 32), fill=(0, 80, 205, 255))
                image.putpixel((30, 32), (0, 80, 205, 0))
                requested = standard_options(profile_engine='Auto', profile_name=profile, profile_key=key,
                                             gartic_phone_gap_join=2, skribbl_gap_join=2, skip_white=False)
                effective, _ = resolve_profile_policy(profile, requested, mode='Auto')
                effective, _ = apply_profile_polish(profile, effective)
                effective['drawing_mode'] = effective['mode']
                with patch.object(DrawBot, function, wraps=getattr(DrawBot, function)) as turbo:
                    plan = DrawBot.make_plan(image, image.size, effective)
                try:
                    turbo.assert_called_once()
                    self.assertEqual(turbo.call_args.kwargs['gap_join'], 0)
                    expected = ({(x, y) for x in range(5, 9) for y in range(5, 9)} |
                                {(x, 32) for x in range(15, 51) if x != 30})
                    self.assertEqual(group_pixels(plan['groups']), expected)
                    self.assertNotIn((30, 32), group_pixels(plan['groups']))
                    self.assert_execution_avoids_absent_pixels(plan, image)
                finally:
                    close_plan(plan, image)

    def test_source_alpha_filter_uses_actual_fill_shape_and_preserves_prior_rejections(self):
        with closing(Image.new('RGBA', (8, 8), 'white')) as image:
            image.putpixel((3, 3), (0, 0, 0, 0))
            image.putpixel((1, 1), (10, 20, 30, 1))
            region = {'bbox': (1, 1, 3, 3), 'row_spans': ((1, 1, 3), (2, 1, 1), (3, 1, 1)),
                      'strategy': 'closed-region'}
            rectangle = dict(region, strategy='rectangle')
            metadata = {'input_regions': 4, 'rejected_regions': 2, 'rejected': {'outside safe fill mask': 2}}
            accepted, meta = filter_fill_regions_by_source_alpha([region, rectangle], image, metadata=metadata)
            self.assertEqual(accepted, [region])
            self.assertIsNot(accepted[0], region)
            self.assertEqual(meta['input_regions'], 4)
            self.assertEqual(meta['rejected_regions'], 3)
            self.assertEqual(meta['transparent_source_rejections'], 1)
            self.assertEqual(metadata['rejected'], {'outside safe fill mask': 2})
            self.assertEqual(image.getpixel((1, 1)), (10, 20, 30, 1))
            with patch('SafeFillMask._row_spans', side_effect=AssertionError('bbox must be bounded first')):
                accepted, meta = filter_fill_regions_by_source_alpha(
                    [dict(rectangle, bbox=(1, 1, 3, 10 ** 12))], image)
            self.assertFalse(accepted)
            self.assertEqual(meta['rejected_regions'], 1)
            with self.assertRaises(InterruptedError):
                filter_fill_regions_by_source_alpha([rectangle], image, cancelled=lambda: True)

    def test_actual_hybrid_filters_source_alpha_before_stateful_fill_validation(self):
        import AdaptiveRegionHybrid as hybrid
        observed = []
        original_filter = hybrid.filter_stateful_fill_regions
        def capture(regions, *args, **kwargs):
            observed.extend(regions)
            return original_filter(regions, *args, **kwargs)
        with closing(Image.new('RGBA', (180, 120), 'white')) as image:
            draw = ImageDraw.Draw(image)
            draw.rectangle((15, 15, 89, 99), fill=(0, 80, 205, 255))
            draw.rectangle((110, 20, 164, 94), fill=(255, 120, 41, 255))
            image.putpixel((50, 50), (255, 255, 255, 0))
            with patch.object(hybrid, 'filter_stateful_fill_regions', side_effect=capture):
                plan = DrawBot.make_plan(image, image.size, standard_options(
                    extra_fast=True, extra_fast_v2=True, use_region_fill_engine=True,
                    fill_tool_available=True, fill_engine='Safe rectangles',
                    fill_tool_actions=[('fill', (10, 10))], fill_restore_actions=[('brush', (20, 10))]))
            try:
                self.assertTrue(plan['options']['adaptive_hybrid_meta']['enabled'])
                self.assertTrue(observed)
                self.assertTrue(all(tuple(region['rgb']) != (0, 80, 205) for region in observed))
                self.assertEqual(plan['options']['region_fill_meta']['safe_fill_mask']['transparent_source_rejections'], 1)
                self.assertNotIn((50, 50), group_pixels(plan['groups']))
                self.assert_execution_avoids_absent_pixels(plan, image)
            finally:
                close_plan(plan, image)


if __name__ == '__main__':
    unittest.main()
