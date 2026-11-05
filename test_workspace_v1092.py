import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from SmoothScroll import ScrollAccumulator,install_scrolling
from ScreenTaskWindow import ScreenTaskWindow
from WorkspaceLayout import window_size,compact_layout
from UpdateCenter import check_for_updates,UpdateCheckError

class WorkspaceTests(unittest.TestCase):
    def test_initial_window_fits_common_desktops(self):
        for sw,sh in ((1366,768),(1920,1080),(1024,768),(800,600)):
            w,h=window_size(sw,sh);self.assertLess(w,sw);self.assertLess(h,sh)
        self.assertTrue(compact_layout(900))
    def test_scroll_burst_is_bounded(self):
        acc=ScrollAccumulator()
        for _ in range(1000):acc.add(1)
        self.assertEqual(acc.take(),12);self.assertEqual(acc.take(),0)
    def test_high_resolution_wheel_keeps_fractional_motion(self):
        acc=ScrollAccumulator();acc.add(.25);self.assertEqual(acc.take(),0)
        acc.add(.75);self.assertEqual(acc.take(),1)
    def test_scroll_reversal(self):
        acc=ScrollAccumulator();acc.add(8);acc.add(-10);self.assertEqual(acc.take(),-2)
    def test_only_pointed_panel_receives_one_coalesced_scroll(self):
        canvas=Mock();canvas.winfo_exists.return_value=True
        widget=SimpleNamespace(_parent_canvas=canvas,winfo_class=lambda:'Frame')
        callbacks=[];bindings={}
        root=SimpleNamespace(winfo_containing=lambda x,y:widget,after=lambda ms,fn:callbacks.append(fn) or 1,bind_all=lambda key,fn:bindings.update({key:fn}))
        install_scrolling(root)
        event=SimpleNamespace(state=0,x_root=1,y_root=2,delta=-120,num=None)
        for _ in range(100):self.assertEqual(bindings['<MouseWheel>'](event),'break')
        self.assertEqual(len(callbacks),1);callbacks[0]()
        canvas.yview_scroll.assert_called_once_with(12,'units')
    def test_native_text_is_not_scrolled_twice(self):
        bindings={};root=SimpleNamespace(winfo_containing=lambda x,y:SimpleNamespace(winfo_class=lambda:'Text'),bind_all=lambda key,fn:bindings.update({key:fn}))
        install_scrolling(root)
        self.assertIsNone(bindings['<MouseWheel>'](SimpleNamespace(state=0,x_root=1,y_root=1)))
    def test_window_restores_maximized_state_once(self):
        root=Mock();root.state.return_value='zoomed';root.winfo_exists.return_value=True
        window=ScreenTaskWindow(root);window.hide();window.hide();window.restore();window.restore()
        root.iconify.assert_called_once();root.deiconify.assert_called_once();root.state.assert_any_call('zoomed')
    def test_existing_minimized_state_is_preserved(self):
        root=Mock();root.state.return_value='iconic';root.winfo_exists.return_value=True
        window=ScreenTaskWindow(root);window.hide();window.restore();root.deiconify.assert_not_called()
    def test_failure_hiding_rolls_back(self):
        root=Mock();root.state.return_value='normal';root.winfo_exists.return_value=True;root.update_idletasks.side_effect=RuntimeError('failed')
        with self.assertRaises(RuntimeError):ScreenTaskWindow(root).hide()
        root.deiconify.assert_called_once()
    def response(self,tag):
        payload=[dict(tag_name=tag,draft=False,prerelease=True,html_url='https://github.com/Vxiey/Image-Draw-Bot/releases/tag/'+tag)]
        return SimpleNamespace(raise_for_status=lambda:None,iter_content=lambda chunk_size:iter([json.dumps(payload).encode('utf-8')]))
    def test_current_version_message(self):
        with patch('UpdateCenter.APP_VERSION','1.0.92-beta'), patch('UpdateCenter.BUILD_CHANNEL','beta'):
            r=check_for_updates(request_get=lambda *a,**k:self.response('v1.0.92-beta'))
        self.assertEqual(r['message'],'You are on the latest version.')
    def test_newer_release_download_label(self):
        with patch('UpdateCenter.APP_VERSION','1.0.92-beta'), patch('UpdateCenter.BUILD_CHANNEL','beta'):
            r=check_for_updates(request_get=lambda *a,**k:self.response('v1.0.93-beta'))
        self.assertTrue(r['update_available']);self.assertEqual(r['message'],'Download version 1.0.93-beta')
    def test_network_failure_is_not_up_to_date(self):
        with self.assertRaises(UpdateCheckError):check_for_updates(request_get=Mock(side_effect=OSError('offline')))
    def test_no_published_releases_is_not_up_to_date(self):
        r=check_for_updates(request_get=lambda *a,**k:SimpleNamespace(raise_for_status=lambda:None,iter_content=lambda chunk_size:iter([b'[]'])))
        self.assertIn('No published',r['message'])
