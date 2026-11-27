import unittest
from unittest.mock import patch
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
    def test_detail_zooms_rank_only_actual_protected_errors_after_the_last_accepted_pass(self):
        # White is a drawable target in the third component. Even where the
        # untouched canvas matches its color, the missing coverage is real.
        pixel_map=pm([[1,1,-1,1,1,-1,0,0,0,-1,2,2,-1,1,1]],
                     protected=[[False,True,False,False,False,False,False,True,False,
                                 False,True,False,False,True,False]])
        sequence=[e(1,((0,0),)),e(2,((1,0),)),e(2,((11,0),)),e(1,((13,0),(14,0)))]
        skipped=refine_with_corrections(pixel_map,sequence,PALETTE,max_passes=0)
        metadata=skipped['metadata']['region_accuracy']
        zooms=metadata['preview_detail_regions']
        self.assertEqual(zooms['size'],(15,1))
        self.assertEqual([r['component_id'] for r in zooms['regions']],[3,0,2])
        for r,bounds,missing,wrong in zip(zooms['regions'],
                ((10,0,11,1),(1,0,2,1),(7,0,8,1)),(1,0,3),(0,1,0)):
            self.assertEqual(r['bbox'],bounds)
            self.assertEqual((r['missing_pixels'],r['wrong_color_pixels'],r['error_pixels']),
                             (missing,wrong,missing+wrong))
            self.assertEqual(r['protected_error_pixels'],1)
        self.assertEqual(metadata['region_count'],5)
        # A very small legacy result cap cannot hide critical detail zooms.
        self.assertEqual(region_accuracy_scores(pixel_map,skipped['simulation'],max_regions=1)
                         ['preview_detail_regions'],zooms)
        fixed=refine_with_corrections(pixel_map,sequence,PALETTE,max_passes=2)
        self.assertGreater(fixed['metadata']['correction_passes_accepted'],0)
        self.assertEqual(fixed['metadata']['region_accuracy']['preview_detail_regions']['regions'],[])

    def test_region_scores_find_worst_missing_component(self):
        pixel_map=pm([[1,1,-1,2,2]])
        sim=simulate_strokes(pixel_map,[e(1,((0,0),(1,0)))],PALETTE,brush_px=1)
        meta=region_accuracy_scores(pixel_map,sim)
        self.assertEqual(meta['region_count'],2)
        self.assertLess(meta['minimum_score'],meta['weighted_score'])
        self.assertEqual(meta['worst_regions'][0]['color_index'],2)
        self.assertGreater(meta['worst_regions'][0]['error_pixels'],0)

    def test_detail_view_allocation_failure_preserves_the_region_measurement(self):
        pixel_map=pm([[1,1]],protected=[[True,True]])
        sim=simulate_strokes(pixel_map,[],PALETTE,brush_px=1)
        with patch('PixelAccuracyEngine._rank_detail_zooms',side_effect=MemoryError):
            measured=region_accuracy_scores(pixel_map,sim)
        self.assertEqual(measured['worst_regions'][0]['error_pixels'],2)
        zooms=measured['preview_detail_regions']
        self.assertEqual(zooms['regions'],[])
        self.assertIn('unavailable',zooms)
        with patch('PixelAccuracyEngine._rank_detail_zooms',side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):
                region_accuracy_scores(pixel_map,sim)

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

    def test_version(self):self.assertEqual(APP_VERSION,'1.0.148')

if __name__=='__main__':unittest.main()
