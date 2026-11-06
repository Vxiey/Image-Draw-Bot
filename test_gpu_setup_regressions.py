import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

import AutoGpuSetup as cuda_setup
import AutoUniversalGpuSetup as opencl_setup
from GpuHardware import NvidiaGpu
import GpuSetupRuntime as setup_runtime


def environment_result(*, virtual=True, frozen=False):
    base = str(Path(sys.executable).resolve().parent)
    prefix = str(Path(base) / "test-venv") if virtual else base
    return subprocess.CompletedProcess([], 0, json.dumps({
        "prefix": prefix, "base_prefix": base, "real_prefix": None, "frozen": frozen,
    }))


class FakeOpenCL:
    device_type = SimpleNamespace(GPU=1)
    mem_flags = SimpleNamespace(READ_WRITE=1, COPY_HOST_PTR=2)

    def __init__(self, modes):
        self.modes = dict(modes)
        self.attempted = []

    def get_platforms(self):
        devices = [SimpleNamespace(name=name, vendor="Vendor", mode=mode) for name, mode in self.modes.items()]
        return [SimpleNamespace(get_devices=lambda **kwargs: devices)]

    def Context(self, *, devices):
        device = devices[0]
        self.attempted.append(device.name)
        if device.mode == "broken":
            raise RuntimeError("driver context failed")
        return SimpleNamespace(device=device)

    def CommandQueue(self, context):
        return SimpleNamespace(context=context, finish=lambda: None)

    def Program(self, context, _source):
        def kernel(_queue, _shape, _local, buffer):
            if context.device.mode == "partial":
                buffer.values[3] = 7.0
            else:
                buffer.values = buffer.values * 2.0 + 1.0
        program = SimpleNamespace(probe=kernel)
        program.build = lambda: program
        return program

    def Buffer(self, _context, _flags, *, hostbuf):
        return SimpleNamespace(values=hostbuf.copy())

    def enqueue_copy(self, _queue, host, buffer):
        np.copyto(host, buffer.values)


class GpuSetupEnvironmentTests(unittest.TestCase):
    def test_target_system_interpreter_is_rejected_even_if_caller_is_in_venv(self):
        runner = mock.Mock(return_value=environment_result(virtual=False))
        with mock.patch.object(setup_runtime.sys, "prefix", "active-venv"), \
             self.assertRaises(setup_runtime.SetupEnvironmentError):
            setup_runtime.require_virtual_environment("selected-system-python", runner)
        self.assertEqual(runner.call_args.args[0][:3], ["selected-system-python", "-I", "-c"])

    def test_verified_virtual_target_is_accepted(self):
        runner = mock.Mock(return_value=environment_result())
        setup_runtime.require_virtual_environment("selected-venv-python", runner)
        self.assertEqual(runner.call_count, 1)

    def test_invalid_environment_protocol_fails_closed(self):
        replies = [subprocess.CompletedProcess([], 0, "null"),
                   subprocess.CompletedProcess([], 0, "not json"),
                   subprocess.CompletedProcess([], 1, ""), environment_result(frozen=True)]
        for reply in replies:
            with self.subTest(reply=reply), self.assertRaises(setup_runtime.SetupEnvironmentError):
                setup_runtime.require_virtual_environment("python", mock.Mock(return_value=reply))

    def test_each_installer_checks_target_before_pip_mutations(self):
        for module in (cuda_setup, opencl_setup):
            with self.subTest(module=module.__name__), \
                 mock.patch.object(module, "_run", return_value=environment_result(virtual=False)) as runner, \
                 self.assertRaises(setup_runtime.SetupEnvironmentError):
                module._pip_install_backend("system-python")
            self.assertEqual(runner.call_count, 1)
            self.assertEqual(runner.call_args.args[0][:3], ["system-python", "-I", "-c"])

    def test_readonly_environment_probe_with_current_interpreter(self):
        def runner(command, *, timeout):
            return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                                  check=False)
        if setup_runtime.running_in_virtual_environment():
            setup_runtime.require_virtual_environment(sys.executable, runner)
        else:
            with self.assertRaises(setup_runtime.SetupEnvironmentError):
                setup_runtime.require_virtual_environment(sys.executable, runner)

    def test_setup_state_is_not_written_to_system_python_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            for module in (cuda_setup, opencl_setup):
                path = Path(tmp) / (module.__name__ + ".json")
                with mock.patch.object(module, "running_in_virtual_environment", return_value=False), \
                     mock.patch.object(module, "_state_path", return_value=path):
                    module._write_state(module.SetupResult(False, "test", "test"))
                self.assertFalse(path.exists())


