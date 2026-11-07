"""Low-VRAM portrait paths must keep the full-frame CUDA pixel contract.

The tests read an existing tracked fixture. Native CUDA kernel bodies execute
as ordinary C++ through a small ABI boundary; this is not a physical GPU test.
Gaussian convolution uses an independent finite-support NumPy reference, so
the production tile slicing, halo and global geometry are all exercised.
"""
from contextlib import ExitStack
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import GpuAcceleration as gpu
from test_gpu_execution_regressions import FakeCupy


FIXTURE = Path(__file__).resolve().parent / 'golden-regression' / 'small-detail-preservation.png'
PROFILE = {'structure_weight': .42, 'dark_weight': .12, 'centre_bias': .20}


class HostKernel:
    """Run the exact production scalar kernel, replacing only CUDA scheduling."""
    def __init__(self, compiler, directory, source, name):
        signature = re.search(r'void\s+' + re.escape(name) + r'\s*\((.*?)\)\s*\{', source, re.S).group(1)
        self.parameters = [parameter.strip() for parameter in signature.split(',')]
        self.names = [parameter.rsplit(None, 1)[-1] for parameter in self.parameters]
        self.inputs = [i for i, parameter in enumerate(self.parameters) if parameter.startswith('const float*')]
        self.outputs = [i for i, parameter in enumerate(self.parameters) if parameter.startswith('float*')]
        self.scalars = [i for i, parameter in enumerate(self.parameters) if '*' not in parameter]
        main = ['int main() {',
                '#ifdef _WIN32', '_setmode(_fileno(stdin), _O_BINARY);',
                '_setmode(_fileno(stdout), _O_BINARY);', '#endif']
        for index in self.scalars:
            parameter, variable = self.parameters[index], self.names[index]
            main += [parameter + ';', f'std::cin.read(reinterpret_cast<char*>(&{variable}), sizeof({variable}));']
        for index in self.inputs + self.outputs:
            variable = self.names[index]
            main.append(f'std::vector<float> {variable}(w*h);')
            if index in self.inputs:
                main.append(f'std::cin.read(reinterpret_cast<char*>({variable}.data()), w*h*sizeof(float));')
        arguments = ','.join(name + ('.data()' if i in self.inputs + self.outputs else '')
                             for i, name in enumerate(self.names))
        main += ['blockDim.x=1; blockIdx.x=0;',
                 f'for(threadIdx.x=0; threadIdx.x<w*h; ++threadIdx.x) {name}({arguments});']
        for index in self.outputs:
            main.append(f'std::cout.write(reinterpret_cast<char*>({self.names[index]}.data()), w*h*sizeof(float));')
        main.append('}')
        prefix = ('#include <cmath>\n#include <iostream>\n#include <vector>\n'
                  '#ifdef _WIN32\n#include <fcntl.h>\n#include <io.h>\n#endif\n'
                  '#define __device__\n#define __forceinline__ inline\n#define __global__\n'
                  'struct Dim { int x; }; static Dim blockDim, blockIdx, threadIdx;\n')
        cpp = directory / (name + '.cpp')
        self.executable = directory / (name + ('.exe' if sys.platform == 'win32' else ''))
        cpp.write_text(prefix + source + '\n' + '\n'.join(main), encoding='utf-8')
        subprocess.run([compiler, '-O2', '-ffp-contract=off', str(cpp), '-o', str(self.executable)],
                       capture_output=True, check=True, timeout=30)
        self.launches = []

    def __call__(self, _grid, _block, arguments):
        if len(arguments) != len(self.parameters):
            raise AssertionError('Production CUDA call does not match its own kernel ABI')
        scalar_values = {}
        payload = []
        for index in self.scalars:
            dtype = np.int32 if self.parameters[index].startswith('int ') else np.float32
            if not isinstance(arguments[index], dtype):
                raise AssertionError(f'{self.names[index]} is not {dtype.__name__}')
            scalar_values[self.names[index]] = arguments[index].item()
            payload.append(arguments[index].tobytes())
        self.launches.append(scalar_values)
        for index in self.inputs:
            payload.append(np.ascontiguousarray(arguments[index], dtype=np.float32).tobytes())
        result = subprocess.run([str(self.executable)], input=b''.join(payload),
                                capture_output=True, check=True, timeout=10)
        count = scalar_values['w'] * scalar_values['h']
        output = np.frombuffer(result.stdout, dtype=np.float32)
        if output.size != count * len(self.outputs):
            raise AssertionError('Host kernel returned an incomplete output')
        for position, index in enumerate(self.outputs):
            arguments[index][...] = output[position*count:(position+1)*count].reshape(arguments[index].shape)


