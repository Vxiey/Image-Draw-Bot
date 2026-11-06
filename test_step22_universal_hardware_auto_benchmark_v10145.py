import tempfile
import unittest
from pathlib import Path
from unittest import mock

import GpuHardware as gh
import UniversalHardwareBenchmark as uhb
import AutoUniversalGpuSetup as aug
from WindowsGpuDiscovery import WindowsGpuAdapter
from PerformanceAutoTuner import build_recommendation


class Step22UniversalHardwareTests(unittest.TestCase):
    def tearDown(self):
        gh._CACHE = None
        gh._ALL_CACHE = None

    def test_windows_dxgi_classifies_nvidia_amd_and_intel(self):
        rows = [
            WindowsGpuAdapter(0, "NVIDIA GeForce RTX 5080", 0x10DE, 1, 16 * 1024**3, driver_version="1"),
            WindowsGpuAdapter(1, "AMD Radeon RX 7900 XTX", 0x1002, 2, 24 * 1024**3, driver_version="2"),
            WindowsGpuAdapter(2, "Intel(R) Arc(TM) A770 Graphics", 0x8086, 3, 8 * 1024**3, driver_version="3"),
        ]
        with mock.patch.object(gh.os, "name", "nt"), \
             mock.patch.object(gh, "_windows_adapters", return_value=rows):
            devices = gh._detect_all_with_windows()
        self.assertEqual([d.vendor for d in devices], ["NVIDIA", "AMD", "Intel"])
        self.assertEqual(devices[1].memory_total_mb, 24576)
        self.assertEqual(devices[2].vendor_id, "8086")
        self.assertFalse(devices[2].integrated)

    def test_nvidia_smi_data_merges_without_dropping_amd_intel(self):
        generic = [
            gh.GpuDevice(0, "NVIDIA GeForce RTX 5080", 4096, "old", source="Windows DXGI", vendor="NVIDIA"),
            gh.GpuDevice(1, "AMD Radeon RX 7800 XT", 16384, "amd", source="Windows DXGI", vendor="AMD"),
            gh.GpuDevice(2, "Intel Arc A770", 16384, "intel", source="Windows DXGI", vendor="Intel"),
        ]
        merged = gh._merge_devices(generic, (gh.NvidiaGpu(0, "NVIDIA GeForce RTX 5080", 16303, "new", "01:00", "nvidia-smi"),))
        self.assertEqual({d.vendor for d in merged}, {"NVIDIA", "AMD", "Intel"})
        nvidia = next(d for d in merged if d.vendor == "NVIDIA")
        self.assertEqual(nvidia.memory_total_mb, 16303)
        self.assertEqual(nvidia.driver_version, "new")

    def test_large_amd_opencl_can_win_while_small_workload_stays_cpu(self):
        small = []
        large = []
        for workload in uhb.WORKLOADS:
            small += [
                uhb.BackendScore("cpu:numpy", "CPU/NumPy", "CPU", "CPU", workload, 128, 16384, 1, 100.0),
                uhb.BackendScore("opencl:0:0", "OpenCL", "AMD", "Radeon", workload, 128, 16384, 2, 70.0, 16384, integrated=False),
            ]
            large += [
                uhb.BackendScore("cpu:numpy", "CPU/NumPy", "CPU", "CPU", workload, 512, 262144, 4, 65.0),
                uhb.BackendScore("opencl:0:0", "OpenCL", "AMD", "Radeon", workload, 512, 262144, 1, 260.0, 16384, integrated=False),
            ]
        prefs = uhb.build_preferences(small_scores=small, large_scores=large)
        self.assertEqual(prefs["primary_backend"]["vendor"], "AMD")
        self.assertEqual(prefs["workloads"]["oklab"]["backend"], "OpenCL")
        self.assertGreaterEqual(prefs["workloads"]["oklab"]["min_pixels"], 65536)
        self.assertGreater(prefs["primary_backend"]["safe_memory_budget_mb"], 4096)

    def test_integrated_gpu_memory_budget_is_conservative(self):
        score = uhb.BackendScore("opencl:0:0", "OpenCL", "Intel", "Intel iGPU", "oklab", 512, 1, 1, 100,
                                 total_memory_mb=16384, integrated=True)
        self.assertLessEqual(uhb._safe_gpu_budget_mb(score), 4096)

    def test_profile_round_trip_and_signature_validation(self):
        payload = {"version": 1, "hardware_signature": "abc", "workload_preferences": {}, "primary_backend": {}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hardware.json"
            uhb.save_hardware_profile(payload, path=path)
            loaded = uhb.load_hardware_profile(path=path, validate_current=False)
            self.assertEqual(loaded["hardware_signature"], "abc")
            with mock.patch.object(uhb, "hardware_snapshot", return_value={"hardware_signature": "different"}):
                self.assertIsNone(uhb.load_hardware_profile(path=path, validate_current=True))

    def test_performance_tuner_keeps_renderer_cpu_for_amd_but_records_opencl(self):
        hardware = {
            "hardware_signature": "sig",
            "detected_gpus": [{"vendor": "AMD", "name": "Radeon", "compute_benchmarked": True}],
            "primary_backend": {"backend": "OpenCL", "vendor": "AMD", "device": "Radeon", "safe_memory_budget_mb": 8192, "tile_size": 2048},
        }
        rec = build_recommendation(
            scheduler_result={"logical_cpus": 16, "recommended_workers": 8, "best_score": 4.0},
            available_mb=12000,
            gpu_result={"used_gpu": False, "accelerated": False, "device": "CPU"},
            hardware_result=hardware,
        )
        self.assertEqual(rec.gpu_mode, "CPU")
        self.assertTrue(rec.universal_gpu_detected)
        self.assertEqual(rec.primary_compute_backend, "OpenCL")
        self.assertEqual(rec.primary_compute_vendor, "AMD")
        self.assertEqual(rec.safe_gpu_memory_mb, 8192)

    def test_cpu_only_benchmark_always_has_fallback(self):
        with mock.patch.object(uhb, "benchmark_cuda", return_value=[]), \
             mock.patch.object(uhb, "benchmark_opencl", return_value=[]), \
             mock.patch.object(uhb, "hardware_snapshot", return_value={"hardware_signature": "cpu", "gpus": [], "logical_cpus": 4}):
            result = uhb.run_universal_hardware_benchmark(save=False, small_size=64, large_size=256, repeats=1, refresh_hardware=False)
        self.assertTrue(result["cpu_fallback_available"])
        self.assertEqual(result["primary_backend"]["backend_id"], "cpu:numpy")

    def test_optional_amd_intel_setup_is_nonfatal_when_not_needed(self):
        with mock.patch.object(aug, "_target_vendors", return_value=()), mock.patch.object(aug, "_write_state"):
            result = aug.ensure_universal_gpu_backend(python="python")
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "not-needed")

    def test_source_startup_contains_vendor_neutral_backend_bootstrap(self):
        base = Path(__file__).resolve().parent
        start = (base / "Start.bat").read_text(encoding="utf-8", errors="replace")
        req = (base / "requirements-gpu-universal.txt").read_text(encoding="utf-8", errors="replace").lower()
        self.assertIn("AutoUniversalGpuSetup.py --ensure", start)
        self.assertIn("AMD / Intel", start)
        self.assertIn("pyopencl", req)

    def test_windows_release_bundles_universal_opencl_benchmark(self):
        base = Path(__file__).resolve().parent
        build = (base / "build_exe.py").read_text(encoding="utf-8", errors="replace")
        self.assertIn("requirements-gpu-universal.txt", build)
        self.assertIn("--collect-all', 'pyopencl", build)
        self.assertIn("UniversalHardwareBenchmark", build)



if __name__ == "__main__":
    unittest.main()
