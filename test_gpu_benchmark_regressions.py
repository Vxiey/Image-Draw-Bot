import builtins
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import UniversalHardwareBenchmark as bench


class GpuBenchmarkRegressionTests(unittest.TestCase):
    def test_cpu_identifier_avoids_unneeded_platform_queries(self):
        with mock.patch.dict(bench.os.environ, {"PROCESSOR_IDENTIFIER": "  Test CPU  "}), \
             mock.patch.object(bench.platform, "processor") as processor, \
             mock.patch.object(bench.platform, "machine") as machine:
            self.assertEqual(bench.cpu_name(), "Test CPU")
        processor.assert_not_called()
        machine.assert_not_called()

    def test_unavailable_cpu_probe_uses_remaining_fallback(self):
        with mock.patch.dict(bench.os.environ, {"PROCESSOR_IDENTIFIER": ""}), \
             mock.patch.object(bench.platform, "processor", side_effect=OSError("WMI unavailable")), \
             mock.patch.object(bench.platform, "machine", return_value="AMD64"):
            self.assertEqual(bench.cpu_name(), "AMD64")

    def test_version_metadata_does_not_import_compute_libraries(self):
        versions = {"cupy-cuda12x": "14.2.0", "pyopencl": "2026.1", "nvidia-cuda-runtime-cu12": "12.9.79"}

        def version(name):
            if name not in versions:
                raise bench.metadata.PackageNotFoundError(name)
            return versions[name]

        real_import = builtins.__import__

        def checked_import(name, *args, **kwargs):
            if name.split(".")[0] in {"cupy", "cupyx", "pyopencl"}:
                raise AssertionError("A version probe must not load GPU libraries")
            return real_import(name, *args, **kwargs)

        with mock.patch.object(bench.metadata, "version", side_effect=version), \
             mock.patch.dict(sys.modules, {"cupy": None, "pyopencl": None}), \
             mock.patch("builtins.__import__", side_effect=checked_import):
            result = bench.runtime_versions()
        self.assertEqual(result["cupy"], "14.2.0")
        self.assertEqual(result["pyopencl"], "2026.1")
        self.assertEqual(result["nvidia-cuda-runtime-cu12"], "12.9.79")

    def test_missing_optional_metadata_is_nonfatal(self):
        with mock.patch.object(bench.metadata, "version", side_effect=bench.metadata.PackageNotFoundError), \
             mock.patch.dict(sys.modules, {"cupy": None, "pyopencl": None}):
            result = bench.runtime_versions()
        self.assertEqual(result["cupy"], "unavailable")
        self.assertEqual(result["pyopencl"], "unavailable")

    def test_corrupt_profile_encoding_shape_and_version_are_recoverable(self):
        samples = [b"\xff\xfe", b"not JSON", b"[]", b"null", b"{\"version\":\"broken\"}",
                   b"{\"version\":[]}", b"{\"version\":NaN}", b"{\"version\":true}"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hardware.json"
            for raw in samples:
                with self.subTest(raw=raw):
                    path.write_bytes(raw)
                    with mock.patch.object(bench, "hardware_snapshot", side_effect=AssertionError("invalid profile")):
                        self.assertIsNone(bench.load_hardware_profile(path=path, validate_current=False))
                        self.assertTrue(bench.profile_needs_benchmark(path=path)[0])

    def test_explicit_empty_preference_does_not_load_saved_profile(self):
        with mock.patch.object(bench, "load_hardware_profile", side_effect=AssertionError("unexpected disk lookup")):
            result = bench.preferred_backend("oklab", pixels=1_000_000, profile={})
        self.assertEqual(result["backend_id"], "cpu:numpy")

    def test_invalid_preference_shapes_and_thresholds_use_cpu(self):
        profiles = [[], {"workload_preferences": []}, {"workload_preferences": {"oklab": []}},
                    {"workload_preferences": {"oklab": {"backend_id": "cuda:0", "min_pixels": "bad"}}},
                    {"workload_preferences": {"oklab": {"backend_id": "cuda:0", "min_pixels": float("inf")}}},
                    {"workload_preferences": {"oklab": {"backend_id": "cuda:0", "min_pixels": -1}}}]
        for profile in profiles:
            with self.subTest(profile=profile):
                self.assertEqual(bench.preferred_backend("oklab", pixels=100_000, profile=profile)["backend_id"],
                                 "cpu:numpy")

    def test_valid_measured_threshold_still_selects_gpu(self):
        profile = {"workload_preferences": {"oklab": {"backend_id": "opencl:0:0", "min_pixels": 80_000}}}
        self.assertEqual(bench.preferred_backend("oklab", pixels=79_999, profile=profile)["backend_id"], "cpu:numpy")
        self.assertEqual(bench.preferred_backend("oklab", pixels=80_000, profile=profile)["backend_id"], "opencl:0:0")

    def test_nonfinite_benchmark_results_cannot_win_backend_selection(self):
        cpu = bench.BackendScore("cpu:numpy", "CPU/NumPy", "CPU", "CPU", "oklab", 512, 262144, 1, 100)
        gpu = bench.BackendScore("cuda:0", "CUDA/CuPy", "NVIDIA", "GPU", "oklab", 512, 262144, 1, 200)
        for bad in (replace(gpu, throughput_mp_s=float("inf")),
                    replace(gpu, throughput_mp_s=float("nan")),
                    replace(gpu, elapsed_ms=float("nan")),
                    replace(gpu, throughput_mp_s="200")):
            with self.subTest(score=bad):
                preferences = bench.build_preferences(small_scores=[cpu], large_scores=[cpu, bad])
                self.assertEqual(preferences["workloads"]["oklab"]["backend_id"], "cpu:numpy")
                json.dumps(preferences, allow_nan=False)

    def test_memory_recommendation_respects_reported_free_memory_including_zero(self):
        score = bench.BackendScore("cuda:0", "CUDA/CuPy", "NVIDIA", "GPU", "oklab", 512, 262144,
                                   1, 200, total_memory_mb=16384, free_memory_mb=100)
        self.assertEqual(bench._safe_gpu_budget_mb(score), 80)
        self.assertEqual(bench._safe_gpu_budget_mb(replace(score, free_memory_mb=0)), 0)
        self.assertGreater(bench._safe_gpu_budget_mb(replace(score, free_memory_mb=None)), 4096)
        small = replace(score, total_memory_mb=256, free_memory_mb=None)
        self.assertLess(bench._safe_gpu_budget_mb(small), 256)
        self.assertLessEqual(bench._safe_gpu_budget_mb(replace(score, integrated=True)), 80)


if __name__ == "__main__":
    unittest.main()
