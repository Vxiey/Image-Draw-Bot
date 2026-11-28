"""Exercise the gap policy through the browser profiles' public planner."""
from pathlib import Path
import unittest

from PIL import Image

from DrawBot import make_plan
from PaletteMaps import PRESETS
from RasterIdentity import canonical_pixels_from_paths
from test_skribbl_fast_renderer_v1017 import base_options
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch42_fidelity import calibrated_palette


class BrowserFastGapPolicyTests(unittest.TestCase):
    profiles = (
        ('Skribbl.io Fast', 'skribbl-fast', 'skribbl_fast', 'skribbl_fast_meta'),
        ('Gartic Phone', 'gartic-phone', 'gartic_phone', 'gartic_phone_fast_meta'),
    )

    def snapshot(self, source, name, key, prefix, metadata, **settings):
        options = base_options(profile_name=name, profile_key=key, paint_current_color=False,
            brush_px=1, color_grouping='Smart', unlimited_time=True,
            _execution_cost_calibration_override={'samples': 0})
        options[prefix + '_min_run'] = 1
        for setting, value in settings.items():
            options[prefix + '_' + setting] = value
        plan = make_plan(source, (800, 600), options)
        try:
            gap = plan['options'][metadata]['gap_join']
            masks = tuple(canonical_pixels_from_paths(paths) for paths in plan['execution_groups'])
            return gap, masks
        finally:
            close_plan(plan, source)

    def test_explicit_zero_preserves_the_same_gaps_as_string_zero(self):
        fixture = Path(__file__).parent / 'golden-regression/small-detail-preservation.png'
        with Image.open(fixture) as source:
            for profile in self.profiles:
                with self.subTest(profile=profile[0]), calibrated_palette(PRESETS[profile[1]].colors):
                    strict = self.snapshot(source, *profile, gap_join=0)
                    self.assertEqual(strict[0], 0)
                    self.assertEqual(strict, self.snapshot(source, *profile, gap_join='0'))
                    legacy = self.snapshot(source, *profile)
                    self.assertEqual(legacy[0], 1)
                    self.assertTrue(any(bridged - exact for bridged, exact in zip(legacy[1], strict[1])))
                    self.assertEqual(legacy, self.snapshot(source, *profile, gap_join=None))
                    self.assertEqual(legacy, self.snapshot(source, *profile, gap_join=''))

    def test_transparency_still_overrides_an_explicit_positive_gap(self):
        fixture = Path(__file__).parent / 'assets/image-draw-bot-icon.png'
        with Image.open(fixture) as source:
            for profile in self.profiles:
                with self.subTest(profile=profile[0]), calibrated_palette(PRESETS[profile[1]].colors):
                    strict = self.snapshot(source, *profile, gap_join=0)
                    self.assertEqual(strict[0], 0)
                    self.assertEqual(strict, self.snapshot(source, *profile, gap_join=2))
