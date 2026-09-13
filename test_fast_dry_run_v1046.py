import unittest
from pathlib import Path
from FastDryRun import sample_indices, sample_plan, DRY_RUN_PLANNING_SECONDS, DRY_RUN_EXECUTION_SECONDS
from PlanningWatchdog import build_planning_attempts
from Version import APP_VERSION, FILE_VERSION

class FastDryRunV1046Tests(unittest.TestCase):
    def test_even_sampling_keeps_edges(self):
        self.assertEqual(sample_indices(10,4),[0,3,6,9])
        self.assertEqual(sample_indices(3,8),[0,1,2])

    def test_plan_caps_colors_and_paths(self):
        groups=[]
        for c in range(18):groups.append([(x,c,x+1,c) for x in range(100)])
        plan={'groups':groups,'execution_groups':None,'execution_sequence':[],'count':1800,
              'options':{'color_order':list(range(18)),'max_seconds':999},'colors':tuple((i,i,i) for i in range(18))}
        out=sample_plan(plan,max_colors=4,max_paths=8)
        self.assertLessEqual(len(out['options']['color_order']),4)
        self.assertLessEqual(out['count'],8)
        self.assertEqual(out['options']['max_seconds'],DRY_RUN_EXECUTION_SECONDS)
        self.assertTrue(out['options']['dry_run_sampled'])
        self.assertFalse(out['options']['adaptive_color_verification'])

    def test_progressive_sequence_is_sampled(self):
        seq=[{'color_index':i%5,'path':((i,0),(i+1,0)),'phase':'details'} for i in range(200)]
        plan={'groups':[[] for _ in range(5)],'execution_sequence':seq,'count':200,'options':{}}
        out=sample_plan(plan,max_paths=8)
        self.assertEqual(len(out['execution_sequence']),8)
        self.assertEqual(out['count'],8)

    def test_watchdog_has_single_short_dry_run_attempt(self):
        attempts=build_planning_attempts({'planning_watchdog':'Auto','cpu_workers_resolved':32,'drawing_mode':'Shape paths'},dry_run=True)
        self.assertEqual(len(attempts),1)
        a=attempts[0]
        self.assertLessEqual(a.timeout_seconds,DRY_RUN_PLANNING_SECONDS)
        self.assertLessEqual(a.options['cpu_workers_resolved'],4)
        self.assertEqual(a.options['target_stroke_count_resolved'],500)
        self.assertEqual(a.options['gpu_mode'],'CPU')

    def test_ui_labels_fast_bounded_dry_run(self):
        text=Path('StudioUI.py').read_text(encoding='utf-8')
        self.assertIn('Fast Dry run · ≤12s',text)

    def test_release_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')

if __name__=='__main__':unittest.main()
