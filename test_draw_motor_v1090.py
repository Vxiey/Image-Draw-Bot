import unittest
from pathlib import Path
from unittest import mock
import numpy as np
from PIL import Image

from AdaptiveBrushEngine import assign_adaptive_brushes, verified_brush_sizes
from PixelAccuracyGpu import compile_swept_rectangles
from PixelAccuracyEngine import simulate_strokes, refine_with_corrections
from PixelAccuratePlanner import build_pixel_map
from Colors import allColors


def brush_plan():
    return {
        'profile_key':'gartic-phone','nominal_sizes':[2,4,8,16,28],
        'control_positions':[[10,10],[20,10],[30,10],[40,10],[50,10]],
        'target_position':[20,10],'confidence':.95,'effective_px':4,
    }


def entry(phase='fill', *, protected=False, importance=.2, path=((1,1),(4,1)), w=20, h=20):
    return {'color_index':2,'path':path,'phase':phase,'protected':protected,'importance':importance,
            'component_width':w,'component_height':h,'component_area':w*h,'serial':0}


class DrawMotorV1090Tests(unittest.TestCase):
    def setUp(self):
        self.palette=tuple(c.RGB for c in allColors)

    def test_01_verified_sizes_never_exceed_effective_brush(self):
        sizes,ok=verified_brush_sizes('gartic-phone',brush_plan(),4)
        self.assertTrue(ok);self.assertEqual(sizes,(2,4))

    def test_02_fine_and_cleanup_use_smallest_verified_brush(self):
        r=assign_adaptive_brushes([entry('fill'),entry('fine_detail'),entry('cleanup')],
                                  profile_key='gartic-phone',default_brush_px=4,browser_brush_plan=brush_plan())
        self.assertEqual([e['brush_px'] for e in r['execution_sequence']],[4,2,2])
        self.assertTrue(r['metadata']['dynamic_brush_enabled'])

    def test_03_unverified_controls_never_invent_dynamic_sizes(self):
        bad=dict(brush_plan());bad['target_position']=None;bad['confidence']=.2
        r=assign_adaptive_brushes([entry('fill'),entry('fine_detail')],profile_key='gartic-phone',
                                  default_brush_px=4,browser_brush_plan=bad)
        self.assertEqual([e['brush_px'] for e in r['execution_sequence']],[4,4])
        self.assertFalse(r['metadata']['dynamic_brush_enabled'])

    def test_04_protected_mid_detail_downshifts(self):
        r=assign_adaptive_brushes([entry('mid_detail',protected=True)],profile_key='gartic-phone',
                                  default_brush_px=4,browser_brush_plan=brush_plan())
        self.assertEqual(r['execution_sequence'][0]['brush_px'],2)

    def test_05_cpu_simulator_respects_per_path_brush(self):
        image=Image.new('RGBA',(8,5),'white')
        px=image.load()
        for x in range(1,5):px[x,2]=self.palette[2]+(255,)
        pm=build_pixel_map(image,self.palette,gpu_mode='CPU',skip_white=True)
        seq=[dict(entry('fill',path=((1,2),(4,2))),brush_px=1)]
        one=simulate_strokes(pm,seq,self.palette,brush_px=4,gpu_mode='CPU')
        seq[0]['brush_px']=3
        three=simulate_strokes(pm,seq,self.palette,brush_px=4,gpu_mode='CPU')
        self.assertEqual(one.metrics['spill_pixels'],0)
        self.assertGreater(three.metrics['spill_pixels'],0)

    def test_06_cuda_rectangle_compiler_respects_entry_brush(self):
        seq=[dict(entry(path=((1,2),(4,2))),brush_px=1),dict(entry(path=((1,4),(4,4))),brush_px=3)]
        r=compile_swept_rectangles(seq,4,8,8)
        self.assertEqual(tuple(r[0]),(1,2,4,2,2))
        self.assertEqual(tuple(r[1]),(0,3,5,5,2))

    def test_07_corrections_use_detail_brush(self):
        image=Image.new('RGBA',(6,1),self.palette[2]+(255,))
        pm=build_pixel_map(image,self.palette,gpu_mode='CPU',skip_white=False)
        result=refine_with_corrections(pm,[],self.palette,brush_px=4,correction_brush_px=1,max_passes=1,gpu_mode='CPU')
        self.assertTrue(result['correction_entries'])
        self.assertTrue(all(e['brush_px']==1 for e in result['correction_entries']))
        self.assertEqual(result['metadata']['correction_brush_px'],1)

    def test_08_brush_metadata_counts_switches(self):
        r=assign_adaptive_brushes([entry('fill'),entry('fine_detail'),entry('mid_detail'),entry('cleanup')],
                                  profile_key='gartic-phone',default_brush_px=4,browser_brush_plan=brush_plan())
        self.assertGreaterEqual(r['metadata']['planned_brush_switches'],1)
        self.assertEqual(r['metadata']['brush_path_counts']['2'],3)

    def test_09_release_build_includes_adaptive_brush_engine(self):
        src=(Path(__file__).parent/'build_exe.py').read_text(encoding='utf-8')
        self.assertIn("'--hidden-import', 'AdaptiveBrushEngine'",src)

    def test_10_runtime_contains_verified_dynamic_brush_switch(self):
        src=(Path(__file__).parent/'DrawBot.py').read_text(encoding='utf-8')
        self.assertIn('def switch_execution_brush',src)
        self.assertIn("entry.get('brush_px'",src)
        self.assertIn('interpolation_step(step_px,current_execution_brush,',src)
        from StrokeDelivery import interpolation_step
        self.assertEqual([interpolation_step(5,brush,pixel_accurate=True)
                          for brush in (1,3,8)], [1.5,4.5,5])
        self.assertEqual(interpolation_step(5,1,pixel_accurate=False),5)

if __name__=='__main__':unittest.main()
