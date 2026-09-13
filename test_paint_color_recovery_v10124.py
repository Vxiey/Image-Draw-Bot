import threading, unittest
from PIL import Image

from DrawBot import execute_plan
from DynamicColors import build_dynamic_color_strokes, _custom_color_policy
from test_drawbot import Mouse, NoWait, options


class Keyboard:
    def __init__(self): self.actions=[]
    def press_and_release(self,key): self.actions.append(('press',key))
    def write(self,text,delay=0): self.actions.append(('write',str(text)))


class RecoveryMouse(Mouse):
    def __init__(self,results):
        super().__init__(); self.results=list(results); self.modal=[]
    def calibrated_modal_click(self,p): self.modal.append(tuple(p)); self.actions.append(('modal',*p))
    def reset_tracking(self): pass
    def inspect_ink_segment(self,start,end,expected,brush_px=1,tolerance=48):
        return dict(self.results.pop(0))


class PaintColorRecoveryV10124Tests(unittest.TestCase):
    def test_palette_mismatch_really_uses_numeric_rgb_recovery(self):
        mouse=RecoveryMouse([
            {'matched':False,'actual':(207,207,207),'error':207,'confidence':19,'sample_count':10,'reason':'wrong selected color'},
            {'matched':True,'actual':(0,0,0),'error':0,'confidence':100,'sample_count':10,'reason':''},
        ])
        kb=Keyboard(); events=[]; cache={}
        opt=options(); opt.update({
            'profile_name':'Microsoft Paint','profile_key':'microsoft-paint','adaptive_color_verification':True,
            'strict_color_verification':True,'color_session_cache':cache,'paint_tool':'Pencil','effective_paint_tool':'Pencil',
            'brush_px':1,'color_order':[0],
            'exact_color_actions':{'OpenCustomColor':(1,1),'ConfirmColor':(2,2),'RedField':(5,5),'GreenField':(6,6),'BlueField':(7,7)},
        })
        plan={'options':opt,'image':Image.new('RGBA',(10,1)),'fitted':(50,10),'groups':[[(0,0,9,0)]],
              'execution_groups':None,'execution_sequence':[],'count':1,'colors':((0,0,0),),
              'color_selectors':({'kind':'palette','palette_index':0,'rgb':(0,0,0)},)}
        execute_plan(plan,(100,100,50,10),[(900,900)],mouse,NoWait(),threading.Event(),lambda *e:events.append(e),keyboard=kb)
        self.assertIn(('write','0'),kb.actions)
        self.assertEqual(cache['000000']['method'],'numeric')
        self.assertTrue(any('Selection verification completed' in str(v) for k,v in events if k=='status'))

    def test_paint_faithful_expands_custom_rgb_budget(self):
        generic=_custom_color_policy(24,'Faithful','Other drawing app',2.5)
        paint=_custom_color_policy(24,'Faithful','Microsoft Paint',2.5)
        self.assertGreater(paint[0],generic[0])
        self.assertLess(paint[1],generic[1])

    def test_paint_faithful_uses_more_custom_selectors(self):
        # 16 distinct colors, deliberately far from the tiny fallback palette.
        data=[]
        for i in range(16):
            data.extend([((25+i*13)%256,(80+i*29)%256,(150+i*41)%256)]*8)
        im=Image.new('RGB',(32,4)); im.putdata(data)
        palette=((0,0,0),(255,255,255),(255,0,0),(0,0,255))
        _,_,generic,gm=build_dynamic_color_strokes(im,palette,max_colors=16,skip_white=False,exact_available=True,color_fidelity='Faithful',profile_name='Other drawing app')
        _,_,paint,pm=build_dynamic_color_strokes(im,palette,max_colors=16,skip_white=False,exact_available=True,color_fidelity='Faithful',profile_name='Microsoft Paint')
        self.assertGreater(sum(s['kind']=='custom' for s in paint),sum(s['kind']=='custom' for s in generic))
        self.assertEqual(pm['custom_color_profile_policy'],'paint-faithful-expanded')
        self.assertLess(pm['custom_color_threshold_deltae2000'],gm['custom_color_threshold_deltae2000'])


    def test_active_swatch_mismatch_recovers_before_canvas_probe(self):
        class SwatchMouse(RecoveryMouse):
            def __init__(self):
                super().__init__([{'matched':True,'actual':(0,0,0),'error':0,'confidence':100,'sample_count':10,'reason':''}])
                self.swatches=[(207,207,207),(0,0,0)]
            def calibrated_modal_color(self,p): return self.swatches.pop(0)
        mouse=SwatchMouse(); kb=Keyboard(); events=[]
        opt=options(); opt.update({
            'profile_name':'Microsoft Paint','profile_key':'microsoft-paint','adaptive_color_verification':True,
            'strict_color_verification':True,'color_session_cache':{},'paint_tool':'Pencil','effective_paint_tool':'Pencil',
            'brush_px':1,'color_order':[0],
            'exact_color_actions':{'OpenCustomColor':(1,1),'ConfirmColor':(2,2),'RedField':(5,5),'GreenField':(6,6),'BlueField':(7,7),'ActiveColorPreview':(9,9)},
        })
        plan={'options':opt,'image':Image.new('RGBA',(10,1)),'fitted':(50,10),'groups':[[(0,0,9,0)]],
              'execution_groups':None,'execution_sequence':[],'count':1,'colors':((0,0,0),),
              'color_selectors':({'kind':'palette','palette_index':0,'rgb':(0,0,0)},)}
        execute_plan(plan,(100,100,50,10),[(900,900)],mouse,NoWait(),threading.Event(),lambda *e:events.append(e),keyboard=kb)
        self.assertIn(('write','0'),kb.actions)
        self.assertEqual(len(mouse.results),0)
        self.assertTrue(any('before any stroke' in str(v) for k,v in events if k=='status'))

    def test_version(self):
        from Version import APP_VERSION, FILE_VERSION
        self.assertEqual(APP_VERSION,'1.0.146-rc1'); self.assertEqual(FILE_VERSION,'1.0.146')

if __name__=='__main__': unittest.main()
