import unittest
from types import SimpleNamespace

from TimeBudgetEngine import resolve_budget
from ResourceScheduler import resolve_resource_schedule
from BrowserOneClick import choose_unique_candidate
from DeadlineScheduler import DeadlineScheduler, CATCH_UP, PANIC
from StartDrawingState import StartDrawingStateMachine
from GpuBackendStatus import verified_gpu_status
from DrawTimeEstimate import estimate_from_plan
from Version import APP_VERSION, FILE_VERSION


class DeadlineRuntimeOptimizerV10119Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_legacy_60_gets_real_reserve_by_default(self):
        meta=resolve_budget('60 sec',180,'Auto')
        self.assertEqual(meta['total_seconds'],60.0)
        self.assertEqual(meta['reserve_seconds'],7.0)
        self.assertEqual(meta['render_budget_seconds'],53.0)
        self.assertEqual(meta['hard_stop_seconds'],60.0)
        off=resolve_budget('60 sec',180,'Off')
        self.assertEqual(off['reserve_seconds'],0.0)
        self.assertEqual(off['render_budget_seconds'],60.0)

    def test_preview_workers_scale_but_stay_bounded(self):
        allocation={'cpu_workers':'Auto','cpu_workers_resolved':16,'logical_cpus':32,'cpu_engine':'Auto','ram_budget_mb':4096}
        small=resolve_resource_schedule(allocation,mode='Auto',area=(200,200),preview=True,gpu_mode='CPU')
        large=resolve_resource_schedule(allocation,mode='Auto',area=(1000,700),preview=True,gpu_mode='CPU')
        self.assertEqual(small['phases']['connected_components']['workers'],1)
        self.assertGreater(large['effective_cpu_workers'],1)
        self.assertLessEqual(large['effective_cpu_workers'],4)

    def test_browser_context_resolves_visual_tie(self):
        a=SimpleNamespace(handle=10,confidence=.90,palette_count=18,canvas_box=(1,2,300,200),client_rect=(0,0,900,600),area=540000)
        b=SimpleNamespace(handle=20,confidence=.895,palette_count=18,canvas_box=(1,2,300,200),client_rect=(0,0,900,600),area=540000)
        with self.assertRaises(ValueError):
            choose_unique_candidate([a,b])
        self.assertIs(choose_unique_candidate([a,b],preferred_handle=20),b)
        self.assertIs(choose_unique_candidate([a,b],foreground_handle=10),a)

    def test_scheduler_enters_catch_up_before_panic(self):
        now=[0.0]
        clock=lambda:now[0]
        seq=[{'estimated_cost_seconds':4.5,'deadline_phase':'major_coverage','importance':.9,'structural_score':.9},
             {'estimated_cost_seconds':4.5,'deadline_phase':'structure','importance':.8,'structural_score':.8}]
        sched=DeadlineScheduler(seq,start_time=0,budget_seconds=10,clock=clock)
        d=sched.before(seq[0])
        self.assertEqual(d.mode,CATCH_UP)
        self.assertFalse(d.panic)
        now[0]=2.0
        # New scheduler whose 9.5s remaining work cannot fit into 8s.
        panic_seq=[{'estimated_cost_seconds':5.0,'deadline_phase':'major_coverage','importance':.9,'structural_score':.9},
                   {'estimated_cost_seconds':4.5,'deadline_phase':'correction','importance':.2,'structural_score':0}]
        panic=DeadlineScheduler(panic_seq,start_time=0,budget_seconds=10,clock=clock)
        pd=panic.before(panic_seq[0])
        self.assertEqual(pd.mode,PANIC)
        self.assertTrue(pd.panic)

    def test_structural_coverage_gate_blocks_early_detail(self):
        now=[0.0];clock=lambda:now[0]
        detail={'estimated_cost_seconds':.4,'deadline_phase':'important_details','importance':.45,'structural_score':0,'optional':True}
        structure={'estimated_cost_seconds':.4,'deadline_phase':'structure','importance':.9,'structural_score':.9}
        sched=DeadlineScheduler([detail,structure],start_time=0,budget_seconds=20,clock=clock)
        decision=sched.before(detail)
        self.assertFalse(decision.execute)
        self.assertIn('75%',decision.reason)

    def test_start_state_tracks_block_reason_and_stall(self):
        now=[0.0]
        sm=StartDrawingStateMachine(clock=lambda:now[0])
        sm.transition('PREFLIGHT','checking browser canvas')
        now[0]=2.2
        self.assertTrue(sm.stalled(2.0))
        self.assertIn('checking browser canvas',sm.watchdog_text(2.0))
        sm.transition('PLAN_READY','ready')
        sm.transition('INPUT_ARMED','armed')
        sm.transition('DRAWING','drawing')
        sm.transition('COMPLETED','done')
        self.assertEqual(sm.state,'COMPLETED')

    def test_cpu_gpu_status_is_explicit(self):
        status=verified_gpu_status('CPU','Auto','Balanced',pixels=500000,preview=False)
        self.assertEqual(status['selected_backend'],'CPU')
        self.assertFalse(status['gpu_analysis_active'])
        self.assertIn('CPU',status['fallback_reason'])

    def test_cold_start_estimate_is_not_raw_theory(self):
        plan={'estimate':10.0,'count':100,'plan_area':(400,300),'preview_area':(400,300),'target_area':(400,300),
              'options':{'profile_key':'v119-test-isolated-no-history'},'path_stats':{}}
        meta=estimate_from_plan(plan)
        self.assertGreater(meta['projected_seconds'],10.0)
        self.assertEqual(meta['confidence'],'cold-start')
        self.assertGreater(meta['high_seconds'],meta['projected_seconds'])


if __name__=='__main__':
    unittest.main()
