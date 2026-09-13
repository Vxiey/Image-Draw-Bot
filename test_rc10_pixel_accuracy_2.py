import unittest
import numpy as np
from PixelAccuratePlanner import PixelMap
from PixelAccuracyEngine import simulate_strokes,refine_with_corrections,region_accuracy_scores
from Version import APP_VERSION

PALETTE=((255,255,255),(0,0,0),(255,0,0))

def pm(index,protected=None,edges=None):
    idx=np.asarray(index,dtype=np.int16);h,w=idx.shape;drawable=idx>=0
    safe=np.where(drawable,idx,0).astype(np.int16);rgb=np.zeros((h,w,3),np.uint8)
    if protected is None:protected=np.zeros((h,w),bool)
    if edges is None:edges=np.where(drawable,.1,0).astype(np.float32)
    importance=np.where(drawable,.3,0).astype(np.float32)
    return PixelMap(w,h,rgb,safe,drawable,np.asarray(edges,np.float32),importance,np.asarray(protected,bool),{})

def e(color,path):return {'color_index':color,'path':tuple(path),'phase':'fine_detail','serial':0,'component_id':0}

class Rc10PixelAccuracy2Tests(unittest.TestCase):
    def test_region_scores_find_worst_missing_component(self):
        pixel_map=pm([[1,1,-1,2,2]])
        sim=simulate_strokes(pixel_map,[e(1,((0,0),(1,0)))],PALETTE,brush_px=1)
        meta=region_accuracy_scores(pixel_map,sim)
        self.assertEqual(meta['region_count'],2)
        self.assertLess(meta['minimum_score'],meta['weighted_score'])
        self.assertEqual(meta['worst_regions'][0]['color_index'],2)
        self.assertGreater(meta['worst_regions'][0]['error_pixels'],0)

    def test_correction_pass_reports_marginal_gain(self):
        pixel_map=pm([[1,1,1,1]])
        result=refine_with_corrections(pixel_map,[e(1,((0,0),(1,0)))],PALETTE,brush_px=1,max_passes=2)
        self.assertTrue(result['metadata']['passes'])
        row=result['metadata']['passes'][0]
        for key in ('accuracy_gain','accuracy_gain_per_path','errors_repaired','repaired_pixels_per_path','stop_reason'):
            self.assertIn(key,row)
        self.assertEqual(result['metadata']['region_accuracy']['region_count'],1)

    def test_region_score_weights_protected_detail(self):
        protected=np.array([[False,True]],bool);edges=np.array([[.1,.9]],np.float32)
        pixel_map=pm([[1,1]],protected=protected,edges=edges)
        sim=simulate_strokes(pixel_map,[e(1,((0,0),))],PALETTE,brush_px=1)
        row=region_accuracy_scores(pixel_map,sim)['worst_regions'][0]
        self.assertLess(row['protected_detail_percent'],100.0)
        self.assertLess(row['edge_accuracy_percent'],100.0)

    def test_version(self):self.assertEqual(APP_VERSION,'1.0.145-rc29')

if __name__=='__main__':unittest.main()