class GaussianReference:
    """Independent separable convolution with the documented default support."""
    def __init__(self):
        self.calls = []

    def gaussian_filter(self, array, *, sigma, mode, truncate=4.0):
        if mode != 'nearest':
            raise AssertionError(mode)
        radius = int(float(sigma) * float(truncate) + .5)
        offsets = np.arange(-radius, radius + 1, dtype=np.float64)
        weights = np.exp(-offsets*offsets/(2.0*float(sigma)*float(sigma)))
        weights /= weights.sum()
        self.calls.append((array.shape, sigma, radius))
        result = array
        for axis in range(array.ndim):
            result = np.apply_along_axis(
                lambda row: np.convolve(np.pad(row, (radius, radius), mode='edge'), weights, mode='valid'),
                axis, result).astype(array.dtype)
        return result


class PortraitTileParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('g++')
        if compiler is None:
            raise unittest.SkipTest('C++ compiler unavailable for the actual CUDA-kernel formula oracle')
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        captured = SimpleNamespace(__version__='portrait-tile-host-oracle', RawKernel=lambda source, name, **kwargs:
            HostKernel(compiler, Path(cls.directory.name), source, name))
        with patch.object(gpu, '_KERNEL_CACHE', {}):
            cls.kernels = gpu._kernels(captured)

    def setUp(self):
        with Image.open(FIXTURE) as existing:
            self.source = existing.convert('L')
        self.addCleanup(self.source.close)
        self.cp = FakeCupy()
        self.cp.asnumpy = lambda array: np.array(array, copy=True)
        self.gaussian = GaussianReference()
        self.info = gpu.AccelerationInfo('Auto', 'CUDA', True, 'Host ABI boundary', 4096, 2048,
                                         vram_budget_mb=1024)
        for kernel in self.kernels:
            kernel.launches.clear()

    def context(self, *, rows=None, real_plan=False):
        stack = ExitStack()
        stack.enter_context(patch.object(gpu, '_resolve_backend', return_value=('CUDA', (self.cp, self.gaussian))))
        stack.enter_context(patch.object(gpu, 'acceleration_info', return_value=self.info))
        stack.enter_context(patch.object(gpu, '_kernels', return_value=self.kernels))
        stack.enter_context(patch.object(gpu, 'best_nvidia_gpu', return_value=None))
        if not real_plan:
            stack.enter_context(patch.object(gpu, 'plan_vram_allocation', return_value={
                'mode': 'full' if rows is None else 'tiled', 'tile_rows': rows or self.source.height,
                'workspace_mb': 1}))
        return stack

    def enhanced(self, image, focus, rows=None):
        with self.context(rows=rows):
            result, info, session = gpu.enhance_portrait(
                image, .42, .97, focus, 54, performance='High throughput')
        try:
            self.assertIsNotNone(result, info.reason)
            return np.array(result)
        finally:
            if result is not None:
                result.close()
            gpu.release_analysis_session(session, trim_cache=False)

    def test_low_vram_subject_focus_keeps_exact_full_frame_pixels(self):
        with self.source.resize((96, 80), Image.Resampling.LANCZOS) as image:
            expected = self.enhanced(image, True)
            for rows in (1, 7, 23, 79):
                with self.subTest(rows=rows):
                    actual = self.enhanced(image, True, rows)
                    np.testing.assert_array_equal(actual, expected)

    def test_no_focus_and_global_minimum_dimensions_keep_existing_pixels(self):
        for shape, focus in (((67, 53), False), ((19, 53), True), ((24, 24), True)):
            with self.subTest(shape=shape, focus=focus), self.source.resize(shape) as image:
                expected = self.enhanced(image, focus)
                np.testing.assert_array_equal(self.enhanced(image, focus, 7), expected)

    def test_tiled_saliency_keeps_global_focus_and_full_gaussian_support(self):
        with self.source.resize((96, 80), Image.Resampling.LANCZOS) as image:
            for focus in (False, True):
                with self.context():
                    expected, info = gpu.saliency(image, focus, PROFILE, performance='High throughput')
                self.assertIsNotNone(expected, info.reason)
                for rows in (1, 7, 23):
                    with self.subTest(focus=focus, rows=rows), self.context(rows=rows):
                        actual, info = gpu.saliency(image, focus, PROFILE, performance='High throughput')
                        self.assertIsNotNone(actual, info.reason)
                        np.testing.assert_array_equal(actual, expected)

    def test_session_analysis_keeps_full_frame_saliency_and_gradients(self):
        with self.source.resize((67, 53)) as image, self.context():
            enhanced, info, session = gpu.enhance_portrait(
                image, .42, .97, True, 54, performance='High throughput')
            try:
                actual, _ = gpu.saliency(enhanced, True, PROFILE, performance='High throughput', session=session)
                expected = session.saliency_map.copy().ravel()
                np.testing.assert_array_equal(actual, expected)
                gradients, _ = gpu.sobel(enhanced, performance='High throughput', session=session,
                                         subject_focus=True, profile=PROFILE)
                np.testing.assert_array_equal(gradients[0], session.gx.ravel())
                np.testing.assert_array_equal(gradients[1], session.gy.ravel())
                self.assertEqual(len(self.kernels[1].launches), 1)
            finally:
                if enhanced is not None:
                    enhanced.close()
                gpu.release_analysis_session(session, trim_cache=False)

    def test_low_memory_plan_reserves_the_entire_native_filter_halo(self):
        from dataclasses import replace
        self.info = replace(self.info, free_vram_mb=1, vram_budget_mb=1)
        original = gpu.plan_vram_allocation
        observed = []
        def plan(*args, **kwargs):
            value = original(*args, **kwargs)
            observed.append((dict(kwargs), value))
            return value
        with self.context(real_plan=True), patch.object(gpu, 'plan_vram_allocation', plan):
            output, info = gpu.saliency(self.source, True, PROFILE, performance='High throughput')
        self.assertIsNotNone(output, info.reason)
        self.assertEqual(observed[0][0]['overlap'], 5)
        self.assertEqual(observed[0][1]['mode'], 'tiled')
        self.assertTrue(all(radius == 5 for _shape, _sigma, radius in self.gaussian.calls))
        max_rows = max(shape[0] for shape, _sigma, _radius in self.gaussian.calls)
        self.assertLessEqual(max_rows, observed[0][1]['tile_rows'] + 10)

    def test_stop_after_first_tile_does_not_start_more_native_work(self):
        stopped = False
        copies = 0
        def copied(array):
            nonlocal stopped, copies
            copies += 1
            stopped = True
            return np.array(array, copy=True)
        self.cp.asnumpy = copied
        for operation in ('enhance', 'saliency'):
            with self.subTest(operation=operation):
                stopped, copies = False, 0
                with self.context(rows=7), self.assertRaises(InterruptedError):
                    if operation == 'enhance':
                        gpu.enhance_portrait(self.source, .42, .97, True, 54,
                                             performance='High throughput', cancelled=lambda: stopped)
                    else:
                        gpu.saliency(self.source, True, PROFILE,
                                     performance='High throughput', cancelled=lambda: stopped)
                self.assertEqual(copies, 1)
        self.assertEqual(self.source.size, (360, 240))

    def test_failed_native_tile_retains_cpu_fallback_and_source_ownership(self):
        for error in (MemoryError('temporary VRAM pressure'), RuntimeError('native kernel failure')):
            with self.subTest(error=type(error).__name__), self.context(rows=7), \
                    patch.object(gpu, '_BACKEND_CACHE', object()), patch.object(gpu, '_DISABLED_REASON', ''), \
                    patch.object(gpu, '_BACKEND_DEVICE_ID', None), \
                    patch.object(self.gaussian, 'gaussian_filter', side_effect=error):
                result, info, session = gpu.enhance_portrait(
                    self.source, .42, .97, True, 54, performance='High throughput')
                self.assertIsNone(result)
                self.assertIsNone(session)
                self.assertFalse(info.accelerated)
                self.assertIn(type(error).__name__, info.reason)
                self.assertEqual(gpu._BACKEND_CACHE is None, isinstance(error, RuntimeError))
        self.assertEqual(self.source.size, (360, 240))
        self.source.getpixel((0, 0))


if __name__ == '__main__':
    unittest.main()
