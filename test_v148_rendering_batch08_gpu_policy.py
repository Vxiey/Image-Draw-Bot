from contextlib import closing
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import AdaptiveRegionHybrid as hybrid
import UniversalGpuAcceleration as gpu
from test_v148_rendering_batch07_transparency import standard_options
from test_v148_rendering_batch06_canvas import close_plan
from test_step23_universal_gpu_acceleration_v10146 import profile


class HybridGpuPolicyTests(unittest.TestCase):
    def tearDown(self):
        gpu.reset_runtime_backend_health()

    def test_reconstructed_map_carries_cpu_auto_and_forced_cuda_policy(self):
        measured = profile('opencl:0:0', 'OpenCL', 'AMD', 'Controlled OpenCL')
        measured['scores_large'] = [{'backend_id': 'cuda:0', 'workload': 'edge_map',
                                    'throughput_mp_s': 200, 'elapsed_ms': 1, 'device': 'Controlled CUDA'}]
        recorded = []
        reference = gpu.edge_magnitude
        def routed(lum, **kwargs):
            route = gpu.select_route('edge_map', pixels=lum.size, gpu_mode=kwargs['gpu_mode'], profile=measured)
            recorded.append(route.backend_id)
            # Test policy against the real route selector without device input.
            # The unchanged CPU kernel supplies a deterministic numerical oracle.
            values, _ = reference(lum, gpu_mode='CPU', cancelled=kwargs['cancelled'])
            return values, route.as_dict()
        with closing(Image.new('RGB', (16, 12), 'white')) as image:
            ImageDraw.Draw(image).rectangle((2, 2, 13, 9), fill='black')
            groups = [[(2, y, 13, y) for y in range(2, 10)]]
            with patch.object(gpu, 'edge_magnitude', side_effect=routed):
                maps = [hybrid.pixel_map_from_groups(image, groups, [(0, 0, 0)], gpu_mode=mode)
                        for mode in ('CPU', 'Auto', 'NVIDIA CUDA')]
            self.assertEqual(recorded, ['cpu:numpy', 'opencl:0:0', 'cuda:0'])
            for value in maps[1:]:
                for field in ('rgb', 'palette_index', 'drawable_mask', 'edge_map', 'importance_map', 'protected_mask'):
                    np.testing.assert_array_equal(getattr(value, field), getattr(maps[0], field))
            self.assertEqual([value.metadata['gpu_edge_route']['backend_id'] for value in maps], recorded)

    def test_actual_cpu_make_plan_never_attempts_accelerator_for_hybrid_edges(self):
        import DrawBot
        import UniversalHardwareBenchmark as hardware
        measured = profile('opencl:0:0', 'OpenCL', 'AMD', 'Controlled OpenCL')
        observed = []
        real = gpu.edge_magnitude
        def record(lum, **kwargs):
            observed.append(kwargs.get('gpu_mode'))
            return real(lum, **kwargs)
        with closing(Image.new('RGBA', (96, 80), 'white')) as image:
            ImageDraw.Draw(image).rectangle((10, 10, 85, 69), fill='black')
            with patch.object(hardware, 'load_hardware_profile', return_value=measured), \
                    patch.object(gpu, '_opencl_context', side_effect=AssertionError('CPU must not open a device')) as opened, \
                    patch.object(gpu, 'edge_magnitude', side_effect=record), \
                    patch.object(hybrid, 'pixel_map_from_groups', wraps=hybrid.pixel_map_from_groups) as reconstruct:
                plan = DrawBot.make_plan(image, image.size, standard_options(
                    extra_fast=True, extra_fast_v2=True, gpu_mode='CPU'))
            try:
                self.assertTrue(plan['options']['adaptive_hybrid_meta']['enabled'])
                reconstruct.assert_called_once()
                self.assertEqual(reconstruct.call_args.kwargs['gpu_mode'], 'CPU')
                self.assertTrue(observed)
                self.assertEqual(set(observed), {'CPU'})
                opened.assert_not_called()
                self.assertFalse(gpu.backend_health_snapshot())
            finally:
                close_plan(plan, image)

    def test_accepted_fill_reconstruction_forwards_policy_to_both_maps(self):
        import DrawBot
        from Colors import allColors
        blue = next(i for i, color in enumerate(allColors) if color.RGB == (0, 80, 205))
        # Isolate the caller's accepted-Fill branch. This centerline rectangle
        # is exact; actual detector/simulator rejection policy is separate.
        region = {'color_index': blue, 'rgb': (0, 80, 205), 'bbox': (20, 20, 150, 99),
                  'seed_pixel': (80, 60), 'area_pixels': 10480, 'bbox_density': 1.,
                  'estimated_saved_strokes': 79, 'strategy': 'rectangle',
                  'row_spans': tuple((y, 20, 150) for y in range(20, 100)),
                  'contour': ((20, 20), (150, 20), (150, 99), (20, 99), (20, 20))}
        with closing(Image.new('RGBA', (180, 120), 'white')) as image:
            ImageDraw.Draw(image).rectangle((20, 20, 150, 99), fill=(0, 80, 205, 255))
            with patch.object(hybrid, '_build_fill_regions', return_value=([region], {'enabled': True})), \
                    patch.object(hybrid, 'pixel_map_from_groups', wraps=hybrid.pixel_map_from_groups) as reconstruct:
                plan = DrawBot.make_plan(image, image.size, standard_options(
                    extra_fast=True, extra_fast_v2=True, gpu_mode='CPU',
                    fill_tool_available=True, use_region_fill_engine=True,
                    fill_engine='Safe rectangles', fill_tool_actions=[('fill', (10, 10))],
                    fill_restore_actions=[('brush', (20, 10))]))
            try:
                self.assertTrue(plan['options']['adaptive_hybrid_meta']['enabled'])
                self.assertTrue(plan['options']['fill_regions'])
                self.assertEqual(reconstruct.call_count, 2)
                self.assertTrue(all(call.kwargs['gpu_mode'] == 'CPU' for call in reconstruct.call_args_list))
            finally:
                close_plan(plan, image)


if __name__ == '__main__':
    unittest.main()
