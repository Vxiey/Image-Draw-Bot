import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from AdaptiveColor import method_candidates
from ColorMatchingEngine import measure_color_pixels, measure_quantized_regions, visible_rgb_image
from DynamicColors import build_dynamic_color_strokes
from DrawBot import execute_plan
from ScreenGuard import GuardedMouse
from test_drawbot import Mouse, NoWait, options


class _KB:
    def __init__(self): self.actions=[]
    def press_and_release(self,key): self.actions.append(('key',key))
    def write(self,text,delay=0): self.actions.append(('write',str(text)))


class _PreviewMouse(Mouse):
    def __init__(self):
        super().__init__();self.preview=[(200,200,200),(200,200,200),(12,34,56)];self.rect_calls=0
    def calibrated_modal_click(self,p): self.actions.append(('modal',*p))
    def calibrated_modal_color(self,p): return self.preview.pop(0)
    def calibrated_modal_nearest_color_rect(self,a,b,rgb,max_samples=70000):
        self.rect_calls+=1;return ((30,30),tuple(rgb),0.0)
    def reset_tracking(self): pass
    def inspect_ink_segment(self,start,end,expected,brush_px=1,tolerance=48):
        return {'matched':True,'actual':tuple(expected),'error':0,'confidence':100.0,'sample_count':9,'reason':''}


class V109AdvancedColorTests(unittest.TestCase):
    def test_alpha_is_measured_as_visible_rgb(self):
        im=Image.new('RGBA',(1,1),(255,0,0,128))
        self.assertEqual(visible_rgb_image(im).getpixel((0,0)),(255,127,127))

    def test_flat_region_keeps_exact_dominant_source_rgb(self):
        px=np.array([(12,34,56)]*90+[(250,250,250)]*10,dtype=np.uint8)
        sample=measure_color_pixels(px)
        self.assertEqual(sample.rgb,(12,34,56))
        self.assertEqual(sample.dominant_rgb,(12,34,56))
        self.assertGreater(sample.dominant_fraction,.8)

    def test_quantized_region_reports_mean_median_and_dominant(self):
        im=Image.new('RGB',(4,1));im.putdata([(10,20,30),(10,20,30),(12,21,31),(200,210,220)])
        labels=Image.new('P',(4,1));labels.putdata([0,0,0,1])
        stats=measure_quantized_regions(im,labels)
        self.assertEqual(stats[0].dominant_rgb,(10,20,30))
        self.assertEqual(stats[1].rgb,(200,210,220))
        self.assertEqual(stats[0].count,3)

    def test_dynamic_custom_selector_carries_source_measurements(self):
        im=Image.new('RGB',(8,1),(120,90,200))
        groups,colors,selectors,meta=build_dynamic_color_strokes(im,((0,0,0),(255,255,255)),max_colors=2,skip_white=False,exact_available=True,exact_threshold=1)
        custom=next(s for s in selectors if s['kind']=='custom')
        self.assertTrue(custom['prefer_numeric'])
        self.assertEqual(custom['source_rgb'],(120,90,200))
        self.assertIn('source_mean_rgb',custom);self.assertIn('source_median_rgb',custom);self.assertIn('source_dominant_rgb',custom)
        self.assertEqual(meta['mode'],'dynamic-exact-v4')

    def test_image_selector_prefers_numeric_rgb_before_spectrum(self):
        selector={'kind':'custom','rgb':(12,34,56),'fallback_palette_index':0,'prefer_numeric':True}
        actions={'OpenCustomColor':(1,1),'ConfirmColor':(2,2),'SpectrumTopLeft':(3,3),'SpectrumBottomRight':(4,4),
                 'RedField':(5,5),'GreenField':(6,6),'BlueField':(7,7)}
        self.assertEqual(method_candidates(selector,actions,keyboard_available=True),('numeric','spectrum','palette'))

    def test_wrong_numeric_preview_is_not_confirmed_and_spectrum_recovers(self):
        mouse=_PreviewMouse();kb=_KB();events=[]
        opt=options();opt.update({'adaptive_color_verification':True,'strict_color_verification':True,'color_order':[0],
            'color_session_cache':{},'paint_tool':'Pencil','brush_px':1,
            'exact_color_actions':{'OpenCustomColor':(1,1),'ConfirmColor':(2,2),'SpectrumTopLeft':(3,3),'SpectrumBottomRight':(4,4),
                                   'RedField':(5,5),'GreenField':(6,6),'BlueField':(7,7),'SelectedColorPreview':(8,8)}})
        selector={'kind':'custom','rgb':(12,34,56),'fallback_palette_index':0,'prefer_numeric':True,
                  'source_mean_rgb':(12,34,56),'source_median_rgb':(12,34,56),'source_dominant_rgb':(12,34,56)}
        plan={'options':opt,'image':Image.new('RGBA',(10,1)),'fitted':(50,10),'groups':[[(0,0,9,0)]],
              'execution_groups':None,'execution_sequence':[],'count':1,'colors':((12,34,56),),'color_selectors':(selector,)}
        execute_plan(plan,(100,100,50,10),[(900,900)],mouse,NoWait(),threading.Event(),lambda *e:events.append(e),keyboard=kb)
        self.assertGreaterEqual(sum(a==('write','12') for a in kb.actions),2)
        self.assertEqual(mouse.rect_calls,1)
        # Confirm is clicked only once, after the preview-verified fallback.
        self.assertEqual(mouse.actions.count(('modal',2,2)),1)
        self.assertTrue(any('preview check' in str(v) for k,v in events if k=='status'))

    def test_modal_preview_uses_patch_median_not_one_bad_pixel(self):
        class Monitor:
            def rectangle(self,handle): return (0,0,500,500)
        class RawMouse:
            def get_position(self): return (0,0)
        guard=GuardedMouse(RawMouse(),Monitor(),(1,(0,0,500,500)))
        img=Image.new('RGB',(5,5),(12,34,56));img.putpixel((2,2),(255,255,255))
        with patch('PIL.ImageGrab.grab',return_value=img):
            self.assertEqual(guard.calibrated_modal_color((20,20),radius=2),(12,34,56))

    def test_version(self):
        from Version import APP_VERSION,FILE_VERSION
        self.assertEqual(APP_VERSION,'1.0.145-rc29');self.assertEqual(FILE_VERSION,'1.0.145')


if __name__=='__main__': unittest.main()
