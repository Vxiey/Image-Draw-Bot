import unittest
import random
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from AxisRegionPlanner import horizontal_components,regional_axis_variants,mask_horizontal_runs,verticalize_horizontal_runs
from GarticSketchPaths import trace_contours


def raster_runs(runs,size=(128,128)):
    image=Image.new('1',size)
    draw=ImageDraw.Draw(image)
    for run in runs:draw.line(run,fill=1,width=1)
    return image.tobytes()


def raster_paths(paths,size=(128,128)):
    image=Image.new('1',size)
    draw=ImageDraw.Draw(image)
    for path in paths:
        if len(path)==1:draw.point(path[0],fill=1)
        else:draw.line(path,fill=1,width=1)
    return image.tobytes()


class AxisRegionHybridTests(unittest.TestCase):
    def test_normalization_stops_before_reading_input_and_between_batches(self):
        class CountingRuns:
            consumed = 0

            def __len__(self):
                return 4096

            def __iter__(self):
                for y in range(len(self)):
                    self.consumed += 1
                    yield (0, y, 4, y)

        for plan in (horizontal_components, regional_axis_variants, verticalize_horizontal_runs):
            with self.subTest(planner=plan.__name__):
                strokes = CountingRuns()
                with self.assertRaises(InterruptedError):
                    plan(strokes, cancelled=lambda: True)
                self.assertEqual(strokes.consumed, 0)
                with self.assertRaises(InterruptedError):
                    plan(strokes, cancelled=lambda: strokes.consumed >= 1)
                self.assertLessEqual(strokes.consumed, 512)

    def test_horizontal_runs_preserve_row_edges_and_order_across_tiles(self):
        fixture = Path(__file__).parent / 'golden-regression' / 'small-detail-preservation.png'
        with Image.open(fixture) as source, source.convert('L') as grayscale:
            ink = np.asarray(grayscale) < 128
        for mask in (ink, ink[::-1, ::-2], ink[:, :1], ink[:, :0], ink[:0]):
            with self.subTest(shape=mask.shape):
                expected = []
                for y, row in enumerate(mask):
                    start = None
                    for x, pixel in enumerate(row):
                        if pixel and start is None:
                            start = x
                        elif not pixel and start is not None:
                            expected.append((start, y, x - 1, y))
                            start = None
                    if start is not None:
                        expected.append((start, y, len(row) - 1, y))
                self.assertEqual(mask_horizontal_runs(mask), expected)

        checks = iter((False, False, True))
        with self.assertRaises(InterruptedError):
            mask_horizontal_runs(ink, cancelled=lambda: next(checks))

    def test_vertical_run_budget_accepts_exact_limit_and_rejects_partial_results(self):
        strokes = [(-5, 1, 84, 1), (-5, 2, -5, 2), (-5, 3, 84, 3)]
        expected = verticalize_horizontal_runs(strokes)
        self.assertEqual(len(expected), 179)
        self.assertEqual(verticalize_horizontal_runs(strokes, max_runs=179), expected)
        self.assertIsNone(verticalize_horizontal_runs(strokes, max_runs=178))

    def test_connected_regions_get_lossless_mixed_axis_candidate(self):
        runs=[]
        runs.extend((5,y,50,y) for y in range(5,10))
        runs.extend((80,y,84,y) for y in range(20,90))
        self.assertEqual(len(horizontal_components(runs)),2)
        variants=regional_axis_variants(runs)
        self.assertTrue(variants)
        best=min(variants,key=lambda item:item[1]['raw_run_delta'])
        self.assertLess(best[1]['raw_run_delta'],0)
        self.assertEqual(raster_runs(best[0]),raster_runs(runs))
        self.assertTrue(any(x0==x1 for x0,y0,x1,y1 in best[0]))
        self.assertTrue(any(y0==y1 for x0,y0,x1,y1 in best[0]))

    def test_random_axis_raster_identity(self):
        rng=random.Random(14524)
        for _ in range(40):
            image=Image.new('1',(48,48))
            draw=ImageDraw.Draw(image)
            for _shape in range(12):
                x0=rng.randrange(0,44);y0=rng.randrange(0,44)
                x1=min(47,x0+rng.randrange(1,8));y1=min(47,y0+rng.randrange(1,8))
                draw.rectangle((x0,y0,x1,y1),fill=1)
            runs=mask_horizontal_runs(image)
            vertical=verticalize_horizontal_runs(runs)
            self.assertIsNotNone(vertical)
            self.assertEqual(raster_runs(vertical,(48,48)),image.tobytes())
            for candidate,_meta in regional_axis_variants(runs):
                self.assertEqual(raster_runs(candidate,(48,48)),image.tobytes())

    def test_diagonal_component_classification_never_bridges_pixels(self):
        runs=[(i,i,i,i) for i in range(20)]
        self.assertEqual(len(horizontal_components(runs,adjacency=1)),1)
        self.assertEqual(len(horizontal_components(runs,adjacency=0)),20)

    def test_dense_sketch_uses_axis_fallback_and_preserves_exact_raster(self):
        image=Image.new('L',(128,128),255)
        ImageDraw.Draw(image).rectangle((10,15,100,95),fill=0)
        paths,meta=trace_contours(image)
        self.assertGreater(meta['axis_components'],0)
        expected=Image.new('1',image.size)
        src=ImageDraw.Draw(expected);src.rectangle((10,15,100,95),fill=1)
        self.assertEqual(raster_paths(paths,image.size),expected.tobytes())
        self.assertGreater(meta['dense_axis_shortcuts'],0)

    def test_thin_sketch_keeps_contour_tracer(self):
        image=Image.new('L',(128,128),255)
        ImageDraw.Draw(image).line((5,5,110,110),fill=0)
        paths,meta=trace_contours(image)
        self.assertEqual(meta['axis_components'],0)
        self.assertEqual(len(paths),1)
        expected=Image.new('1',image.size);ImageDraw.Draw(expected).line((5,5,110,110),fill=1)
        self.assertEqual(raster_paths(paths,image.size),expected.tobytes())

if __name__=='__main__':unittest.main()
