import unittest
from pathlib import Path

import numpy as np
from PIL import Image,ImageDraw

from DrawingStyleProfiles import DRAWING_STYLES,apply_drawing_style,classify_drawing_style,validate_drawing_style


class DrawingStyleProfileTests(unittest.TestCase):
    def test_style_catalog(self):
        self.assertEqual(DRAWING_STYLES[0],'Auto')
        for name in ('Pixel Art','Logo / Flat Graphic','Portrait','Photo / Shaded','Line Art','Cartoon / Illustration'):
            self.assertIn(name,DRAWING_STYLES)

    def test_pixel_art_is_accuracy_first(self):
        image=Image.new('RGB',(32,32),'white');ImageDraw.Draw(image).rectangle((4,4,27,27),fill='red')
        out=apply_drawing_style(image,{'drawing_style':'Pixel Art','render_preset':'Manual'})
        self.assertEqual(out['draw_quality'],'Pixel Accurate')
        self.assertEqual(out['brush_px'],1)
        self.assertEqual(out['background_simplification'],'Off')
        self.assertEqual(out['gartic_opacity'],'100%')

    def test_logo_is_fill_first_flat_color(self):
        out=apply_drawing_style(Image.new('RGB',(400,200),'white'),{'drawing_style':'Logo / Flat Graphic'})
        self.assertEqual(out['drawing_mode'],'Shape paths')
        self.assertEqual(out['shape_order'],'Fill first')
        self.assertEqual(out['fill_engine'],'Closed regions v2')
        self.assertEqual(out['gartic_opacity'],'100%')

    def test_portrait_protects_subject_detail(self):
        out=apply_drawing_style(Image.new('RGB',(300,400),(140,120,110)),{'drawing_style':'Portrait'})
        self.assertEqual(out['render_style'],'Portrait / shaded')
        self.assertEqual(out['subject_focus'],'Subject first')
        self.assertEqual(out['draw_quality'],'Maximum likeness')
        self.assertEqual(out['detail_zoom'],'Auto')

    def test_auto_tiny_low_palette_can_detect_pixel_art(self):
        image=Image.new('RGB',(48,48),'white');d=ImageDraw.Draw(image)
        for y in range(0,48,8):
            for x in range(0,48,8):
                if (x+y)//8%2:d.rectangle((x,y,x+7,y+7),fill='black')
        style,meta=classify_drawing_style(image)
        self.assertEqual(style,'Pixel Art')
        self.assertIn('unique',meta)

    def test_sparse_colored_artwork_keeps_color_in_the_executable_plan_and_preview(self):
        import Colors
        from DrawBot import make_plan
        from PixelData import closest_color
        from test_drawbot import options
        from test_v148_rendering_batch06_canvas import close_plan

        original_palette = Colors.allColors.copy()
        self.addCleanup(closest_color.cache_clear)
        self.addCleanup(Colors.allColors.__setitem__, slice(None), original_palette)
        Colors.reset_palette()
        asset = Path(__file__).parent / 'assets' / 'paint-tools-reference.png'
        with Image.open(asset) as image:
            source = np.asarray(image)[:, :, :3].astype(np.int16)
            colored = np.ptp(source, axis=2) > 35
            self.assertGreater(int(colored.sum()), 200)
            for preset in ('Auto', 'Extra fast'):
                settings = dict(options(), render_preset=preset, drawing_style='Auto',
                                gpu_mode='CPU', preview_plan=True, profile_name='Microsoft Paint',
                                brush_px=1, _execution_cost_calibration_override={})
                with self.subTest(preset=preset):
                    plan = make_plan(image, image.size, settings)
                    try:
                        self.assertFalse(plan['options']['outline'])
                        self.assertTrue(any(group and max(rgb) - min(rgb) > 35 for group, rgb in
                                            zip(plan['execution_groups'], plan['colors'])))
                        preview = np.asarray(plan['preview'])[:, :, :3].astype(np.int16)
                        self.assertLess(np.abs(preview - source)[colored].mean(), 45)
                        self.assertGreater((np.ptp(preview, axis=2)[colored] > 35).mean(), .60)
                    finally:
                        close_plan(plan, image)

    def test_explicit_outline_and_physical_brush_survive_colored_paper_detection(self):
        from AutoDrawing import resolve_drawing
        asset = Path(__file__).parent / 'tests' / 'fixtures' / 'paint-light-ribbon.png'
        with Image.open(asset) as image:
            for preset in ('Auto', 'Extra fast'):
                for explicit in ({'drawing_style': 'Line Art'}, {'outline': True},
                                 {'paint_current_color': True}):
                    with self.subTest(preset=preset, explicit=explicit):
                        result = resolve_drawing(image, {'render_preset': preset, 'brush_px': 5,
                                                        **explicit})
                        self.assertTrue(result['outline'])
                        self.assertEqual(result['brush_px'], 5)

    def test_validation_rejects_unknown(self):
        with self.assertRaises(ValueError):validate_drawing_style('Oil painting')

    def test_auto_drawing_explicit_style_short_circuits_generic_auto(self):
        from AutoDrawing import resolve_drawing
        image=Image.new('RGB',(100,100),'red')
        out=resolve_drawing(image,{'drawing_style':'Logo / Flat Graphic','render_preset':'Auto','fill_tool_available':True})
        self.assertTrue(out['auto_engine_resolved'])
        self.assertEqual(out['drawing_mode'],'Shape paths')
        self.assertEqual(out['auto_drawing_meta']['engine'],'drawing style profile')


if __name__=='__main__':unittest.main()
