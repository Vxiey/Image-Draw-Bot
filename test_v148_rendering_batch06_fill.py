"""Discarded Fill-border geometry cannot change component evidence or Stop."""
from collections import deque
from contextlib import closing
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import FillOptimizer as fill
from Colors import allColors


PALETTE=tuple(tuple(c.RGB) for c in allColors)


def groups_from_labels(labels):
    groups=[[] for _ in PALETTE]
    # Independent one-pixel inputs deliberately leave run coalescing to the
    # real group rasterizer rather than duplicate the component implementation.
    for y,row in enumerate(labels):
        for x,color in enumerate(row):
            if color>=0:groups[int(color)].append((x,y,x,y))
    return groups


def components(labels):
    height,width=labels.shape;unvisited={(x,y) for y in range(height) for x in range(width) if labels[y,x]>=0}
    result=[]
    while unvisited:
        first=min(unvisited,key=lambda p:(p[1],p[0]));color=int(labels[first[1],first[0]])
        pending=deque([first]);unvisited.remove(first);pixels={first}
        while pending:
            x,y=pending.popleft()
            for point in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if point in unvisited and labels[point[1],point[0]]==color:
                    unvisited.remove(point);pixels.add(point);pending.append(point)
        border=any(x in (0,width-1) or y in (0,height-1) for x,y in pixels)
        result.append((color,pixels,border))
    return result


def fixture():
    labels=np.full((80,96),1,np.int16)
    labels[8:56,8:36]=0  # Real interior Fill candidate.
    labels[10:71,65:81]=2
    labels[70:80,72]=2  # This component encounters the bottom border later.
    labels[4,50]=0      # One interior component below the candidate floor.
    return labels


class FillBorderStorageTests(unittest.TestCase):
    def test_both_detectors_preserve_independently_flooded_interior_geometry(self):
        labels=fixture();expected=components(labels)
        candidate_sets=[(color,pixels) for color,pixels,border in expected if not border and len(pixels)>=36]
        rgb=np.asarray(PALETTE,np.uint8)[labels]
        outputs=[]
        for kind in ('image','groups'):
            captured=[];original=fill._component_to_region
            def observe(color,points,width,height,*args,**kwargs):
                captured.append((color,{(pos%width,pos//width) for pos in points}))
                return original(color,points,width,height,*args,**kwargs)
            with self.subTest(kind=kind),closing(Image.fromarray(rgb)) as image,patch.object(fill,'_component_to_region',side_effect=observe):
                result=(fill.detect_fill_regions(image,'Balanced',engine='Safe rectangles',return_meta=True)
                        if kind=='image' else fill.detect_fill_regions_from_groups(groups_from_labels(labels),PALETTE,
                            image.size,'Balanced',engine='Safe rectangles',return_meta=True))
                regions,meta=result
                self.assertEqual(captured,candidate_sets)
                self.assertEqual(meta['total_components'],len(expected))
                self.assertEqual(meta['interior_components'],sum(not border for _,_,border in expected))
                self.assertEqual(len(regions),1)
                region=regions[0]
                self.assertEqual((region.bbox,region.area_pixels,region.rgb),((8,8,35,55),28*48,PALETTE[0]))
                painted={(x,y) for y,x0,x1 in region.row_spans for x in range(x0,x1+1)}
                self.assertEqual(painted,candidate_sets[0][1])
                self.assertIn(region.seed_pixel,painted)
                sx,sy=region.seed_pixel
                self.assertTrue(all(point in painted for point in ((sx-1,sy),(sx+1,sy),(sx,sy-1),(sx,sy+1))))
                outputs.append([region.as_dict() for region in regions])
        self.assertEqual(outputs[0],outputs[1])

    def test_sparse_group_components_keep_exact_encounter_counts_and_empty_pixels(self):
        rng=np.random.default_rng(14806)
        for _ in range(10):
            labels=rng.integers(-1,3,(18,23),dtype=np.int16)
            expected=components(labels)
            regions,meta=fill.detect_fill_regions_from_groups(groups_from_labels(labels),PALETTE,(23,18),
                'Balanced',engine='Safe rectangles',return_meta=True)
            self.assertEqual(regions,[])
            self.assertEqual(meta['total_components'],len(expected))
            self.assertEqual(meta['interior_components'],sum(not border for _,_,border in expected))

    def test_known_border_component_remains_cancellable_in_both_detectors(self):
        for kind in ('image','groups'):
            calls=0
            def cancelled():
                nonlocal calls
                calls+=1
                return calls>=4
            with self.subTest(kind=kind),closing(Image.new('RGB',(128,128),PALETTE[0])) as image:
                with self.assertRaises(InterruptedError):
                    if kind=='image':fill.detect_fill_regions(image,'Balanced',cancelled=cancelled)
                    else:fill.detect_fill_regions_from_groups([[(0,y,127,y) for y in range(128)]],
                        [PALETTE[0]],image.size,'Balanced',cancelled=cancelled)
                self.assertEqual(image.getpixel((0,0)),PALETTE[0])

    def test_real_application_fill_route_keeps_its_interior_region(self):
        from DrawBot import make_plan
        from test_autofill_smart_tools_v107 import opts
        from test_v148_rendering_batch06_canvas import close_plan
        with closing(Image.new('RGBA',(180,120),'white')) as source:
            ImageDraw.Draw(source).rectangle((40,25,140,95),fill=(255,120,41,255))
            import RegionFillEngine
            with patch('DrawBot.log_event'),patch.object(RegionFillEngine,'detect_fill_regions',wraps=fill.detect_fill_regions) as detector:
                plan=make_plan(source,(720,480),opts(preview_plan=True,detail_zoom='Off',adaptive_detail='Off'))
            try:
                self.assertGreater(detector.call_count,0)
                self.assertTrue(plan['options']['fill_regions'])
                self.assertGreater(plan['options']['region_fill_meta']['interior_components'],0)
                self.assertGreater(plan['options']['region_fill_meta']['total_components'],
                                   plan['options']['region_fill_meta']['interior_components'])
            finally:close_plan(plan,source)


if __name__=='__main__':unittest.main()
