import ast
import unittest
from pathlib import Path


class Rc29ReleaseBuilderTests(unittest.TestCase):
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
