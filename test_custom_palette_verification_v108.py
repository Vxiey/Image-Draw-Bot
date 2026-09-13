import unittest
from pathlib import Path

from AdaptiveColor import method_candidates, method_label
from ScreenGuard import GuardedMouse
from UIState import classify_error


class _Mouse:
    def get_position(self): return (0, 0)


class _LightCanvasMonitor:
    def verify(self, target, point): pass
    def colors_near(self, point, radius=2): return [(207, 207, 207)] * 9
    def color(self, point): return (207, 207, 207)


class V108RegressionTests(unittest.TestCase):
    def test_dark_probe_no_longer_claims_transparency(self):
        guard = GuardedMouse(_Mouse(), _LightCanvasMonitor(), 1)
        result = guard.inspect_ink_segment((10, 10), (30, 10), (0, 0, 0), 1)
        self.assertFalse(result['matched'])
        self.assertEqual(result['failure_kind'], 'stroke-or-selection-mismatch')
        self.assertNotIn('transluc', result['reason'].lower())
        self.assertNotIn('opacity', result['reason'].lower())

    def test_ui_error_no_longer_claims_translucency(self):
        item = classify_error('Stopped: Closest rendered RGB was (207, 207, 207); expected color (0, 0, 0)')
        self.assertIsNotNone(item)
        text = ' '.join(item.values()).lower()
        self.assertNotIn('transluc', text)

    def test_spectrum_only_custom_palette_is_a_runtime_candidate(self):
        selector={'kind':'custom','rgb':(12,34,56),'fallback_palette_index':0}
        actions={'OpenCustomColor':(1,1),'ConfirmColor':(2,2),
                 'SpectrumTopLeft':(3,3),'SpectrumBottomRight':(4,4)}
        self.assertEqual(method_candidates(selector, actions, keyboard_available=False), ('spectrum','palette'))
        self.assertEqual(method_label('spectrum'), 'Paint custom color palette')

    def test_adaptive_exact_is_visible_in_ui(self):
        ui=Path('StudioUI.py').read_text(encoding='utf-8')
        self.assertIn("['Adaptive exact (recommended)', 'Exact custom + palette fallback'", ui)

    def test_real_preflight_accepts_spectrum_without_rgb_fields(self):
        bot=Path('DrawBot.py').read_text(encoding='utf-8')
        self.assertIn("options['exact_color_available']=bool(spectrum_ready or numeric_ready)", bot)
        self.assertIn("options['exact_color_capabilities']={'spectrum':bool(spectrum_ready),'numeric':bool(numeric_ready)}", bot)

    def test_version(self):
        from Version import APP_VERSION, FILE_VERSION
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')


if __name__ == '__main__':
    unittest.main()