class GpuSetupFailureTests(unittest.TestCase):
    gpu = NvidiaGpu(0, "Test NVIDIA", 8192)

    def test_cuda_probe_timeout_does_not_trigger_package_installation(self):
        with mock.patch.object(cuda_setup, "best_nvidia_gpu", return_value=self.gpu), \
             mock.patch.object(cuda_setup, "_smoke_test", side_effect=subprocess.TimeoutExpired("probe", 45)), \
             mock.patch.object(cuda_setup, "_pip_install_backend") as install, \
             mock.patch.object(cuda_setup, "_write_state"):
            result = cuda_setup.ensure_gpu_backend(python="target-python")
        self.assertEqual(result.status, "probe-failed")
        self.assertFalse(result.ok)
        self.assertIn("CPU fallback", result.message)
        install.assert_not_called()

    def test_cuda_install_failure_and_final_probe_failure_are_results(self):
        for install_error in (OSError("cannot start"), subprocess.TimeoutExpired("pip", 900)):
            with self.subTest(error=install_error), \
                 mock.patch.object(cuda_setup, "best_nvidia_gpu", return_value=self.gpu), \
                 mock.patch.object(cuda_setup, "_smoke_test", return_value=(False, "missing")), \
                 mock.patch.object(cuda_setup, "_pip_install_backend", side_effect=install_error), \
                 mock.patch.object(cuda_setup, "_write_state"):
                self.assertEqual(cuda_setup.ensure_gpu_backend(python="target").status, "install-failed")
        with mock.patch.object(cuda_setup, "best_nvidia_gpu", return_value=self.gpu), \
             mock.patch.object(cuda_setup, "_smoke_test", side_effect=[(False, "missing"), OSError("probe failed")]), \
             mock.patch.object(cuda_setup, "_pip_install_backend", return_value=(True, "installed")), \
             mock.patch.object(cuda_setup, "_write_state"):
            result = cuda_setup.ensure_gpu_backend(python="target")
        self.assertEqual(result.status, "smoke-failed")
        self.assertTrue(result.installed)

    def test_invalid_pip_package_list_is_not_treated_as_an_empty_environment(self):
        for stdout in ("null", "{}", "broken"):
            with self.subTest(stdout=stdout), \
                 mock.patch.object(cuda_setup, "_run", return_value=subprocess.CompletedProcess([], 0, stdout)), \
                 self.assertRaises(RuntimeError):
                cuda_setup._read_pip_packages("target")

    def test_opencl_probe_and_install_timeouts_keep_cpu_fallback(self):
        with mock.patch.object(opencl_setup, "_target_vendors", return_value=("AMD",)), \
             mock.patch.object(opencl_setup, "_smoke_test", side_effect=subprocess.TimeoutExpired("probe", 45)), \
             mock.patch.object(opencl_setup, "_pip_install_backend") as install, \
             mock.patch.object(opencl_setup, "_write_state"):
            result = opencl_setup.ensure_universal_gpu_backend(python="target")
        self.assertEqual(result.status, "probe-failed")
        install.assert_not_called()
        with mock.patch.object(opencl_setup, "_target_vendors", return_value=("AMD",)), \
             mock.patch.object(opencl_setup, "_smoke_test", return_value=(False, (), "missing")), \
             mock.patch.object(opencl_setup, "_pip_install_backend", side_effect=subprocess.TimeoutExpired("pip", 600)), \
             mock.patch.object(opencl_setup, "_write_state"):
            result = opencl_setup.ensure_universal_gpu_backend(python="target")
        self.assertEqual(result.status, "install-failed")
        self.assertIn("CPU fallback", result.message)

    def test_environment_check_failure_is_reported_without_install_claim(self):
        with mock.patch.object(cuda_setup, "best_nvidia_gpu", return_value=self.gpu), \
             mock.patch.object(cuda_setup, "_smoke_test", return_value=(False, "missing")), \
             mock.patch.object(cuda_setup, "_pip_install_backend", side_effect=setup_runtime.SetupEnvironmentError("system Python")), \
             mock.patch.object(cuda_setup, "_write_state"):
            result = cuda_setup.ensure_gpu_backend(python="target")
        self.assertEqual(result.status, "environment-not-verified")
        self.assertFalse(result.installed)


