import unittest
from pathlib import Path
from unittest.mock import patch

from Version import APP_VERSION, FILE_VERSION
from RuntimePaths import helper_command
import GetColorPositions

class FakeRoot:
    def mainloop(self): pass

class Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_palette_helper_command_source_build(self):
        cmd=helper_command('palette','--profile','microsoft-paint')
        self.assertTrue(cmd[1].endswith('GetColorPositions.py'))
        self.assertIn('--profile',cmd)

    def test_palette_helper_uses_tk_not_customtkinter(self):
        source=Path(GetColorPositions.__file__).read_text(encoding='utf-8')
        self.assertNotIn('import customtkinter',source)
        self.assertIn('root=tk.Tk()',source)

    def test_palette_main_can_exit_cleanly_without_real_gui(self):
        with patch('GetColorPositions.enable_dpi_awareness'), \
             patch('GetColorPositions.tk.Tk',return_value=FakeRoot()), \
             patch('GetColorPositions.CalibrationApp'):
            self.assertEqual(GetColorPositions.main(['--profile','generic']),0)

    def test_drawbot_uses_isolated_palette_helper(self):
        source=Path(__file__).with_name('DrawBot.py').read_text(encoding='utf-8')
        section=source[source.index('    def calibrate(self):'):source.index('    def capture_target(self):')]
        self.assertIn("helper_command('palette'",section)
        self.assertIn('subprocess.Popen',section)
        self.assertNotIn('CTkToplevel',section)

if __name__=='__main__': unittest.main()
