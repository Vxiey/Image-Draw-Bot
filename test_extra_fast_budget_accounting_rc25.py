import unittest
from AdaptiveRegionHybrid import RegionChoice,_schedule
from ExecutionCostModel import build_cost_model
from Version import APP_VERSION

def choice(cid,color,cost=.01,gain=.1,phase='structure',protected=0,importance=.3):
    return RegionChoice(cid,color,'test',phase,100,importance,.2,protected,cost,gain,gain/(cost*1000),1,2,True,'test')

def seq(cid,color,brush=2,length=120,phase='structure'):
    y=cid*3+1
    return [{'color_index':color,'brush_px':brush,'path':((1,y),(length,y)),'phase':phase,'component_id':cid}]

def options(limit=8.0):
    return {'profile_key':'gartic','brush_px':2,'speed':'Balanced','delay':0.0,'time_budget_active':True,
            'time_budget_mode':'Custom','max_seconds':limit,'paint_current_color':False,
            'adaptive_color_verification':False,'fill_tool_available':False}

class ExtraFastBudgetAccountingRc25Tests(unittest.TestCase):
    def test_local_component_cost_does_not_pay_first_palette_switch_twice(self):
        opts=options();model=build_cost_model(opts,(200,120),(200,120));s=seq(1,3)
        global_cost=model.sequence_cost(s,initial_brush=2).total_seconds
        local_cost=model.sequence_cost(s,initial_color=3,initial_brush=2).total_seconds
        self.assertGreater(global_cost,local_cost)
        self.assertAlmostEqual(global_cost-local_cost,model.switch_cost('palette_change'),places=6)

    def test_same_phase_components_are_colour_batched(self):
        opts=options(30);model=build_cost_model(opts,(300,180),(300,180))
        choices=[choice(1,0),choice(2,1),choice(3,0),choice(4,1)]
        seqs={c.component_id:seq(c.component_id,c.color_index,length=20) for c in choices}
        _groups,execution,meta=_schedule(choices,seqs,(300,180),model,opts,[])
        colors=[e['color_index'] for e in execution]
        transitions=sum(a!=b for a,b in zip(colors,colors[1:]))
        self.assertLessEqual(transitions,1);self.assertTrue(meta['phase_color_batching'])
        self.assertEqual(meta['palette_switches'],transitions+1)

    def test_exact_final_sequence_never_exceeds_usable_deadline(self):
        opts=options(5.0);model=build_cost_model(opts,(500,300),(500,300))
        choices=[choice(i,i%3,cost=.001,gain=.05+i*.001) for i in range(1,25)]
        seqs={c.component_id:seq(c.component_id,c.color_index,length=450) for c in choices}
        _groups,_execution,meta=_schedule(choices,seqs,(500,300),model,opts,[])
        self.assertTrue(meta['exact_budget_guard'])
        self.assertLessEqual(meta['selected_path_cost_seconds'],meta['usable_path_seconds']+1e-6)
        self.assertLessEqual(meta.get('risk_adjusted_path_cost_seconds',meta['selected_path_cost_seconds']),meta['usable_path_seconds']+1e-6)

    def test_brush_switches_are_in_exact_schedule_cost(self):
        opts=options(30);model=build_cost_model(opts,(300,180),(300,180))
        choices=[choice(1,0),choice(2,0)];seqs={1:seq(1,0,2,length=30),2:seq(2,0,28,length=30)}
        _groups,_execution,meta=_schedule(choices,seqs,(300,180),model,opts,[])
        self.assertGreaterEqual(meta['brush_switches'],1)
        self.assertGreater(meta['selected_operation_cost']['brush_seconds'],0)

    def test_version_stays_rc25(self): self.assertEqual(APP_VERSION,'1.0.145-rc29')

if __name__=='__main__':unittest.main()
