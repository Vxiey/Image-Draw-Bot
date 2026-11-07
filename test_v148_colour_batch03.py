"""Color/quality regressions for batch03; generated images and pure helpers only."""
from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw


class ColorTextTests(unittest.TestCase):
    def test_hex_channels_never_accept_signs_or_non_ascii_digits(self):
        from Colors import normalize_rgb, argb_to_rgb
        for value in ('#-10000', '#00+F00', '0x-1FF0000', '#FF-10000', '#００FF00', '#red', '#blue'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_rgb(value)
        for value in ('-1FF0000', 'FF-10000', '+1FF0000'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                argb_to_rgb(value)
        self.assertEqual(normalize_rgb('#ff_0000'), (255, 0, 0))
        self.assertEqual(normalize_rgb('#80112233'), (136, 144, 153))
        self.assertEqual(normalize_rgb('sienna'), (160, 82, 45))

    def test_functional_colors_accept_whitespace_before_parenthesis(self):
        from Colors import normalize_rgb
        for value in ('rgb (17,34,51)', 'RGB\t(17,34,51)', 'rgb\n(17,34,51)'):
            with self.subTest(value=value):
                self.assertEqual(normalize_rgb(value), (17, 34, 51))
        self.assertEqual(normalize_rgb('rgba (255,0,0,0.5)'), (255, 127, 127))
        self.assertEqual(normalize_rgb('argb (128,255,0,0)'), (255, 127, 127))


class AccuracyEvidenceTests(unittest.TestCase):
    def test_extra_contours_cannot_keep_perfect_edge_accuracy(self):
        from AccuracyEvaluator import evaluate_preview
        source = Image.new('RGB', (48, 32), 'white')
        ImageDraw.Draw(source).rectangle((5, 5, 12, 13), fill='black')
        drawn = source.copy()
        ImageDraw.Draw(drawn).rectangle((30, 5, 37, 13), fill='black')
        unchanged = evaluate_preview(source, source, gpu_mode='CPU')
        extra = evaluate_preview(source, drawn, gpu_mode='CPU')
        self.assertEqual(unchanged['edge_accuracy_percent'], 100.0)
        self.assertLess(extra['edge_accuracy_percent'], 65.0)
        self.assertGreater(extra['edge_accuracy_percent'], 35.0)

    def test_no_mapping_measurements_are_not_rated_excellent(self):
        from ColorFidelity import finalize_mapping_stats
        result=finalize_mapping_stats({'mapped_pixels':0})
        self.assertEqual(result['color_fidelity_rating'],'Unavailable')
        self.assertIs(result['evaluated'],False)


class RegionMassTests(unittest.TestCase):
    def test_merged_region_coverage_is_additive(self):
        from RegionAwareQuantization import RegionColorStats, _weighted_stats, cluster_region_relation
        row = RegionColorStats(0, 30, .03, 50, 'red', 'midtone', .1, .5, 0., .4, (.5, .5, 0., 0.))
        large = replace(row, qindex=2, pixel_count=940, coverage=.94, importance=.1)
        context = {'stats': {0: row, 1: replace(row, qindex=1), 2: large}, 'grid_size': 2}
        merged = {'items': [{'qindex': 0, 'count': 30}, {'qindex': 1, 'count': 30}]}
        self.assertAlmostEqual(_weighted_stats(merged['items'], context)['coverage'], .06)
        self.assertFalse(cluster_region_relation(merged, {'qindex': 2, 'count': 940}, context)['detail_conflict'])
        self.assertTrue(cluster_region_relation(merged['items'][0], {'qindex': 2, 'count': 940}, context)['detail_conflict'])

    def test_region_context_excludes_ignored_background_and_adjacency(self):
        from RegionAwareQuantization import build_region_context
        labels=Image.fromarray(np.array([[0,0,1]],dtype=np.uint8))
        source=Image.new('RGB',(3,1),'white')
        source.putpixel((0,0),(255,0,0));source.putpixel((2,0),(0,0,255))
        entries=[{'qindex':0,'rgb':(255,0,0),'count':1},{'qindex':1,'rgb':(0,0,255),'count':1}]
        context=build_region_context(source,labels,entries,drawable_mask=np.array([[True,False,True]]))
        self.assertEqual(context['stats'][0].pixel_count,1)
        self.assertEqual(context['stats'][0].coverage,.5)
        self.assertEqual(context['adjacency'],{})


class DynamicSourceMaskTests(unittest.TestCase):
    def test_identical_palette_actions_merge_without_losing_pixels(self):
        from DynamicColors import build_dynamic_color_strokes
        source=Image.new('RGB',(10,1));source.putdata([(255,0,0)]*5+[(0,0,255)]*5)
        groups,colors,selectors,meta=build_dynamic_color_strokes(
            source,[(0,0,0)],max_colors=2,skip_white=False,exact_available=False)
        self.assertEqual(colors,((0,0,0),))
        self.assertEqual(groups,[[(0,0,9,0)]])
        self.assertEqual(len(selectors),1)
        self.assertEqual(meta['active_colors'],1)
        self.assertEqual(meta['color_actions_coalesced'],1)
        self.assertEqual(meta['coverage_priority'],(1.0,))
        self.assertEqual(meta['color_fidelity_diagnostics']['mapped_pixels'],10)

    def test_different_exact_selection_contracts_are_not_coalesced(self):
        from DynamicColors import _coalesce_color_actions
        colors=[(30,40,50)]*3
        actions=[{'kind':'palette','palette_index':0},
                 {'kind':'custom','fallback_palette_index':0,'require_exact':True},
                 {'kind':'custom','fallback_palette_index':0,'require_exact':False}]
        result=_coalesce_color_actions(colors,actions,[.3,.3,.4])
        self.assertEqual(len(result[0]),3)

    def test_palette_only_analysis_matches_full_plan_without_allocating_strokes(self):
        import DynamicColors as dynamic
        source=Image.new('RGB',(30,4));source.paste((255,0,0),(0,0,14,4));source.paste((0,0,255),(14,0,30,4))
        options={'max_colors':2,'skip_white':False,'exact_available':True,'source_palette':True}
        full=dynamic.build_dynamic_color_strokes(source,[(0,0,0)],**options)
        with patch.object(dynamic,'_groups_from_labels',side_effect=AssertionError('unused geometry')):
            palette=dynamic.build_dynamic_color_palette(source,[(0,0,0)],**options)
        self.assertEqual(palette,full[1:])

    def test_skip_white_does_not_spend_or_contaminate_exact_color_budget(self):
        from DynamicColors import build_dynamic_color_strokes
        source=Image.new('RGB',(10,1),'white');source.putpixel((9,0),(255,0,0))
        groups,colors,_selectors,meta=build_dynamic_color_strokes(
            source,[(0,0,255)],max_colors=1,skip_white=True,exact_available=True,source_palette=True)
        self.assertEqual(colors,((255,0,0),))
        self.assertEqual(groups,[[(9,0,9,0)]])
        self.assertEqual(meta['white_skipped'],9)
        self.assertEqual(meta['color_fidelity_diagnostics']['mapped_pixels'],1)

    def test_transparency_gaps_are_never_drawn_even_when_white_is_enabled(self):
        from DynamicColors import build_dynamic_color_strokes
        source=Image.new('RGBA',(3,1),(255,0,0,255));source.putpixel((1,0),(0,0,255,0))
        groups,colors,_selectors,meta=build_dynamic_color_strokes(
            source,[(255,0,0)],max_colors=1,skip_white=False,exact_available=True,source_palette=True)
        self.assertEqual(colors,((255,0,0),))
        self.assertEqual(groups,[[(0,0,0,0),(2,0,2,0)]])
        self.assertEqual(meta['color_fidelity_diagnostics']['mapped_pixels'],2)
        self.assertEqual(meta['white_skipped'],0)

    def test_source_whiteness_is_decided_before_merging(self):
        from DynamicColors import build_dynamic_color_strokes
        source=Image.new('RGB',(2,1));source.putdata([(244,250,250),(250,244,250)])
        groups,colors,_selectors,meta=build_dynamic_color_strokes(
            source,[(250,250,250)],max_colors=1,skip_white=True,exact_available=True,source_palette=True)
        self.assertEqual(sum(x2-x1+1 for group in groups for x1,y1,x2,y2 in group),2)
        self.assertEqual(meta['white_skipped'],0)

    def test_empty_drawable_source_has_no_invented_color(self):
        from DynamicColors import build_dynamic_color_strokes
        for image,skip in ((Image.new('RGB',(3,2),'white'),True),(Image.new('RGBA',(3,2),(1,2,3,0)),False)):
            result=build_dynamic_color_strokes(image,[(0,0,0)],skip_white=skip)
            self.assertEqual(result[:3],([],(),()))
            self.assertEqual(result[3]['color_fidelity_diagnostics']['mapped_pixels'],0)

    def test_stop_during_visible_conversion_cannot_publish_empty_success(self):
        import DynamicColors as dynamic
        for image, skip in ((Image.new('RGB',(2,2),'white'),True),
                            (Image.new('RGBA',(2,2),(1,2,3,0)),False)):
            stopped=[False]
            def converted(_source):
                stopped[0]=True
                return Image.new('RGB',image.size,'white')
            with patch.object(dynamic,'visible_rgb_image',side_effect=converted):
                result=dynamic.build_dynamic_color_strokes(image,[(0,0,0)],
                    skip_white=skip,cancelled=lambda:stopped[0])
            self.assertEqual(result,(None,None,None,None))

    def test_row_run_builder_matches_independent_pixel_walk(self):
        from DynamicColors import _groups_from_labels
        rng=np.random.default_rng(812)
        for lines in (False,True):
            for width,height in ((1,1),(19,7),(97,3)):
                labels=rng.integers(0,4,(height,width),dtype=np.uint8)
                draw=rng.random((height,width))>.3
                mapping={0:2,1:0,2:1,3:2}
                expected=[[],[],[]]
                for y in range(height):
                    previous=None;start=None
                    for x in range(width+1):
                        group=mapping[int(labels[y,x])] if x<width and draw[y,x] else None
                        if not lines:
                            if group is not None:expected[group].append((x,y,x,y))
                        elif group!=previous:
                            if previous is not None:expected[previous].append((start,y,x-1,y))
                            previous,start=group,(x if group is not None else None)
                self.assertEqual(_groups_from_labels(labels,draw,mapping,3,lines,lambda:False),expected)

    def test_scan_cancel_does_not_return_partial_groups(self):
        from DynamicColors import _groups_from_labels
        calls=0
        def stop():
            nonlocal calls
            calls+=1
            return calls==2
        self.assertIsNone(_groups_from_labels(np.zeros((4,5),dtype=np.uint8),np.ones((4,5),dtype=bool),{0:0},1,True,stop))

    def test_stop_during_late_diagnostics_prevents_success(self):
        import DynamicColors as dynamic
        stopped=[False]
        def named(*_args):stopped[0]=True;return {}
        with patch('NamedColorIntelligence.describe_color_mapping',side_effect=named):
            result=dynamic.build_dynamic_color_strokes(Image.new('RGB',(4,3),(40,50,60)),
                [(40,50,60)],skip_white=False,cancelled=lambda:stopped[0])
        self.assertEqual(result,(None,None,None,None))


class SourceRepresentativeTests(unittest.TestCase):
    def test_exact_source_color_after_sampling_prefix_is_kept(self):
        from ExactColorEngine import _nearest_actual
        pixels=np.zeros((16000,3),dtype=np.uint8)
        pixels[:,0]=np.arange(16000)%240
        pixels[-1]=(255,230,197)
        self.assertEqual(_nearest_actual(pixels,(255,230,197)),(255,230,197))

    def test_nonexact_candidates_span_the_whole_sorted_color_range(self):
        from ExactColorEngine import _nearest_actual
        pixels=np.column_stack((np.arange(3000)//256,np.arange(3000)%256,np.full(3000,32))).astype(np.uint8)
        pixels[-1]=(255,255,255)
        self.assertEqual(_nearest_actual(pixels,(255,255,254)),(255,255,255))


class MatchingWorkTests(unittest.TestCase):
    def test_cost_only_paths_skip_unused_ciede2000_but_preserve_winners(self):
        import ExactColorEngine as exact
        import DynamicColors as dynamic
        from ShadowToneMapper import shadow_candidate_cost
        rng=np.random.default_rng(933)
        palette=[tuple(map(int,row)) for row in rng.integers(0,256,(20,3))]
        for fidelity in ('Fast','Balanced','Faithful','Exact'):
            for source in palette[:4]+[(240,190,20)]:
                scores=[(exact.score_candidate(source,rgb,fidelity=fidelity).total_cost,index) for index,rgb in enumerate(palette)]
                with patch.object(exact,'delta_e2000',side_effect=AssertionError('unused diagnostic')):
                    self.assertEqual(dynamic._closest_palette_index(source,palette,fidelity),min(scores))
                    shadow_candidate_cost(source,palette[0])

    def test_named_color_vector_search_matches_scalar_reference_and_exact_aliases(self):
        import NamedColorIntelligence as names
        from ColorFidelity import delta_e_oklab
        rng=np.random.default_rng(934)
        samples=[tuple(map(int,row)) for row in rng.integers(0,256,(35,3))]
        samples+=list(names._EXTENDED_CANONICAL)[:10]
        for extended in (False,True):
            rows=names._EXTENDED_NEAREST_ROWS if extended else names._CSS_NEAREST_ROWS
            for rgb in samples:
                result=names.nearest_named_color(rgb,extended=extended)
                if rgb in names._EXTENDED_CANONICAL:
                    expected_rgb=rgb;expected_name=names._EXTENDED_CANONICAL[rgb]
                else:
                    expected_rgb,expected_name=min(rows,key=lambda row:delta_e_oklab(rgb,row[0]))
                self.assertEqual((result['rgb'],result['name']),(expected_rgb,expected_name))
                self.assertEqual(result['delta_e_oklab'],round(delta_e_oklab(rgb,expected_rgb),4))
        self.assertFalse(names._nearest_reference(False)[1].flags.writeable)

    def test_region_stop_after_contrast_skips_histogram_work(self):
        import RegionAwareQuantization as regions
        stopped=[False]
        def contrast(source):
            stopped[0]=True
            return np.ones(source.shape[:2],np.float32),np.zeros(source.shape[:2],np.float32)
        with patch.object(regions,'_local_importance',side_effect=contrast),patch.object(regions.np,'bincount') as bins:
            with self.assertRaises(InterruptedError):
                regions.build_region_context(Image.new('RGB',(4,4)),Image.new('L',(4,4)),
                    [{'qindex':0,'rgb':(0,0,0),'count':16}],cancelled=lambda:stopped[0])
            bins.assert_not_called()


if __name__ == '__main__':
    unittest.main()
