import unittest
from pathlib import Path
from types import SimpleNamespace

from ProfileIsolation import register_controls


class _Widget:
    def __init__(self, parent):
        self.master = parent
        self.manager = 'pack'
        parent.children.append(self)

    def pack_info(self):
        return {'fill': 'x'}

    def winfo_manager(self):
        return self.manager


class CompactUILayoutTests(unittest.TestCase):
    def test_source_exposes_progressive_disclosure_sections(self):
        source = Path('UICompactLayout.py').read_text(encoding='utf-8')
        for label in (
            'Profile & ink options',
            'Image options & automation',
            'Manual calibration',
            'Fine tuning',
            'Preview options',
            'Review & safety shortcuts',
        ):
            with self.subTest(label=label):
                self.assertIn(label, source)
        self.assertIn("('🎨  Quality', '🛠  Developer tools')", source)

    def test_compactor_is_presentation_only_and_profile_aware(self):
        source = Path('UICompactLayout.py').read_text(encoding='utf-8')
        self.assertIn('scope_visible(scope, key)', source)
        self.assertIn('widget.pack_forget()', source)
        self.assertIn('widget.pack(**options)', source)
        self.assertNotIn('widget.destroy()', source)
        self.assertIn('self.shell.destroy()', source)
        self.assertNotIn('.set(', source)

    def test_register_controls_still_supports_non_ui_test_apps(self):
        parent = SimpleNamespace(children=[])
        widget = _Widget(parent)
        app = SimpleNamespace()
        register_controls(app, [(widget, 'paint')])
        self.assertEqual(len(app._scoped_profile_controls), 1)
        self.assertIsNone(app._compact_ui_layout)

    def test_studio_ui_keeps_original_controls_for_compatibility(self):
        source = Path('StudioUI.py').read_text(encoding='utf-8')
        for marker in (
            'Choose target app', 'Add image', 'Prepare target app',
            'Configure drawing', "step_card(5, 'Safety & draw'",
            'GPU performance', 'VRAM budget', 'Fill engine',
            'Fast Dry run · ≤12s', 'Unlock full drawing', 'Build preview',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)


if __name__ == '__main__':
    unittest.main()
