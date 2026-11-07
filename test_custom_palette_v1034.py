import threading,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from CalibrationAnchors import make_anchor
from ExactColorTools import save,load,custom_rgb_available,spectrum_available,numeric_rgb_available
from DrawBot import execute_plan,finish_plan
from ScreenGuard import GuardedMouse
from test_drawbot import Mouse,NoWait,options


class CustomPaletteV1034Tests(unittest.TestCase):
    def test_spectrum_only_calibration_enables_exact_color(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'exact.json';anchor=make_anchor((0,0,800,600))
            controls={'OpenCustomColor':(10,10),'SpectrumTopLeft':(20,20),'SpectrumBottomRight':(220,180),'ConfirmColor':(250,250)}
            save('x',controls,anchor=anchor,path=path)
            self.assertTrue(spectrum_available('x',path));self.assertFalse(numeric_rgb_available('x',path));self.assertTrue(custom_rgb_available('x',path))
            self.assertEqual(load('x',path)['version'],2)

    def test_visual_scale_selected_before_numeric_or_palette_fallback(self):
        class ScaleMouse(Mouse):
            def __init__(self):super().__init__();self.rect_calls=[];self.line_calls=[]
            def calibrated_modal_nearest_color_rect(self,a,b,rgb,max_samples=70000):
                self.rect_calls.append((a,b,rgb));return ((35,45),rgb,0.0)
            def calibrated_modal_nearest_color_line(self,a,b,rgb,samples=320):
                self.line_calls.append((a,b,rgb));return ((250,100),rgb,0.0)
            def calibrated_modal_click(self,p):self.actions.append(('modal',*p))
            def reset_tracking(self):pass
        mouse=ScaleMouse();opt=options();opt['exact_color_actions']={
            'OpenCustomColor':(1,1),'SpectrumTopLeft':(20,20),'SpectrumBottomRight':(200,180),
            'BrightnessTop':(250,20),'BrightnessBottom':(250,180),'ConfirmColor':(5,5)}
        plan={'options':opt,'image':Image.new('RGBA',(2,1)),'fitted':(20,10),'groups':[[(0,0,1,0)]],
              'execution_groups':None,'execution_sequence':[],'count':1,'colors':((12,34,56),),
              'color_selectors':({'kind':'custom','rgb':(12,34,56),'fallback_palette_index':0},)}
        execute_plan(plan,(100,100,20,10),[(900,900)],mouse,NoWait(),threading.Event(),lambda *a:None,keyboard=None)
        self.assertGreaterEqual(len(mouse.rect_calls),2);self.assertEqual(len(mouse.line_calls),1)
        self.assertIn(('modal',35,45),mouse.actions);self.assertIn(('modal',5,5),mouse.actions)
        self.assertNotIn(('move',900,900),mouse.actions)

    def test_finish_color_first_suppresses_cross_color_progressive_sequence(self):
        opt=options();opt.update({'drawing_mode':'Smart paths (recommended)','smart_paths':True,'progressive_rendering':'On',
                                  'color_workflow':'Finish color first','color_order':[0,1],'brush_px':1,'max_seconds':180})
        groups=[[(0,0,4,0)],[(0,1,4,1)]]
        plan=finish_plan(Image.new('RGBA',(5,2)),(50,20),groups,opt)
        self.assertEqual(plan['execution_sequence'],[])
        self.assertTrue(plan['path_stats'].get('progressive_suppressed_by_color_batching'))

    def test_finish_color_first_selects_each_color_once(self):
        mouse=Mouse();events=[]
        opt=options();opt.update({'color_workflow':'Finish color first','color_order':[0,1]})
        plan={'options':opt,'image':Image.new('RGBA',(4,2)),'fitted':(40,20),
              'groups':[[(0,0,1,0),(2,0,3,0)],[(0,1,1,1),(2,1,3,1)]],
              'execution_groups':None,'execution_sequence':[],'count':4,'colors':((0,0,0),(255,0,0)),'color_selectors':()}
        palette=[(10,10),(20,20)]
        execute_plan(plan,(100,100,40,20),palette,mouse,NoWait(),threading.Event(),lambda *e:events.append(e))
        palette_moves=[a for a in mouse.actions if a in [('move',10,10),('move',20,20)]]
        self.assertEqual(palette_moves,[('move',10,10),('move',20,20)])
        statuses=[v for k,v in events if k=='status' and isinstance(v,str) and v.startswith('Color ')]
        self.assertEqual(len(statuses),2);self.assertIn('finishing 2 path(s)',statuses[0])

    def test_modal_spectrum_sampling_finds_nearest_pixel(self):
        class Monitor:
            def rectangle(self,handle):return (0,0,500,500)
            def verify_modal(self,target,point):pass  # This fixture isolates pixel selection.
        class RawMouse:
            def get_position(self):return (0,0)
        guard=GuardedMouse(RawMouse(),Monitor(),(123,(0,0,500,500)))
        img=Image.new('RGB',(3,2),(0,0,0));img.putpixel((2,1),(120,80,200))
        with patch('PIL.ImageGrab.grab',return_value=img):
            point,rgb,error=guard.calibrated_modal_nearest_color_rect((10,20),(12,21),(121,79,201))
        self.assertEqual(point,(12,21));self.assertEqual(rgb,(120,80,200));self.assertLess(error,2)

if __name__=='__main__':unittest.main()
