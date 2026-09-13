import unittest
from types import SimpleNamespace

from DrawBot import DrawBotApp
from ScreenGuard import GuardedMouse
from Version import APP_VERSION, FILE_VERSION


class Value:
    def __init__(self, value=None): self.value=value
    def get(self): return self.value
    def set(self, value): self.value=value


class Button:
    def configure(self, **kwargs): pass


class Mouse:
    def __init__(self): self.position=(40, 40); self.moves=[]; self.armed=False
    def get_position(self): return self.position
    def move(self, x, y): self.position=(x, y); self.moves.append((x, y))
    def click(self): pass
    def press(self): pass
    def release(self): pass
    def arm_input(self): self.armed=True
    def disarm_input(self): self.armed=False


class Monitor:
    def __init__(self):
        self.rect=(0, 0, 400, 400)
        self.client=(10, 10, 390, 390)
        self.dpi_value=96
    def rectangle(self, handle): return self.rect
    def client_rectangle(self, handle): return self.client
    def dpi(self, handle): return self.dpi_value
    def verify(self, target, point): return True


class LiveTargetMonitorV1025Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def make_app(self):
        image=SimpleNamespace(size=(64, 64))
        app=SimpleNamespace(
            original=image, corners=[(20, 30), (120, 130)],
            target_window=(123, (0, 0, 400, 400)), target_client_rect=(10, 10, 390, 390), target_dpi=96,
            game=Value('Microsoft Paint'), paint_simple=Value(True), paint_tool=Value('Use current tool'),
            target_lock_passed=False, target_lock_fingerprint=None, target_lock_signature=None,
            safety_preflight_passed=False, safety_preflight_signature=None, safety_preflight_valid_until=0.0,
            dry_run_passed=False, dry_run_signature=None, dry_run_valid_until=0.0,
            full_draw_armed_until=0.0, draw_arm_after=None,
            target_lock_text=Value(), status=Value(), summary=Value(),
            target_lock_button=Button(), target_lock_secondary=Button(), start=Button(), start_secondary=Button(),
            start_unlock=Button(), start_unlock_secondary=Button(), root=SimpleNamespace(after_cancel=lambda *a: None))
        app.area=lambda: (20, 30, 100, 100)
        fp=DrawBotApp._build_target_lock_fingerprint(app)
        app.target_lock_passed=True
        app.target_lock_fingerprint=fp
        app.target_lock_signature=DrawBotApp._target_lock_signature_from(fp)
        return app

    def test_live_monitor_allows_unchanged_fingerprint(self):
        app=self.make_app(); monitor=Monitor()
        live=DrawBotApp._make_live_target_check(app, interval=0.0)
        self.assertTrue(live(monitor, app.target_window, (30, 40)))
        self.assertTrue(app.target_lock_passed)

    def test_live_monitor_stops_on_dpi_change_and_invalidates_lock(self):
        app=self.make_app(); monitor=Monitor(); monitor.dpi_value=144
        live=DrawBotApp._make_live_target_check(app, interval=0.0)
        with self.assertRaisesRegex(InterruptedError, 'DPI changed'):
            live(monitor, app.target_window, (30, 40))
        self.assertFalse(app.target_lock_passed)

    def test_guarded_mouse_runs_live_check_before_move(self):
        calls=[]
        def live(monitor, target, point):
            calls.append((target, point))
            raise InterruptedError('live stop')
        mouse=Mouse(); monitor=Monitor(); guarded=GuardedMouse(mouse, monitor, (123, monitor.rect), live_target_check=live)
        with self.assertRaisesRegex(InterruptedError, 'live stop'):
            guarded.move(50, 60)
        self.assertEqual(mouse.moves, [])
        self.assertEqual(calls[0][1], (50, 60))


if __name__ == '__main__':
    unittest.main()
