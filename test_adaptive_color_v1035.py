import threading,unittest
from pathlib import Path
from PIL import Image

from AdaptiveColor import method_candidates,probe_item,rgb_key
from DrawBot import execute_plan
from test_drawbot import Mouse,NoWait,options


class Keyboard:
    def __init__(self):self.actions=[]
    def press_and_release(self,key):self.actions.append(('press',key))
    def write(self,text,delay=0):self.actions.append(('write',str(text)))


class AdaptiveMouse(Mouse):
    def __init__(self,results):
        super().__init__();self.results=list(results);self.inspect_calls=[];self.modal=[]
    def calibrated_modal_nearest_color_rect(self,a,b,rgb,max_samples=70000):
        return ((30,30),tuple(rgb),0.0)
    def calibrated_modal_click(self,p):self.modal.append(tuple(p));self.actions.append(('modal',*p))
    def reset_tracking(self):pass
    def inspect_ink_segment(self,start,end,expected,brush_px=1,tolerance=48):
        self.inspect_calls.append((start,end,tuple(expected),brush_px,tolerance))
        return dict(self.results.pop(0))


class AdaptiveColorV1035Tests(unittest.TestCase):
    def test_method_candidates_use_eye_then_cached_then_exact_fallbacks(self):
        selector={'kind':'custom','rgb':(1,2,3),'fallback_palette_index':0}
        actions={'OpenCustomColor':(1,1),'ConfirmColor':(2,2),'SpectrumTopLeft':(3,3),'SpectrumBottomRight':(4,4),
                 'RedField':(5,5),'GreenField':(6,6),'BlueField':(7,7),'Eyedropper':(8,8)}
        self.assertEqual(method_candidates(selector,actions,has_sample=True,keyboard_available=True,cached_method='numeric'),
                         ('eyedropper','numeric','spectrum','palette'))

    def test_probe_item_is_shorter_than_full_path(self):
        self.assertEqual(probe_item((0,0,100,0),False,4),(0,0,4,0))
        p=probe_item([(0,0),(100,0),(100,20)],True,4)
        self.assertEqual(p,[(0,0),(4,0)])

    def test_custom_color_recovers_spectrum_to_numeric_then_paints_batch(self):
        mouse=AdaptiveMouse([
            {'matched':False,'actual':(90,90,90),'error':80,'confidence':68.6,'sample_count':20,'reason':'mismatch'},
            {'matched':True,'actual':(12,34,55),'error':1,'confidence':99.6,'sample_count':20,'reason':''},
        ])
        keyboard=Keyboard();events=[];cache={}
        opt=options();opt.update({'adaptive_color_verification':True,'strict_color_verification':True,'color_verification_tolerance':48,
                                  'color_probe_source_span':4,'color_session_cache':cache,'paint_tool':'Pencil','brush_px':2,
                                  'exact_color_actions':{'OpenCustomColor':(1,1),'ConfirmColor':(2,2),'SpectrumTopLeft':(3,3),'SpectrumBottomRight':(4,4),
                                                         'RedField':(5,5),'GreenField':(6,6),'BlueField':(7,7)},
                                  'color_workflow':'Finish color first','color_order':[0]})
        plan={'options':opt,'image':Image.new('RGBA',(20,1)),'fitted':(100,10),
              'groups':[[(0,0,19,0)]],'execution_groups':None,'execution_sequence':[],'count':1,
              'colors':((12,34,56),),'color_selectors':({'kind':'custom','rgb':(12,34,56),'fallback_palette_index':0},)}
        execute_plan(plan,(100,100,100,10),[(900,900)],mouse,NoWait(),threading.Event(),lambda *e:events.append(e),keyboard=keyboard)
        self.assertEqual(len(mouse.inspect_calls),2)
        # Two short verification probes + one real full path.
        self.assertEqual(sum(a[0]=='press' for a in mouse.actions),3)
        self.assertTrue(any(a==('write','12') for a in keyboard.actions))
        self.assertEqual(cache[rgb_key((12,34,56))]['method'],'numeric')
        self.assertGreater(cache[rgb_key((12,34,56))]['confidence'],99)
        plans=[v for k,v in events if k=='color_plan' and isinstance(v,dict)]
        self.assertTrue(any(not v.get('matched') for v in plans));self.assertTrue(any(v.get('matched') for v in plans))

    def test_unrecoverable_color_stops_only_after_all_safe_methods(self):
        mouse=AdaptiveMouse([
            {'matched':False,'actual':(120,120,120),'error':120,'confidence':52,'sample_count':10,'reason':'bad'},
            {'matched':False,'actual':(110,110,110),'error':110,'confidence':56,'sample_count':10,'reason':'bad'},
            {'matched':False,'actual':(100,100,100),'error':100,'confidence':60,'sample_count':10,'reason':'bad'},
        ])
        keyboard=Keyboard();opt=options();opt.update({'adaptive_color_verification':True,'strict_color_verification':True,
            'color_session_cache':{},'paint_tool':'Pencil','brush_px':1,'color_order':[0],
            'exact_color_actions':{'OpenCustomColor':(1,1),'ConfirmColor':(2,2),'SpectrumTopLeft':(3,3),'SpectrumBottomRight':(4,4),
                                   'RedField':(5,5),'GreenField':(6,6),'BlueField':(7,7)}})
        plan={'options':opt,'image':Image.new('RGBA',(10,1)),'fitted':(50,10),'groups':[[(0,0,9,0)]],
              'execution_groups':None,'execution_sequence':[],'count':1,'colors':((5,6,7),),
              'color_selectors':({'kind':'custom','rgb':(5,6,7),'fallback_palette_index':0},)}
        with self.assertRaisesRegex(InterruptedError,'adaptive recovery'):
            execute_plan(plan,(100,100,50,10),[(900,900)],mouse,NoWait(),threading.Event(),lambda *e:None,keyboard=keyboard)
        self.assertEqual(len(mouse.inspect_calls),3)

    def test_non_paint_mode_can_disable_extra_color_verification(self):
        mouse=AdaptiveMouse([{'matched':False,'actual':(255,255,255),'error':255,'confidence':0,'sample_count':1,'reason':'unused'}])
        opt=options();opt.update({'adaptive_color_verification':False,'strict_color_verification':False,'color_order':[0]})
        plan={'options':opt,'image':Image.new('RGBA',(4,1)),'fitted':(40,10),'groups':[[(0,0,3,0)]],
              'execution_groups':None,'execution_sequence':[],'count':1,'colors':((0,0,0),),'color_selectors':()}
        execute_plan(plan,(100,100,40,10),[(10,10)],mouse,NoWait(),threading.Event(),lambda *e:None)
        self.assertEqual(mouse.inspect_calls,[])

    def test_release_version_and_ui_status_hook(self):
        from Version import APP_VERSION,FILE_VERSION
        self.assertEqual(APP_VERSION,'1.0.145-rc29');self.assertEqual(FILE_VERSION,'1.0.145')
        ui=Path('StudioUI.py').read_text(encoding='utf-8');bot=Path('DrawBot.py').read_text(encoding='utf-8')
        self.assertIn('color_plan_text',ui);self.assertIn("elif kind=='color_plan'",bot)
        self.assertIn("'adaptive_color_verification':bool(paint_profile",bot)
        self.assertIn("'strict_color_verification':bool(paint_profile",bot)

if __name__=='__main__':unittest.main()
