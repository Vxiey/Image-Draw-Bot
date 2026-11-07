"""Bounded source analysis and palette-quality regression oracles."""
import math
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image


class BoundedPaletteSampleTests(unittest.TestCase):
    def test_samples_equal_full_visible_conversion_in_original_order(self):
        from ColorMatchingEngine import visible_rgb_image
        from ImageSampling import visible_samples
        rng=np.random.default_rng(471)
        rgba=Image.fromarray(rng.integers(0,256,(277,531,4),dtype=np.uint8))
        rgb=rgba.convert('RGB')
        keyed=rgb.copy();keyed.info['transparency']=keyed.getpixel((0,0))
        indexed=rgb.quantize(colors=32);indexed.info['transparency']=bytes(range(32))
        gray=rgb.convert('L');gray.info['transparency']=gray.getpixel((0,0))
        indices=np.concatenate(([0,530,531,277*531-1,0],rng.integers(0,277*531,1700)))
        for source in (rgba,rgb,keyed,indexed,gray):
            with self.subTest(mode=source.mode,info=bool(source.info)),visible_rgb_image(source) as complete:
                expected=np.asarray(complete).reshape(-1,3)[indices]
                np.testing.assert_array_equal(visible_samples(source,indices),expected)
                self.assertIsNotNone(source.getpixel((0,0)))
        for source in (rgba,rgb,keyed,indexed,gray):source.close()

    def test_large_source_conversion_is_bounded_by_tile_area(self):
        from ImageSampling import visible_samples
        source=Image.new('RGBA',(4000,3000),(20,30,40,127))
        convert=Image.Image.convert;areas=[]
        def checked(image,*args,**kwargs):
            areas.append(image.width*image.height)
            self.assertLessEqual(areas[-1],65536)
            return convert(image,*args,**kwargs)
        with patch.object(Image.Image,'convert',checked):
            result=visible_samples(source,np.array([0,4000*2999+3999],dtype=np.int64))
        self.assertEqual(result.shape,(2,3));self.assertTrue(areas)
        np.testing.assert_array_equal(result[0],result[1]);source.close()

    def test_cancel_after_last_tile_does_not_publish_samples(self):
        from ImageSampling import visible_samples
        source=Image.new('RGB',(8,8));calls=0
        def stop():
            nonlocal calls
            calls+=1
            return calls>=3
        with self.assertRaises(InterruptedError):visible_samples(source,np.array([0]),cancelled=stop)
        source.close()

    def test_invalid_sample_indexes_fail_before_cropping(self):
        from ImageSampling import visible_samples
        with Image.new('RGB',(2,2)) as source,patch.object(source,'crop',side_effect=AssertionError('crop')):
            for indices in ([-1],[4],[.5],[True],[[1]]):
                with self.subTest(indices=indices),self.assertRaises(ValueError):visible_samples(source,indices)

    def test_refined_palette_matches_original_full_raster_sampling(self):
        import PicturePaletteRefinement as refinement
        from ColorMatchingEngine import visible_rgb_image
        def old_samples(image,indices,**_kwargs):
            with visible_rgb_image(image) as rgb:return np.asarray(rgb).reshape(-1,3)[indices]
        source=Image.fromarray(np.random.default_rng(6).integers(0,256,(160,180,4),dtype=np.uint8))
        seeds=((0,0,0),(255,255,255),(220,20,30),(20,80,220))
        with patch('ImageSampling.visible_samples',old_samples):expected=refinement.refine_picture_palette(source,seeds,10)
        self.assertEqual(refinement.refine_picture_palette(source,seeds,10),expected)
        source.close()

    def test_palette_contract_rejects_wrapped_colors_and_fractional_sizes(self):
        from PicturePaletteRefinement import refine_picture_palette
        with Image.new('RGB',(2,2)) as source:
            for seeds in (((-1,2,3),),((256,2,3),),((1,2),),((True,2,3),),((1.,2,3),)):
                with self.subTest(seeds=seeds),self.assertRaises(ValueError):refine_picture_palette(source,seeds,2)
            for cap in (True,0,-1,1.5,float('inf'),'2'):
                with self.subTest(cap=cap),self.assertRaises(ValueError):refine_picture_palette(source,((0,0,0),),cap)
            self.assertEqual(refine_picture_palette(source,((0,0,0),),np.int64(2)),((0,0,0),))


