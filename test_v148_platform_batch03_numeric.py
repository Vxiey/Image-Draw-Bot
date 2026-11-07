from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from ImageGradients import luminance_edges
import UniversalGpuAcceleration as gpu


def numpy_gradient(value):
    gradients = [np.gradient(value, axis=axis) if value.shape[axis] > 1 else np.zeros_like(value)
                 for axis in (0, 1)]
    return np.sqrt(gradients[0] ** 2 + gradients[1] ** 2)


class EdgeBoundaryTests(unittest.TestCase):
    def test_thin_axes_outer_boundaries_and_interior_match_gradient_oracle(self):
        rng = np.random.default_rng(91)
        for shape in ((1, 1), (1, 2), (2, 1), (2, 2), (1, 17), (17, 1), (19, 23)):
            lum = rng.random(shape, dtype=np.float32)
            actual, _ = gpu.edge_magnitude(lum, gpu_mode="CPU")
            np.testing.assert_array_equal(actual, numpy_gradient(lum))
        np.testing.assert_array_equal(luminance_edges(np.array([[0, 1]], dtype=np.float32)), [[1, 1]])

    def test_cuda_formula_matches_cpu_with_array_compatible_backend(self):
        cp = SimpleNamespace(**{name: getattr(np, name) for name in ("asarray", "float32", "zeros_like", "sqrt")})
        cp.asnumpy = np.asarray
        cp.cuda = SimpleNamespace(Device=lambda _index: mock.MagicMock(),
                                  Stream=SimpleNamespace(null=SimpleNamespace(synchronize=lambda: None)))
        route = gpu.RouteInfo("edge_map", "edge_map", "cuda:0", "CUDA", "NVIDIA", "fake", True, 2)
        for lum in (np.array([[0, 1]], dtype=np.float32), np.arange(12, dtype=np.float32).reshape(4, 3)):
            with mock.patch.dict(sys.modules, {"cupy": cp}), mock.patch.object(gpu, "select_route", return_value=route):
                actual, metadata = gpu.edge_magnitude(lum)
            self.assertTrue(metadata["accelerated"])
            np.testing.assert_array_equal(actual, numpy_gradient(lum))

    def test_nonfinite_luminance_does_not_dispatch_or_quarantine_backend(self):
        for value in (np.nan, np.inf, -np.inf):
            with mock.patch.object(gpu, "select_route") as route, \
                 mock.patch.object(gpu, "_mark_failed") as failed, self.assertRaises(ValueError):
                gpu.edge_magnitude([[value]])
            route.assert_not_called()
            failed.assert_not_called()

    def test_opencl_edge_kernel_source_matches_cpu_oracle(self):
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("C++ compiler is unavailable for the host kernel-formula oracle")
        kernel = gpu._OPENCL_SOURCE.split("__kernel void ds_edge_kernel", 1)[1].split("__kernel", 1)[0]
        source = (
            "#include <cmath>\n#include <algorithm>\n#include <iostream>\n#include <iomanip>\n"
            "#include <vector>\nusing std::max; using std::min;\n"
            "#define __global\nstatic int thread_index; int get_global_id(int){return thread_index;}\n"
            "void ds_edge_kernel" + kernel +
            '\nint main(){int w,h;std::cin>>w>>h;std::vector<float> src(w*h),dst(w*h);'
            'for(float& v:src)std::cin>>v;'
            'for(thread_index=0;thread_index<w*h;++thread_index)ds_edge_kernel(src.data(),dst.data(),w,h);'
            'std::cout<<std::setprecision(9);for(float v:dst)std::cout<<v<<" ";}\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cpp = root / "edge.cpp"
            executable = root / ("edge.exe" if sys.platform == "win32" else "edge")
            cpp.write_text(source, encoding="utf-8")
            subprocess.run([compiler, "-O2", str(cpp), "-o", str(executable)],
                           capture_output=True, text=True, check=True, timeout=30)
            for shape in ((1, 1), (1, 2), (2, 1), (2, 2), (7, 11)):
                lum = np.random.default_rng(92).random(shape, dtype=np.float32)
                payload = f"{shape[1]} {shape[0]} " + " ".join(str(float(value)) for value in lum.flat)
                completed = subprocess.run([str(executable)], input=payload, capture_output=True,
                                           text=True, check=True, timeout=10)
                output = np.fromstring(completed.stdout, sep=" ", dtype=np.float32).reshape(shape)
                np.testing.assert_allclose(output, numpy_gradient(lum), rtol=1e-6, atol=1e-7)


class PaletteAllocationTests(unittest.TestCase):
    def test_single_buffer_compositing_preserves_exact_previous_values(self):
        raw = np.random.default_rng(93).integers(0, 256, (64, 91, 4), dtype=np.uint8)
        for opacity in (None, 255, 0, 1, 254):
            source = raw.copy()
            if opacity is not None:
                source[..., 3] = opacity
            alpha = source[..., 3].astype(np.float32)
            expected = np.where(alpha[..., None] >= 255, source[..., :3].astype(np.float32),
                                (source[..., :3].astype(np.float32) * alpha[..., None]
                                 + 255 * (255 - alpha[..., None])) / 255)
            actual, visible = gpu._rgba_visible_rgb(source)
            np.testing.assert_array_equal(actual, expected)
            np.testing.assert_array_equal(visible, alpha > 0)
            np.testing.assert_array_equal(source, raw if opacity is None else np.dstack((raw[..., :3], np.full(raw.shape[:2], opacity, dtype=np.uint8))))

    def test_duplicate_candidates_keep_first_tie_and_invalid_indices_fail_closed(self):
        with Image.new("RGB", (1, 1), "black") as image:
            palette = [(0, 0, 0), (0, 0, 0)]
            (indices, _), _ = gpu.palette_indices_rgba(image, palette, [1, 1, 0, 0], [], gpu_mode="CPU")
            self.assertEqual(indices[0, 0], 1)
            for value in (-1, 2, True, 1.5, "1"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    gpu.palette_indices_rgba(image, palette, [value], [], gpu_mode="CPU")
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))

    def test_pairwise_distances_match_dense_reference_and_bound_scratch_rows(self):
        colors = np.random.default_rng(94).integers(0, 256, (777, 3), dtype=np.uint8)
        lab = gpu._oklab_cpu(colors)
        delta = lab[:, None, :] - lab[None, :, :]
        expected = np.sqrt(np.sum(delta * delta, axis=2, dtype=np.float32)) * 100
        shapes = []
        original = gpu._squared_color_distances
        def tracked(source, palette):
            shapes.append((len(source), len(palette)))
            return original(source, palette)
        with mock.patch.object(gpu, "_squared_color_distances", side_effect=tracked):
            actual, _ = gpu.pairwise_oklab_distance(colors, gpu_mode="CPU")
        np.testing.assert_array_equal(actual, expected)
        self.assertGreater(len(shapes), 1)
        self.assertTrue(all(rows <= 256 and rows * columns <= 1_048_576 for rows, columns in shapes))

    def test_pairwise_cancellation_interrupts_between_row_tiles(self):
        count = [0]
        original = gpu._squared_color_distances
        def tracked(*args):
            count[0] += 1
            return original(*args)
        with mock.patch.object(gpu, "_squared_color_distances", side_effect=tracked), \
             self.assertRaises(InterruptedError):
            gpu._pairwise_lab_distance(np.zeros((777, 3), dtype=np.float32), cancelled=lambda: count[0] >= 1)
        self.assertEqual(count[0], 1)


if __name__ == "__main__":
    unittest.main()
