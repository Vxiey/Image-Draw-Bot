import unittest
from collections import Counter
from pathlib import Path

from StrokeOptimizer import (STROKE_OPTIMIZER_MODES, optimize_execution_groups,
                             optimize_path_group, pen_up_distance,
                             resolve_stroke_optimizer, validate_stroke_optimizer)


def segments(paths):
    out=[]
    for path in paths:
        for a,b in zip(path,path[1:]):
            out.append((a,b) if a<=b else (b,a))
    return Counter(out)


class StrokeOptimizerV1037Tests(unittest.TestCase):
    def test_modes_and_auto_resolution(self):
        self.assertEqual(STROKE_OPTIMIZER_MODES,('Auto','Off','Travel only','Smart merge','Smart merge + 2-opt'))
        self.assertEqual(resolve_stroke_optimizer('Auto',drawing_mode='Shape paths'),'Smart merge')
        self.assertEqual(resolve_stroke_optimizer('Auto',drawing_mode='Smart paths (recommended)'),'Smart merge')
        self.assertEqual(resolve_stroke_optimizer('Auto',drawing_mode='Lines (fastest)'),'Travel only')
        with self.assertRaises(ValueError):validate_stroke_optimizer('Unsafe shortcut')

    def test_smart_merge_preserves_exact_segment_geometry(self):
        paths=[((0,0),(5,0)),((10,0),(5,0)),((20,0),(30,0)),((30,0),(40,0))]
        before=segments(paths)
        out,meta=optimize_path_group(paths,mode='Smart merge',drawing_mode='Shape paths',speed='Balanced')
        self.assertEqual(segments(out),before)
        self.assertEqual(len(out),2)
        self.assertEqual(meta['optimizer_merged_paths'],2)

    def test_near_endpoints_are_never_joined(self):
        paths=[((0,0),(10,0)),((11,0),(20,0))]
        out,meta=optimize_path_group(paths,mode='Smart merge',drawing_mode='Shape paths')
        self.assertEqual(len(out),2)
        self.assertEqual(meta['optimizer_merged_paths'],0)
        self.assertEqual(segments(out),segments(paths))

    def test_travel_only_reduces_bad_pen_up_order(self):
        paths=[]
        for i in range(80):
            x=0 if i%2==0 else 1000
            paths.append(((x,i*3),(x+5,i*3)))
        before=pen_up_distance(paths)
        out,meta=optimize_path_group(paths,mode='Travel only',drawing_mode='Shape paths',speed='Fast')
        self.assertEqual(len(out),len(paths))
        self.assertEqual(segments(out),segments(paths))
        self.assertLess(pen_up_distance(out),before)
        self.assertGreater(meta['optimizer_travel_reduction'],0)

    def test_progressive_phase_boundaries_are_preserved(self):
        groups=[[((0,0),(5,0)),((5,0),(10,0)),((100,0),(105,0)),((105,0),(110,0))]]
        hints=[['foundation','foundation','details','details']]
        out,new_hints,meta=optimize_execution_groups(groups,mode='Smart merge',drawing_mode='Shape paths',speed='Fast',phase_hints=hints)
        self.assertEqual(new_hints,[['foundation','details']])
        self.assertEqual(len(out[0]),2)
        self.assertEqual(meta['optimizer_merged_paths'],2)

    def test_off_mode_is_identity_order(self):
        paths=[((10,0),(20,0)),((0,0),(1,0)),((5,0),(6,0))]
        out,meta=optimize_path_group(paths,mode='Off',drawing_mode='Shape paths')
        self.assertEqual(out,paths)
        self.assertEqual(meta['stroke_optimizer_effective'],'Off')

    def test_release_metadata_and_ui_control(self):
        from Version import APP_VERSION,FILE_VERSION
        self.assertEqual(APP_VERSION,'1.0.145-rc29');self.assertEqual(FILE_VERSION,'1.0.145')
        ui=Path('StudioUI.py').read_text(encoding='utf-8')
        bot=Path('DrawBot.py').read_text(encoding='utf-8')
        self.assertIn("'Stroke optimizer'",ui)
        self.assertIn('optimizer_travel_reduction',bot)
        self.assertIn("optimize_execution_groups",bot)

if __name__=='__main__':unittest.main()
