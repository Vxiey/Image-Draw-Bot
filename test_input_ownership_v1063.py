import unittest
from unittest.mock import patch
from ScreenGuard import GuardedMouse
from Version import APP_VERSION, FILE_VERSION

class Mouse:
    def __init__(self, positions): self.positions=list(positions);self.position=self.positions[-1] if self.positions else (0,0);self.moves=[]
    def get_position(self):
        if self.positions: self.position=self.positions.pop(0)
        return self.position
    def move(self,x,y): self.position=(x,y);self.moves.append((x,y))

class Monitor:
    def verify(self,target,point): return None

class InputOwnershipV1063Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29');self.assertEqual(FILE_VERSION,'1.0.145')

    def test_one_transient_position_read_does_not_false_stop(self):
        mouse=Mouse([(105,100),(100,100),(110,100)])
        guard=GuardedMouse(mouse,Monitor(),1);guard.last=(100,100);guard.tracking_tolerance=3
        with patch('ScreenGuard.time.sleep'):
            guard.move(110,100)
        self.assertEqual(mouse.moves,[(110,100)])

    def test_persistent_manual_deviation_still_stops(self):
        mouse=Mouse([(120,100),(120,100)])
        guard=GuardedMouse(mouse,Monitor(),1);guard.last=(100,100);guard.tracking_tolerance=3
        with patch('ScreenGuard.time.sleep'):
            with self.assertRaises(InterruptedError): guard.check((110,100))

if __name__=='__main__': unittest.main()
