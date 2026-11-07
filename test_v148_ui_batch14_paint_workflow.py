"""Manual Paint guidance follows the same live Start policy as the controller."""
import tkinter as tk
import unittest
from unittest.mock import Mock

import DrawBot
import GettingStarted as guide
from BeginnerSetupWizard import build_setup_wizard, next_action, format_setup_status
from test_v148_ui_profiles_batch04 import Var, studio_state_renderer
from test_v148_ui_workflow_batch05_runtime import GuideHarness


def paint_app(tool):
    app, scope = studio_state_renderer(paint_tool=Var(tool), corners=((10, 10), (100, 100)),
        palette_ready=True, _paint_tool_preflight_ready=Mock(return_value=True),
        _full_draw_unlocked=Mock(return_value=True))
    app._automatic_paint_preparation = Mock(side_effect=lambda: DrawBot.DrawBotApp._automatic_paint_preparation(app))
    app._strict_safety_required = Mock(side_effect=lambda: DrawBot.DrawBotApp._strict_safety_required(app))
    scope['palette_ready_now'] = lambda: app.palette_ready
    return app, scope


class ManualPaintGuidanceTests(unittest.TestCase):
    def test_workspace_uses_the_live_controller_policy_and_optional_diagnostic_rules(self):
        for tool in ('Auto (recommended)', 'Pencil', 'Brush', 'Eraser', 'Use current tool'):
            with self.subTest(tool=tool):
                app, scope = paint_app(tool)
                compute = scope['compute_workspace_state']
                scope['compute_workspace_state'] = Mock(wraps=compute)
                scope['_apply_ui_state']()
                kwargs = scope['compute_workspace_state'].call_args.kwargs
                self.assertEqual(kwargs['prepare_on_start'], tool == 'Auto (recommended)')
                self.assertFalse(kwargs['strict_safety'])
                self.assertFalse(kwargs['preflight_passed'])
                self.assertFalse(kwargs['dry_run_passed'])
                state = compute(**kwargs)
                self.assertTrue(state.ready)
                self.assertEqual(state.label, 'Ready to prepare Paint' if tool == 'Auto (recommended)' else 'Ready to draw')
                app._automatic_paint_preparation.assert_called_once_with()
                app._strict_safety_required.assert_called_once_with()
                expected = 'Prepare Paint & draw' if tool == 'Auto (recommended)' else 'Start drawing'
                self.assertIn('ready. ' + expected, app.setup_wizard_text.get())

    def test_manual_tool_readiness_and_unlock_expiry_are_reported_without_auto_setup(self):
        settings = dict(profile_name='Microsoft Paint', prepare_on_start=False,
            image_loaded=True, area_ready=True, palette_ready=True, tools_ready=False)
        steps = build_setup_wizard(**settings)
        self.assertNotIn('prepare', [step.key for step in steps])
        calibration = next(step for step in steps if step.key == 'calibration')
        self.assertTrue(calibration.blocks_start)
        self.assertIn('selected Paint tool', next_action(steps))
        self.assertNotIn('Prepare Paint & draw', format_setup_status(steps))
        steps = build_setup_wizard(**dict(settings, tools_ready=True, full_draw_unlocked=True))
        self.assertEqual(next_action(steps), 'Press Start drawing before the confirmation expires.')
        for changed in ({'full_draw_unlocked': False}, {'activity': 'draw'}):
            steps = build_setup_wizard(**(settings | {'tools_ready': True, 'full_draw_unlocked': True} | changed))
            expected = 'Unlock full drawing' if not changed.get('activity') else 'Wait for the current operation'
            self.assertIn(expected, next_action(steps))

    def test_actual_wizard_controller_passes_tool_policy_instead_of_profile_alone(self):
        for tool in ('Auto (recommended)', 'Brush', 'Eraser', 'Use current tool'):
            with self.subTest(tool=tool):
                app, _scope = paint_app(tool)
                steps = DrawBot.DrawBotApp._beginner_setup_steps(app)
                self.assertEqual(any(step.key == 'prepare' for step in steps), tool == 'Auto (recommended)')
                self.assertEqual(any(step.key == 'unlock' for step in steps), tool != 'Auto (recommended)')
                self.assertEqual(app.paint_tool.get(), tool)

    def test_open_guide_tracks_tool_changes_and_releases_both_variable_traces(self):
        with GuideHarness() as h:
            h.window.destroy()
            h.app.paint_tool = tk.StringVar(h.interpreter, value='Auto (recommended)')
            h.app._automatic_paint_preparation = lambda: DrawBot.DrawBotApp._automatic_paint_preparation(h.app)
            h.window = guide.show_guide(h.app)
            h.window.flush()
            h.menu = next(child for child in h.window.children if 'values' in child.options)
            h.body = next(child for child in h.window.children if '<Configure>' in child.bindings)
            h.page('Start, pause and stop')
            self.assertIn('Start in Paint', h.texts())
            h.app.paint_tool.set('Eraser')
            h.app.paint_tool.set('Brush')
            self.assertEqual(len(h.window.jobs), 1)
            h.window.flush()
            self.assertEqual(h.menu.options['value'], 'Start, pause and stop')
            self.assertIn('Start with the selected Paint tool', h.texts())
            self.assertTrue(any('Unlock full drawing and Start drawing' in text for text in h.texts()))
            self.assertFalse(any('press Prepare Paint & draw' in text for text in h.texts()))
            h.app.paint_tool.set('Auto (recommended)')
            h.window.flush()
            self.assertIn('Start in Paint', h.texts())
            self.assertEqual(len(h.app.game.trace_info()), 1)
            self.assertEqual(len(h.app.paint_tool.trace_info()), 1)
            h.app.paint_tool.set('Eraser')
            pending = list(h.window.jobs.values())
            h.window.destroy()
            self.assertFalse(h.app.game.trace_info())
            self.assertFalse(h.app.paint_tool.trace_info())
            self.assertFalse(h.window.jobs)
            for callback in pending: callback()
            self.assertIsNone(h.app._getting_started_window)
            h.seen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
