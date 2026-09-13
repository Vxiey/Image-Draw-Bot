import unittest

from StrokeDeliveryVerification import (
    StrokeDeliveryVerificationError, inspect_delivery, resolve_policy, retry_parameters
)
from Version import APP_VERSION, FILE_VERSION


class InspectMouse:
    def __init__(self, matched=True): self.matched=matched; self.calls=0
    def inspect_ink_segment(self,start,end,expected,brush_px,tolerance):
        self.calls += 1
        return {'matched':self.matched,'expected':tuple(expected),'actual':tuple(expected) if self.matched else (255,255,255),'confidence':99 if self.matched else 10}


class StrokeDeliveryVerificationV1078Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1');self.assertEqual(FILE_VERSION,'1.0.146')

    def test_browser_profiles_enabled_with_hard_one_retry_cap(self):
        for key in ('gartic-phone','skribbl','skribbl-fast','sketchheads','sketchful'):
            p=resolve_policy({'profile_key':key})
            self.assertTrue(p.enabled,key);self.assertEqual(p.retry_cap,1)

    def test_paint_and_dry_run_do_not_enable_browser_delivery_verification(self):
        self.assertFalse(resolve_policy({'profile_key':'microsoft-paint'}).enabled)
        self.assertFalse(resolve_policy({'profile_key':'skribbl-fast'},dry_run=True).enabled)

    def test_long_browser_stroke_is_checked(self):
        mouse=InspectMouse(True);p=resolve_policy({'profile_key':'skribbl-fast'})
        r=inspect_delivery(mouse,(10,10),(80,10),(0,0,0),4,p)
        self.assertTrue(r['checked']);self.assertTrue(r['matched']);self.assertEqual(mouse.calls,1)

    def test_tiny_stroke_is_not_false_failed(self):
        mouse=InspectMouse(False);p=resolve_policy({'profile_key':'gartic-phone'})
        r=inspect_delivery(mouse,(10,10),(11,10),(0,0,0),3,p)
        self.assertFalse(r['checked']);self.assertTrue(r['matched']);self.assertEqual(mouse.calls,0)

    def test_retry_is_denser_and_slower_but_bounded(self):
        p=resolve_policy({'profile_key':'skribbl-fast'})
        r=retry_parameters(p,12,.00045)
        self.assertLess(r['step_px'],12);self.assertGreater(r['path_delay'],.00045);self.assertEqual(p.retry_cap,1)

    def test_error_is_interrupt_compatible(self):
        self.assertTrue(issubclass(StrokeDeliveryVerificationError,InterruptedError))

if __name__=='__main__':unittest.main()
