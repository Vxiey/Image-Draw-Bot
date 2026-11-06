import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class Rc29ReleaseBuilderTests(unittest.TestCase):
    def test_supported_launcher_rejects_outdated_existing_build_environment(self):
        import build_exe
        with patch.object(build_exe.sys, 'platform', 'win32'), \
             patch.object(build_exe.sys, 'version_info', (3, 12, 0)), \
             patch.object(build_exe.sys, 'maxsize', 2**63 - 1), \
             patch.object(build_exe.Path, 'exists', return_value=True), \
             patch.object(build_exe.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as run:
            with self.assertRaisesRegex(SystemExit, 'Rename .build-venv'):
                build_exe.main([])
        # Reject the existing interpreter before any dependency installation.
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertIn('.build-venv', command[0])
        self.assertEqual(command[1], '-c')
        self.assertNotIn('pip', command)

    def test_dynamic_modules_are_explicit_hidden_imports(self):
        source = Path('build_exe.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        command_values = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.List):
                continue
            if not any(isinstance(target, ast.Name) and target.id == 'command' for target in node.targets):
                continue
            command_values = [
                item.value if isinstance(item, ast.Constant) and isinstance(item.value, str) else None
                for item in node.value.elts
            ]
            break
        self.assertIsNotNone(command_values, 'build_exe.py must define the PyInstaller command list')
        for module in ('CompletedDrawingAnalysis', 'DrawingStyleProfiles', 'BackgroundRemoval'):
            with self.subTest(module=module):
                index = command_values.index(module)
                self.assertGreater(index, 0)
                self.assertEqual(command_values[index - 1], '--hidden-import')

    def test_rc29_modules_are_not_bare_pyinstaller_positionals(self):
        source = Path('build_exe.py').read_text(encoding='utf-8')
        self.assertNotIn("'CompletedDrawingAnalysis','DrawingStyleProfiles'", source)
        self.assertIn("'--hidden-import', 'DrawingStyleProfiles'", source)


if __name__ == '__main__':
    unittest.main()
