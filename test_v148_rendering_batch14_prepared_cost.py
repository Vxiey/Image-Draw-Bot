"""Immutable cursor repricing preserves the calibrated model and scheduler."""
from contextlib import closing
import copy
import random
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import ExecutionCostModel as costs
import PixelStrokeEngine as strokes
from DrawBot import make_plan
from test_pixel_accurate_v1086 import opts
from test_v148_rendering_batch06_canvas import close_plan


def components_fixture(count=90):
    result=[]
    for cid in range(count):
        x=(cid%15)*12;y=(cid//15)*16
        path=tuple((x+(7 if row%2 else 0),y+row//2) for row in range(18))
        result.append(strokes.Component(cid,cid%3,area=64,bbox=(x,y,x+7,y+8),
            importance_mean=.3+(cid%7)*.03,importance_max=.5+(cid%5)*.04,
            phase=strokes.PHASES[(cid//25)%4],paths=[path]))
    return result


class PreparedCursorCostTests(unittest.TestCase):
    def test_all_breakdown_fields_remain_exact_across_geometry_and_calibration(self):
        rng=random.Random(1481403)
        paths=[(),((5,-2),),((3,4),(3,4)),((0,0),(20,0)),
               ((0,0),(40,20)),((0,0),(8,0),(8,5),(0,0)),
               tuple((rng.randrange(-30,50),rng.randrange(-30,50)) for _ in range(35))]
        cursors=(None,(-10000,10000),(0,0),(5,-2),(.125,-.25))
        for precision in ('Normal','High','Ultra'):
            for sx,sy in ((1,1),(.35,.8),(2.6,1.25)):
                for calibration in ({},{'samples':1,'ratio':1.7},
                        {'samples':5,'ratio':2.3,'operation_runtime':{
                            'dot':{'average_seconds':.07},'short_stroke':{'average_seconds':.12},
                            'long_stroke':{'average_seconds':.45},'outline':{'average_seconds':.62}}}):
                    model=costs.ExecutionCostModel(dict(precision=precision,delay=.007,
                        _execution_scale_x=sx,_execution_scale_y=sy,
                        _execution_cost_calibration_override=calibration),(100,100),(100,100))
                    for path in paths:
                        prepared=model.prepare_path_cost(path,brush_px=4)
                        for cursor in cursors:
                            with self.subTest(precision=precision,scale=(sx,sy),path=path,cursor=cursor):
                                expected=model.path_cost(path,cursor=cursor,brush_px=4)
                                self.assertEqual(prepared.cost(cursor=cursor),expected)
                                self.assertEqual(prepared.seconds(cursor=cursor),expected.total_seconds)

    def test_snapshot_owns_no_mutable_path_or_model_state_and_fresh_calls_observe_changes(self):
        model=costs.ExecutionCostModel({'_execution_cost_calibration_override':{}},(40,40),(40,40))
        path=[(0,0),(12,0),(12,3)]
        prepared=model.prepare_path_cost(path)
        expected=prepared.cost(cursor=(5,5))
        path[1]=(200,200);model.multiplier=3.0;model.sx=2.0
        self.assertEqual(prepared.cost(cursor=(5,5)),expected)
        changed=model.prepare_path_cost(path)
        self.assertEqual(changed.cost(cursor=(5,5)),model.path_cost(path,cursor=(5,5)))
        self.assertNotEqual(changed.cost(cursor=(5,5)),expected)
        self.assertFalse(any(value is path or value is model for value in vars(prepared).values()))

    def test_complete_scheduler_result_is_unchanged_with_bounded_geometry_work(self):
        components=components_fixture()
        original=copy.deepcopy(components)
        model=costs.ExecutionCostModel({'_execution_cost_calibration_override':{}},(200,120),(200,120))
        with patch.object(model,'prepare_path_cost',None),patch.object(model,'path_cost',wraps=model.path_cost) as slow:
            expected=strokes.schedule_components(components,3,cost_model=model)
            original_calls=slow.call_count
        with patch.object(model,'path_cost',wraps=model.path_cost) as fast:
            actual=strokes.schedule_components(components,3,cost_model=model)
            current_calls=fast.call_count
        self.assertEqual(actual,expected)
        self.assertEqual(components,original)
        self.assertGreater(original_calls,10*len(components))
        self.assertLessEqual(current_calls,3*len(components))

    def test_stop_during_preparation_or_final_sequence_pricing_is_propagated(self):
        model=costs.ExecutionCostModel({'_execution_cost_calibration_override':{}},(200,120),(200,120))
        with self.assertRaises(InterruptedError):
            model.prepare_path_cost(((0,0),(8,0)),cancelled=lambda:True)
        components=components_fixture(6)
        with patch.object(model,'prepare_path_cost',side_effect=InterruptedError),self.assertRaises(InterruptedError):
            strokes.schedule_components(components,3,cost_model=model)
        with patch.object(model,'sequence_cost',side_effect=InterruptedError),self.assertRaises(InterruptedError):
            strokes.schedule_components(components,3,cost_model=model)

    def test_real_public_pixel_plan_keeps_sequence_costs_and_all_preview_pixels(self):
        with closing(Image.new('RGB',(84,56),'white')) as source:
            draw=ImageDraw.Draw(source)
            for y in range(5,48,10):
                for x in range(5,76,12):
                    draw.rectangle((x,y,x+5,y+4),fill=('black','red','blue')[(x//12+y//10)%3])
            settings=opts(render_preset='Manual',time_budget_mode='Unlimited',unlimited_time=True,
                skip_white=True,detail_zoom='Off',cpu_workers_resolved=1,
                _execution_cost_calibration_override={})
            with patch('DrawTimeCalibration.load_profile',return_value=None):
                with patch.object(costs.ExecutionCostModel,'prepare_path_cost',None):
                    before=make_plan(source,source.size,dict(settings))
                try:
                    after=make_plan(source,source.size,dict(settings))
                    try:
                        for key in ('groups','execution_groups','execution_sequence','colors','fitted','estimate','path_stats','count'):
                            self.assertEqual(after[key],before[key],key)
                        self.assertEqual(after['options']['pixel_accuracy_meta'],before['options']['pixel_accuracy_meta'])
                        for key in before['ui_previews']:
                            np.testing.assert_array_equal(np.asarray(after['ui_previews'][key]),np.asarray(before['ui_previews'][key]))
                    finally:close_plan(after,source)
                finally:close_plan(before,source)


if __name__=='__main__':
    unittest.main()
