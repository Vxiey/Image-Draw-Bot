import tempfile
import unittest
from pathlib import Path

from DrawTimeCalibration import record_sample, correction_for
from DrawTimeEstimate import _operation_calibration_adjustment
from Version import APP_VERSION


class Rc12EtaCalibrationTests(unittest.TestCase):
    def options(self):
        return {'profile_key':'gartic-phone','speed':'Fast','precision':'Normal','use_region_fill_engine':True,
                'drawing_mode':'Smart paths (recommended)','draw_quality':'Balanced','render_style':'Standard / pixel'}

    def test_operation_runtime_is_smoothed_across_completed_draws(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'eta.json';opts=self.options()
            a={'stroke':{'count':10,'total_seconds':1.0,'average_seconds':.1}}
            b={'stroke':{'count':10,'total_seconds':2.0,'average_seconds':.2}}
            self.assertTrue(record_sample(opts,10,12,operation_runtime=a,path=path)['recorded'])
            self.assertTrue(record_sample(opts,10,13,operation_runtime=b,path=path)['recorded'])
            cal=correction_for(opts,path=path);row=cal['operation_runtime']['stroke']
            self.assertEqual(cal['operation_runtime_source'],'ema')
            self.assertEqual(row['samples'],2)
            self.assertGreater(row['average_seconds'],.1)
            self.assertLess(row['average_seconds'],.2)

    def test_operation_calibration_can_correct_an_overestimate_downward(self):
        cal={'samples':8,'mape':.04,'operation_runtime_source':'ema',
             'operation_runtime':{'stroke':{'average_seconds':.05,'samples':8}}}
        meta={'operation_counts':{'stroke':100},'operation_model_average_seconds':{'stroke':.10}}
        result=_operation_calibration_adjustment(cal,meta)
        self.assertTrue(result['used'])
        self.assertEqual(result['coverage_percent'],100.0)
        self.assertLess(result['raw_ratio'],1.0)
        self.assertLess(result['applied_ratio'],1.0)

    def test_partial_operation_coverage_has_lower_confidence(self):
        cal={'samples':8,'mape':.04,'operation_runtime_source':'ema',
             'operation_runtime':{'stroke':{'average_seconds':.08,'samples':8}}}
        full={'operation_counts':{'stroke':100},'operation_model_average_seconds':{'stroke':.10}}
        partial={'operation_counts':{'stroke':50,'palette_change':50},
                 'operation_model_average_seconds':{'stroke':.10,'palette_change':.10}}
        a=_operation_calibration_adjustment(cal,full);b=_operation_calibration_adjustment(cal,partial)
        self.assertGreater(a['coverage_percent'],b['coverage_percent'])
        self.assertGreater(a['confidence'],b['confidence'])

    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')

if __name__=='__main__':unittest.main()
