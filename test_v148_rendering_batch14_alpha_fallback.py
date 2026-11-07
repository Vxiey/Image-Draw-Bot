"""Backend fallback preserves translucent palette choices and drawable pixels."""
from contextlib import closing
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from Colors import allColors
from DrawBot import make_plan
import PixelAccuratePlanner as pixel_planner
from PixelAccuratePlanner import exact_palette_map
from test_pixel_accurate_v1086 import opts
from test_v148_rendering_batch06_canvas import close_plan


class TransparentFallbackTests(unittest.TestCase):
    def maps(self, source, palette, **kwargs):
        expected = exact_palette_map(source, palette, gpu_mode='CPU', **kwargs)
        with patch('UniversalGpuAcceleration.palette_indices_rgba', side_effect=RuntimeError('backend unavailable')):
            actual = exact_palette_map(source, palette, gpu_mode='CPU', **kwargs)
        for index in range(3):
            np.testing.assert_array_equal(actual[index], expected[index])
        self.assertIn('backend unavailable', actual[3]['palette_route']['fallback_reason'])
        return actual

    def test_fractional_visible_colour_and_white_threshold_match_independent_rgb_oracle(self):
        pixels = [(210,145,222,152),(202,187,174,33),(57,234,136,96),
                  (255,255,255,255),(0,0,0,0),(245,245,245,255)]
        palette = tuple(color.RGB for color in allColors)
        with closing(Image.new('RGBA',(len(pixels),1))) as source:
            source.putdata(pixels)
            indices, drawable, _, _ = self.maps(source, palette,
                color_rendering='RGB nearest', color_fidelity='Fast', skip_white=True)
            for index, (*channels, alpha) in enumerate(pixels):
                # Compare integer numerators: no production float/compositing
                # helper or premature byte rounding enters this reference.
                visible = [channel*alpha+255*(255-alpha) for channel in channels]
                expected = min(range(len(palette)), key=lambda ci:
                    sum((visible[c]-255*palette[ci][c])**2 for c in range(3)))
                self.assertEqual(int(indices[0,index]), expected)
                self.assertEqual(bool(drawable[0,index]), alpha>0 and min(visible)<245*255)

    def test_large_varied_rgba_and_palette_modes_keep_fallback_results(self):
        raw = np.random.default_rng(1481402).integers(0,256,(50,80,4),dtype=np.uint8)
        palette = tuple(color.RGB for color in allColors)
        with closing(Image.fromarray(raw,'RGBA')) as source:
            original = source.tobytes()
            for rendering, fidelity in (('RGB nearest','Fast'), ('Perceptual match','Balanced'),
                                         ('Perceptual match','Faithful')):
                for skip in (False, True):
                    with self.subTest(rendering=rendering, fidelity=fidelity, skip=skip):
                        self.maps(source, palette, color_rendering=rendering,
                                  color_fidelity=fidelity, skip_white=skip)
            self.assertEqual(source.tobytes(), original)
        with closing(Image.new('P',(4,1))) as indexed:
            indexed.putpalette([210,145,222,202,187,174,0,0,0,255,255,255]+[0]*756)
            indexed.putdata([0,1,2,3]); indexed.info['transparency']=bytes([152,33,0,255])
            self.maps(indexed,palette,color_rendering='RGB nearest',skip_white=True)

    def test_real_public_plan_retains_strokes_and_previews_after_backend_failure(self):
        with closing(Image.new('RGBA',(24,20),(0,0,0,0))) as source:
            draw=ImageDraw.Draw(source)
            draw.rectangle((5,5,11,14),fill=(210,145,222,152))
            draw.rectangle((13,5,18,14),fill=(202,187,174,33))
            settings=opts(render_preset='Manual',time_budget_mode='Unlimited',unlimited_time=True,
                skip_white=True,color_rendering='RGB nearest',color_fidelity='Fast',
                detail_zoom='Off',cpu_workers_resolved=1,_execution_cost_calibration_override={})
            with patch('DrawTimeCalibration.load_profile',return_value=None):
                reference=make_plan(source,source.size,dict(settings))
                try:
                    with patch('UniversalGpuAcceleration.palette_indices_rgba',side_effect=RuntimeError('backend unavailable')):
                        fallback=make_plan(source,source.size,dict(settings))
                    try:
                        for key in ('colors','groups','execution_groups','execution_sequence','count','fitted','estimate'):
                            self.assertEqual(fallback[key],reference[key],key)
                        for key in reference['ui_previews']:
                            np.testing.assert_array_equal(np.asarray(fallback['ui_previews'][key]),
                                                          np.asarray(reference['ui_previews'][key]))
                        np.testing.assert_array_equal(np.asarray(fallback['preview']),np.asarray(reference['preview']))
                        self.assertEqual(fallback['options']['pixel_map_meta']['drawable_pixels'],130)
                    finally:close_plan(fallback,source)
                finally:close_plan(reference,source)

    def test_wide_fallback_composites_only_bounded_matching_tiles(self):
        palette=tuple(color.RGB for color in allColors)
        sizes=[];original=pixel_planner._matching_rgb_tile
        def observed(rgb,alpha,rows,columns):
            result=original(rgb,alpha,rows,columns)
            sizes.append(result.shape[0]*result.shape[1])
            return result
        with closing(Image.new('RGBA',(30000,1),(202,187,174,33))) as source, \
                patch.object(pixel_planner,'_matching_rgb_tile',side_effect=observed):
            result=self.maps(source,palette,color_rendering='RGB nearest',skip_white=True)
        self.assertTrue(np.all(result[1]))
        self.assertGreater(len(sizes),1)
        self.assertLessEqual(max(sizes),262144//len(palette))
        self.assertEqual(sum(sizes),30000)

    def test_stop_from_backend_and_during_fallback_cannot_publish_a_map(self):
        with closing(Image.new('RGBA',(8,8),(202,187,174,33))) as source:
            palette=((0,0,0),(255,255,255))
            with patch('UniversalGpuAcceleration.palette_indices_rgba',side_effect=InterruptedError), \
                    self.assertRaises(InterruptedError):
                exact_palette_map(source,palette,gpu_mode='CPU')
            stopped=False
            def fail(*_args,**_kwargs):
                nonlocal stopped
                stopped=True
                raise RuntimeError('backend unavailable')
            with patch('UniversalGpuAcceleration.palette_indices_rgba',side_effect=fail), \
                    patch('PixelAccuratePlanner._cpu_palette_map',side_effect=AssertionError('Stop must precede matching')), \
                    self.assertRaises(InterruptedError):
                exact_palette_map(source,palette,gpu_mode='CPU',cancelled=lambda:stopped)


if __name__=='__main__':
    unittest.main()
