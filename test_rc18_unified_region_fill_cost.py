\
import unittest
from unittest import mock
from types import SimpleNamespace

from RegionFillEngine import _batchable_tool_cost, _region_cost, evaluate_region_candidates
from Version import APP_VERSION


class FakeModel:
    def __init__(self):self.calls=[]
    def sequence_cost(self,sequence,**kwargs):
        seq=list(sequence);self.calls.append((seq,kwargs))
        # Scanlines contain several entries; one contour is intentionally cheaper.
        return SimpleNamespace(total_seconds=2.0*len(seq) if len(seq)>1 else 1.25)
    def switch_cost(self,kind):
        return {'tool_change':.30,'fill':.20,'verification':.10}.get(kind,.05)


def region():
    return {'color_index':2,'row_spans':[(y,2,10) for y in range(6)],
            'contour':[(2,0),(10,0),(10,5),(2,5),(2,0)],'seed_pixel':(5,2),
            'guard_pixels':[(0,2),(12,2)],'area_pixels':54,'safety_score':.99,
            'bbox_density':1.0,'perimeter_pixels':28}


class Rc18UnifiedRegionFillCostTests(unittest.TestCase):
    def test_region_cost_uses_shared_execution_model(self):
        fake=FakeModel()
        with mock.patch('ExecutionCostModel.build_cost_model',return_value=fake):
            stroke,fill=_region_cost(region(),{'brush_px':4},(20,20),(200,200))
        self.assertAlmostEqual(stroke,12.0);self.assertAlmostEqual(fill,1.85)
        self.assertEqual(fake.calls[0][1]['initial_color'],2)
        self.assertEqual(fake.calls[0][1]['initial_brush'],4)

    def test_batchable_tool_cost_uses_same_model(self):
        with mock.patch('ExecutionCostModel.build_cost_model',return_value=FakeModel()):
            self.assertAlmostEqual(_batchable_tool_cost({'brush_px':2}),.30)

    def test_cost_model_failure_falls_back_without_disabling_fill_engine(self):
        opts={'speed':'Balanced','delay':.003,'brush_px':2}
        with mock.patch('ExecutionCostModel.build_cost_model',side_effect=RuntimeError('no model')):
            stroke,fill=_region_cost(region(),opts,(20,20),(200,200))
        self.assertGreater(stroke,0);self.assertGreater(fill,0)

    def test_safety_gate_still_rejects_thin_neck_before_cost_wins(self):
        thin={'color_index':1,'row_spans':[(y,5,5) for y in range(8)],
              'contour':[(5,0),(5,1),(5,7),(5,6),(5,0)],'seed_pixel':(5,3),
              'guard_pixels':[(3,3),(7,3)],'area_pixels':8,'safety_score':.99,
              'bbox_density':1.0,'perimeter_pixels':16}
        accepted,meta=evaluate_region_candidates([thin],(20,20),(200,200),
            {'speed':'Fast','brush_px':4,'fill_aggressiveness':'Aggressive','fill_tool_available':True})
        self.assertEqual(accepted,[]);self.assertGreaterEqual(meta['rejected_by_safety'],1)

    def test_metadata_reports_shared_cost_policy(self):
        accepted,meta=evaluate_region_candidates([region()],(20,20),(200,200),
            {'speed':'Fast','brush_px':2,'fill_aggressiveness':'Balanced','fill_tool_available':True})
        self.assertEqual(meta['execution_cost_model'],'ExecutionCostModel stateful v2')

    def test_version(self):self.assertEqual(APP_VERSION,'1.0.146-rc1')


if __name__=='__main__':unittest.main()
