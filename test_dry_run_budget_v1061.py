import threading
import unittest
from PIL import Image

from DrawBot import execute_plan
from Version import APP_VERSION, FILE_VERSION


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Stop:
    def __init__(self, clock):
        self.clock = clock

    def is_set(self):
        return False

    def wait(self, seconds):
        self.clock.t += max(0.0, float(seconds))
        return False


class Mouse:
    def __init__(self):
        self.position = (0, 0)
        self.actions = []
        self.held = False

    def get_position(self):
        return self.position

    def configure_precision(self, *_):
        pass

    def move(self, x, y):
        self.position = (int(x), int(y))
        self.actions.append(('move', int(x), int(y)))

    def click(self):
        self.actions.append(('click',))

    def press(self):
        self.held = True
        self.actions.append(('press',))

    def release(self):
        self.held = False
        self.actions.append(('release',))

    def disarm_input(self):
        pass


def make_plan():
    path = tuple((x, 5) for x in range(1, 10))
    return {
        'image': Image.new('RGBA', (10, 10), 'white'),
        'fitted': (10, 10),
        'groups': [[]],
        'execution_groups': [[path]],
        'execution_sequence': [],
        'count': 1,
        'options': {
            'delay': 0.05,
            'max_seconds': 0.20,
            'precision': 'High',
            'speed': 'Safe',
            'brush_px': 1,
            'paint_current_color': True,
            'strict_color_verification': False,
            'adaptive_color_verification': False,
            'visual_verification_enabled': False,
            'profile_name': 'Microsoft Paint',
            'edge_behavior': 'Hard Clip',
            'tool_actions': [],
            'fill_tool_actions': [],
            'fill_regions': [],
            'background_fill_plan': None,
        },
        'colors': ((0, 0, 0),),
        'color_selectors': (),
    }


class DryRunBudgetV1061Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_budget_expiry_is_normal_dry_run_completion(self):
        clock = Clock()
        mouse = Mouse()
        events = []
        plan = make_plan()
        execute_plan(
            plan,
            (100, 100, 20, 20),
            [],
            mouse,
            Stop(clock),
            threading.Event(),
            lambda *event: events.append(event),
            clock=clock,
            dry_run=True,
        )
        report = plan['options'].get('runtime_safety_report') or {}
        self.assertTrue(plan['options'].get('dry_run_budget_complete'))
        self.assertTrue(report.get('completed'))
        self.assertEqual((report.get('counts') or {}).get('stopped'), 0)
        self.assertTrue(any(k == 'status' and 'Dry run PASS' in str(v) for k, v in events))
        actions = [a[0] for a in mouse.actions]
        self.assertNotIn('click', actions)
        self.assertNotIn('press', actions)


if __name__ == '__main__':
    unittest.main()
