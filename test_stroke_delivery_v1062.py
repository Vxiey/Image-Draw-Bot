import unittest
from unittest.mock import patch

from StrokeDelivery import resolve_stroke_delivery
from WindowsMouse import WindowsMouse
from Version import APP_VERSION, FILE_VERSION


class StrokeDeliveryV1063Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_paint_auto_uses_reliable_delivery_for_non_pixel_draws(self):
        policy=resolve_stroke_delivery({'profile_name':'Microsoft Paint','stroke_step_px':8},dry_run=False)
        self.assertLessEqual(policy.step_px,2.5)
        self.assertGreaterEqual(policy.min_path_delay,0.003)
        self.assertGreaterEqual(policy.press_settle,0.010)
        self.assertGreaterEqual(policy.release_settle,0.006)
        self.assertEqual(policy.drag_backend,'sendinput')
        self.assertTrue(policy.native_drag_reliability)

    def test_paint_shape_paths_get_denser_reliable_line_policy(self):
        policy=resolve_stroke_delivery({'profile_name':'Microsoft Paint','stroke_step_px':8,'drawing_mode':'Shape paths'},dry_run=False)
        self.assertEqual(policy.step_px,2.0)
        self.assertEqual(policy.drag_backend,'sendinput')
        self.assertIn('line',policy.label.lower())

    def test_paint_pixel_accurate_auto_uses_noncoalesced_sendinput_drag(self):
        policy=resolve_stroke_delivery({
            'profile_name':'Microsoft Paint',
            'profile_key':'microsoft-paint',
            'stroke_step_px':8,
            'pixel_accurate':True,
        },dry_run=False)
        self.assertEqual(policy.drag_backend,'sendinput')
        self.assertTrue(policy.native_drag_reliability)
        self.assertLessEqual(policy.step_px,2.0)
        self.assertGreater(policy.min_path_delay,0)
        self.assertIn('Pixel Accurate',policy.label)

    def test_paint_pixel_accurate_string_fallback_is_reliable(self):
        policy=resolve_stroke_delivery({
            'profile_name':'Microsoft Paint',
            'stroke_step_px':8,
            'draw_quality':'Pixel Accurate',
        },dry_run=False)
        self.assertEqual(policy.drag_backend,'sendinput')
        self.assertTrue(policy.native_drag_reliability)

    def test_explicit_compatible_still_overrides_pixel_accurate_auto(self):
        policy=resolve_stroke_delivery({
            'profile_name':'Microsoft Paint',
            'stroke_step_px':8,
            'pixel_accurate':True,
            'paint_stroke_delivery':'Compatible',
        },dry_run=False)
        self.assertEqual(policy.drag_backend,'cursor')
        self.assertFalse(policy.native_drag_reliability)

    def test_explicit_reliable_mode_remains_available(self):
        policy=resolve_stroke_delivery({'profile_name':'Microsoft Paint','stroke_step_px':8,'paint_stroke_delivery':'Reliable'},dry_run=False)
        self.assertEqual(policy.drag_backend,'sendinput')
        self.assertTrue(policy.native_drag_reliability)
        self.assertLessEqual(policy.step_px,3.0)

    def test_dry_run_does_not_arm_reliable_paint_drag(self):
        policy=resolve_stroke_delivery({'profile_name':'Microsoft Paint','stroke_step_px':8,'pixel_accurate':True},dry_run=True)
        self.assertEqual(policy.step_px,8.0)
        self.assertEqual(policy.drag_backend,'cursor')
        self.assertFalse(policy.native_drag_reliability)

    def test_held_mouse_defaults_to_compatible_cursor_backend(self):
        mouse=WindowsMouse.__new__(WindowsMouse)
        mouse._input_armed=True;mouse.held=True;mouse.drag_backend='cursor'
        mouse.position_tolerance=0;mouse.position_attempts=2;mouse.position_retry_after=0
        mouse.get_position=lambda:(100,100);mouse.desktop_rect=lambda:(0,0,1920,1080);mouse.buttons_down=lambda:()
        sent=[];mouse._send_absolute_move=lambda x,y:sent.append((x,y))
        class Api:
            def SetCursorPos(self,x,y):return 1
        mouse.api=Api()
        with patch('WindowsMouse.time.sleep'), patch('WindowsMouse.ctypes.set_last_error', create=True):
            mouse.move(100,100)
        self.assertEqual(sent,[])

    def test_held_sendinput_backend_uses_absolute_noncoalesced_path(self):
        mouse=WindowsMouse.__new__(WindowsMouse)
        mouse._input_armed=True;mouse.held=True;mouse.drag_backend='sendinput'
        mouse.position_tolerance=0;mouse.position_attempts=2;mouse.position_retry_after=0
        position=[100,100]
        mouse.get_position=lambda:tuple(position)
        mouse.desktop_rect=lambda:(0,0,1920,1080);mouse.buttons_down=lambda:()
        sent=[]
        def absolute(x,y):
            sent.append((x,y));position[:]=[x,y]
        mouse._send_absolute_move=absolute
        class Api:
            def SetCursorPos(self,x,y):
                raise AssertionError('held reliable drag must not fall back to SetCursorPos')
        mouse.api=Api()
        with patch('WindowsMouse.time.sleep'):
            mouse.move(120,130)
        self.assertEqual(sent,[(120,130)])

if __name__=='__main__': unittest.main()
