import unittest
from Version import APP_VERSION, FILE_VERSION
import numpy as np
from ExactColorEngine import analyze_region_pixels, score_candidate, best_candidate
from ColorFidelity import delta_e2000, mapping_pair_metrics
from ColorPreviewDiagnostics import fidelity_rating, should_auto_remap
from ShadowToneMapper import shadow_candidate_cost

class ExactColorEngineV10122Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1');self.assertEqual(FILE_VERSION,'1.0.146')

    def test_deltae2000_identity_and_ordering(self):
        self.assertAlmostEqual(delta_e2000((120,90,200),(120,90,200)),0.0,places=7)
        self.assertLess(delta_e2000((120,90,200),(122,91,198)),delta_e2000((120,90,200),(20,220,40)))

    def test_region_statistics_keep_dominant_flat_color(self):
        px=np.array([[120,90,200]]*20+[[121,90,200]]*2,dtype=np.uint8)
        stats=analyze_region_pixels(px,importance_score=.8)
        self.assertEqual(stats.representative_rgb,(120,90,200))
        self.assertGreater(stats.dominant_fraction,.8)

    def test_faithful_penalizes_unnecessary_darkening(self):
        src=(220,170,120)
        light=(220,165,118); dark=(170,130,100)
        self.assertLess(score_candidate(src,light,fidelity='Faithful').total_cost,
                        score_candidate(src,dark,fidelity='Faithful').total_cost)

    def test_best_candidate_uses_perceptual_cost(self):
        idx,score=best_candidate((230,180,130),[(180,140,100),(228,178,132)],fidelity='Faithful',importance=1.0)
        self.assertEqual(idx,1);self.assertLess(score.delta_e2000,5)

    def test_preview_rating_and_remap_threshold(self):
        self.assertEqual(fidelity_rating(average_delta_e2000=1.5,luminance_drift_percent=2,max_delta_e2000=6),'Excellent')
        self.assertTrue(should_auto_remap({'average_delta_e2000':9,'luminance_drift_percent':3,'dark_bias_detected':False}))

    def test_mapping_metrics_include_deltae2000(self):
        meta=mapping_pair_metrics((200,100,50),(190,95,48))
        self.assertIn('delta_e2000',meta);self.assertIn('hue_error',meta)

    def test_shadow_cost_avoids_crushing_mid_shadow_to_black(self):
        src=(75,65,60)
        self.assertLess(shadow_candidate_cost(src,(70,61,57)),shadow_candidate_cost(src,(0,0,0)))

if __name__=='__main__':unittest.main()
