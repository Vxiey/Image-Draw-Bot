import tempfile
import threading
import unittest
from pathlib import Path

from PIL import Image

from AppTools import save_calibration, load_calibration, build_tool_action
from CalibrationAnchors import make_anchor
from CanvasClear import resolve_clear_strategy, eraser_row_spacing, estimate_eraser_sweep_seconds
from DrawBot import make_plan, execute_plan
from test_drawbot import Mouse, NoWait, options


class Keyboard:
    def __init__(self):
        self.actions=[]
    def press_and_release(self, keys):
        self.actions.append(('press_and_release',keys))
    def write(self, value, delay=0):
        self.actions.append(('write',str(value)))


class AutoCanvasClearTests(unittest.TestCase):
    def test_strategy_priority(self):
        self.assertEqual(resolve_clear_strategy(paint_profile=True,keyboard_available=True).strategy,'paint-shortcut')
        self.assertEqual(resolve_clear_strategy(paint_profile=False,tools={'Clear':[1,2]}).strategy,'native-clear')
        self.assertEqual(resolve_clear_strategy(paint_profile=False,tools={'Brush':[1,2],'Eraser':[3,4]}).strategy,'eraser-sweep')
        self.assertEqual(resolve_clear_strategy(paint_profile=False,tools={'Eraser':[3,4]}).strategy,'unavailable')

    def test_clear_control_is_profile_anchored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tools.json'
            anchor=make_anchor((100,100,900,700))
            save_calibration('gartic-phone',{'Brush':(140,150),'Eraser':(170,150),'Clear':(220,150)},anchor=anchor,path=path)
            loaded=load_calibration('gartic-phone',path)
            self.assertIn('Clear',loaded['tools'])
            kind,point=build_tool_action('gartic-phone','Clear',(120,130,920,730),path)
            self.assertEqual(kind,'clear')
            self.assertEqual(point,(240,180))

    def test_eraser_sweep_estimate_scales_with_brush(self):
        self.assertGreaterEqual(eraser_row_spacing(1),1)
        self.assertGreater(eraser_row_spacing(20),eraser_row_spacing(3))
        slow=estimate_eraser_sweep_seconds(900,500,3)
        fast=estimate_eraser_sweep_seconds(900,500,20)
        self.assertGreater(slow,fast)

    def _plan(self, strategy, **extra):
        o=dict(options(),auto_clear_canvas=True,canvas_clear_strategy=strategy,
               canvas_clear_actions=[],canvas_clear_restore_actions=[],canvas_clear_estimate_seconds=.8,
               paint_profile=False,brush_px=6,canvas_guard_brush_px=6)
        o.update(extra)
        return make_plan(Image.new('RGB',(8,4),'black'),(80,40),o)

    def test_planner_execution_estimate_already_includes_clear_once(self):
        without = self._plan('paint-shortcut', paint_profile=True,
                             canvas_clear_estimate_seconds=0)
        with_clear = self._plan('paint-shortcut', paint_profile=True)
        self.assertAlmostEqual(with_clear['estimate'] - without['estimate'], .8)
        self.assertAlmostEqual(with_clear['raw_execution_estimate_seconds'],
                               with_clear['estimate'])
        self.assertAlmostEqual(with_clear['options']['operation_timing_meta']
                               ['canvas_clear_seconds'], .8)

    def test_paint_shortcut_runs_before_full_drawing(self):
        plan=self._plan('paint-shortcut',paint_profile=True)
        mouse=Mouse();kb=Keyboard()
        execute_plan(plan,(100,100,80,40),[(10,i) for i in range(18)],mouse,NoWait(),threading.Event(),lambda *a:None,keyboard=kb)
        self.assertEqual([a[1] for a in kb.actions[:3]],['ctrl+a','delete','esc'])
        self.assertTrue(any(a[0]=='click' for a in mouse.actions))

    def test_small_test_never_clears(self):
        plan=self._plan('paint-shortcut',paint_profile=True,test_run=True)
        mouse=Mouse();kb=Keyboard()
        execute_plan(plan,(100,100,80,40),[(10,i) for i in range(18)],mouse,NoWait(),threading.Event(),lambda *a:None,keyboard=kb)
        self.assertFalse(kb.actions)

    def test_dry_run_sends_no_clear_key_or_click(self):
        plan=self._plan('paint-shortcut',paint_profile=True)
        mouse=Mouse();kb=Keyboard()
        execute_plan(plan,(100,100,80,40),[(10,i) for i in range(18)],mouse,NoWait(),threading.Event(),lambda *a:None,keyboard=kb,dry_run=True)
        self.assertFalse(kb.actions)
        self.assertFalse(any(a[0] in ('click','press') for a in mouse.actions))

    def test_native_clear_clicks_calibrated_control_before_palette(self):
        plan=self._plan('native-clear',canvas_clear_actions=[('clear',(900,100))])
        mouse=Mouse();kb=Keyboard()
        execute_plan(plan,(100,100,80,40),[(10,i) for i in range(18)],mouse,NoWait(),threading.Event(),lambda *a:None,keyboard=kb)
        clear_move=mouse.actions.index(('move',900,100))
        first_click=next(i for i,a in enumerate(mouse.actions) if a[0]=='click')
        self.assertLess(clear_move,first_click)

    def test_eraser_fallback_restores_brush(self):
        plan=self._plan('eraser-sweep',canvas_clear_actions=[('eraser',(900,100))],canvas_clear_restore_actions=[('brush',(920,100))],brush_px=10,canvas_guard_brush_px=10)
        mouse=Mouse();kb=Keyboard();events=[]
        execute_plan(plan,(100,100,80,40),[(10,i) for i in range(18)],mouse,NoWait(),threading.Event(),lambda *a:events.append(a),keyboard=kb)
        self.assertIn(('move',900,100),mouse.actions)
        self.assertIn(('move',920,100),mouse.actions)
        self.assertTrue(any(a[0]=='press' for a in mouse.actions))
        self.assertTrue(any(e[0]=='status' and 'Brush restored' in str(e[1]) for e in events))


if __name__=='__main__':
    unittest.main()
