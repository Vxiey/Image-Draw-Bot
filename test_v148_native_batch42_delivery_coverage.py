"""Actual browser verifier samples several sites from an existing source raster."""
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from ScreenGuard import GuardedMouse,WindowMonitor
from StrokeDeliveryVerification import inspect_delivery,resolve_policy
from test_v148_native_batch25_screen_sampling import _NativeBoundary,_Library


class BrowserCoverageTests(unittest.TestCase):
    def boundary(self):
        source=Image.open(Path(__file__).with_name('golden-regression')/'small-detail-preservation.png')
        self.addCleanup(source.close)
        image=source.convert('RGB');self.addCleanup(image.close)
        native=_NativeBoundary();native.rgb=lambda x,y:image.getpixel((x,y))
        self.enterContext(patch('ScreenPixelSampling.load_system_library',return_value=_Library(native)))
        self.enterContext(patch('ScreenGuard.time.sleep'))
        monitor=object.__new__(WindowMonitor);monitor.verify=lambda *_:None
        guard=GuardedMouse(SimpleNamespace(get_position=lambda:(5,5)),monitor,(10,native.rect))
        return guard,monitor,native,image

    def test_one_matching_site_does_not_confirm_the_rest_of_a_browser_stroke(self):
        guard,monitor,native,image=self.boundary()
        start,end=(5,50),(354,50);expected=(248,211,45)
        # This committed raster has exactly one matching neighborhood. Paint's
        # nearest-color API intentionally remains available for color selection.
        self.assertTrue(guard.inspect_ink_segment(start,end,expected,1,82)['matched'])
        result=inspect_delivery(guard,start,end,expected,1,resolve_policy({'profile_key':'skribbl'}))
        self.assertTrue(result['checked']);self.assertFalse(result['matched'])
        self.assertEqual((result['matched_sites'],result['tested_sites'],result['required_sites']),(1,5,3))
        self.assertEqual(result['actual'],expected)
        self.assertEqual(result['sample_count'],500)
        self.assertIn('1/5',result['reason'])
        names=[name for name,_ in native.calls]
        self.assertEqual(names.count('BitBlt'),5)
        self.assertEqual(names.count('GetDC'),names.count('ReleaseDC'))
        self.assertEqual(native.buffers,{})

    def test_complete_existing_background_and_old_inspector_backend_remain_supported(self):
        guard,monitor,native,image=self.boundary()
        expected=image.getpixel((5,5))
        result=inspect_delivery(guard,(5,5),(354,5),expected,1,resolve_policy({'profile_key':'gartic-phone'}))
        self.assertTrue(result['matched']);self.assertEqual(result['matched_sites'],5)
        self.assertEqual(result['sample_count'],125)
        legacy=SimpleNamespace(inspect_ink_segment=guard.inspect_ink_segment)
        legacy_result=inspect_delivery(legacy,(5,5),(354,5),expected,1,resolve_policy({'profile_key':'gartic-phone'}))
        self.assertTrue(legacy_result['matched'])
        self.assertNotIn('matched_sites',legacy_result)

    def test_site_evidence_does_not_accumulate_across_four_sampling_attempts(self):
        guard,monitor,native,image=self.boundary()
        expected=image.getpixel((5,5));other=image.getpixel((75,50))
        attempt=[0]
        def changing(points,radius):
            selected=attempt[0];attempt[0]+=1
            count=(2*radius+1)**2
            return [color for i in range(len(points))
                    for color in [expected if i==selected else other]*count]
        monitor.colors_near_many=changing
        result=inspect_delivery(guard,(5,5),(354,5),expected,1,resolve_policy({'profile_key':'skribbl'}))
        self.assertFalse(result['matched']);self.assertEqual(result['matched_sites'],1)
        self.assertEqual(attempt[0],4)

    def test_one_physical_pixel_cannot_vote_for_overlapping_short_stroke_sites(self):
        for start,end,radius in (((0,0),(10,0),2),((0,0),(7,7),2),((-10,4),(0,4),6)):
            with self.subTest(start=start,end=end,radius=radius):
                points=tuple(dict.fromkeys(GuardedMouse._ink_probe_points(start,end)))
                indices=GuardedMouse._ink_site_sample_indices(points,radius)
                assigned=[];side=2*radius+1
                for (x,y),offsets in zip(points,indices):
                    assigned.append({(x+offset%side-radius,y+offset//side-radius) for offset in offsets})
                self.assertEqual(sum(map(len,assigned)),len(set.union(*assigned)),
                                 'A physical sample was attributed to several sites.')
                for center,site in zip(points,assigned):self.assertIn(center,site)
                if start==(0,0) and end==(10,0):
                    self.assertEqual(sum((4,0) in site for site in assigned),1)

    def test_incomplete_grouped_capture_never_shifts_site_membership(self):
        guard,monitor,native,image=self.boundary();expected=image.getpixel((5,5))
        monitor.colors_near_many=lambda *_:[expected]*124
        result=inspect_delivery(guard,(5,5),(354,5),expected,1,resolve_policy({'profile_key':'skribbl'}))
        self.assertFalse(result['matched']);self.assertEqual(result['matched_sites'],0)
        self.assertIn('Incomplete',result['reason'])

    def test_stop_or_focus_loss_during_capture_cannot_publish_matching_evidence(self):
        for mode in ('stop','focus'):
            with self.subTest(mode=mode):
                guard,monitor,native,image=self.boundary();stop=threading.Event();guard._stop_event=stop
                valid=[True];original=native.GdiFlush
                def verify(*_):
                    if not valid[0]:raise InterruptedError('foreground changed')
                monitor.verify=verify
                def flush():
                    result=original()
                    if mode=='stop':stop.set()
                    else:valid[0]=False
                    return result
                native.GdiFlush=flush
                with self.assertRaises(InterruptedError):
                    inspect_delivery(guard,(5,5),(354,5),image.getpixel((5,5)),1,resolve_policy({'profile_key':'skribbl'}))
                self.assertEqual(native.buffers,{})


if __name__=='__main__':unittest.main()
