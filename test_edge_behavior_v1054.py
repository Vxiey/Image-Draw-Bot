import threading
import unittest
from PIL import Image

from CanvasGuard import CanvasGuard, point_in_polygon
from DrawBot import execute_plan
from EdgeBehavior import (EDGE_BEHAVIOR_MODES, apply_edge_behavior, resolve_edge_behavior,
                          validate_edge_behavior)
from ProfileEngine import resolve_profile_policy
from Version import APP_VERSION, FILE_VERSION


class Stop:
    def is_set(self): return False
    def wait(self, seconds): return False


class Mouse:
    def __init__(self):
        self.position=(0,0);self.held=False;self.actions=[]
    def get_position(self): return self.position
    def move(self,x,y):
        self.position=(int(x),int(y));self.actions.append(('move',int(x),int(y)))
    def click(self): self.actions.append(('click',))
    def press(self): self.held=True;self.actions.append(('press',))
    def release(self): self.held=False;self.actions.append(('release',))


def plan_with_group(group, edge_behavior='Hard Clip'):
    return {
        'image': Image.new('RGBA',(10,10),'black'),
        'fitted': (20,20),
        'groups': [group],
        'execution_groups': None,
        'execution_sequence': [],
        'count': len(group),
        'options': {'delay':0,'max_seconds':30,'precision':'Normal','speed':'Fast','brush_px':3,
                    'paint_current_color':False,'strict_color_verification':False,
                    'edge_behavior':edge_behavior,'outline':False},
        'colors': ((0,0,0),),
        'color_selectors': ({'kind':'palette','palette_index':0},),
    }


class EdgeBehaviorV1054Tests(unittest.TestCase):
    def test_version_bumped(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_modes_validate(self):
        for value in EDGE_BEHAVIOR_MODES:
            self.assertEqual(validate_edge_behavior(value), value)
        with self.assertRaises(ValueError): validate_edge_behavior('AI Edge')

    def test_auto_resolves_safely_by_profile(self):
        self.assertEqual(resolve_edge_behavior('Auto', profile_name='Microsoft Paint'), 'Adaptive Clip')
        self.assertEqual(resolve_edge_behavior('Auto', profile_name='Skribbl.io Fast'), 'Hard Clip')
        self.assertEqual(resolve_edge_behavior('Auto', outline=True), 'Preserve Outline')

    def test_profile_policy_sets_edge_behavior(self):
        base={'edge_behavior':'Auto'}
        paint,_=resolve_profile_policy('Microsoft Paint',base,mode='Auto')
        fast,_=resolve_profile_policy('Skribbl.io Fast',base,mode='Auto')
        self.assertEqual(paint['edge_behavior'],'Adaptive Clip')
        self.assertEqual(fast['edge_behavior'],'Hard Clip')

    def test_hard_clip_keeps_step7_edge_skip(self):
        guard=CanvasGuard.from_area((100,100,20,20),brush_px=3,edge_margin_px=2)
        result=apply_edge_behavior(guard, ((100,100),(119,100)), behavior='Hard Clip')
        self.assertEqual(result.subpaths, ())
        self.assertEqual(result.strategy, 'hard_skip')

    def test_adaptive_clip_can_follow_safe_inset_edge(self):
        guard=CanvasGuard.from_area((100,100,20,20),brush_px=3,edge_margin_px=2)
        result=apply_edge_behavior(guard, ((100,100),(119,100)), behavior='Adaptive Clip')
        self.assertEqual(result.strategy, 'adaptive_boundary')
        self.assertTrue(result.subpaths)
        for path in result.subpaths:
            for point in path:
                self.assertTrue(point_in_polygon(point, guard.model.safe_polygon), (point, guard.model.safe_polygon))

    def test_preserve_outline_can_follow_safe_inset_edge(self):
        guard=CanvasGuard.from_area((100,100,20,20),brush_px=3,edge_margin_px=2)
        result=apply_edge_behavior(guard, ((100,119),(119,119)), behavior='Preserve Outline')
        self.assertEqual(result.strategy, 'preserve_outline_boundary')
        self.assertTrue(result.subpaths)

    def test_execute_plan_uses_adaptive_edge_behavior(self):
        plan=plan_with_group([(0,0,9,0)], edge_behavior='Adaptive Clip')
        mouse=Mouse();events=[]
        execute_plan(plan,(100,100,20,20),[(10,10)],mouse,Stop(),threading.Event(),lambda *e: events.append(e),dry_run=True)
        drawing_moves=[a for a in mouse.actions if a[0]=='move' and a[1]>=100 and a[2]>=100]
        self.assertTrue(drawing_moves)
        meta=plan['options']['edge_behavior_meta']
        self.assertEqual(meta['mode'],'Adaptive Clip')
        self.assertGreaterEqual(meta.get('adaptive_boundary',0),1)


if __name__=='__main__':unittest.main()
