import unittest
from StrokeDelivery import resolve_stroke_delivery
from Version import APP_VERSION, FILE_VERSION


class PerGameInputEngineV1075Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')

    def test_three_games_have_distinct_policies(self):
        g=resolve_stroke_delivery({'profile_name':'Gartic Phone','stroke_step_px':8})
        s=resolve_stroke_delivery({'profile_name':'Skribbl.io Fast','stroke_step_px':8})
        h=resolve_stroke_delivery({'profile_name':'SketchHeads','stroke_step_px':8})
        self.assertEqual(g.profile_key,'gartic-phone')
        self.assertEqual(s.profile_key,'skribbl-fast')
        self.assertEqual(h.profile_key,'sketchheads')
        self.assertNotEqual(g.palette_click_delay,s.palette_click_delay)
        self.assertNotEqual(s.palette_click_delay,h.palette_click_delay)
        self.assertNotEqual(g.press_settle,h.press_settle)
        self.assertGreaterEqual(g.step_px,12)
        self.assertGreaterEqual(s.step_px,12)
        self.assertGreaterEqual(h.step_px,8)

    def test_skribbl_quality_and_fast_are_independently_tuned(self):
        q=resolve_stroke_delivery({'profile_name':'Skribbl.io','stroke_step_px':8})
        f=resolve_stroke_delivery({'profile_name':'Skribbl.io Fast','stroke_step_px':8})
        self.assertGreater(q.palette_click_delay,f.palette_click_delay)
        self.assertGreater(q.press_settle,f.press_settle)
        self.assertLessEqual(q.step_px,f.step_px)

    def test_dry_run_remains_click_free_timing(self):
        g=resolve_stroke_delivery({'profile_name':'Gartic Phone','stroke_step_px':8},dry_run=True)
        self.assertEqual(g.press_settle,0)
        self.assertEqual(g.release_settle,0)
        self.assertEqual(g.min_path_delay,0)
        self.assertEqual(g.drag_backend,'cursor')

    def test_paint_policy_is_unchanged_by_browser_engine(self):
        p=resolve_stroke_delivery({'profile_name':'Microsoft Paint','stroke_step_px':8},dry_run=False)
        self.assertEqual(p.profile_key,'microsoft-paint')
        self.assertLessEqual(p.step_px,2.5)
        self.assertEqual(p.drag_backend,'sendinput')
        self.assertTrue(p.native_drag_reliability)
        self.assertEqual(p.palette_click_delay,.28)


if __name__=='__main__': unittest.main()
