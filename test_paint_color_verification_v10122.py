import unittest, tempfile
from Version import APP_VERSION, FILE_VERSION
from pathlib import Path
from PaintColorVerifier import verify_paint_color
from AdaptiveColor import method_candidates
import ColorCache

class PaintColorVerificationV10122Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2');self.assertEqual(FILE_VERSION,'1.0.146')

    def test_exact_color_is_accepted(self):
        r=verify_paint_color((132,97,54),(132,97,54))
        self.assertTrue(r.accepted);self.assertFalse(r.retry_recommended);self.assertAlmostEqual(r.delta_e2000,0.0)

    def test_small_drift_can_be_accepted(self):
        r=verify_paint_color((132,97,54),(131,98,55))
        self.assertTrue(r.accepted)

    def test_wrong_color_is_rejected(self):
        r=verify_paint_color((0,0,0),(207,207,207),context='rendered')
        self.assertFalse(r.accepted);self.assertTrue(r.fallback_required)

    def test_paint_palette_mismatch_can_recover_with_numeric_exact(self):
        actions={'OpenCustomColor':(1,1),'ConfirmColor':(2,2),'RedField':(3,3),'GreenField':(4,4),'BlueField':(5,5)}
        methods=method_candidates({'kind':'palette','palette_index':0,'rgb':(0,0,0)},actions,
                                  allow_exact_palette_recovery=True,keyboard_available=True)
        self.assertEqual(methods[:2],('palette','numeric'))

    def test_palette_behavior_unchanged_without_recovery_flag(self):
        self.assertEqual(method_candidates({'kind':'palette','palette_index':0,'rgb':(0,0,0)},{}),('palette',))

    def test_verified_cache_is_profile_isolated(self):
        old=ColorCache.cache_path
        with tempfile.TemporaryDirectory() as d:
            ColorCache.cache_path=lambda profile: Path(d)/f'{profile}.json'
            try:
                ColorCache.put_verified('microsoft-paint',(10,20,30),(10,20,30),delta_e2000=0,method='numeric')
                self.assertIn('0A141E',ColorCache.load_cache('microsoft-paint'))
                self.assertEqual(ColorCache.load_cache('gartic-phone'),{})
            finally:ColorCache.cache_path=old

if __name__=='__main__':unittest.main()
