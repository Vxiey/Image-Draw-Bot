import unittest
from ProgressiveRenderer import build_progressive_sequence
from Version import APP_VERSION

class Rc9ProgressiveDrawingTests(unittest.TestCase):
    def test_spatial_seeding_spreads_foundation_early(self):
        groups=[[
            ((0,0),(30,0)),((100,0),(130,0)),((0,100),(30,100)),((100,100),(130,100)),
            ((1,2),(70,2)),
        ]]
        hints=[['foundation']*5]
        seq,meta=build_progressive_sequence(groups,phase_hints=hints,enabled=True)
        self.assertGreaterEqual(meta['progressive_spatial_seed_paths'],4)
        prefix=seq[:meta['progressive_spatial_seed_paths']]
        centers=[((p['path'][0][0]+p['path'][-1][0])/2,(p['path'][0][1]+p['path'][-1][1])/2) for p in prefix]
        self.assertGreaterEqual(len({(int(x>=65),int(y>=50)) for x,y in centers}),3)

    def test_phase_barriers_and_geometry_are_preserved(self):
        groups=[[((0,0),(50,0)),((10,10),(10,40)),((3,3),)]]
        hints=[['foundation','contour','details']]
        seq,meta=build_progressive_sequence(groups,phase_hints=hints,enabled=True)
        self.assertEqual([e['phase'] for e in seq],['foundation','contour','details'])
        self.assertEqual(sorted(tuple(e['path']) for e in seq),sorted(groups[0]))

    def test_runtime_priority_metadata_is_bounded(self):
        seq,_=build_progressive_sequence([[((0,0),(100,0)),((1,1),)]],phase_hints=[['foundation','details']],enabled=True)
        for e in seq:
            self.assertGreaterEqual(e['importance'],0.0);self.assertLessEqual(e['importance'],1.0)
            self.assertIn('structural_score',e);self.assertIn('optional',e)

    def test_version(self):self.assertEqual(APP_VERSION,'1.0.145-rc29')

if __name__=='__main__':unittest.main()
