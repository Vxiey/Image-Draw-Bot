import unittest
from unittest import mock

import AutoGpuSetup as ags


class AutoGpuSetupV1085Tests(unittest.TestCase):
    def test_conflicting_cupy_packages_removes_other_cuda_families(self):
        installed = {"cupy", "cupy-cuda12x", "cupy-cuda13x", "requests"}
        self.assertEqual(
            ags.conflicting_cupy_packages(installed, desired="cupy-cuda12x"),
            ["cupy", "cupy-cuda13x"],
        )

    def test_no_nvidia_is_successful_skip(self):
        with mock.patch.object(ags, "best_nvidia_gpu", return_value=None), \
             mock.patch.object(ags, "_write_state"):
            result = ags.ensure_gpu_backend(python="python")
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "no-nvidia")
        self.assertFalse(result.installed)

    def test_ready_gpu_does_not_reinstall(self):
        gpu = mock.Mock(name="gpu", name_attr="unused")
        gpu.name = "NVIDIA GeForce RTX 5080"
        gpu.driver_version = "591.74"
        with mock.patch.object(ags, "best_nvidia_gpu", return_value=gpu), \
             mock.patch.object(ags, "_smoke_test", return_value=(True, "CUDA ready on RTX 5080")), \
             mock.patch.object(ags, "_pip_install_backend") as installer, \
             mock.patch.object(ags, "_write_state"):
            result = ags.ensure_gpu_backend(python="python")
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "ready")
        installer.assert_not_called()

    def test_missing_backend_auto_installs_then_smoke_tests_again(self):
        gpu = mock.Mock()
        gpu.name = "NVIDIA GeForce RTX 5080"
        gpu.driver_version = "591.74"
        with mock.patch.object(ags, "best_nvidia_gpu", return_value=gpu), \
             mock.patch.object(ags, "_smoke_test", side_effect=[(False, "CuPy missing"), (True, "CUDA ready")]) as smoke, \
             mock.patch.object(ags, "_pip_install_backend", return_value=(True, "installed")) as installer, \
             mock.patch.object(ags, "_write_state"):
            result = ags.ensure_gpu_backend(python="python")
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "installed")
        self.assertTrue(result.installed)
        self.assertEqual(smoke.call_count, 2)
        installer.assert_called_once_with("python")

    def test_failed_install_keeps_cpu_fallback(self):
        gpu = mock.Mock()
        gpu.name = "NVIDIA GeForce RTX 5080"
        gpu.driver_version = "591.74"
        with mock.patch.object(ags, "best_nvidia_gpu", return_value=gpu), \
             mock.patch.object(ags, "_smoke_test", return_value=(False, "missing")), \
             mock.patch.object(ags, "_pip_install_backend", return_value=(False, "network error")), \
             mock.patch.object(ags, "_write_state"):
            result = ags.ensure_gpu_backend(python="python")
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "install-failed")
        self.assertIn("CPU fallback", result.message)

    def test_start_bat_uses_automatic_gpu_bootstrap(self):
        text = (ags.BASE / "Start.bat").read_text(encoding="utf-8", errors="replace")
        self.assertIn("-E -s SourceStartup.py", text)
        source = (ags.BASE / "SourceStartup.py").read_text(encoding="utf-8")
        self.assertIn("'AutoGpuSetup.py'", source)
        self.assertIn("'--ensure'", source)
        self.assertIn("'--force'", source)

    def test_manual_gpu_installer_uses_same_bootstrap(self):
        text = (ags.BASE / "Install-GPU-NVIDIA.bat").read_text(encoding="utf-8", errors="replace")
        self.assertIn("SourceStartup.py --setup-gpu nvidia --force --require-nvidia", text)


if __name__ == "__main__":
    unittest.main()
