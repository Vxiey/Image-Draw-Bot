import unittest
from types import SimpleNamespace
from unittest.mock import patch

from AnchorTransform import rebase_canvas_area, area_inside_client
from DrawBot import DrawBotApp
from Version import APP_VERSION, FILE_VERSION


class Value:
    def __init__(self, value=None): self.value=value
    def get(self): return self.value
    def set(self, value): self.value=value


class Button:
    def __init__(self): self.config={}
    def configure(self, **kwargs): self.config.update(kwargs)


class Root:
    def after_cancel(self, *args): pass


def anchor_options():
    return {
        'canvas_polygon': ((0.0,0.0),(1.0,0.0),(1.0,1.0),(0.0,1.0)),
        'canvas_polygon_space': 'normalized',
        'canvas_anchors': (
            {'kind':'corner','center':(0.0,0.0),'confidence':1.0},
            {'kind':'corner','center':(1.0,0.0),'confidence':1.0},
            {'kind':'corner','center':(1.0,1.0),'confidence':1.0},
            {'kind':'corner','center':(0.0,1.0),'confidence':1.0},
            {'kind':'triangle','center':(0.20,0.20),'tip':(0.22,0.12),'confidence':0.90},
            {'kind':'triangle','center':(0.80,0.20),'tip':(0.78,0.12),'confidence':0.90},
            {'kind':'triangle','center':(0.50,0.50),'tip':(0.50,0.42),'confidence':0.90},
            {'kind':'triangle','center':(0.20,0.80),'tip':(0.12,0.78),'confidence':0.90},
            {'kind':'triangle','center':(0.80,0.80),'tip':(0.88,0.78),'confidence':0.90},
            {'kind':'triangle','center':(0.50,0.86),'tip':(0.50,0.94),'confidence':0.90},
        ),
        'canvas_anchor_space': 'normalized',
        'canvas_anchor_meta': {'confidence': 1.0, 'triangle_count': 6, 'corner_count': 4},
    }


class AnchorTransformV1050Tests(unittest.TestCase):
    def test_version_bumped(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_rebase_translation_uses_anchor_evidence(self):
        area, transform = rebase_canvas_area((100,200,500,300), (8,31,1008,731), (28,41,1028,741), anchor_options())
        self.assertEqual(area, (120,210,500,300))
        self.assertEqual(transform.method, 'anchors+triangles')
        self.assertEqual(transform.used_triangles, 6)
        self.assertGreaterEqual(transform.used_anchors, 10)
        self.assertAlmostEqual(transform.sx, 1.0)
        self.assertAlmostEqual(transform.sy, 1.0)

    def test_tiny_client_scale_rebases_canvas(self):
        area, transform = rebase_canvas_area((100,200,500,300), (0,0,1000,700), (10,20,1018,724), anchor_options())
        self.assertEqual(area, (111,221,504,302))
        self.assertEqual(transform.method, 'anchors+triangles')
        self.assertTrue(transform.scale_changed)
        self.assertTrue(area_inside_client(area, (10,20,1018,724)))

    def test_large_resize_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'too large'):
            rebase_canvas_area((100,200,500,300), (0,0,1000,700), (0,0,1200,850), anchor_options())

    def make_locked_app(self):
        image=SimpleNamespace(size=(64,64))
        app=SimpleNamespace(
            original=image, corners=[(100,200),(600,500)], saved_area=[(100,200),(600,500)],
            target_window=(123,(0,0,1016,739)), target_client_rect=(8,31,1008,731), target_dpi=96,
            game=Value('Other drawing app'), paint_simple=Value(False), paint_tool=Value('Use current tool'),
            palette_ready=True, small_test_passed=True, canvas_anchor_detection=anchor_options(),
            canvas_anchor_transform_meta=None, calibration_path='unused.json',
            target_lock_passed=True, target_lock_fingerprint=None, target_lock_signature=None,
            safety_preflight_passed=False, safety_preflight_signature=None, safety_preflight_valid_until=0.0,
            dry_run_passed=False, dry_run_signature=None, dry_run_valid_until=0.0,
            full_draw_armed_until=0.0, draw_arm_after=None,
            target_lock_text=Value(), status=Value(), summary=Value(), next_step=Value(), root=Root(),
            target_lock_button=Button(), target_lock_secondary=Button(), start=Button(), start_secondary=Button(),
            start_unlock=Button(), start_unlock_secondary=Button())
        app.area=lambda: (min(app.corners[0][0],app.corners[1][0]), min(app.corners[0][1],app.corners[1][1]),
                          abs(app.corners[1][0]-app.corners[0][0]), abs(app.corners[1][1]-app.corners[0][1]))
        app._palette_preflight_ready=lambda: DrawBotApp._palette_preflight_ready(app)
        app._disarm_full_draw=lambda reason='',update_text=True: DrawBotApp._disarm_full_draw(app,reason,update_text)
        app._refresh_start_buttons_text=lambda: DrawBotApp._refresh_start_buttons_text(app)
        app._refresh_target_lock_text=lambda: DrawBotApp._refresh_target_lock_text(app)
        fp=DrawBotApp._build_target_lock_fingerprint(app)
        app.target_lock_fingerprint=fp
        app.target_lock_signature=DrawBotApp._target_lock_signature_from(fp)
        return app

    def test_verify_target_lock_allows_same_size_move_by_rebasing(self):
        app=self.make_locked_app()
        meta={'handle':123,'rect':(20,10,1036,749),'client_rect':(28,41,1028,741),'target_pid':1,'dpi':96}
        with patch('TargetCapture.probe_handle_isolated', return_value=meta), patch('DrawBot.load_calibration', return_value={'count':0}):
            self.assertTrue(DrawBotApp._verify_target_lock(app))
        self.assertEqual(app.corners, [(120,210),(620,510)])
        self.assertTrue(app.target_lock_passed)
        self.assertEqual(app.canvas_anchor_transform_meta['method'], 'anchors+triangles')


if __name__ == '__main__':
    unittest.main()
