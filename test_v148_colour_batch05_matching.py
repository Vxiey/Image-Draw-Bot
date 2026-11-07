"""Independent scalar color costs versus production CPU and CUDA paths."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from ColorFidelity import palette_match_cost, rgb_to_oklab
import GpuAcceleration as cuda
import UniversalGpuAcceleration as universal
import PixelAccuratePlanner as planner


PALETTE = ((200, 177, 197), (209, 168, 206), (186, 185, 190), (195, 201, 235))
SOURCES = ((222, 200, 194), (130, 125, 143), (70, 82, 75), (255, 0, 0),
           (0, 255, 255), (0, 0, 0), (255, 255, 255))


def scalar_choices(sources, palette, rendering, fidelity):
    return [min(range(len(palette)), key=lambda i: palette_match_cost(
        source, palette[i], color_rendering=rendering, fidelity=fidelity)) for source in sources]


class HostCupy:
    """Execute the actual CuPy array expression using NumPy, without a device."""
    cuda = SimpleNamespace(Stream=SimpleNamespace(null=SimpleNamespace(synchronize=lambda: None)))
    asnumpy = staticmethod(np.asarray)

    def __getattr__(self, name):
        return getattr(np, name)


class PaletteParityTests(unittest.TestCase):
    def test_near_neutral_scalar_and_vector_costs_agree(self):
        for fidelity in ('Fast', 'Balanced', 'Faithful', 'Exact'):
            for rendering in ('RGB nearest', 'Perceptual match'):
                with self.subTest(fidelity=fidelity, rendering=rendering):
                    expected = np.asarray([[palette_match_cost(source, color,
                        color_rendering=rendering, fidelity=fidelity) for color in PALETTE]
                        for source in SOURCES])
                    actual = universal._palette_cost_cpu(np.asarray(SOURCES), np.asarray(PALETTE),
                        perceptual=rendering != 'RGB nearest', fidelity=fidelity)
                    np.testing.assert_allclose(actual, expected, atol=4e-5, rtol=2e-6)
        self.assertEqual(scalar_choices(SOURCES[:1], PALETTE, 'Perceptual match', 'Faithful'), [3])

    def test_pixel_map_and_emergency_fallback_choose_the_same_swatch(self):
        with Image.fromarray(np.asarray([SOURCES], np.uint8)) as source:
            for fidelity in ('Balanced', 'Faithful'):
                expected = scalar_choices(SOURCES, PALETTE, 'Perceptual match', fidelity)
                normal, _draw, _rgb, _meta = planner.exact_palette_map(
                    source, PALETTE, skip_white=False, color_fidelity=fidelity, gpu_mode='CPU')
                with patch.object(universal, 'palette_indices_rgba', side_effect=RuntimeError('backend unavailable')):
                    fallback, _draw, _rgb, meta = planner.exact_palette_map(
                        source, PALETTE, skip_white=False, color_fidelity=fidelity, gpu_mode='CPU')
                self.assertEqual(normal[0].tolist(), expected)
                self.assertEqual(fallback[0].tolist(), expected)
                self.assertIn('backend unavailable', meta['palette_route']['fallback_reason'])

    def test_cuda_array_branch_matches_scalar_including_rgb_nearest(self):
        info = cuda.AccelerationInfo('NVIDIA CUDA', 'CUDA', True, vram_budget_mb=256)
        plan = {'mode': 'full', 'tile_rows': 1, 'workspace_mb': 1}
        with Image.fromarray(np.asarray([SOURCES], np.uint8)) as source, \
             patch.object(cuda, '_resolve_backend', return_value=('CUDA', (HostCupy(), None))), \
             patch.object(cuda, 'acceleration_info', return_value=info), \
             patch.object(cuda, 'plan_vram_allocation', return_value=plan), \
             patch.object(cuda, '_relieve_pool_pressure'), \
             patch.object(cuda, '_pool_stats', return_value=(0, 0)), \
             patch.object(cuda, '_refresh_info', side_effect=lambda value, _cp: value):
            for fidelity in ('Balanced', 'Faithful', 'Exact'):
                for rendering in ('RGB nearest', 'Perceptual match'):
                    with self.subTest(fidelity=fidelity, rendering=rendering):
                        result, meta = cuda.palette_indices_rgba(source, PALETTE, tuple(range(4)), (),
                            color_rendering=rendering, color_fidelity=fidelity, skip_white=False,
                            mode='NVIDIA CUDA', performance='High throughput')
                        self.assertIsNotNone(result, meta.reason)
                        self.assertTrue(meta.accelerated)
                        self.assertEqual(result[0][0].tolist(), scalar_choices(SOURCES, PALETTE, rendering, fidelity))

    def test_opencl_kernel_matches_scalar_when_a_device_is_available(self):
        try:
            import pyopencl as cl
            candidates = [(pi, di) for pi, platform in enumerate(cl.get_platforms())
                          for di, _device in enumerate(platform.get_devices())]
        except Exception as exc:
            self.skipTest(f'OpenCL device unavailable: {exc}')
        if not candidates:
            self.skipTest('OpenCL device unavailable')
        pi, di = candidates[0]
        backend = f'opencl:{pi}:{di}'
        route = universal.RouteInfo('palette_match', 'palette_match', backend,
            'OpenCL', 'test device', 'test device', True, len(SOURCES))
        with Image.fromarray(np.asarray([SOURCES], np.uint8)) as source, \
             patch.object(universal, 'select_route', return_value=route):
            for fidelity in ('Balanced', 'Faithful'):
                result, meta = universal.palette_indices_rgba(source, PALETTE, tuple(range(4)), (),
                    color_fidelity=fidelity, skip_white=False)
                self.assertEqual(meta['backend_id'], backend, meta)
                self.assertEqual(result[0][0].tolist(), scalar_choices(SOURCES, PALETTE, 'Perceptual match', fidelity))


class BoundedColorTransformTests(unittest.TestCase):
    def test_chunk_boundary_views_match_independent_scalar_color_space(self):
        rng = np.random.default_rng(148051)
        colors = rng.integers(0, 256, (257, 259, 3), dtype=np.uint8)
        for source in (colors, colors[:, ::-1], colors.transpose(1, 0, 2)):
            actual = universal._oklab_cpu(source)
            flat = source.reshape(-1, 3)
            probes = (0, 1, 65535, 65536, len(flat)-1)
            expected = [rgb_to_oklab(tuple(map(int, flat[i]))) for i in probes]
            np.testing.assert_allclose(actual.reshape(-1, 3)[list(probes)], expected, atol=3e-7, rtol=1e-5)

    def test_normalized_input_is_borrowed_but_never_modified(self):
        source = np.linspace(0, 1, 900, dtype=np.float32).reshape(10, 30, 3)
        expected = source.copy()
        source.setflags(write=False)
        self.assertIs(universal._rgb01(source), source)
        universal._oklab_cpu(source)
        universal.perceptual_pair(source, source, gpu_mode='CPU')
        np.testing.assert_array_equal(source, expected)
        for array, wanted in ((np.array([[0, 1, 255]], np.uint8), [[0, 1/255, 1]]),
                              (np.array([[-.1, .5, 1.1]], np.float32), [[0, .5, 1]])):
            np.testing.assert_allclose(universal._rgb01(array), wanted, atol=1e-8)


if __name__ == '__main__':
    unittest.main()
