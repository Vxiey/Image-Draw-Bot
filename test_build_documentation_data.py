import tempfile
import unittest
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import patch

import build_exe


class BuildDocumentationDataTests(unittest.TestCase):
    def build_command(self, root, *, gpu=False):
        bundled_help = {}

        def record_run(command, **kwargs):
            if 'PyInstaller' in command:
                for index, value in enumerate(command):
                    if value != '--add-data':
                        continue
                    source, destination = command[index + 1].rsplit(';', 1)
                    if destination == 'docs':
                        docs = Path(source)
                        bundled_help.update({
                            'docs/' + path.relative_to(docs).as_posix(): path.read_bytes()
                            for path in docs.rglob('*') if path.is_file()
                        })
            return SimpleNamespace(returncode=0)

        (root / 'version_info.txt').write_text(
            f"StringStruct('FileVersion', '{build_exe.FILE_VERSION}')\n"
            f"StringStruct('ProductVersion', '{build_exe.FILE_VERSION}')\n",
            encoding='utf-8',
        )
        builder = root / '.build-venv/Scripts/python.exe'
        builder.parent.mkdir(parents=True)
        builder.touch()
        output = root / 'dist/ImageDrawBot/ImageDrawBot.exe'
        output.parent.mkdir(parents=True)
        output.write_bytes(b'MZtest fixture')
        with patch.object(build_exe, '__file__', str(root / 'build_exe.py')), \
             patch.object(build_exe.sys, 'platform', 'win32'), \
             patch.object(build_exe.sys, 'version_info', (3, 12, 0)), \
             patch.object(build_exe.sys, 'maxsize', 2**63 - 1), \
             patch.object(build_exe.sys, 'argv', ['build_exe.py'] + (['--gpu'] if gpu else [])), \
             patch.object(build_exe, 'prepare_builder', return_value=build_exe.Builder(builder, root.resolve(), {})), \
             patch.object(build_exe.subprocess, 'run', side_effect=record_run) as run, \
             patch('builtins.print'):
            build_exe.main()
        command = next(call.args[0] for call in run.call_args_list if 'PyInstaller' in call.args[0])
        return command, bundled_help

    def make_fixture(self, root):
        files = {
            'README.md': b'application README',
            'VERSION-HISTORY.md': b'application history',
            'docs/README.md': b'documentation index',
            'docs/VERSION-HISTORY.md': b'documentation history',
            'docs/guides/first-use.md': b'![preview](images/preview.png)',
            'docs/guides/images/preview.png': b'preview image',
            'docs/engine-benchmarks/example.json': b'{"result": "example"}',
            'docs/history/README.md': b'historical release notes',
            'docs/history/archives/README.md': b'source archive inventory',
            'docs/history/archives/legacy-source.zip': b'archived source',
            'docs/history/archives/old-installer.exe': b'archived installer',
        }
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return files

    def test_help_layout_and_resources_preserved_without_archived_releases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.make_fixture(root)
            packaged = {
                (PurePosixPath(destination) / source.name).as_posix(): source.read_bytes()
                for source, destination in build_exe.documentation_data(root)
            }
            expected = {
                name: content for name, content in files.items()
                if name.startswith('docs/') and not name.startswith('docs/history/archives/')
            }
            self.assertEqual(packaged, expected)
            # Historical originals remain available in the source checkout.
            self.assertEqual((root / 'docs/history/archives/legacy-source.zip').read_bytes(),
                             b'archived source')

    def test_missing_optional_documentation_is_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(build_exe.documentation_data(Path(temporary)), [])

    def test_build_passes_filtered_help_files_at_their_runtime_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.make_fixture(root)
            command, bundled_help = self.build_command(root)
            data_arguments = [command[index + 1] for index, value in enumerate(command)
                              if value == '--add-data']
            self.assertIn(f'{(root / "README.md").resolve()};.', data_arguments)
            docs_arguments = [argument for argument in data_arguments if argument.endswith(';docs')]
            self.assertEqual(len(docs_arguments), 1, 'Help uses one argument even as its file count grows')
            expected = {
                name: content for name, content in files.items()
                if name.startswith('docs/') and not name.startswith('docs/history/archives/')
            }
            self.assertEqual(bundled_help, expected)
            self.assertFalse(Path(docs_arguments[0].rsplit(';', 1)[0]).exists(),
                             'The temporary documentation tree must be cleaned after the build')

    def test_build_uses_native_tkinterdnd2_hook_without_collecting_other_platforms(self):
        with tempfile.TemporaryDirectory() as temporary:
            command, _ = self.build_command(Path(temporary))
            pairs = list(zip(command, command[1:]))
            self.assertIn(('--hidden-import', 'tkinterdnd2'), pairs)
            self.assertIn(('--copy-metadata', 'tkinterdnd2'), pairs)
            self.assertNotIn(('--collect-all', 'tkinterdnd2'), pairs)
            self.assertIn('--onedir', command)
            self.assertIn('--noupx', command)


if __name__ == '__main__':
    unittest.main()
