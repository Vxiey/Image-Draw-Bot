import tempfile
import unittest
from pathlib import Path

from DrawTimeCalibration import record_sample, correction_for
from Version import APP_VERSION, FILE_VERSION


class DrawTimeCalibrationV10117Tests(unittest.TestCase):
    def options(self):
        return {'profile_key':'gartic-phone','speed':'Fast','precision':'Normal','use_region_fill_engine':True}

    def test_completed_draw_teaches_underestimate_ratio(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'time.json'
            first=record_sample(self.options(),100.0,150.0,completed_paths=500,fill_actions=12,path=path)
            self.assertTrue(first['recorded'])
            cal=correction_for(self.options(),path=path)
            self.assertTrue(cal['learned'])
            self.assertAlmostEqual(cal['ratio'],1.5,places=3)
            second=record_sample(self.options(),120.0,156.0,completed_paths=600,fill_actions=8,path=path)
            self.assertTrue(second['recorded'])
            cal2=correction_for(self.options(),path=path)
            self.assertGreater(cal2['ratio'],1.25)
            self.assertLess(cal2['ratio'],1.5)

    def test_test_run_is_not_learned(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'time.json'
            opts=dict(self.options(),test_run=True)
            result=record_sample(opts,100,150,path=path)
            self.assertFalse(result['recorded'])

    def test_release_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')


if __name__ == '__main__':
    unittest.main()
