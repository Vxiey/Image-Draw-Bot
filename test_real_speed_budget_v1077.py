import unittest
import tempfile
from collections import Counter
from pathlib import Path
from RealSpeedBudget import record_runtime_sample,load_profile,recommend_budget,apply_budget_policy,reduce_palette_groups


class RealSpeedBudgetIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp_path = Path(directory.name)

    def test_records_actual_completed_throughput(self):
        p=self.tmp_path/'speed.json'
        result=record_runtime_sample('gartic-phone',120,20.0,colors=6,path=p)
        assert result['recorded']
        assert 5.9 < result['paths_per_second'] < 6.1
        saved=load_profile('gartic-phone',p)
        assert saved['samples']==1 and saved['total_paths']==120


    def test_learned_30_60_90_budgets_scale(self):
        p=self.tmp_path/'speed.json'
        record_runtime_sample('skribbl-fast',180,30.0,path=p)
        a=recommend_budget('skribbl-fast',30,path=p)
        b=recommend_budget('skribbl-fast',60,path=p)
        c=recommend_budget('skribbl-fast',90,path=p)
        assert a.learned and a.path_cap < b.path_cap < c.path_cap
        assert a.max_colors <= b.max_colors <= c.max_colors <= 6
        assert a.structure_priority


    def test_budget_policy_reduces_detail_and_colors(self):
        p=self.tmp_path/'speed.json'
        record_runtime_sample('gartic-phone',60,20.0,path=p)
        options={
            'profile_key':'gartic-phone','profile_engine':'Auto','time_budget_active':True,
            'time_budget_seconds':30,'max_seconds':30,'target_stroke_count':'Auto',
            'target_stroke_count_resolved':500,'adaptive_detail':'Auto','color_grouping':'Smart',
            'planning_resolution':'High',
        }
        out=apply_budget_policy(options,path=p)
        assert out['target_stroke_count_resolved'] < 500
        assert out['gartic_phone_max_colors'] <= 4
        assert out['adaptive_detail']=='Strong simplify'
        assert out['real_speed_structure_priority']


    def test_palette_reduction_preserves_hue_families_before_extra_dark_tones(self):
        groups=[[(0,0,20,0)],[(0,1,2,1)],[(0,2,4,2)],[(0,3,3,3)],[(0,4,3,4)]]
        palette=[(0,0,0),(250,0,0),(0,250,0),(0,0,250),(220,220,0)]
        reduced,meta=reduce_palette_groups(groups,palette,3)
        assert meta['active'] and meta['after_colors']<=3
        # The current reducer reserves dominant hue families before adding a
        # neutral extreme.  Keep the original five-color fixture as a control:
        # its three slots retain green, blue and yellow, with every stroke moved
        # intact to a retained color instead of being discarded.
        expected_strokes=Counter(stroke for group in groups for stroke in group)
        assert {i for i,group in enumerate(reduced) if group}=={2,3,4}
        assert Counter(stroke for group in reduced for stroke in group)==expected_strokes
        # With two red shades there are only three chromatic families.  A
        # fourth slot can now preserve the dark structural color as well.
        palette[-1]=(220,20,20)
        for cap,expected_colors in ((3,{2,3,4}),(4,{0,2,3,4})):
            with self.subTest(cap=cap):
                reduced,meta=reduce_palette_groups(groups,palette,cap)
                assert meta['active'] and meta['after_colors']<=cap
                assert {i for i,group in enumerate(reduced) if group}==expected_colors
                assert Counter(stroke for group in reduced for stroke in group)==expected_strokes
                if cap==4:
                    assert reduced[0]


    def test_structural_priority_keeps_large_outline(self):
        from TimeBudget import apply_target_path_cap
        tiny=tuple((i,0) for i in range(2))
        outline=((0,0),(100,0),(100,100),(0,100),(0,0))
        groups=[[tiny,tiny,tiny,outline]]
        capped,meta=apply_target_path_cap(groups,1,prioritize_structure=True)
        assert capped[0]==[outline]
        assert meta['structure_priority']



if __name__ == "__main__":
    unittest.main()
