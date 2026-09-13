import tempfile
import unittest
from pathlib import Path

from ResourceScheduler import (RESOURCE_SCHEDULER_MODES, benchmark_scheduler, load_recommendation,
                               recommended_workers, resolve_resource_schedule, save_recommendation,
                               validate_resource_scheduler)
from ResourceAllocation import resolve_allocation
from DrawBot import make_plan
from PIL import Image, ImageDraw
from Version import APP_VERSION, FILE_VERSION


class ResourceSchedulerV1044Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_modes_validate(self):
        for mode in RESOURCE_SCHEDULER_MODES:
            self.assertEqual(validate_resource_scheduler(mode), mode)
        with self.assertRaises(ValueError):
            validate_resource_scheduler('Max everything')

    def test_auto_avoids_all_32_threads(self):
        allocation={'cpu_workers':'Auto','cpu_workers_resolved':30,'logical_cpus':32,'cpu_engine':'Auto','ram_budget_mb':4096}
        workers,reason=recommended_workers(allocation,mode='Auto')
        self.assertLess(workers,32)
        self.assertLessEqual(workers,16)
        self.assertIn('auto', reason)

    def test_phase_schedule_routes_work(self):
        allocation={'cpu_workers':'Auto','cpu_workers_resolved':8,'logical_cpus':16,'cpu_engine':'Auto','ram_budget_mb':2048}
        schedule=resolve_resource_schedule(allocation,mode='Auto',area=(1200,800),drawing_mode='Shape paths',gpu_mode='Auto',gpu_available=True)
        self.assertEqual(schedule['phases']['color_analysis']['backend'],'CPU/SIMD')
        self.assertEqual(schedule['phases']['image_matrix']['backend'],'GPU')
        self.assertEqual(schedule['phases']['path_optimization']['backend'],'CPU')
        self.assertGreaterEqual(schedule['phases']['shape_extraction']['chunks'],1)
        self.assertLessEqual(schedule['phases']['path_optimization']['workers'],4)

    def test_small_image_keeps_matrix_on_cpu(self):
        allocation={'cpu_workers':'Auto','cpu_workers_resolved':8,'logical_cpus':16,'cpu_engine':'Auto','ram_budget_mb':2048}
        schedule=resolve_resource_schedule(allocation,mode='Auto',area=(200,200),gpu_mode='Auto',gpu_available=True)
        self.assertEqual(schedule['phases']['image_matrix']['backend'],'CPU')

    def test_benchmark_recommendation_roundtrip(self):
        allocation={'cpu_workers':'Auto','cpu_workers_resolved':8,'logical_cpus':8,'cpu_engine':'Auto','ram_budget_mb':512}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'resource-scheduler-v2.json'
            result=benchmark_scheduler(allocation,loops_per_worker=1500,save=True,path=path)
            saved=load_recommendation(path, signature=result['machine_signature'])
            self.assertIsNotNone(saved)
            self.assertEqual(saved['recommended_workers'], result['recommended_workers'])

    def test_make_plan_carries_scheduler_metadata(self):
        image=Image.new('RGBA',(180,120),'white')
        ImageDraw.Draw(image).rectangle((10,10,130,90),fill=(30,90,180,255))
        plan=make_plan(image,(720,480),dict(detail=8,delay=.01,lines=True,skip_white=True,contrast=1,outline=False,
            drawing_mode='Shape paths',speed='Balanced',precision='High',brush_px=2,max_seconds=180,
            cpu_workers='Auto',cpu_engine='Auto',ram_budget='512 MB',ram_custom_mb='4096',planning_resolution='Standard',
            resource_scheduler='Auto',gpu_mode='CPU',gpu_vram='Auto',gpu_performance='Balanced',
            background_fill='Off',fill_engine='Auto',background_simplification='Off',color_grouping='Smart',color_workflow='Finish color first',
            stroke_optimizer='Auto',adaptive_detail='Off',visual_verification='Off',color_rendering='Perceptual match',color_layers='Off',
            custom_color_workflow='Calibrated palette',draw_quality='Balanced',human_mode='Off',tool_strategy='Auto',portrait_focus=True,
            paint_current_color=False,erase_mode=False,paint_tool='Use current tool',effective_paint_tool='Use current tool',
            tool_actions=[],fill_tool_available=False,fill_tool_actions=[],fill_restore_actions=[]))
        self.assertIn('resource_scheduler_plan', plan['options'])
        self.assertEqual(plan['options']['resource_scheduler_plan']['phases']['color_analysis']['backend'],'CPU/SIMD')


if __name__ == '__main__':
    unittest.main()
