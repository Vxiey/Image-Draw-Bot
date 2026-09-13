import unittest
from types import SimpleNamespace

from DrawBot import runtime_palette_guard_colors
from Version import APP_VERSION, FILE_VERSION


class BrowserRuntimePaletteGuardTests(unittest.TestCase):
    def setUp(self):
        self.positions=((10,20),(30,40))
        self.colors=[SimpleNamespace(RGB=(0,0,0)),SimpleNamespace(RGB=(255,255,255))]

    def test_supported_browser_profiles_delegate_to_visual_preflight(self):
        for key in ('gartic-phone','skribbl','skribbl-fast','sketchheads'):
            self.assertEqual(runtime_palette_guard_colors(key,self.positions,self.colors),{})

    def test_paint_and_generic_targets_keep_strict_palette_guard(self):
        expected={(10,20):(0,0,0),(30,40):(255,255,255)}
        self.assertEqual(runtime_palette_guard_colors('paint',self.positions,self.colors),expected)
        self.assertEqual(runtime_palette_guard_colors('other',self.positions,self.colors),expected)

    def test_release_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')


if __name__ == '__main__':
    unittest.main()
