"""Manual capture coordinate and ownership regression tests with mocked targets."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

from PIL import Image

import BrowserOneClick as one_click
import ExactColorCalibration as exact
import GetColorPositions as palette
import PaintToolCalibration as paint_tools


class ManualCaptureRegressionTests(unittest.TestCase):
    def palette_app(self):
        app=palette.CalibrationApp.__new__(palette.CalibrationApp)
        app.anchor={'version':1,'client_rect':[0,0,600,400]};app.anchor_handle=42
        app.pending=[];app.rgbs=[];app.map_names=None;app.map_indices=None;app.max_colors=64
        app.is_paint=False;app.job=None;app.closed=False;app.snapshot=None;app.on_close=None
        app.mouse=SimpleNamespace(get_position=lambda:(250,150));app.root=Mock();app.status=Mock();app.refresh=Mock()
        app.capture_visibility=Mock()
        for name in ('add','add_code','auto','rescan','undo_button','save_button'):setattr(app,name,Mock())
        return app

    def test_manual_palette_samples_live_coordinate_and_stores_original_frame(self):
        app=self.palette_app();meta={'handle':42,'client_rect':(200,100,800,500)}
        with patch('TargetCapture.capture_target_metadata_isolated',return_value=meta),patch.object(palette,'sample_screen_color',return_value=(1,2,3)) as sample:
            app.capture(0)
        sample.assert_called_once_with(250,150)
        self.assertEqual(app.pending,[(50,50)]);self.assertEqual(app.rgbs,[(1,2,3)])

    def test_failed_palette_anchor_replacement_leaves_old_anchor_identity(self):
        app=self.palette_app();original=app.anchor
        with patch('TargetCapture.capture_target_metadata_isolated',return_value={'handle':99,'client_rect':(0,0,0,400)}),self.assertRaises(ValueError):
            app._capture_anchor_for_area((0,0,100,100),replace=True)
        self.assertEqual(app.anchor_handle,42);self.assertIs(app.anchor,original)

    def test_palette_capture_refuses_second_pending_countdown_and_overflow(self):
        app=self.palette_app();app.job='existing'
        app.capture(3);app.root.after.assert_not_called()
        app.job=None;app.pending=[(i,0) for i in range(64)]
        app.capture(0)
        self.assertEqual(len(app.pending),64);self.assertEqual(app.rgbs,[])

    def test_palette_capture_refuses_coordinates_outside_captured_client(self):
        app=self.palette_app()
        with patch('TargetCapture.capture_target_metadata_isolated',return_value={'handle':42,'client_rect':(0,0,200,100)}),patch.object(palette,'sample_screen_color') as sample:
            app.capture(0)
        self.assertFalse(app.pending);sample.assert_not_called()

    def test_owned_palette_snapshot_is_closed_on_replacement_and_shutdown(self):
        app=self.palette_app();old=Image.new('RGB',(100,80),'red');new=Image.new('RGB',(100,80),'blue')
        app.snapshot=((0,0,100,80),old)
        app.preset=None;app.detect_mode=SimpleNamespace(get=lambda:'Auto detect');app.preview=Mock()
        meta={'handle':42,'client_rect':(0,0,600,400)}
        with patch('TargetCapture.capture_target_metadata_isolated',return_value=meta),\
             patch('RegionPicker.select_region',side_effect=lambda root,selected,error:selected((0,0,100,80),new)),\
             patch.object(palette,'detect_color_swatches',return_value=([(50,40)],[(0,0,255)],{'found':1,'duplicates':0})),\
             patch.object(palette.ImageTk,'PhotoImage'):
            app.start_scan()
        with self.assertRaises(ValueError):old.getpixel((0,0))
        self.assertEqual(new.getpixel((0,0)),(0,0,255))
        app.close();app.close()
        with self.assertRaises(ValueError):new.getpixel((0,0))
        app.root.destroy.assert_called_once_with()

    def test_failed_paint_recapture_does_not_bind_the_failed_window(self):
        app=paint_tools.PaintToolCalibrationApp.__new__(paint_tools.PaintToolCalibrationApp)
        app.anchor={'version':1,'client_rect':[0,0,600,400]};app.anchor_handle=None
        app.positions={'Pencil':(50,50)};app.mouse=SimpleNamespace(get_position=lambda:(250,150))
        app.status=Mock();app.refresh=Mock();app.capture_visibility=Mock()
        with patch('TargetCapture.capture_target_metadata_isolated',return_value={'handle':99,'client_rect':(0,0,800,400)}):app._capture_now('Fill')
        self.assertIsNone(app.anchor_handle);self.assertEqual(app.positions,{'Pencil':(50,50)})

    def test_paint_save_waits_for_pending_capture(self):
        app=paint_tools.PaintToolCalibrationApp.__new__(paint_tools.PaintToolCalibrationApp);app.job='pending'
        with patch.object(paint_tools,'save_tool_calibration') as save:app.save()
        save.assert_not_called()

    def exact_app(self):
        app=exact.App.__new__(exact.App)
        app.anchor={'version':1,'client_rect':[0,0,600,400]};app.anchor_handle=42;app.anchor_owner=42;app.anchor_pid=7
        app.positions={'OpenCustomColor':(50,30)};app.mouse=SimpleNamespace(get_position=lambda:(250,150))
        app.status=Mock();app.refresh=Mock();app.root=Mock();app.capture_visibility=Mock();app.job=None;app.closed=False
        return app

    def test_exact_control_reprobes_and_rebases_each_capture(self):
        app=self.exact_app();meta={'handle':42,'owner_root_handle':42,'target_pid':7,'client_rect':(200,100,800,500)}
        with patch('TargetCapture.capture_target_metadata_isolated',return_value=meta) as probe:app._now('RedField')
        probe.assert_called_once();self.assertEqual(app.positions['RedField'],(50,50))

    def test_owned_modal_uses_original_targets_coordinate_frame(self):
        app=self.exact_app()
        modal={'handle':43,'owner_root_handle':42,'target_pid':7,'client_rect':(220,120,600,400)}
        main={'handle':42,'owner_root_handle':42,'target_pid':7,'client_rect':(200,100,800,500)}
        with patch('TargetCapture.capture_target_metadata_isolated',return_value=modal),patch('TargetCapture.probe_handle_isolated',return_value=main) as probe:app._now('RedField')
        probe.assert_called_once_with(42);self.assertEqual(app.positions['RedField'],(50,50))

    def test_same_process_unrelated_window_is_rejected(self):
        app=self.exact_app();wrong={'handle':43,'owner_root_handle':43,'target_pid':7,'client_rect':(200,100,800,500)}
        with patch('TargetCapture.capture_target_metadata_isolated',return_value=wrong):app._now('RedField')
        self.assertNotIn('RedField',app.positions);self.assertEqual(app.anchor_handle,42)

    def test_exact_reload_requires_open_control_to_bind_current_target(self):
        app=self.exact_app();app.anchor_handle=None
        with patch('TargetCapture.capture_target_metadata_isolated') as probe:app._now('RedField')
        probe.assert_not_called();self.assertNotIn('RedField',app.positions)

    def test_explicit_opener_restarts_incompatible_saved_layout_without_old_controls(self):
        app=self.exact_app();app.anchor_handle=None;app.positions['RedField']=(90,80)
        meta={'handle':42,'owner_root_handle':42,'target_pid':7,'client_rect':(0,0,800,600)}
        with patch('TargetCapture.capture_target_metadata_isolated',return_value=meta):app._now('OpenCustomColor')
        self.assertEqual(app.anchor['client_rect'],[0,0,800,600])
        self.assertEqual(app.positions,{'OpenCustomColor':(250,150)})
        self.assertEqual(app.anchor_handle,42)

    def test_explicit_opener_preserves_compatible_translated_controls(self):
        app=self.exact_app();app.anchor_handle=None;app.positions['RedField']=(90,80)
        meta={'handle':42,'owner_root_handle':42,'target_pid':7,'client_rect':(200,100,800,500)}
        with patch('TargetCapture.capture_target_metadata_isolated',return_value=meta):app._now('OpenCustomColor')
        self.assertEqual(app.anchor['client_rect'],[0,0,600,400])
        self.assertEqual(app.positions,{'OpenCustomColor':(50,50),'RedField':(90,80)})

    def test_exact_save_waits_for_capture_and_close_cancels_late_callback(self):
        app=self.exact_app();app.job='pending'
        with patch.object(exact,'save') as save:app.save()
        save.assert_not_called()
        app.close();app.close();app.root.after_cancel.assert_called_once_with('pending');app.root.destroy.assert_called_once_with()
        with patch('TargetCapture.capture_target_metadata_isolated') as probe:app._tick('RedField',0)
        probe.assert_not_called()


class BrowserDiscoveryOwnershipTests(unittest.TestCase):
    def metadata(self,handle):
        return {'handle':handle,'rect':(0,0,800,600),'client_rect':(0,0,800,600),'dpi':96,'pid':100+handle,'title':'Game'}

    def result(self,confidence):
        return {'canvas_box':(100,100,700,500),'palette_confidence':confidence,'canvas_confidence':confidence,'positions':[(20+i*20,550) for i in range(18)]}

    def test_discovery_retains_only_selected_screenshot(self):
        captures=[];conversions=[];original=Image.Image.convert
        def capture(**kwargs):
            image=Image.new('RGB',(800,600),'white');captures.append(image);return image
        def convert(image,*args,**kwargs):
            converted=original(image,*args,**kwargs);conversions.append(converted);return converted
        with patch.object(one_click,'_enumerate_windows',return_value=[self.metadata(1),self.metadata(2)]),patch.object(one_click,'_foreground_window_handle',return_value=None),patch('PIL.ImageGrab.grab',side_effect=capture),patch.object(Image.Image,'convert',new=convert),patch.object(one_click,'detect_browser_setup',side_effect=[self.result(.98),self.result(.75)]):
            result=one_click.discover_browser_target('skribbl')
        self.assertEqual(result.handle,1);self.assertEqual(result.screenshot.getpixel((0,0)),(255,255,255))
        for image in captures+[conversions[1]]:
            with self.assertRaises(ValueError):image.getpixel((0,0))
        result.screenshot.close()

    def test_discovery_cancellation_closes_pending_capture(self):
        captured=Image.new('RGB',(800,600),'white');converted=[];original=Image.Image.convert
        def convert(image,*args,**kwargs):result=original(image,*args,**kwargs);converted.append(result);return result
        with patch.object(one_click,'_enumerate_windows',return_value=[self.metadata(1)]),patch.object(one_click,'_foreground_window_handle',return_value=None),patch('PIL.ImageGrab.grab',return_value=captured),patch.object(Image.Image,'convert',new=convert),patch.object(one_click,'detect_browser_setup',side_effect=InterruptedError('cancelled')),self.assertRaises(InterruptedError):
            one_click.discover_browser_target('skribbl')
        for image in [captured,*converted]:
            with self.assertRaises(ValueError):image.getpixel((0,0))

    def test_discovery_rejects_canvas_outside_captured_target(self):
        wrong=self.result(.99);wrong['canvas_box']=(100,100,900,500)
        with patch.object(one_click,'_enumerate_windows',return_value=[self.metadata(1)]),patch.object(one_click,'_foreground_window_handle',return_value=None),patch('PIL.ImageGrab.grab',return_value=Image.new('RGB',(800,600))),patch.object(one_click,'detect_browser_setup',return_value=wrong),self.assertRaises(ValueError):
            one_click.discover_browser_target('skribbl')


if __name__=='__main__':unittest.main()
