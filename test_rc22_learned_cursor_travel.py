\
import unittest
from unittest.mock import patch

from ExecutionCostModel import build_cost_model,EXECUTION_MODEL_VERSION
from Version import APP_VERSION


def opts():
    return {'profile_key':'gartic','speed':'Balanced','delay':.004,'brush_px':2,
            'paint_current_color':False}


def cal(runtime,ratio=1.6,samples=8):
    return {'samples':samples,'ratio':ratio,'operation_runtime':runtime}


class Rc22LearnedCursorTravelTests(unittest.TestCase):
    def test_learned_short_stroke_never_erases_cursor_distance(self):
        learned=cal({'short_stroke':{'average_seconds':.20}})
        with patch('ExecutionCostModel.correction_for',return_value=learned):
            model=build_cost_model(opts(),(100,100),(100,100))
        path=((50,50),(60,50))
        near=model.path_cost(path,cursor=(50,50));far=model.path_cost(path,cursor=(-1000,50))
        self.assertGreater(far.total_seconds,near.total_seconds)
        self.assertGreater(far.travel_seconds,near.travel_seconds)
        self.assertAlmostEqual(near.total_seconds,.20,places=6)

    def test_generic_stroke_runtime_alias_applies_to_short_and_long(self):
        learned=cal({'stroke':{'average_seconds':.31}})
        with patch('ExecutionCostModel.correction_for',return_value=learned):
            model=build_cost_model(opts(),(100,100),(100,100))
        self.assertAlmostEqual(model.path_cost(((0,0),(10,0)),cursor=(0,0)).total_seconds,.31,places=6)
        self.assertAlmostEqual(model.path_cost(((0,0),(80,0)),cursor=(0,0)).total_seconds,.31,places=6)

    def test_dot_runtime_also_preserves_distance(self):
        learned=cal({'dot':{'average_seconds':.12}})
        with patch('ExecutionCostModel.correction_for',return_value=learned):
            model=build_cost_model(opts(),(100,100),(100,100))
        near=model.path_cost(((20,20),),cursor=(20,20))
        far=model.path_cost(((20,20),),cursor=(-1000,20))
        self.assertAlmostEqual(near.total_seconds,.12,places=6)
        self.assertGreater(far.total_seconds,near.total_seconds)

    def test_breakdown_sums_to_total_under_learning(self):
        learned=cal({'stroke':{'average_seconds':.25}})
        with patch('ExecutionCostModel.correction_for',return_value=learned):
            model=build_cost_model(opts(),(100,100),(400,400))
        row=model.path_cost(((5,5),(30,5)),cursor=(0,0))
        summed=row.drag_seconds+row.travel_seconds+row.press_release_seconds+row.target_processing_seconds
        self.assertAlmostEqual(row.total_seconds,summed,places=9)

    def test_cold_path_still_increases_with_distance(self):
        cold={'samples':0,'ratio':1.0,'operation_runtime':{}}
        with patch('ExecutionCostModel.correction_for',return_value=cold):
            model=build_cost_model(opts(),(100,100),(100,100))
        path=((20,20),(40,20))
        self.assertGreater(model.path_seconds(path,cursor=(-1000,20)),model.path_seconds(path,cursor=(20,20)))

    def test_version(self):
        self.assertEqual(EXECUTION_MODEL_VERSION,4)
        self.assertEqual(APP_VERSION,'1.0.146-rc1')


if __name__=='__main__':unittest.main()
