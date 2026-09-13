\
import unittest
from unittest import mock

from DrawTimeEstimate import _sequence_operation_estimate, estimate_from_plan
from ExecutionCostModel import build_cost_model
from Version import APP_VERSION


def options():
    return {'delay':0.006,'speed':'Balanced','brush_px':2,'paint_current_color':False,
            'profile_key':'gartic','fill_tool_available':True,'fill_tool_actions':[],
            'fill_restore_actions':[],'draw_quality':'Balanced'}


def plan(sequence, **extra):
    p={'execution_sequence':sequence,'options':options(),'image':type('I',(),{'size':(100,100)})(),
       'fitted':(500,500),'plan_area':(100,100),'preview_area':(100,100),'target_area':(100,100),
       'estimate':1.0,'count':len(sequence),'path_stats':{}}
    p.update(extra);return p


class Rc17UnifiedExecutionCostEtaTests(unittest.TestCase):
    def test_execution_cost_override_bypasses_learned_profile(self):
        learned={'samples':20,'ratio':4.0,'operation_runtime':{'dot':{'average_seconds':2.0}}}
        with mock.patch('ExecutionCostModel.correction_for',return_value=learned):
            normal=build_cost_model(options(),(100,100),(500,500))
            cold_opts=options();cold_opts['_execution_cost_calibration_override']={'samples':0,'ratio':1.0,'operation_runtime':{}}
            cold=build_cost_model(cold_opts,(100,100),(500,500))
        self.assertGreater(normal.samples,0);self.assertEqual(cold.samples,0);self.assertEqual(cold.multiplier,1.0)
        self.assertLess(cold.path_cost(((5,5),)).total_seconds,normal.path_cost(((5,5),)).total_seconds)

    def test_eta_uses_shared_stateful_execution_cost_model(self):
        seq=[{'color_index':0,'brush_px':2,'path':((1,1),(20,1))},
             {'color_index':1,'brush_px':8,'path':((20,1),(20,20))}]
        seconds,meta=_sequence_operation_estimate(plan(seq))
        self.assertGreater(seconds,0);self.assertEqual(meta['execution_cost_model'],'ExecutionCostModel')
        self.assertEqual(meta['color_changes'],2);self.assertEqual(meta['brush_changes'],1)
        self.assertIn('sequence_seconds',meta);self.assertIn('breakdown',meta)

    def test_cursor_travel_changes_visible_base_cost(self):
        near=[{'color_index':0,'brush_px':2,'path':((1,1),(10,1))},
              {'color_index':0,'brush_px':2,'path':((11,1),(20,1))}]
        far=[{'color_index':0,'brush_px':2,'path':((1,1),(10,1))},
             {'color_index':0,'brush_px':2,'path':((90,90),(99,90))}]
        a,_=_sequence_operation_estimate(plan(near));b,_=_sequence_operation_estimate(plan(far))
        self.assertGreater(b,a)

    def test_fill_eta_reuses_region_fill_batch_estimator(self):
        p=plan([{'color_index':0,'brush_px':2,'path':((1,1),(10,1))}])
        p['options']['fill_regions']=[{'color_index':0,'contour':[(1,1),(5,1),(5,5),(1,5),(1,1)]}]
        with mock.patch('RegionFillEngine.estimate_fill_execution_seconds',return_value={
            'fill_regions':1,'fill_color_batches':1,'total_seconds':7.5,
            'fill_contour_and_click_seconds':6.5,'fill_tool_switch_seconds':1.0}):
            seconds,meta=_sequence_operation_estimate(p)
        self.assertAlmostEqual(meta['fill_seconds'],7.5,places=5)
        self.assertGreater(seconds,7.5);self.assertEqual(meta['fill_actions'],1)

    def test_explicit_ui_operations_are_first_class(self):
        model=build_cost_model({'_execution_cost_calibration_override':{'samples':0,'ratio':1.0,'operation_runtime':{}},**options()},(100,100),(100,100))
        seq=[{'operation_type':'palette_change','color_index':2},
             {'operation_type':'brush_change','brush_px':8},
             {'operation_type':'tool_change'}, {'operation_type':'verification'}, {'operation_type':'fill'}]
        cost=model.sequence_cost(seq)
        self.assertEqual(cost.palette_switches,1);self.assertEqual(cost.brush_switches,1);self.assertEqual(cost.tool_switches,1)
        self.assertGreater(cost.fill_seconds,0);self.assertGreater(cost.verification_seconds,0)

    def test_visible_estimate_exports_shared_model_metadata(self):
        seq=[{'color_index':0,'brush_px':2,'path':((1,1),(20,1))}]
        meta=estimate_from_plan(plan(seq))
        self.assertFalse(meta['is_projection'])
        self.assertEqual(meta['sequence_operation_model']['execution_cost_model'],'ExecutionCostModel')

    def test_version(self):self.assertEqual(APP_VERSION,'1.0.146-rc2')


if __name__=='__main__':unittest.main()
