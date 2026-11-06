"""Existing browser worker cancellation reaches its isolated native probe."""
from pathlib import Path
import threading
import unittest
from unittest.mock import patch


class BrowserProbeCancellationTests(unittest.TestCase):
    def test_selected_browser_probes_stop_before_capturing_or_calibrating(self):
        import BrowserOneClick as oneclick
        import SmartDropInCanvas as drop
        stop=threading.Event()
        def probe(handle,*,cancelled):
            self.assertEqual(handle,42)
            self.assertFalse(cancelled())
            stop.set()
            self.assertTrue(cancelled())
            raise InterruptedError('native probe cancelled')
        operations=(lambda:oneclick.one_click_setup('Gartic Phone','gartic-phone',Path('unused.json'),
                                                    current_handle=42,cancelled=stop.is_set),
                    lambda:drop.discover_canvas_target('gartic-phone',preferred_handle=42,
                                                       cancelled=stop.is_set))
        for operation in operations:
            stop.clear()
            with patch('TargetCapture.probe_handle_isolated',side_effect=probe) as child,\
                 patch('PIL.ImageGrab.grab') as capture,patch.object(drop,'_capture_candidate') as candidate:
                with self.assertRaisesRegex(InterruptedError,'native probe cancelled'):operation()
                child.assert_called_once();capture.assert_not_called();candidate.assert_not_called()


if __name__=='__main__':unittest.main()
