"""Queued starts, runtime reporting and browser control correctness."""
import dataclasses
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from DrawBot import DrawBotApp, execute_plan, make_plan
from DropInStart import DROP_IN_ACTION
from DropInSynchronization import make_request, request_expired, target_fingerprint, target_matches
from SmartDropInCanvas import (SmartCanvasCandidate, choose_candidate, discover_canvas_target,
                               point_in_canvas, score_candidate)
from UIState import classify_error, compute_workspace_state
from test_drawbot import Mouse, NoWait, options
from test_drop_in_synchronization_v1073 import make_app


def plan_for_runtime(**extra):
    return make_plan(Image.new('RGB', (8, 4), 'black'), (80, 40),
                     dict(options(), brush_px=3, **extra))


def execute(plan, mouse=None, keyboard=None, *, dry_run=False):
    mouse = mouse or Mouse()
    execute_plan(plan, (100, 100, 80, 40), [(10, i) for i in range(18)], mouse,
                 NoWait(), threading.Event(), lambda *_: None, keyboard=keyboard,dry_run=dry_run)
    return mouse


class RuntimeControlTests(unittest.TestCase):
    def brush_plan(self):
        return {'profile_key':'gartic-phone','target_position':(900,100),
                'control_positions':[(900+i*40,100) for i in range(5)],
                'nominal_sizes':[2,4,8,16,28],'verified_sizes':[2,4,8,16,28],
                'verified_indices':[0,1,2,3,4],'selected_index':0,'target_index':0,
                'confidence':.95,'effective_px':2,'safe_guard_px':4}

    def test_dry_run_does_not_claim_opacity_was_applied(self):
        plan=plan_for_runtime(gartic_opacity_plan={'selected_percent':100,'target_position':(900,100)})
        mouse=execute(plan,dry_run=True)
        self.assertFalse(plan['options']['gartic_opacity_runtime_meta']['applied'])
        self.assertTrue(plan['options']['gartic_opacity_runtime_meta']['simulated'])
        self.assertFalse(any(action[0] in ('click','press') for action in mouse.actions))

    def test_stale_selected_brush_cannot_shrink_guard(self):
        plan=plan_for_runtime(browser_brush_plan=self.brush_plan())
        with patch('BrowserBrushSize.verify_brush_selection',return_value=False) as verify:
            execute(plan)
        self.assertEqual(verify.call_count,2)
        self.assertFalse(plan['options']['browser_brush_runtime']['verified'])
        self.assertEqual(plan['options']['canvas_guard_meta']['brush_inset']['brush_px'],28)

    def test_fresh_selected_brush_installs_its_actual_inset(self):
        plan=plan_for_runtime(browser_brush_plan=self.brush_plan())
        with patch('BrowserBrushSize.verify_brush_selection',return_value=True):
            execute(plan)
        self.assertFalse(plan['options']['browser_brush_runtime']['clicked'])
        self.assertTrue(plan['options']['browser_brush_runtime']['verified'])
        self.assertEqual(plan['options']['canvas_guard_meta']['brush_inset']['brush_px'],2)

    def test_unconfirmed_adaptive_selection_stops_before_a_stroke(self):
        plan=plan_for_runtime(browser_brush_plan=self.brush_plan())
        plan['execution_sequence']=[{'color_index':0,'path':((1,1),(2,1)),'brush_px':8}]
        mouse=Mouse()
        with patch('BrowserBrushSize.verify_brush_selection',side_effect=[True,False]), \
             self.assertRaisesRegex(InterruptedError,'brush selection'):
            execute(plan,mouse)
        self.assertFalse(any(action[0]=='press' for action in mouse.actions))
        self.assertEqual(plan['options']['canvas_guard_meta']['brush_inset']['brush_px'],28)

    def test_eraser_spacing_uses_ink_width_not_conservative_guard(self):
        plan=plan_for_runtime(canvas_guard_brush_px=12,auto_clear_canvas=True,
            canvas_clear_strategy='eraser-sweep',canvas_clear_actions=[('eraser',(900,100))],
            canvas_clear_restore_actions=[('brush',(910,100))])
        with patch('CanvasClear.eraser_row_spacing',return_value=2) as spacing:
            execute(plan)
        spacing.assert_called_once_with(3)

    def test_full_opacity_is_applied_after_previous_transparent_drawing(self):
        plan = plan_for_runtime(gartic_opacity_plan={'selected_percent': 100, 'target_position': (900, 100)})
        mouse = execute(plan)
        self.assertIn(('move', 900, 100), mouse.actions)
        meta = plan['options']['gartic_opacity_runtime_meta']
        self.assertTrue(meta['applied'])
        self.assertEqual(meta['percent'], 100)

    def test_unknown_opacity_is_not_reported_as_applied_opaque(self):
        plan = plan_for_runtime(gartic_opacity_plan={'selected_percent': 30, 'target_position': None})
        execute(plan)
        meta = plan['options']['gartic_opacity_runtime_meta']
        self.assertFalse(meta['applied'])
        self.assertIsNone(meta['percent'])

    def test_old_brush_selection_does_not_prove_a_new_selection(self):
        plan = plan_for_runtime(browser_brush_plan={'target_position': (900, 100),
            'selected_index': 0, 'target_index': 3, 'confidence': .95, 'effective_px': 8, 'safe_guard_px': 16})
        with patch('BrowserBrushSize.capture_control_patch', return_value=None), \
             patch('BrowserBrushSize.patch_change_score', return_value=0):
            execute(plan)
        self.assertFalse(plan['options']['browser_brush_runtime']['verified'])

    def test_keyboard_focus_is_rechecked_between_clear_commands(self):
        plan = plan_for_runtime(auto_clear_canvas=True, canvas_clear_strategy='paint-shortcut', paint_profile=True)
        mouse = Mouse()
        mouse.check_keyboard = Mock(side_effect=[None, InterruptedError('focus changed')])
        keyboard = Mock()
        with self.assertRaisesRegex(InterruptedError, 'focus changed'):
            execute(plan, mouse, keyboard)
        keyboard.press_and_release.assert_called_once_with('ctrl+a')

    def test_report_export_failure_keeps_actual_execution_evidence(self):
        plan = plan_for_runtime()
        with patch('RuntimeSafetyReport.replace_text_files', side_effect=PermissionError('locked')):
            execute(plan)
        report = plan['options']['runtime_safety_report']
        self.assertEqual(report['save_error'], 'locked')
        self.assertGreater(report['counts']['processed'], 0)
        self.assertIn('fills', report)

    def test_successful_filename_does_not_turn_ready_state_into_error(self):
        kwargs = dict(image_loaded=True, target_name='Gartic Phone', paint_tools_ready=True,
                      area_ready=True, palette_ready=True, test_passed=True, strict_safety=False)
        for status in ('PNG saved: crash.png', 'Recording saved: timeout.gif',
                       'Diagnostics package created: crash-report.zip', 'App data: C:/crash-reports'):
            with self.subTest(status=status):
                self.assertIsNone(classify_error(status))
                self.assertTrue(compute_workspace_state(**kwargs, status=status).ready)
        self.assertIsNotNone(classify_error('Could not save PNG: disk full'))


