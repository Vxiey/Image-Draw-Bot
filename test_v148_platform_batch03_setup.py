import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import venv

import AutoGpuSetup as cuda
import AutoUniversalGpuSetup as opencl
import GpuSetupRuntime as runtime
from test_gpu_setup_regressions import environment_result


def temporary_pip_python(root):
    """Use a real isolated target even when CI runs under a base interpreter.

    ensurepip seeds only Python's bundled pip wheel; this fixture never resolves
    or downloads a package. Create it before installing the hostile test env.
    """
    directory = Path(root) / "pip-venv"
    venv.EnvBuilder(with_pip=True).create(directory)
    return str(directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))


class PipTargetIsolationTests(unittest.TestCase):
    def test_snapshot_removes_relocation_and_preserves_network_precedence(self):
        rows = "\n".join((
            "global.target='/outside'", "install.prefix='/also-outside'", "global.python='/other-python'",
            "install.root='/root-override'", "global.user='yes'", "global.proxy='http://proxy.example:8080'",
            "global.cert='/corporate/ca.pem'", "install.index-url='https://packages.example/simple'",
            "list.timeout='17'", "global.timeout='30'", ":env:.target='/environment-target'",
        ))
        runner = mock.Mock(side_effect=[environment_result(), subprocess.CompletedProcess([], 0, rows, "")])
        with mock.patch.dict(os.environ, {"PIP_TARGET": "/escape", "PIP_PYTHON": "/other", "PIP_USER": "1",
                                           "PIP_CERT": "/explicit/ca.pem", "HTTPS_PROXY": "http://system-proxy",
                                           "PYTHONHOME": "/unexpected-home", "PYTHONPATH": "/unexpected-path",
                                           "PYTHONINSPECT": "1", "PYTHONWARNINGS": "error",
                                           "PYTHONNOUSERSITE": "", "PYTHONSAFEPATH": "",
                                           "PYTHON_FUTURE_OVERRIDE": "unknown-startup-setting"}, clear=True):
            with runtime.pip_environment("selected-python", runner) as policy:
                install = policy.for_command("install")
                listing = policy.for_command("list")
        for key in ("PIP_TARGET", "PIP_PREFIX", "PIP_ROOT", "PIP_USER", "PIP_PYTHON"):
            self.assertNotIn(key, install)
            self.assertNotIn(key, runner.call_args.kwargs["env"])
        self.assertEqual(install["PIP_PROXY"], "http://proxy.example:8080")
        self.assertEqual(install["PIP_CERT"], "/explicit/ca.pem")
        self.assertEqual(install["HTTPS_PROXY"], "http://system-proxy")
        self.assertEqual(install["PIP_INDEX_URL"], "https://packages.example/simple")
        self.assertEqual(install["PIP_TIMEOUT"], "30")
        self.assertEqual(listing["PIP_TIMEOUT"], "17")
        self.assertEqual(install["PIP_CONFIG_FILE"], os.devnull)
        self.assertEqual({key: value for key, value in install.items() if key.startswith("PYTHON")},
                         {"PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1"})
        self.assertEqual({key: value for key, value in runner.call_args.kwargs["env"].items()
                          if key.startswith("PYTHON")},
                         {"PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1"})
        self.assertEqual(runner.call_args.args[0][:4], ["selected-python", "-I", "-m", "pip"])
        self.assertIn("--require-virtualenv", runner.call_args.args[0])

    def test_malformed_snapshot_is_rejected_without_echoing_credentials(self):
        for value in ("secret-token-without-row", "global.proxy=[]", "not even a setting", "x" * (1024 * 1024 + 1)):
            runner = mock.Mock(side_effect=[environment_result(), subprocess.CompletedProcess([], 0, value, "")])
            with self.subTest(value=value[:40]), self.assertRaises(runtime.SetupEnvironmentError) as caught:
                with runtime.pip_environment("python", runner):
                    self.fail("invalid config was accepted")
            self.assertNotIn("secret-token", str(caught.exception))

    def test_actual_pip_parser_cannot_reinherit_target_from_original_config(self):
        # Read-only option parsing; no pip install, resolver or network call.
        with tempfile.TemporaryDirectory() as tmp:
            python = temporary_pip_python(tmp)
            conf = Path(tmp) / "pip.ini"
            conf.write_text("[global]\ntarget = /synthetic/outside\nproxy = http://proxy.example:8080\n", encoding="utf-8")
            environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("PIP_")}
            environment.update(PIP_CONFIG_FILE=str(conf), PIP_TARGET="/synthetic/env-escape")
            def runner(command, **kwargs):
                kwargs.pop("capture_stderr", None)
                return subprocess.run(command, text=True, capture_output=True, check=False, **kwargs)
            with mock.patch.dict(os.environ, environment, clear=True):
                with runtime.pip_environment(python, runner) as policy:
                    child_env = policy.for_command("install")
            probe = (
                "import json; from pip._internal.commands import create_command; "
                "o,_=create_command('install').parse_args(['--no-index','--no-deps','synthetic-never-installed']); "
                "print(json.dumps({'target':o.target_dir,'prefix':o.prefix_path,'root':o.root_path,'proxy':o.proxy}))"
            )
            completed = subprocess.run([python, "-I", "-c", probe], env=child_env,
                                       text=True, capture_output=True, check=True, timeout=30)
            parsed = json.loads(completed.stdout)
            self.assertIsNone(parsed["target"])
            self.assertIsNone(parsed["prefix"])
            self.assertIsNone(parsed["root"])
            self.assertEqual(parsed["proxy"], "http://proxy.example:8080")

    def test_actual_pip_reinvocation_cannot_import_inherited_pythonpath_startup(self):
        # This sitecustomize is created by this test and only writes a marker.
        # pip --python starts a child without -I; the private environment must
        # still prevent importing arbitrary inherited startup modules there.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python = temporary_pip_python(root)
            marker = root / "startup-was-executed.txt"
            (root / "sitecustomize.py").write_text(
                "from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('unexpected startup')\n",
                encoding="utf-8")
            environment = dict(os.environ, PYTHONPATH=str(root))
            def runner(command, **kwargs):
                kwargs.pop("capture_stderr", None)
                return subprocess.run(command, text=True, capture_output=True, check=False, **kwargs)
            with mock.patch.dict(os.environ, environment, clear=True):
                with runtime.pip_environment(python, runner) as policy:
                    child_env = policy.for_command("install")
            self.assertFalse(marker.exists())
            probe = ("import json,sys; print(json.dumps({'inspect':sys.flags.inspect,"
                     "'no_user_site':sys.flags.no_user_site,'safe_path':sys.flags.safe_path}))")
            completed = subprocess.run([python, "-c", probe], env=child_env,
                                       text=True, capture_output=True, check=True, timeout=30)
            self.assertEqual(json.loads(completed.stdout),
                             {"inspect": 0, "no_user_site": 1, "safe_path": True})
            self.assertFalse(marker.exists())