class AutomaticAnalysisTests(unittest.TestCase):
    @staticmethod
    def original_statistics(image):
        with image.copy() as flat:
            flat.thumbnail((128,128))
            a=np.asarray(flat,dtype=np.int16)
        white=float(np.mean(np.min(a,axis=2)>235));chroma=float(np.mean(a.max(axis=2)-a.min(axis=2)>35))
        bins=(a//32).astype(np.int32);codes=bins[:,:,0]*64+bins[:,:,1]*8+bins[:,:,2]
        hist=np.bincount(codes.ravel(),minlength=512)
        return white,chroma,float(np.sort(hist)[-12:].sum()/hist.sum())

    def test_direct_thumbnail_matches_copy_then_thumbnail(self):
        from AutoDrawing import _image_statistics
        rng=np.random.default_rng(7)
        for w,h in ((4000,3000),(533,277),(1,1001),(1001,1),(127,65),(129,129),(17,11)):
            with self.subTest(size=(w,h)),Image.fromarray(rng.integers(0,256,(h,w,3),dtype=np.uint8)) as source:
                expected=self.original_statistics(source)
                with patch.object(source,'copy',side_effect=AssertionError('full source copy')):
                    self.assertEqual(_image_statistics(source),expected)

    def test_stop_after_statistics_prevents_tuning(self):
        from AutoDrawing import resolve_drawing
        stopped=False
        def stats(image):
            nonlocal stopped
            stopped=True
            return .2,.5,.3
        with Image.new('RGB',(8,8)) as image,patch('AutoDrawing.apply_drawing_style',side_effect=lambda im,options:options),patch('AutoDrawing._image_statistics',stats),patch('EndToEndAutoTuner.tune_options') as tune:
            with self.assertRaises(InterruptedError):resolve_drawing(image,{'render_preset':'Auto','drawing_style':'Auto'},cancelled=lambda:stopped)
            tune.assert_not_called()


class PaletteGroupingTests(unittest.TestCase):
    def test_diagonal_weight_is_covered_raster_length(self):
        from ColorGrouping import group_palette_strokes
        _groups,order,meta=group_palette_strokes([[(0,0,5,5)],[(0,6,7,6)]],((0,0,0),(255,0,0)))
        self.assertEqual(order,[1,0]);self.assertEqual(meta['stroke_weight'],14)

    def test_chain_merge_cannot_exceed_original_color_distance_limit(self):
        from ColorGrouping import group_palette_strokes
        palette=((0,0,0),(30,0,0),(60,0,0),(255,255,255))
        groups=[[(0,i,n-1,i)] for i,n in enumerate((2,4,40,1000))]
        result,_order,meta=group_palette_strokes(groups,palette,'Reduced palette')
        self.assertEqual(meta['merged_colors'],1)
        self.assertEqual(sorted(s for g in result for s in g),sorted(s for g in groups for s in g))
        for target,group in enumerate(result):
            for stroke in group:
                source=stroke[1]
                self.assertLessEqual(sum((a-b)**2 for a,b in zip(palette[source],palette[target])),38**2)

    def test_missing_palette_group_is_a_controlled_error(self):
        from ColorGrouping import group_palette_strokes
        with self.assertRaises(ValueError):group_palette_strokes([[(0,0,0,0)],[(1,0,1,0)]],[(0,0,0)])


class HueSummaryTests(unittest.TestCase):
    def test_streamed_representatives_equal_independent_member_list_oracle(self):
        import DominantHuePreservation as hue
        from ColorFidelity import oklab_metrics
        rng=np.random.default_rng(9);colors=[tuple(map(int,c)) for c in rng.integers(0,256,(1200,3))];weights=rng.integers(1,100,1200).tolist()
        total=sum(weights);buckets={}
        for i,(rgb,weight) in enumerate(zip(colors,weights)):
            family=hue.dominant_hue_family(rgb)
            if family is not None:buckets.setdefault(family,[]).append((i,weight,oklab_metrics(rgb)[1],rgb))
        expected=[]
        for family,members in buckets.items():
            mass=float(sum(x[1] for x in members));coverage=mass/total
            if coverage+1e-12<.035:continue
            i,w,c,rgb=max(members,key=lambda x:(x[1]*(1+min(40,x[2])/160),x[1],x[2],-x[0]))
            expected.append(hue.HueFamilySummary(family,mass,coverage,i,rgb,c))
        expected.sort(key=lambda s:(-s.weight,-s.representative_chroma,s.representative_index,s.family))
        with patch.object(hue,'oklab_metrics',wraps=oklab_metrics) as probe:
            self.assertEqual(hue.summarize_hue_families(colors,weights),expected)
            self.assertEqual(probe.call_count,len(colors))

    def test_invalid_weight_domains_cannot_publish_nan_coverage(self):
        from DominantHuePreservation import summarize_hue_families
        for weights in ([float('inf')],[float('nan')],[-1],[True],['1'],[10**400],[1,2]):
            with self.subTest(weights=weights),self.assertRaises(ValueError):summarize_hue_families([(255,0,0)],weights)
        with self.assertRaises(ValueError):summarize_hue_families([(255,0,0)]*2,[1.5e308,1.5e308])

    def test_zero_capacity_or_mass_does_not_compute_color_metrics(self):
        from DominantHuePreservation import summarize_hue_families
        with patch('DominantHuePreservation.oklab_metrics',side_effect=AssertionError('no color work')):
            self.assertEqual(summarize_hue_families([(255,0,0)],[1],max_families=0),[])
            self.assertEqual(summarize_hue_families([(255,0,0)],[0]),[])

    def test_invalid_cap_or_threshold_is_rejected(self):
        from DominantHuePreservation import summarize_hue_families
        for cap in (True,-1,.5,'2'):
            with self.subTest(cap=cap),self.assertRaises(ValueError):summarize_hue_families([],[],max_families=cap)
        for threshold in (True,-1,float('inf'),float('nan'),'4'):
            with self.subTest(threshold=threshold),self.assertRaises(ValueError):summarize_hue_families([],[],chroma_threshold=threshold)


if __name__=='__main__':unittest.main()
