import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from AutoDrawing import resolve_drawing
from ExtraFastProfilePolicy import strategy_log_line


class ExtraFastProfileRecognitionTests(unittest.TestCase):
    def flat_image(self):
        image=Image.new('RGB',(160,120),'white')
        d=ImageDraw.Draw(image)
        d.rectangle((18,18,142,102),fill=(230,75,40))
        d.rectangle((48,38,112,82),fill=(40,120,220))
        return image

    def noisy_photo(self):
        # Deterministic high-colour image; no AI/object classification is used.
        image=Image.new('RGB',(180,130))
        px=image.load()
        for y in range(image.height):
            for x in range(image.width):
                px[x,y]=((x*17+y*7)%256,(x*5+y*19)%256,(x*11+y*13)%256)
        return image

    def test_gartic_phone_binds_speed_palette_and_recognition_strategy(self):
        out=resolve_drawing(self.noisy_photo(),{
            'render_preset':'Extra fast','drawing_style':'Photo / Shaded',
            'profile_name':'Gartic Phone','profile_key':'gartic-phone',
            'fill_tool_available':False,'outline':False,'erase_mode':False,
            'paint_current_color':False,'exact_color_available':False,
        })
        meta=out['extra_fast_strategy_meta']
        self.assertTrue(meta['recognition_first'])
        self.assertEqual(meta['target_profile'],'Gartic Phone')
        self.assertEqual(meta['target_policy'],'Gartic recognition sprint')
        self.assertEqual(out['speed'],'Fast')
        self.assertEqual(out['precision'],'Normal')
        self.assertEqual(out['color_grouping'],'Reduced palette')
        self.assertEqual(out['exact_color_limit_profile_ceiling'],12)
        self.assertEqual(out['background_fill'],'Off')
        self.assertTrue(out['extra_fast_v2_meta']['path_policy'].startswith('RECOGNITION-FIRST/Gartic Phone/'))

    def test_skribbl_fast_has_its_own_target_policy(self):
        out=resolve_drawing(self.flat_image(),{
            'render_preset':'Extra fast','drawing_style':'Cartoon / Illustration',
            'profile_name':'Skribbl.io Fast','profile_key':'skribbl-io-fast',
            'fill_tool_available':True,'outline':False,'erase_mode':False,
            'paint_current_color':False,
        })
        meta=out['extra_fast_strategy_meta']
        self.assertEqual(meta['target_policy'],'Skribbl recognition sprint')
        self.assertEqual(out['speed'],'Fast')
        self.assertEqual(out['color_grouping'],'Reduced palette')
        self.assertEqual(out['exact_color_limit_profile_ceiling'],10)
        self.assertEqual(out['background_fill'],'Balanced')
        self.assertEqual(meta['engine_kind'],'regional-hybrid')

    def test_paint_keeps_more_detail_than_short_round_profiles(self):
        out=resolve_drawing(self.flat_image(),{
            'render_preset':'Extra fast','drawing_style':'Cartoon / Illustration',
            'profile_name':'Microsoft Paint','profile_key':'microsoft-paint',
            'fill_tool_available':True,'outline':False,'erase_mode':False,
            'paint_current_color':False,
        })
        self.assertEqual(out['planning_resolution'],'High')
        self.assertEqual(out['color_grouping'],'Smart')
        self.assertEqual(out['exact_color_limit_profile_ceiling'],28)
        self.assertEqual(out['precision'],'High')
        self.assertEqual(out['extra_fast_strategy_meta']['target_policy'],'Paint region quality')

    def test_pixel_art_profile_cannot_fall_back_to_generic_line_soup(self):
        pixel=Image.new('RGB',(48,48),'white')
        d=ImageDraw.Draw(pixel)
        d.rectangle((4,4,43,43),fill=(20,20,20))
        d.rectangle((8,8,39,39),fill=(245,60,60))
        d.rectangle((18,18,29,29),fill=(40,190,90))
        out=resolve_drawing(pixel,{
            'render_preset':'Extra fast','drawing_style':'Pixel Art',
            'profile_name':'Gartic Phone','profile_key':'gartic-phone',
            'fill_tool_available':False,'outline':False,'erase_mode':False,
            'paint_current_color':False,
        })
        meta=out['extra_fast_strategy_meta']
        self.assertEqual(meta['engine_kind'],'pixel-components')
        self.assertEqual(out['draw_quality'],'Pixel Accurate')
        self.assertEqual(out['background_simplification'],'Off')
        self.assertEqual(out['adaptive_detail'],'Off')
        self.assertEqual(out['detail_zoom'],'Off')
        self.assertEqual(out['color_grouping'],'Accurate')
        self.assertEqual(out['color_fidelity'],'Exact')
        self.assertEqual(out['max_stroke_cap'],'Unlimited')

    def test_line_art_uses_contours_not_generic_scanlines(self):
        line=Image.new('RGB',(120,90),'white')
        d=ImageDraw.Draw(line)
        d.rectangle((20,18,100,72),outline='black',width=2)
        d.line((20,72,60,32,100,72),fill='black',width=2)
        out=resolve_drawing(line,{
            'render_preset':'Extra fast','drawing_style':'Line Art',
            'profile_name':'Skribbl.io Fast','profile_key':'skribbl-io-fast',
            'fill_tool_available':True,'outline':False,'erase_mode':False,
            'paint_current_color':False,
        })
        self.assertTrue(out['outline'])
        self.assertEqual(out['background_fill'],'Off')
        self.assertEqual(out['extra_fast_strategy_meta']['engine_kind'],'contour-sketch')

    def test_eta_and_preview_log_explain_the_real_strategy(self):
        out=resolve_drawing(self.flat_image(),{
            'render_preset':'Extra fast','drawing_style':'Logo / Flat Graphic',
            'profile_name':'Gartic Phone','profile_key':'gartic-phone',
            'fill_tool_available':True,'outline':False,'erase_mode':False,
            'paint_current_color':False,
        })
        meta=out['extra_fast_strategy_meta']
        self.assertIn('final execution sequence',meta['eta_model'])
        self.assertIn('brush',meta['eta_model'])
        self.assertIn('Fill',meta['eta_model'])
        log=strategy_log_line(meta)
        self.assertIn('RECOGNITION FIRST',log)
        self.assertIn('Gartic Phone',log)
        self.assertIn('ETA=final execution sequence',log)

        # Existing Preview workspace summary/session log consumes this exact
        # metadata through DrawBot._plan_log_text; no second renderer is needed.
        source=Path('DrawBot.py').read_text(encoding='utf-8')
        self.assertIn("extra_fast_v2_meta=options.get('extra_fast_v2_meta')",source)
        self.assertIn("extra_fast_v2_meta.get('path_policy','?')",source)

    def test_generic_auto_keeps_legacy_adaptive_detail_default(self):
        out=resolve_drawing(object(),{
            'render_preset':'Extra fast','adaptive_detail':'Strong simplify',
            'fill_tool_available':False,'erase_mode':False,'paint_current_color':False,
            'outline':False,'exact_color_available':False,
        })
        self.assertEqual(out['adaptive_detail'],'Auto')
        self.assertIn('regional hybrid',out['auto_drawing_meta']['engine'].lower())


if __name__=='__main__':
    unittest.main()