class RequirementsPreflightTests(unittest.TestCase):
    def test_missing_or_empty_requirement_never_upgrades_uninstalls_or_installs(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.txt"
            empty = Path(tmp) / "empty.txt"
            empty.write_text("# nothing to install\n", encoding="utf-8")
            for module, attribute in ((cuda, "GPU_REQUIREMENTS"), (opencl, "REQUIREMENTS")):
                for path in (missing, empty):
                    runner = mock.Mock(side_effect=[environment_result(), subprocess.CompletedProcess([], 0, "", "")])
                    with self.subTest(module=module.__name__, path=path.name), \
                         mock.patch.object(module, attribute, path), mock.patch.object(module, "_run", runner), \
                         self.assertRaises(runtime.SetupEnvironmentError):
                        module._pip_install_backend("selected-python")
                    self.assertEqual(runner.call_count, 2)
                    self.assertEqual(runner.call_args.args[0][-2:], ["config", "list"])

    def test_all_cuda_pip_operations_use_same_isolated_policy(self):
        calls = []
        def runner(command, **kwargs):
            calls.append((command, kwargs))
            if command[1:3] == ["-I", "-c"]:
                return environment_result()
            if command[-2:] == ["config", "list"]:
                return subprocess.CompletedProcess(command, 0, "global.cert='/corporate/ca.pem'\n", "")
            if "list" in command:
                return subprocess.CompletedProcess(command, 0, '[{"name":"cupy-cuda11x"}]')
            return subprocess.CompletedProcess(command, 0, "ok")
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(cuda, "_run", side_effect=runner):
            ok, _ = cuda._pip_install_backend("selected-python")
        self.assertTrue(ok)
        mutations = [c for c in calls if "install" in c[0] or "uninstall" in c[0]]
        self.assertEqual(len(mutations), 3)
        for command, kwargs in mutations:
            self.assertEqual(command[:4], ["selected-python", "-I", "-m", "pip"])
            self.assertIn("--require-virtualenv", command)
            self.assertIn("--no-input", command)
            self.assertEqual(kwargs["env"]["PIP_CONFIG_FILE"], os.devnull)
            self.assertEqual(kwargs["env"]["PIP_CERT"], "/corporate/ca.pem")


if __name__ == "__main__":
    unittest.main()
