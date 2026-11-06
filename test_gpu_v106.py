import unittest
from unittest import mock
from types import SimpleNamespace
from pathlib import Path

from PIL import Image

from LocalSanitization import safe_context
import GpuAcceleration as ga
import PortraitPlanner as pp
from DrawBot import DrawBotApp, make_plan


class Value:
    def __init__(self,value): self.value=value
    def get(self): return self.value


class GpuAccelerationV106Tests(unittest.TestCase):
    def setUp(self):
        self.image=Image.new('RGBA',(180,120),'white')
        px=self.image.load()
        for y in range(20,100):
            for x in range(30,150):
                if (x*3+y*5)%17<6: px[x,y]=(35,35,35,255)

    def test_modes_are_explicit_and_invalid_value_is_rejected(self):
        self.assertEqual(ga.ACCELERATION_MODES,('Auto','CPU','NVIDIA CUDA'))
        for value in ga.ACCELERATION_MODES:self.assertEqual(ga.validate_acceleration_mode(value),value)
        with self.assertRaises(ValueError):ga.validate_acceleration_mode('Magic GPU')

    def test_vram_and_performance_values_are_explicit(self):
        self.assertIn('90%',ga.VRAM_BUDGETS)
        self.assertIn('16 GB',ga.VRAM_BUDGETS)
        self.assertEqual(ga.validate_vram_budget('8 GB'),'8 GB')
        self.assertEqual(ga.validate_gpu_performance('Maximum'),'Maximum')
        with self.assertRaises(ValueError):ga.validate_vram_budget('All VRAM')
        with self.assertRaises(ValueError):ga.validate_gpu_performance('Unsafe')

    def test_vram_budget_reserves_headroom_and_respects_selection(self):
        auto=ga.resolve_vram_budget_mb('Auto',16384,15000)
        half=ga.resolve_vram_budget_mb('50%',16384,15000)
        fixed=ga.resolve_vram_budget_mb('8 GB',16384,15000)
        self.assertGreater(auto,8192)
        self.assertEqual(half,8192)
        self.assertEqual(fixed,8192)
        self.assertLess(ga.resolve_vram_budget_mb('90%',16384,9000),9000)

    def test_cpu_mode_never_requires_gpu_package(self):
        image=Image.new('L',(256,256),128)
        result,info=ga.local_contrast(image,.4,'CPU')
        self.assertIsNone(result)
        self.assertFalse(info.accelerated)
        self.assertEqual(info.backend,'CPU')

    def test_cpu_benchmark_is_safe(self):
        result=ga.benchmark('CPU',256)
        self.assertFalse(result['used_gpu'])
        self.assertEqual(result['backend'],'CPU')
        self.assertGreaterEqual(result['elapsed_ms'],0)

    def test_gpu_enhanced_has_more_analysis_resolution_than_maximum(self):
        maximum=pp.portrait_sample_limit(10,'Maximum likeness')
        gpu=pp.portrait_sample_limit(10,'GPU enhanced')
        self.assertGreater(gpu,maximum*1.15)

    def test_planner_cpu_fallback_records_backend(self):
        options=dict(detail=8,delay=.005,speed='Balanced',precision='High',lines=True,
                     render_style='Portrait / shaded',draw_quality='GPU enhanced',human_mode='Subtle',gpu_mode='CPU',
                     gpu_vram='8 GB',gpu_performance='Maximum',portrait_focus=True,skip_white=True,contrast=1.0,
                     outline=False,brush_px=1,max_seconds=180,paint_current_color=True,erase_mode=False,
                     paint_tool='Use current tool',tool_actions=[])
        plan=make_plan(self.image,(700,500),options)
        stats=plan['options']['portrait_stats']
        self.assertFalse(stats['gpu_accelerated'])
        self.assertEqual(stats['acceleration_backend'],'CPU')
        self.assertEqual(stats['gpu_requested'],'CPU')
        self.assertEqual(stats['gpu_vram'],'8 GB')
        self.assertEqual(stats['gpu_performance'],'Maximum')

    def test_planner_accepts_accelerated_metadata(self):
        fake_info=ga.AccelerationInfo('Auto','Fake CUDA',True,'Test GPU',8192,7000,
                                      vram_budget_mb=4096,compute_capability='9.0',multiprocessors=80,
                                      performance_mode='High throughput')
        def fake_enhance(gray,strength,gamma,focus,lift,mode,vram,performance,**kwargs):
            return gray.copy(),fake_info,None
        def fake_saliency(gray,focus,profile,mode,vram,performance,session,**kwargs):
            return [1.5]*(gray.width*gray.height),fake_info
        def fake_sobel(gray,mode,vram,performance,session,focus,profile,**kwargs):
            zeros=[0.0]*(gray.width*gray.height)
            return (zeros,zeros),fake_info
        meta={}
        with mock.patch.object(pp,'gpu_enhance_portrait',fake_enhance), \
             mock.patch.object(pp,'gpu_saliency',fake_saliency), \
             mock.patch.object(pp,'gpu_sobel',fake_sobel):
            gray,_=pp.prepare_portrait_image(self.image,(600,400),8,draw_quality='High likeness',gpu_mode='Auto',
                                             acceleration_meta=meta,gpu_vram='4 GB',gpu_performance='High throughput')
            _,stats=pp.portrait_strokes(gray,8,True,max_strokes=180,draw_quality='High likeness',gpu_mode='Auto',
                                        acceleration_meta=meta,gpu_vram='4 GB',gpu_performance='High throughput')
        self.assertTrue(stats.gpu_accelerated)
        self.assertEqual(stats.acceleration_backend,'Fake CUDA')
        self.assertEqual(meta['vram_budget_mb'],4096)

    def test_options_exposes_gpu_controls(self):
        app=SimpleNamespace(
            brush_px=Value('1'),max_seconds=Value('180'),quality=Value('Balanced'),
            speed=Value('Balanced'),precision=Value('High'),mode=Value('Lines (fastest)'),
            render_style=Value('Auto'),draw_quality=Value('GPU enhanced'),human_mode=Value('Subtle'),
            gpu_mode=Value('NVIDIA CUDA'),gpu_vram=Value('8 GB'),gpu_performance=Value('Maximum'),
            game=Value('Other drawing app'),paint_tool=Value('Use current tool'),contrast=Value(1.0),
            portrait_focus=Value(True),skip_white=Value(True),outline=Value(False),paint_simple=Value(False))
        result=DrawBotApp.options(app)
        self.assertEqual(result['gpu_mode'],'NVIDIA CUDA')
        self.assertEqual(result['gpu_vram'],'8 GB')
        self.assertEqual(result['gpu_performance'],'Maximum')
        self.assertEqual(result['draw_quality'],'GPU enhanced')

    def test_bug_report_context_allows_only_safe_gpu_fields(self):
        cleaned=safe_context({'gpu_mode':'NVIDIA CUDA','gpu_vram':'8 GB','gpu_performance':'Maximum','secret':'no'})
        self.assertEqual(cleaned['gpu_mode'],'NVIDIA CUDA')
        self.assertEqual(cleaned['gpu_vram'],'8 GB')
        self.assertEqual(cleaned['gpu_performance'],'Maximum')
        self.assertNotIn('secret',cleaned)

    def test_clear_cache_is_safe_without_cuda(self):
        with mock.patch.object(ga,'_BACKEND_CACHE',None), mock.patch.object(ga,'_DISABLED_REASON','No CUDA for test'):
            result=ga.clear_gpu_cache('Auto')
        self.assertFalse(result['cleared'])

    def test_ui_exposes_vram_and_performance_controls(self):
        ui=(Path(__file__).resolve().parent/'StudioUI.py').read_text(encoding='utf-8')
        self.assertIn("'GPU performance'",ui)
        self.assertIn("'VRAM budget'",ui)
        self.assertIn("'Clear GPU cache'",ui)

    def test_gpu_build_scripts_are_separate_from_normal_requirements(self):
        base=Path(__file__).resolve().parent
        normal=(base/'requirements.txt').read_text(encoding='utf-8').lower()
        gpu=(base/'requirements-gpu-nvidia.txt').read_text(encoding='utf-8').lower()
        build=(base/'build_exe.py').read_text(encoding='utf-8')
        self.assertNotIn('cupy',normal)
        self.assertIn('cupy-cuda12x',gpu)
        self.assertIn("'--gpu'",build)
        release=(base/'Build-Release.bat').read_text(encoding='utf-8')
        builder=(base/'build_release.py').read_text(encoding='utf-8')
        self.assertIn('Build-Release.bat', (base/'README.md').read_text(encoding='utf-8'))
        self.assertIn('--gpu', builder)
        self.assertTrue((base/'Install-GPU-NVIDIA.bat').is_file())

    def test_gpu_source_contains_fused_raw_kernels_and_memory_pool(self):
        source=(Path(__file__).resolve().parent/'GpuAcceleration.py').read_text(encoding='utf-8')
        self.assertIn('cp.RawKernel',source)
        self.assertIn('saliency_sobel',source)
        self.assertIn('get_default_memory_pool',source)
        self.assertIn('set_limit',source)
        self.assertIn('alloc_pinned_memory',source)


if __name__=='__main__': unittest.main()
