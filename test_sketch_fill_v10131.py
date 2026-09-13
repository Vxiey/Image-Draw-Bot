import unittest
from pathlib import Path
from PIL import Image,ImageDraw
from SketchFillRenderer import SKETCH_FILL_RENDER_STYLE,build_sketch_fill_plan,is_sketch_fill,render_sequence_preview

class SketchFillV10131Tests(unittest.TestCase):
    def base(self,**changes):
        d=dict(profile_name='Microsoft Paint',profile_key='microsoft-paint',render_style=SKETCH_FILL_RENDER_STYLE,
               render_preset='Auto',outline=False,paint_current_color=False,erase_mode=False,sketch_detail='Detailed')
        d.update(changes);return d

    def fake_color_plan(self,image,area,options,cancelled):
        # Two plan-local colors, including a custom selector, prove propagation.
        paths=[ [((3,8),(25,8)),((3,9),(25,9))], [((30,12),(50,12))] ]
        return {'image':image.convert('RGBA'),'fitted':image.size,'execution_groups':paths,'colors':((220,30,30),(20,120,220)),
                'color_selectors':({'kind':'custom','rgb':(220,30,30)},{'kind':'palette','palette_index':1,'rgb':(20,120,220)}),
                'options':dict(options,plan_palette_rgb=((220,30,30),(20,120,220)),color_order=[0,1],exact_color_available=True)}

    def fake_finish(self,image,fitted,groups,options,cancelled):
        return {'image':image,'fitted':fitted,'groups':groups,'options':options,'colors':tuple(options['plan_palette_rgb']),
                'color_selectors':tuple(options['color_selectors']),'execution_groups':options['_sketch_fill_execution_groups'],
                'execution_sequence':options['_sketch_fill_execution_sequence']}

    def picture(self):
        im=Image.new('RGB',(64,40),'white');d=ImageDraw.Draw(im);d.rectangle((5,5,28,32),fill=(220,30,30));d.ellipse((34,7,58,32),fill=(20,120,220));return im

    def test_phase_order_is_strict(self):
        p=build_sketch_fill_plan(self.picture(),(64,40),self.base(),self.fake_color_plan,self.fake_finish)
        phases=[e['phase'] for e in p['execution_sequence']]
        order={'sketch':0,'color_fill':1,'reoutline':2}
        self.assertEqual([order[x] for x in phases],sorted(order[x] for x in phases))
        self.assertIn('sketch',phases);self.assertIn('color_fill',phases);self.assertIn('reoutline',phases)

    def test_native_fill_prelude_is_disabled_and_custom_colors_survive(self):
        p=build_sketch_fill_plan(self.picture(),(64,40),self.base(),self.fake_color_plan,self.fake_finish)
        self.assertEqual(p['options']['fill_regions'],[])
        self.assertEqual(p['options']['background_fill'],'Off')
        self.assertFalse(p['options']['sketch_fill_meta']['native_bucket_prelude'])
        self.assertTrue(p['options']['sketch_fill_meta']['custom_colors_reused'])
        self.assertTrue(any(s.get('kind')=='custom' for s in p['color_selectors']))

    def test_browser_target_fails_closed(self):
        with self.assertRaises(ValueError):
            build_sketch_fill_plan(self.picture(),(64,40),self.base(profile_name='Gartic Phone',profile_key='gartic-phone'),self.fake_color_plan,self.fake_finish)

    def test_sequence_preview_finishes_with_reoutline(self):
        seq=[{'color_index':0,'phase':'sketch','path':((2,2),(30,2))},{'color_index':1,'phase':'color_fill','path':((2,2),(30,2))},{'color_index':0,'phase':'reoutline','path':((2,2),(30,2))}]
        out=render_sequence_preview((32,16),(32,16),seq,((0,0,0),(255,0,0)),1)
        self.assertEqual(out.getpixel((16,2)),(0,0,0))

    def test_source_keeps_gartic_legacy_route(self):
        source=Path('DrawBot.py').read_text(encoding='utf-8')
        self.assertIn("from GarticSketchPaths import trace_contours",source)
        self.assertIn("('gartic-phone','gartic-io')",source)
        self.assertNotIn("profile_name') == 'Gartic Phone' and is_sketch_fill",source)

    def test_version(self):
        from Version import APP_VERSION,FILE_VERSION,BUILD_CHANNEL
        self.assertEqual((APP_VERSION,FILE_VERSION,BUILD_CHANNEL),('1.0.145-rc29','1.0.145','rc'))

if __name__=='__main__':unittest.main()