class PendingAuthorizationTests(unittest.TestCase):
    def test_missing_target_identity_cannot_match_itself(self):
        fp = target_fingerprint('Gartic Phone', None)
        request = make_request(None, 'image', DROP_IN_ACTION, fp, now=10)
        self.assertFalse(target_matches(request, fp))

    def test_geometry_reflow_keeps_the_same_positive_window_identity(self):
        fp = target_fingerprint('Gartic Phone', (123, (0, 0, 800, 600)))
        request = make_request(None, 'image', DROP_IN_ACTION, fp, now=10)
        moved = target_fingerprint('Gartic Phone', (123, (-800, 0, 0, 600)), dpi=144)
        self.assertTrue(target_matches(request, moved))

    def test_invalid_optional_probe_metadata_is_a_missing_value(self):
        fp = target_fingerprint('Gartic Phone', (float('inf'), [0, 0, float('inf'), 600]), dpi=float('nan'))
        self.assertEqual(fp[1:3], (None, None))
        self.assertIsNone(fp[4])

    def test_unbounded_or_nonfinite_authorization_is_not_created(self):
        for kwargs in ({'now': float('nan')}, {'timeout_seconds': float('inf')}, {'timeout_seconds': -5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                make_request(None, 'image', DROP_IN_ACTION, ('Gartic Phone', 123), **kwargs)
        request = make_request(None, 'image', DROP_IN_ACTION, ('Gartic Phone', 123), now=10, timeout_seconds=1e9)
        self.assertEqual(request.deadline, 310)
        self.assertTrue(request_expired(dataclasses.replace(request, deadline=float('nan')), now=10))
        self.assertTrue(request_expired(request, now=310))

    def test_escape_before_queued_start_revokes_authorization(self):
        app = make_app()
        app.drop_action_pending = DROP_IN_ACTION
        app.stop = threading.Event(); app.stop.set()
        with patch.object(DrawBotApp, 'draw') as draw:
            self.assertFalse(DrawBotApp._run_pending_drop_in_start(app))
        draw.assert_not_called()
        self.assertFalse(app.manual_drop_in_start.get())

    def test_escape_during_target_verification_cannot_be_cleared_by_new_worker(self):
        app = make_app()
        app.drop_action_pending = DROP_IN_ACTION
        app.stop = threading.Event(); app.original = object()
        def refresh():
            app.stop.set()
            return app.target_client_rect
        app._refresh_target_for_draw = refresh
        with patch.object(DrawBotApp, '_start_guard_ready', return_value=(True, 'ready')), \
             patch.object(DrawBotApp, 'draw') as draw:
            self.assertFalse(DrawBotApp._run_pending_drop_in_start(app))
        draw.assert_not_called()

    def test_unrelated_work_does_not_leave_a_future_drop_in_start_armed(self):
        app = make_app(activity='record')
        app.drop_action_pending = DROP_IN_ACTION
        self.assertFalse(DrawBotApp._run_pending_drop_in_start(app))
        self.assertIsNone(app.drop_action_pending)
        self.assertFalse(app.manual_drop_in_start.get())


class SmartTargetTests(unittest.TestCase):
    def candidate(self, **kwargs):
        fields = dict(handle=10, rect=(0, 0, 800, 600), client_rect=(0, 0, 800, 600),
                      dpi=96, pid=1234, title='Gartic', canvas_box=(100, 100, 700, 500),
                      canvas_confidence=.9, score=1.0)
        fields.update(kwargs)
        return SmartCanvasCandidate(**fields)

    def test_invalid_high_ranked_detection_cannot_be_selected(self):
        for changes in ({'score': float('nan')}, {'canvas_confidence': float('nan')},
                        {'canvas_confidence': 2}, {'handle': 0}, {'canvas_box': (-5, 0, 700, 500)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                choose_candidate([self.candidate(**changes)])

    def test_invalid_detection_does_not_hide_a_valid_candidate(self):
        good = self.candidate()
        self.assertIs(choose_candidate([self.candidate(score=float('inf')), good]), good)
        self.assertEqual(score_candidate('gartic-phone', confidence=float('nan'),
            canvas_box=good.canvas_box, client_rect=good.client_rect), -1)

    def test_tiny_canvas_cannot_disable_its_drop_edge_margin(self):
        self.assertFalse(point_in_canvas((1, 1), (0, 0, 6, 6), margin=4))
        self.assertFalse(point_in_canvas((float('nan'), 10), (0, 0, 100, 100)))

    def test_preferred_target_failure_never_silently_selects_another_window(self):
        with patch('TargetCapture.probe_handle_isolated', side_effect=ValueError('not visible')), \
             patch('BrowserOneClick._enumerate_windows') as enumerate_windows:
            with self.assertRaisesRegex(ValueError, 'selected browser'):
                discover_canvas_target('gartic-phone', preferred_handle=10)
        enumerate_windows.assert_not_called()

    def test_discovery_cancellation_propagates_before_capture(self):
        with patch('BrowserOneClick._enumerate_windows') as enumerate_windows:
            with self.assertRaises(InterruptedError):
                discover_canvas_target('gartic-phone', cancelled=lambda: True)
        enumerate_windows.assert_not_called()

    def test_live_discovery_forwards_stop_into_canvas_scan_and_closes_capture(self):
        stop = threading.Event()
        meta = {'handle': 10, 'rect': (0, 0, 800, 600), 'client_rect': (0, 0, 800, 600)}
        for preferred in (None, 10):
            stop.clear()
            shot = Image.new('RGB', (800, 600))
            def capture(box):
                stop.set()
                return shot
            def detect(key, image, *, cancelled, **kwargs):
                self.assertTrue(cancelled())
                raise InterruptedError('stopped inside detector')
            with self.subTest(preferred=preferred), \
                 patch('TargetCapture.probe_handle_isolated', return_value=meta), \
                 patch('BrowserOneClick._enumerate_windows', return_value=[meta]), \
                 patch('ScreenGuard._grab_rgb', side_effect=capture), \
                 patch('BrowserAutoCalibration.detect_browser_canvas', side_effect=detect):
                with self.assertRaisesRegex(InterruptedError, 'inside detector'):
                    discover_canvas_target('gartic-phone', preferred_handle=preferred, cancelled=stop.is_set)
                with self.assertRaises(ValueError):
                    shot.getpixel((0, 0))


if __name__ == '__main__':
    unittest.main()
