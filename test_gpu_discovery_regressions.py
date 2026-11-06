import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import GpuHardware as gh
from WindowsGpuDiscovery import WindowsGpuAdapter


class GpuDiscoveryRegressionTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, gh, "_CACHE", gh._CACHE)
        self.addCleanup(setattr, gh, "_ALL_CACHE", gh._ALL_CACHE)
        gh._CACHE = gh._ALL_CACHE = None

    def test_windows_nvidia_executable_ignores_path_cwd_and_environment_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            system = root / "TrustedWindows" / "System32"
            program = root / "TrustedPrograms"
            vendor = program / "NVIDIA Corporation" / "NVSMI"
            malicious = root / "Untrusted"
            for folder in (system, vendor, malicious):
                folder.mkdir(parents=True)
                (folder / "nvidia-smi.exe").write_bytes(b"")
            expected = [str(system / "nvidia-smi.exe"), str(vendor / "nvidia-smi.exe")]
            with mock.patch.object(gh.os, "name", "nt"), \
                 mock.patch.dict(os.environ, {"PATH": str(malicious), "WINDIR": str(malicious),
                                              "ProgramFiles": str(malicious), "ProgramW6432": str(malicious)}), \
                 mock.patch.object(gh, "system_directory", return_value=system), \
                 mock.patch.object(gh, "program_files_directories", return_value=(program, program)), \
                 mock.patch.object(gh.shutil, "which", side_effect=AssertionError("PATH lookup forbidden")):
                self.assertEqual(list(gh._nvidia_smi_candidates()), expected)

    def test_windows_path_api_failure_does_not_use_unsafe_fallback(self):
        with mock.patch.object(gh.os, "name", "nt"), \
             mock.patch.object(gh, "system_directory", side_effect=OSError("unavailable")), \
             mock.patch.object(gh, "program_files_directories", side_effect=OSError("unavailable")), \
             mock.patch.object(gh.shutil, "which") as search:
            self.assertEqual(list(gh._nvidia_smi_candidates()), [])
        search.assert_not_called()

    def test_linux_nvidia_discovery_keeps_path_lookup(self):
        with mock.patch.object(gh.os, "name", "posix"), \
             mock.patch.object(gh.shutil, "which", return_value="/usr/bin/nvidia-smi") as search, \
             mock.patch.object(gh, "system_directory") as windows:
            self.assertEqual(list(gh._nvidia_smi_candidates()), ["/usr/bin/nvidia-smi"])
        search.assert_called_once_with("nvidia-smi")
        windows.assert_not_called()

    def test_exact_model_merge_does_not_overwrite_similar_gpu(self):
        generic = [gh.GpuDevice(0, "NVIDIA RTX A5000", 24576, vendor="NVIDIA"),
                   gh.GpuDevice(1, "NVIDIA RTX A500", 4096, vendor="NVIDIA")]
        enriched = gh.NvidiaGpu(0, "NVIDIA RTX A500", 4095, "new", "01:00.0", "nvidia-smi")
        rows = gh._merge_devices(generic, (enriched,))
        self.assertEqual(len(rows), 2)
        self.assertEqual(next(row for row in rows if "A5000" in row.name).memory_total_mb, 24576)
        self.assertEqual(next(row for row in rows if row.name.endswith("A500")).driver_version, "new")

    def test_same_model_native_fallback_keeps_two_physical_cards(self):
        generic = [gh.GpuDevice(index, "NVIDIA RTX 5080", 16384, vendor="NVIDIA", source="Windows DXGI")
                   for index in (0, 1)]
        fallback = tuple(gh.NvidiaGpu(None, gpu.name, gpu.memory_total_mb, source="Windows DXGI")
                         for gpu in generic)
        rows = gh._merge_devices(generic, fallback)
        self.assertEqual([row.index for row in rows], [0, 1])
        self.assertEqual(len(rows), 2)

    def test_partial_smi_metadata_preserves_native_information(self):
        native = gh.GpuDevice(4, "NVIDIA RTX5080", 16384, "32.0.1.2", "native-id", "Windows DXGI",
                              "NVIDIA", "10DE", "existing-pnp", "existing-processor", False)
        smi = gh.NvidiaGpu(0, "NVIDIA RTX 5080", None, "", "", "nvidia-smi")
        rows = gh._merge_devices([native], (smi,))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].memory_total_mb, 16384)
        self.assertEqual(rows[0].driver_version, "32.0.1.2")
        self.assertEqual(rows[0].bus_id, "native-id")
        self.assertEqual(rows[0].pnp_device_id, "existing-pnp")

    def test_smi_csv_handles_quoted_names_and_unavailable_numeric_fields(self):
        output = ('0, "NVIDIA Device, Revision X", 16384, 591.74, 0000:01:00.0\n'
                  'nan, NVIDIA Broken, 100, 1, 0000:02:00.0\n'
                  '-1, NVIDIA Broken, 100, 1, 0000:02:00.0\n'
                  '1.5, NVIDIA Fractional index, 100, 1, 0000:02:00.0\n'
                  '2, NVIDIA RTX 5080, inf, [N/A], [N/A]\n'
                  '3, NVIDIA RTX A500, -4, 1, 0000:03:00.0\n'
                  '4, , 100, 1, 0000:04:00.0\n'
                  'malformed diagnostic output\n')
        with mock.patch.object(gh, "_nvidia_smi_candidates", return_value=["trusted.exe"]), \
             mock.patch.object(gh, "_run", return_value=output):
            rows = gh._detect_with_nvidia_smi()
        self.assertEqual([row.index for row in rows], [0, 2, 3])
        self.assertEqual(rows[0].name, "NVIDIA Device, Revision X")
        self.assertIsNone(rows[1].memory_total_mb)
        self.assertEqual(rows[1].driver_version, "")
        self.assertEqual(rows[1].bus_id, "")
        self.assertIsNone(rows[2].memory_total_mb)
        self.assertIsNone(gh._parse_int("1.5"))
        self.assertEqual(gh._parse_int("18446744073709551615"), 18446744073709551615)

    def test_one_native_probe_per_full_refresh_and_no_cuda_index_from_dxgi(self):
        adapters = (WindowsGpuAdapter(3, "NVIDIA RTX 5080", 0x10DE, 1, 16 * 1024**3),)
        with mock.patch.object(gh.os, "name", "nt"), \
             mock.patch.object(gh, "_windows_adapters", return_value=adapters) as probe, \
             mock.patch.object(gh, "_detect_with_nvidia_smi", return_value=[]) as smi:
            full = gh.detect_gpus(refresh=True)
            self.assertEqual(gh.detect_gpus(), full)
            self.assertIsNone(gh.detect_nvidia_gpus()[0].index)
        self.assertEqual(full[0].index, 3)
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(smi.call_count, 1)

    def test_nvidia_refresh_invalidates_universal_snapshot(self):
        gh._ALL_CACHE = (gh.GpuDevice(0, "Old GPU", vendor="NVIDIA"),)
        new = gh.NvidiaGpu(0, "New GPU", 8192, source="nvidia-smi")
        with mock.patch.object(gh, "_detect_with_nvidia_smi", return_value=[new]) as smi, \
             mock.patch.object(gh.os, "name", "nt"), \
             mock.patch.object(gh, "_detect_all_with_windows", return_value=[]):
            gh.detect_nvidia_gpus(refresh=True)
            self.assertIsNone(gh._ALL_CACHE)
            self.assertEqual(gh.detect_gpus()[0].name, "New GPU")
        self.assertEqual(smi.call_count, 1)

    def test_native_failure_keeps_nvidia_fallback_without_shell_discovery(self):
        new = gh.NvidiaGpu(0, "RTX", 8192, source="nvidia-smi")
        with mock.patch.object(gh.os, "name", "nt"), \
             mock.patch.object(gh, "_windows_adapters", side_effect=OSError("driver unavailable")), \
             mock.patch.object(gh, "_detect_with_nvidia_smi", return_value=[new]), \
             mock.patch.object(gh, "_run", side_effect=AssertionError("unexpected subprocess")):
            self.assertEqual(gh.detect_gpus(refresh=True)[0].name, "RTX")


if __name__ == "__main__":
    unittest.main()
