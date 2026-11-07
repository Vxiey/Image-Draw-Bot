"""Visible sketch choices reach the real options and renderer together."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import DrawBot
from Colors import reset_palette
from test_v148_ui_batch07_renderer import close_images
import test_v148_ui_batch07_renderer as renderer_fixtures
import test_v148_ui_batch12_switches as switch_fixtures


class SketchModeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # This fixture replaces Tk widget allocation/drawing only. Switches
        # retain CTk's real variable trace, toggle and command implementation.
        self.surface = switch_fixtures.SwitchKeyboardTests(methodName='runTest')
        self.surface.setUp()
        self.addCleanup(self.surface.doCleanups)
        self.tcl = self.surface.interpreter
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=self.directory))
        self.stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
        self.addCleanup(reset_palette)
        self.source = Image.new('RGB', (48, 36), 'white')
        self.addCleanup(self.source.close)
        drawing = ImageDraw.Draw(self.source)
        drawing.rectangle((6, 5, 22, 30), fill='red', outline='black', width=2)
        drawing.rectangle((25, 5, 41, 30), fill='blue', outline='black', width=2)

    def app(self, profile='Skribbl.io'):
        app = DrawBot.DrawBotApp.__new__(DrawBot.DrawBotApp)
        values = renderer_fixtures.AdvertisedRendererTests().app(profile)
        for name, value in vars(values).items():
            current = value.get()
            variable = tk.BooleanVar if isinstance(current, bool) else tk.DoubleVar if isinstance(current, float) else tk.StringVar
            setattr(app, name, variable(self.tcl, value=current))
        for name in switch_fixtures.SWITCH_VARIABLES:
            if not hasattr(app, name):
                setattr(app, name, tk.BooleanVar(self.tcl, value=False))
        for name, value in (
                ('render_style', 'Standard / pixel'), ('subject_focus', 'Off'),
                ('time_budget_mode', 'Unlimited'), ('preview_mode', 'Manual'),
                ('drawing_style', 'Auto'), ('status', ''), ('summary', ''),
                ('palette_text', ''), ('next_step', '')):
            setattr(app, name, tk.StringVar(self.tcl, value=value))
        app.root = switch_fixtures.Scheduler()
        app.controls = []
        app.activity = None
        app.closing = False
        app.profile_change_in_progress = False
        app.paint_config_after = None
        app.original = self.source
        app.plan = None
        app.preview_generation = 0
        app.corners = []
        app.target_window = None
        app.palette_ready = False
        app.saved_area = None
        app.calibration_path = self.directory / 'calibration.json'
        widgets = switch_fixtures.actual_switch_rows(app, object())
        app.switches = dict(zip(switch_fixtures.SWITCH_VARIABLES, widgets))
        app.refresh_palette()
        return app

    def toggle(self, app, name, *, keyboard=False):
        widget = app.switches[name]
        if keyboard:
            self.surface.press(widget)
        else:
            widget.toggle()
        app.root.flush()
        self.assertEqual(bool(widget.get()), bool(getattr(app, name).get()))

    def plan(self, app):
        options = app.options()
        plan = DrawBot.make_plan(self.source, self.source.size, options)
        self.addCleanup(close_images, plan)
        return options, plan

    def test_turning_black_contour_off_exits_its_dependent_browser_ink_mode(self):
        for profile in ('Skribbl.io', 'Gartic Phone'):
            with self.subTest(profile=profile):
                app = self.app(profile)
                self.toggle(app, 'paint_simple')
                before, sketch = self.plan(app)
                self.assertTrue(before['paint_current_color'])
                self.assertTrue(before['outline'])
                self.assertTrue(sketch['options']['black_sketch'])
                self.assertGreater(sketch['count'], 0)
                self.toggle(app, 'outline', keyboard=True)
                options, colored = self.plan(app)
                self.assertFalse(app.switches['outline'].get())
                self.assertFalse(app.switches['paint_simple'].get())
                self.assertFalse(options['outline'])
                self.assertFalse(options['paint_current_color'])
                self.assertFalse(colored['options'].get('black_sketch', False))
                self.assertGreater(sum(bool(group) for group in colored['groups']), 1)

    def test_turning_current_ink_off_preserves_an_independent_palette_contour(self):
        app = self.app()
        self.toggle(app, 'outline')
        self.toggle(app, 'paint_simple')
        self.toggle(app, 'paint_simple', keyboard=True)
        options, plan = self.plan(app)
        self.assertTrue(app.switches['outline'].get())
        self.assertFalse(app.switches['paint_simple'].get())
        self.assertTrue(options['outline'])
        self.assertFalse(options['paint_current_color'])
        self.assertTrue(plan['options']['black_sketch'])
        self.assertGreater(plan['count'], 0)
        self.assertEqual(sum(bool(group) for group in plan['groups']), 1)

    def test_paint_contour_off_keeps_the_supported_current_ink_shaded_renderer(self):
        app = self.app('Microsoft Paint')
        self.toggle(app, 'paint_simple')
        self.toggle(app, 'outline')
        app.render_style.set('Portrait / shaded')
        self.toggle(app, 'outline', keyboard=True)
        options, plan = self.plan(app)
        self.assertFalse(app.switches['outline'].get())
        self.assertTrue(app.switches['paint_simple'].get())
        self.assertFalse(options['outline'])
        self.assertTrue(options['paint_current_color'])
        self.assertTrue(plan['options']['portrait_stats'])
        self.assertFalse(plan['options'].get('black_sketch', False))
        self.assertGreater(plan['count'], 0)
        self.assertEqual(len(plan['groups']), 1)

    def test_saved_browser_current_ink_still_normalizes_to_supported_contours(self):
        app = self.app()
        # Applying saved settings writes variables without delivering a user's
        # explicit Off command. The established compatibility policy remains.
        app.paint_simple.set(True)
        app.outline.set(False)
        options, plan = self.plan(app)
        self.assertTrue(app.switches['outline'].get())
        self.assertTrue(app.switches['paint_simple'].get())
        self.assertTrue(options['outline'])
        self.assertTrue(options['paint_current_color'])
        self.assertTrue(plan['options']['black_sketch'])
        self.assertGreater(plan['count'], 0)

    def test_busy_and_closing_switch_callbacks_do_not_change_current_ink_policy(self):
        for attribute, value in (('activity', 'draw'), ('closing', True)):
            with self.subTest(attribute=attribute):
                app = self.app()
                app.paint_simple.set(True)
                app.outline.set(False)
                setattr(app, attribute, value)
                app.sketch_mode_changed()
                self.assertTrue(app.paint_simple.get())
                self.assertFalse(app.outline.get())
                self.assertFalse(app.root.pending)


if __name__ == '__main__':
    unittest.main()
