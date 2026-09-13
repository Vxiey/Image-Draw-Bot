\
import unittest
from pathlib import Path
from unittest.mock import patch

from RegionFillEngine import _legacy_region_cost,_seal_cost_seconds
from ExecutionCostModel import build_cost_model
from Version import APP_VERSION


def region():
    return {'color_index':1,'row_spans':[(y,2,18) for y in range(3,14)],
            'contour':[(2,3),(18,3),(18,13),(2,13),(2,3)],
            'perimeter_pixels':52,'area_pixels':187,'bbox_density':1.0,
            'fill_seal_paths':[((4,4),(4,8)),((10,5),(14,5))]}


class Rc21CostModelCleanupTests(unittest.TestCase):
    def test_region_fill_source_has_no_live_hybrid_import(self):
        src=Path('RegionFillEngine.py').read_text(encoding='utf-8')
        self.assertNotIn('from HybridCostModel import build_cost_model',src)
        self.assertIn('from ExecutionCostModel import build_cost_model',src)

    def test_legacy_fallback_is_calibration_free_and_positive(self):
        opts={'speed':'Balanced','delay':.004,'brush_px':2}
        with patch('DrawTimeCalibration.correction_for',side_effect=AssertionError('fallback must not read calibration')):
            stroke,fill=_legacy_region_cost(region(),opts,(40,30),(400,300))
        self.assertGreater(stroke,0);self.assertGreater(fill,0)

    def test_seal_cost_matches_shared_model_paths(self):
        r=region();opts={'speed':'Balanced','delay':.004,'brush_px':2,'_hybrid_scale_x':10.0,'_hybrid_scale_y':10.0}
        measured=_seal_cost_seconds(r['fill_seal_paths'],opts,(40,30),(400,300))
        model=build_cost_model(opts,(40,30),(400,300))
        expected=model.paths_seconds(r['fill_seal_paths'])
        self.assertAlmostEqual(measured,expected,places=9)

    def test_benchmark_uses_shared_sequence_cost(self):
        src=Path('benchmark_engine.py').read_text(encoding='utf-8')
        self.assertIn('from ExecutionCostModel import build_cost_model',src)
        self.assertIn('model.sequence_cost(',src)
        self.assertNotIn('from HybridCostModel import build_cost_model',src)

    def test_version(self):self.assertEqual(APP_VERSION,'1.0.145-rc29')


if __name__=='__main__':unittest.main()
