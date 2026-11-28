"""Observe the native boundary without synthesizing screenshots or sending input."""
from contextlib import ExitStack
import os
import unittest
from unittest.mock import patch

from PIL import Image
import GuidedCanvasDiscovery as guided


class GuidedCanvasTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.image = self.stack.enter_context(Image.open('tests/fixtures/paint-light-ribbon.png'))
        self.client = (-400, 100, self.image.width - 400, self.image.height + 100)
        self.rect = (-405, 68, self.client[2]+5, self.client[3]+5)
        self.row = dict(handle=11, rect=self.rect, client_rect=self.client, pid=121, dpi=144,
                        title='skribbl.io — Mozilla Firefox')
        self.enum = self.stub('_enumerate_windows', return_value=[self.row])
        self.exe = self.stub('_process_name', return_value='firefox.exe')
        self.fg = self.stub('_foreground_window_handle', return_value=0)
        self.monitor = self.stub('WindowMonitor').return_value
        self.monitor._process_identity.return_value = (121, 7)
        self.monitor.rectangle.return_value = self.rect
        self.monitor.dpi.return_value = 144
        self.monitor.client_rectangle.return_value = self.client
        self.monitor.capture.return_value = (11, self.rect)
        self.monitor.active.return_value = True
        self.grab = self.stack.enter_context(patch('PIL.ImageGrab.grab', side_effect=lambda **kw: self.image.copy()))
        self.box = (self.client[0]+10, self.client[1]+10, self.client[2]-10, self.client[3]-10)
        self.detect = self.stub('detect_browser_canvas', return_value=dict(canvas_box=self.box, canvas_confidence=.91))

    def stub(self, k, **kwargs):
        return self.stack.enter_context(patch.object(guided, k, **kwargs))

    def test_candidate_and_explicit_confirmation_use_two_current_owned_frames(self):
        candidate = guided.discover_guided_canvas('skribbl')
        confirmed = guided.discover_guided_canvas('skribbl', previous=candidate)
        self.assertEqual(confirmed, candidate)
        self.assertEqual(confirmed['target_meta']['target_thread'], 7)
        self.assertEqual(self.detect.call_count, 2)
        self.assertEqual(self.grab.call_count, 2)
        self.assertEqual(self.detect.call_args.kwargs['screen_origin'], self.client[:2])
        self.monitor.activate.assert_not_called()

    def test_passive_draw_recheck_checks_title_and_thread_without_capturing_or_requiring_focus(self):
        accepted = guided.discover_guided_canvas('skribbl')
        self.monitor.active.return_value = False
        self.stub('_window_title', side_effect=lambda monitor, handle: self.row['title'])
        self.enum.reset_mock()
        self.assertEqual(guided.recheck_guided_window(accepted), accepted['target_meta'])
        self.row['title'] = 'Another room — skribbl.io — Mozilla Firefox'
        with self.assertRaisesRegex(ValueError, 'document or tab changed'):
            guided.recheck_guided_window(accepted)
        self.row['title'] = 'skribbl.io — Mozilla Firefox'
        self.monitor._process_identity.return_value = (121, 99)
        with self.assertRaises(ValueError):
            guided.recheck_guided_window(accepted)
        self.assertEqual(self.grab.call_count, 1)
        self.enum.assert_not_called()

    def test_ambiguous_wrong_profile_and_wrong_process_do_not_capture(self):
        self.enum.return_value.append(dict(self.row, handle=12))
        with self.assertRaisesRegex(ValueError, 'Several'):
            guided.discover_guided_canvas('skribbl')
        self.exe.return_value = 'editor.exe'
        with self.assertRaises(ValueError):
            guided.discover_guided_canvas('skribbl')
        with self.assertRaises(ValueError):
            guided.discover_guided_canvas('generic')
        self.grab.assert_not_called()

    def test_unverified_edges_explain_manual_fallback_before_ownership_check(self):
        self.detect.return_value = dict(canvas_box=None, canvas_confidence=0)
        with self.assertRaisesRegex(ValueError, 'select it manually'):
            guided.discover_guided_canvas('skribbl')
        self.monitor.capture.assert_not_called()

    def test_rejects_recycled_window_changed_dpi_canvas_and_occlusion(self):
        candidate = guided.discover_guided_canvas('skribbl')
        for key, changed in (('target_thread', 8), ('dpi', 96), ('target_pid', 120)):
            old = dict(candidate, target_meta=dict(candidate['target_meta'], **{key:changed}))
            with self.subTest(key=key), self.assertRaises(ValueError):
                guided.discover_guided_canvas('skribbl', previous=old)
        self.monitor.active.return_value = False
        with self.assertRaisesRegex(ValueError, 'front'):
            guided.discover_guided_canvas('skribbl', previous=candidate)
        self.monitor.active.return_value = True
        self.detect.return_value = dict(canvas_box=(self.box[0]+1, *self.box[1:]), canvas_confidence=.95)
        with self.assertRaisesRegex(ValueError, 'changed'):
            guided.discover_guided_canvas('skribbl', previous=candidate)
        self.monitor.capture.return_value = (25, self.rect)
        with self.assertRaisesRegex(ValueError, 'covers'):
            guided.discover_guided_canvas('skribbl')

    def test_cancelled_or_changed_game_does_not_publish(self):
        with self.assertRaises(InterruptedError):
            guided.discover_guided_canvas('skribbl', cancelled=lambda: True)
        self.enum.assert_not_called()
        self.enum.side_effect = [[self.row], [dict(self.row, title='Other tab')]]
        with self.assertRaises(ValueError):
            guided.discover_guided_canvas('skribbl')

    def test_same_game_tab_change_while_capturing_is_rejected(self):
        self.enum.side_effect = [[self.row], [dict(self.row, title='Room two — skribbl.io — Mozilla Firefox')]]
        with self.assertRaisesRegex(ValueError, 'changed'):
            guided.discover_guided_canvas('skribbl')

    def test_gartic_phone_uses_the_supported_chrome_workflow(self):
        self.row['title'] = 'Gartic Phone — Mozilla Firefox'
        with self.assertRaisesRegex(ValueError, 'Google Chrome with Artist Tools'):
            guided.discover_guided_canvas('gartic-phone')
        self.grab.assert_not_called()
        self.exe.return_value = 'chrome.exe'
        self.row['title'] = 'Gartic Phone - Google Chrome'
        self.assertEqual(guided.discover_guided_canvas('gartic-phone')['canvas_box'], self.box)

    def test_same_paint_window_switching_documents_before_reuse_is_rejected(self):
        self.exe.return_value = 'mspaint.exe'
        self.row['title'] = 'Original.png – Paint'
        self.stack.enter_context(patch('PaintFullCalibration.detect_canvas_area',
            return_value=dict(canvas_box=self.box, canvas_confidence=.90)))
        offer = guided.discover_guided_canvas('microsoft-paint')
        accepted = guided.discover_guided_canvas('microsoft-paint', previous=offer)
        self.assertNotIn('Original.png', str(accepted))
        self.assertNotIn('_window_title_fingerprint', accepted['target_meta'])
        self.row['title'] = 'Replacement.png – Paint'
        with self.assertRaisesRegex(ValueError, 'document or tab changed'):
            guided.discover_guided_canvas('microsoft-paint', previous=accepted)
        self.assertEqual(self.grab.call_count, 2)


class NativeProcessTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt', 'native Win32 API')
    def test_real_window_process_lookup(self):
        self.assertTrue(guided._process_name(os.getpid()).endswith('.exe'))

    @unittest.skipUnless(os.name=='nt', 'native Win32 API')
    def test_reads_unicode_title_from_known_hidden_win32_window(self):
        import ctypes
        from ctypes import wintypes
        monitor = guided.WindowMonitor()
        user = monitor.api
        create = user.CreateWindowExW
        create.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                           wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        create.restype = wintypes.HWND
        user.DestroyWindow.argtypes = [wintypes.HWND]
        user.DestroyWindow.restype = wintypes.BOOL
        title = 'Räksmörgås — Paint'
        handle = create(0, 'STATIC', title, 0x80000000, 0, 0, 1, 1, None, None, None, None)
        self.assertTrue(handle)
        self.addCleanup(user.DestroyWindow, handle)
        self.assertEqual(guided._window_title(monitor, handle), title)
