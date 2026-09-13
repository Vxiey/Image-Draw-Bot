\
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from ExecutionCostModel import build_cost_model,EXECUTION_MODEL_VERSION
from ExtraFast2 import build_fast_paths
from Version import APP_VERSION


class Rc19ExtraFastExecutionCostTests(unittest.TestCase):
    def test_scale_override_is_authoritative(self):
        model=build_cost_model({'_hybrid_scale_x':4.0,'_hybrid_scale_y':2.5,'delay':.004},(1,1),(1,1))
        self.assertAlmostEqual(model.scale_x,4.0);self.assertAlmostEqual(model.scale_y,2.5)
        self.assertEqual(model.model_version,EXECUTION_MODEL_VERSION)

    def test_compatibility_api_delegates_to_stateful_path_cost(self):
        model=build_cost_model({'delay':.004,'brush_px':2},(100,100),(500,500))
        paths=[((0,0),(20,0)),((20,0),(20,20))]
        stateful=model.paths_seconds(paths)
        manual=model.path_seconds(paths[0])+model.path_seconds(paths[1],cursor=paths[0][-1])
        self.assertAlmostEqual(stateful,manual,places=9)
        self.assertGreater(model.draw_seconds_per_px,0);self.assertGreater(model.path_fixed_seconds,0)
        self.assertEqual(model.as_dict()['model'],'ExecutionCostModel')

    def test_extra_fast_reports_shared_model_and_scale(self):
        group=[(x,2,x,60) for x in range(2,60)]
        paths,meta=build_fast_paths([group],{'_hybrid_scale_x':3.0,'_hybrid_scale_y':2.0})
        self.assertTrue(paths[0]);self.assertEqual(meta['execution_cost_model'],'ExecutionCostModel stateful v3')
        self.assertEqual(meta['execution_scale'],[3.0,2.0])
        self.assertLessEqual(meta['ordered_cost_after_seconds'],meta['ordered_cost_before_seconds']+1e-9)

    def test_downstream_guard_still_rejects_slower_candidate(self):
        group=[(10,y,390,y) for y in range(10,350)]
        row={'target_cap_applied':False,'stroke_optimizer_effective':'Travel only'}
        with patch('ExtraFast2._downstream_plan_cost',side_effect=[(1.0,row),(2.0,row)]):
            _paths,meta=build_fast_paths([group],{})
        self.assertFalse(meta['downstream_plan_accepted'])
        self.assertEqual(meta['ordered_cost_after_seconds'],meta['ordered_cost_before_seconds'])

    def test_version(self):self.assertEqual(APP_VERSION,'1.0.146-rc1')


if __name__=='__main__':unittest.main()
