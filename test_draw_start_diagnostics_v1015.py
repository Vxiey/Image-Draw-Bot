import unittest
from types import SimpleNamespace
from unittest.mock import patch

from DrawBot import DrawBotApp
from Version import APP_VERSION, FILE_VERSION


class Value:
    def __init__(self, value=None):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class Root:
    def after_cancel(self, token):
        pass


class DrawStartDiagnosticsV1015Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_start_without_image_is_not_silent(self):
        app = SimpleNamespace(
            activity=None, closing=False, preview_after=None, preview_render_after=None,
            root=Root(), corners=[(0, 0), (100, 100)], original=None,
            status=Value(), summary=Value())
        with patch('DrawBot.log_event') as log:
            DrawBotApp.draw(app, user_initiated=True)
        self.assertIn('Load or paste an image', app.status.get())
        self.assertIn('No image loaded', app.summary.get())
        self.assertTrue(any('no source image loaded' in str(call).lower() for call in log.call_args_list))

    def test_start_without_area_is_logged(self):
        app = SimpleNamespace(
            activity=None, closing=False, preview_after=None, preview_render_after=None,
            root=Root(), corners=[], original=object(), status=Value(), summary=Value())
        with patch('DrawBot.log_event') as log:
            DrawBotApp.draw(app, user_initiated=True)
        self.assertEqual(app.status.get(), 'Select the drawing area first.')
        self.assertTrue(any('no drawing area selected' in str(call).lower() for call in log.call_args_list))

    def test_source_contains_final_planning_diagnostics(self):
        import pathlib
        source = (pathlib.Path(__file__).resolve().parent / 'DrawBot.py').read_text(encoding='utf-8')
        self.assertIn('Final planning started:', source)
        self.assertIn('Final planning finished in', source)
        self.assertIn('CPU/GPU/RAM allocation is used here', source)
        self.assertIn('_plan_log_text', source)

    def test_release_collects_diagnostics_doc(self):
        import pathlib
        source = (pathlib.Path(__file__).resolve().parent / 'build_exe.py').read_text(encoding='utf-8')
        self.assertNotIn('DRAW-START-DIAGNOSTICS-v1.0.15.md', source)
        self.assertIn('Collect-Diagnostics.bat', source)


if __name__ == '__main__':
    unittest.main()
