import unittest
from pathlib import Path
from DeadlineScheduler import DeadlineScheduler, NORMAL, CATCH_UP, PANIC
from Version import APP_VERSION


def entry(i, *, phase='structure', importance=.5, structural=.5, optional=False, color=0, brush=4, cost=1.0):
    return {'source_index':i,'path':((i,0),(i+1,0)),'deadline_phase':phase,
            'estimated_cost_seconds':cost,'importance':importance,'structural_score':structural,
            'optional':optional,'color_index':color,'brush_px':brush,'operation_type':'stroke'}

class Rc8DynamicReplannerTests(unittest.TestCase):
    def scheduler(self, seq):
        return DeadlineScheduler(seq,start_time=0.0,budget_seconds=20.0,clock=lambda:0.0)

    def test_normal_mode_preserves_planned_order(self):
        seq=[entry(0,importance=.1),entry(1,importance=.9)]
        s=self.scheduler(seq)
        self.assertEqual([x['source_index'] for x in s.replan_remaining(seq,force=True)],[0,1])
        self.assertEqual(s.mode,NORMAL)

    def test_catchup_prioritizes_high_value_inside_phase_only(self):
        seq=[entry(0,importance=.2,structural=.2),entry(1,importance=.95,structural=.9),entry(2,importance=.6,structural=.6)]
        s=self.scheduler(seq);s.mode=CATCH_UP;s._global_samples=3
        out=s.replan_remaining(seq,force=True)
        self.assertEqual(out[0]['source_index'],1)
        self.assertEqual(sorted(x['source_index'] for x in out),[0,1,2])
        self.assertGreaterEqual(s.replan_count,1)

    def test_phase_barriers_are_never_crossed(self):
        seq=[entry(0,phase='structure',importance=.1),entry(1,phase='important_details',importance=.1),entry(2,phase='structure',importance=.99)]
        s=self.scheduler(seq);s.mode=PANIC;s._global_samples=4
        out=s.replan_remaining(seq,force=True)
        self.assertEqual([x['deadline_phase'] for x in out],['structure','important_details','structure'])
        self.assertEqual([x['source_index'] for x in out],[0,1,2])

    def test_replan_never_increases_color_brush_transitions(self):
        seq=[entry(0,importance=.2,color=0,brush=4),entry(1,importance=.95,color=1,brush=8),entry(2,importance=.8,color=0,brush=4)]
        s=self.scheduler(seq);s.mode=CATCH_UP;s._global_samples=3
        before=s._transition_count(seq);out=s.replan_remaining(seq,force=True)
        self.assertLessEqual(s._transition_count(out),before)
        self.assertEqual(sorted(tuple(x['path']) for x in out),sorted(tuple(x['path']) for x in seq))

    def test_drawbot_has_runtime_replan_hook(self):
        src=Path('DrawBot.py').read_text(encoding='utf-8')
        self.assertIn('enumerate(execution_sequence)',src)
        self.assertIn('deadline_scheduler.replan_remaining(_tail)',src)

    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')

if __name__=='__main__':unittest.main()
