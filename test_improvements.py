import tempfile
import unittest
import threading
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from Colors import allColors,save_calibration,load_calibration
from DrawBot import make_plan,make_test_plan,execute_plan
from ScreenGuard import GuardedMouse
from test_drawbot import Mouse,Monitor,NoWait,options


class Improvements(unittest.TestCase):
    def test_atomic_calibration_failure_keeps_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'calibration.json'
            positions=[(i,20) for i in range(18)];rgbs=[c.RGB for c in allColors]
            save_calibration(positions,rgbs,path);before=path.read_bytes()
            with patch('RuntimePaths.os.replace',side_effect=OSError('disk')):
                with self.assertRaises(OSError):save_calibration(positions,rgbs,path)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(len(list(Path(directory).iterdir())),1)

    def test_bad_calibration_does_not_mutate_colors(self):
        before=[(c.x,c.y,c.RGB) for c in allColors]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'calibration.json';path.write_text('{"version":1,"colors":[]}')
            with self.assertRaises(ValueError):load_calibration(path)
        self.assertEqual(before,[(c.x,c.y,c.RGB) for c in allColors])

    def test_three_stroke_test_plan(self):
        plan=make_test_plan((600,400),options())
        self.assertEqual(plan['count'],3)
        self.assertEqual(sum(bool(g) for g in plan['groups']),3)
        self.assertLessEqual(plan['fitted'][0],180)

    def test_deadline_stops_before_click(self):
        plan=make_test_plan((100,100),dict(options(),max_seconds=5))
        mouse=Mouse();ticks=iter([0,6])
        with self.assertRaisesRegex(InterruptedError,'Time limit'):
            execute_plan(plan,(0,0,100,100),[(0,0)]*18,mouse,NoWait(),threading.Event(),lambda *a:None,clock=lambda:next(ticks))
        self.assertEqual(mouse.actions,[('release',)])

    def test_brush_changes_preview_and_click_time_is_counted(self):
        original=Image.new('RGBA',(4,4),'black')
        a=make_test_plan((180,135),dict(options(),brush_px=1))
        b=make_test_plan((180,135),dict(options(),brush_px=20))
        self.assertTrue(a['preview'].tobytes()!=b['preview'].tobytes())
        self.assertGreater(a['estimate'],3)

    def test_wrong_rendered_color_stops(self):
        mouse=Mouse();monitor=Monitor();monitor.color=lambda p:(255,255,255)
        guard=GuardedMouse(mouse,monitor,1)
        with self.assertRaisesRegex(InterruptedError,'expected color'):
            guard.verify_ink((0,0),(0,0,0))
        self.assertFalse(mouse.held)

    def test_each_new_color_is_checked(self):
        mouse=Mouse();checks=[];mouse.verify_ink=lambda p,rgb:checks.append(rgb)
        plan=make_test_plan((180,135),options())
        execute_plan(plan,(0,0,180,135),[(0,0)]*18,mouse,NoWait(),threading.Event(),lambda *a:None)
        self.assertEqual(len(checks),3)


if __name__=='__main__':unittest.main()
