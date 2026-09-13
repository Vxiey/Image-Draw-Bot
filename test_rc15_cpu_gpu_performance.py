\
import unittest
from pathlib import Path

from GpuAcceleration import (AccelerationInfo,gpu_memory_recovery_steps,gpu_score_tile_rows,
                             is_gpu_memory_error)
from ResourceScheduler import memory_pressure_profile,resolve_resource_schedule
from UniversalGpuAcceleration import RouteInfo,_mark_failed,backend_health_snapshot,reset_runtime_backend_health
from Version import APP_VERSION


class Rc15CpuGpuPerformanceTests(unittest.TestCase):
    def test_gpu_memory_error_detection_is_runtime_agnostic(self):
        self.assertTrue(is_gpu_memory_error(MemoryError('host pressure')))
        self.assertTrue(is_gpu_memory_error(RuntimeError('CUDA_ERROR_OUT_OF_MEMORY')))
        self.assertTrue(is_gpu_memory_error(RuntimeError('CL_MEM_OBJECT_ALLOCATION_FAILURE')))
        self.assertFalse(is_gpu_memory_error(RuntimeError('kernel syntax error')))

    def test_recovery_steps_shrink_tiles_and_batches(self):
        steps=gpu_memory_recovery_steps(128,8192,max_retries=3)
        self.assertGreaterEqual(len(steps),3)
        self.assertEqual((steps[0]['tile_rows'],steps[0]['batch_size']),(128,8192))
        for a,b in zip(steps,steps[1:]):
            self.assertLessEqual(b['tile_rows'],a['tile_rows']);self.assertLessEqual(b['batch_size'],a['batch_size'])
        self.assertLess(steps[-1]['tile_rows'],steps[0]['tile_rows'])

    def test_score_tiles_respect_small_vram_budget(self):
        info=AccelerationInfo('Auto','CUDA',True,'GPU',total_vram_mb=1024,free_vram_mb=180,vram_budget_mb=128)
        rows=gpu_score_tile_rows(info,5000,4000,bytes_per_pixel=64)
        self.assertGreaterEqual(rows,8);self.assertLess(rows,4000)

    def test_live_ram_pressure_reduces_auto_workers_and_chunks(self):
        allocation={'cpu_workers':'Auto','cpu_workers_resolved':16,'logical_cpus':32,'cpu_engine':'Auto',
                    'ram_budget_mb':4096,'available_ram_mb':700}
        pressure=memory_pressure_profile(allocation)
        self.assertIn(pressure['level'],('high','critical'))
        pressured=resolve_resource_schedule(allocation,mode='Auto',area=(1800,1200),gpu_mode='CPU')
        unconstrained=resolve_resource_schedule(dict(allocation,available_ram_mb=None),mode='Auto',area=(1800,1200),gpu_mode='CPU')
        self.assertLess(pressured['base_workers'],unconstrained['base_workers'])
        self.assertLessEqual(pressured['phases']['shape_extraction']['rows_per_chunk'],unconstrained['phases']['shape_extraction']['rows_per_chunk'])

    def test_scheduler_off_keeps_worker_behavior(self):
        allocation={'cpu_workers':'8','cpu_workers_resolved':8,'logical_cpus':16,'cpu_engine':'Threads',
                    'ram_budget_mb':4096,'available_ram_mb':500}
        schedule=resolve_resource_schedule(allocation,mode='Off',area=(1000,800),gpu_mode='CPU')
        self.assertEqual(schedule['base_workers'],8)

    def test_large_correction_scoring_advertises_safe_gpu_route(self):
        allocation={'cpu_workers':'Auto','cpu_workers_resolved':8,'logical_cpus':16,'cpu_engine':'Auto','ram_budget_mb':2048}
        schedule=resolve_resource_schedule(allocation,mode='Auto',area=(1200,800),gpu_mode='Auto',gpu_available=True)
        self.assertEqual(schedule['phases']['correction_scoring']['backend'],'GPU/CPU fallback')

    def test_transient_oom_does_not_quarantine_backend(self):
        reset_runtime_backend_health()
        route=RouteInfo('pixel_math','bulk_matrix','cuda:0','CUDA/CuPy','NVIDIA','GPU',True,500000)
        fallback=_mark_failed(route,RuntimeError('CUDA_ERROR_OUT_OF_MEMORY'))
        self.assertFalse(fallback.accelerated);self.assertEqual(backend_health_snapshot(),{})
        _mark_failed(route,RuntimeError('illegal memory access'))
        self.assertTrue(backend_health_snapshot())
        reset_runtime_backend_health()

    def test_pixel_accuracy_gpu_contains_bounded_retry_and_tiled_score(self):
        src=Path('PixelAccuracyGpu.py').read_text(encoding='utf-8')
        self.assertIn('gpu_memory_recovery_steps',src);self.assertIn('score_tile_rows',src)
        self.assertIn('score_vram_retries',src);self.assertNotIn('CUDA accuracy scoring exceeds allocation budget; using CPU scoring.',src)

    def test_version(self):self.assertEqual(APP_VERSION,'1.0.146-rc2')


if __name__=='__main__':unittest.main()
