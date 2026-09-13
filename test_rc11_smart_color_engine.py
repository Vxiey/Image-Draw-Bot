import unittest
from SmartColorEngine import smart_color_weights, should_keep_color_candidate
from AdaptivePaletteFidelity import select_adaptive_palette
from Version import APP_VERSION

class Rc11SmartColorEngineTests(unittest.TestCase):
    def test_local_unique_accent_receives_relative_priority(self):
        palette=[(120,120,120),(150,150,150),(0,220,230)]
        groups=[
            [(0,0,120,0),(0,25,120,25),(0,50,120,50),(0,75,120,75)],
            [(0,90,90,90),(0,100,90,100)],
            [(102,102,112,102),(102,104,112,104)],
        ]
        base=[480.0,180.0,20.0]
        adjusted,meta=smart_color_weights(groups,palette,base,fidelity='Faithful')
        self.assertTrue(meta['smart_color_enabled'])
        self.assertIn(2,meta['smart_color_unique_indexes'])
        self.assertGreater(adjusted[2]/base[2],adjusted[0]/base[0])

    def test_switch_cost_can_stop_low_value_palette_growth(self):
        self.assertTrue(should_keep_color_candidate(.0002,.55,'Faithful',.30))
        self.assertFalse(should_keep_color_candidate(.0002,.30,'Faithful',.30))
        self.assertTrue(should_keep_color_candidate(.02,.30,'Faithful',.30))

    def test_selector_exports_smart_color_diagnostics(self):
        palette=[(20,20,20),(100,100,100),(240,240,240),(220,30,30),(30,80,220),(20,190,90)]
        groups=[[(0,i*10,40+i*3,i*10)] for i in range(len(palette))]
        _keep,_mapping,meta=select_adaptive_palette(groups,palette,4,fidelity='Faithful',color_switch_seconds=.12)
        self.assertEqual(meta['smart_color_engine'],'Smart Color Engine v1')
        self.assertIn('smart_color_anchor_indexes',meta)
        self.assertAlmostEqual(meta['smart_color_switch_cost_seconds'],.12,places=5)

    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')

if __name__=='__main__':unittest.main()
