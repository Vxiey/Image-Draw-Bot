
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from DrawBot import DrawBotApp
from ResourceAllocation import resolve_cpu_workers, choose_parallel_backend, logical_cpu_count
from Version import APP_VERSION, FILE_VERSION


class Value:
    def __init__(self, value=None): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class Root:
    def __init__(self): self.after_calls = []; self.cancelled = []
    def after(self, delay, func=None): self.after_calls.append((delay, func)); return f'after-{len(self.after_calls)}'
    def after_cancel(self, token): self.cancelled.append(token)


class Button:
    def __init__(self): self.config = {}
    def configure(self, **kwargs): self.config.update(kwargs)


class PreviewStartSafetyV1018Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def make_app(self, *, palette=True, tool=True, armed=False):
        return SimpleNamespace(
            activity=None, closing=False, original=object(), corners=[(0, 0), (100, 100)], target_window=(123,(0,0,200,200)),
            palette_ready=palette, game=Value('Other drawing app'), paint_simple=Value(False),
            paint_tool=Value('Auto (recommended)'), full_draw_armed_until=(time.monotonic()+10 if armed else 0.0),
            draw_arm_after=None, root=Root(), status=Value(), summary=Value(), start=Button(), start_secondary=Button(), start_unlock=Button(), start_unlock_secondary=Button(), small_test_passed=True, safety_preflight_passed=True, safety_preflight_signature=None, safety_preflight_valid_until=time.monotonic()+60, dry_run_passed=True, dry_run_signature=None, dry_run_valid_until=time.monotonic()+60, target_lock_passed=True, target_lock_fingerprint=None, target_lock_signature=None, target_lock_text=Value(), target_lock_button=Button(), target_lock_secondary=Button(), preview_after=None,
            preview_render_after=None, needs_plan=False, plan={'old': True})

    def wire_start_methods(self, app):
        app._paint_tool_preflight_ready = lambda: True
        app._palette_preflight_ready = lambda: DrawBotApp._palette_preflight_ready(app)
        app._start_guard_ready = lambda require_image=True: DrawBotApp._start_guard_ready(app, require_image=require_image)
        app._refresh_start_buttons_text = lambda: DrawBotApp._refresh_start_buttons_text(app)
        app._disarm_full_draw = lambda reason='', update_text=True: DrawBotApp._disarm_full_draw(app, reason, update_text)
        app._full_draw_unlocked = lambda: DrawBotApp._full_draw_unlocked(app)
        app.area = lambda: (0, 0, 100, 100)
        app.target_client_rect = (0,0,200,200)
        app.target_dpi = 96
        app.target_lock_fingerprint = DrawBotApp._build_target_lock_fingerprint(app)
        app.target_lock_signature = DrawBotApp._target_lock_signature_from(app.target_lock_fingerprint)
        app.safety_preflight_signature = DrawBotApp._current_safety_signature(app)
        app.dry_run_signature = DrawBotApp._current_safety_signature(app)

    def test_start_button_is_locked_before_separate_unlock(self):
        app = self.make_app()
        self.wire_start_methods(app)
        with patch.object(DrawBotApp, 'draw') as draw, patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            DrawBotApp.start_full_drawing(app)
        draw.assert_not_called()
        self.assertIn('locked', app.status.get().lower())

    def test_unlock_button_never_draws(self):
        app = self.make_app()
        self.wire_start_methods(app)
        with patch.object(DrawBotApp, 'draw') as draw, patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            DrawBotApp.unlock_full_drawing(app)
        draw.assert_not_called()
        self.assertIn('Start Drawing', app.start.config.get('text', ''))
        self.assertIn('unlocked', app.status.get().lower())

    def test_start_after_unlock_calls_draw(self):
        app = self.make_app(armed=True)
        self.wire_start_methods(app)
        with patch.object(DrawBotApp, 'draw') as draw, patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            DrawBotApp.start_full_drawing(app)
        draw.assert_called_once()
        self.assertIs(draw.call_args.args[0], app)
        self.assertTrue(draw.call_args.kwargs['user_initiated'])

    def test_full_draw_blocked_without_palette(self):
        app = self.make_app(palette=False)
        self.wire_start_methods(app)
        DrawBotApp.unlock_full_drawing(app)
        self.assertIn('palette', app.status.get().lower())

    def test_manual_mode_blocks_profile_auto_preview(self):
        app = self.make_app()
        app.preview_mode = Value('Manual')
        app._auto_preview_enabled = lambda: DrawBotApp._auto_preview_enabled(app)
        with patch('DrawBot.log_event') as log:
            result = DrawBotApp._maybe_auto_preview(app, delay=1, reason='profile-change')
        self.assertFalse(result)
        self.assertEqual(app.root.after_calls, [])
        self.assertTrue(log.called)

    def test_auto_cpu_is_capped_and_engine_auto_uses_threads(self):
        workers = resolve_cpu_workers('Auto')
        self.assertLessEqual(workers, max(1, logical_cpu_count()))
        if logical_cpu_count() > 10:
            self.assertLessEqual(workers, 8)
        self.assertEqual(choose_parallel_backend('Auto', width=900, height=900, workers=max(2, workers), ram_budget_mb=4096), 'threads')

    def test_source_exposes_arm_button(self):
        source = (Path(__file__).resolve().parent / 'StudioUI.py').read_text(encoding='utf-8')
        self.assertIn('Unlock full drawing', source)
        self.assertIn('Start locked', source)
        self.assertIn('start_full_drawing', source)


if __name__ == '__main__': unittest.main()