class OpenCLProbeRegressionTests(unittest.TestCase):
    def test_probe_uses_selected_python_and_separates_stderr(self):
        payload = {"ok": True, "devices": ["AMD GPU"], "message": "ready"}
        reply = subprocess.CompletedProcess([], 0, json.dumps(payload), "driver warning")
        with mock.patch.object(opencl_setup, "_run", return_value=reply) as run:
            result = opencl_setup._smoke_test("selected-venv-python")
        self.assertEqual(result, (True, ("AMD GPU",), "ready"))
        self.assertEqual(run.call_args.args[0][0], "selected-venv-python")
        self.assertEqual(run.call_args.args[0][-1], "--smoke-json")
        self.assertTrue(run.call_args.kwargs["capture_stderr"])

    def test_after_installation_same_target_is_validated_again(self):
        with mock.patch.object(opencl_setup, "_target_vendors", return_value=("AMD",)), \
             mock.patch.object(opencl_setup, "_smoke_test", side_effect=[(False, (), "missing"),
                                                                        (True, ("AMD GPU",), "ready")]) as smoke, \
             mock.patch.object(opencl_setup, "_pip_install_backend", return_value=subprocess.CompletedProcess([], 0, "")), \
             mock.patch.object(opencl_setup, "opencl_smoke_test", side_effect=AssertionError("wrong interpreter")), \
             mock.patch.object(opencl_setup, "_write_state"):
            result = opencl_setup.ensure_universal_gpu_backend(python="selected-venv-python")
        self.assertTrue(result.ok)
        self.assertEqual(smoke.call_args_list, [mock.call("selected-venv-python"), mock.call("selected-venv-python")])

    def test_malformed_probe_json_is_a_failed_probe(self):
        for value in ("null", "[]", '{"ok": true, "devices": "wrong"}', "not JSON"):
            with self.subTest(value=value), \
                 mock.patch.object(opencl_setup, "_run", return_value=subprocess.CompletedProcess([], 0, value)):
                self.assertFalse(opencl_setup._smoke_test("target")[0])

    def test_broken_first_adapter_does_not_hide_healthy_gpu(self):
        fake = FakeOpenCL([("broken GPU", "broken"), ("working GPU", "good")])
        with mock.patch.dict(sys.modules, {"pyopencl": fake}):
            ok, devices, message = opencl_setup.opencl_smoke_test()
        self.assertTrue(ok)
        self.assertEqual(fake.attempted, ["broken GPU", "working GPU"])
        self.assertEqual(devices, ("Vendor working GPU",))
        self.assertIn("working GPU", message)

    def test_partial_kernel_output_is_not_a_successful_device(self):
        fake = FakeOpenCL([("partial GPU", "partial"), ("working GPU", "good")])
        with mock.patch.dict(sys.modules, {"pyopencl": fake}):
            ok, devices, _message = opencl_setup.opencl_smoke_test()
        self.assertTrue(ok)
        self.assertEqual(fake.attempted, ["partial GPU", "working GPU"])
        self.assertEqual(devices, ("Vendor working GPU",))

    def test_all_failed_adapters_return_a_clear_failure(self):
        fake = FakeOpenCL([("broken GPU", "broken"), ("partial GPU", "partial")])
        with mock.patch.dict(sys.modules, {"pyopencl": fake}):
            ok, devices, message = opencl_setup.opencl_smoke_test()
        self.assertFalse(ok)
        self.assertEqual(devices, ())
        self.assertIn("No OpenCL GPU passed validation", message)


if __name__ == "__main__":
    unittest.main()
