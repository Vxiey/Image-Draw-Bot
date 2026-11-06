import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
import CrashDiagnostics as cd
import DiagnosticsPackage as dp
from CrashDumpConfig import restore_values
from WindowsMouse import WindowsMouse
from PixelAccuracyEngine import simulate_strokes, progressive_accuracy_checkpoints, progressive_time_budget
from PixelAccuracyGpu import compile_swept_rectangles, _plan
from PixelAccuratePlanner import build_pixel_map
from PixelStrokeEngine import _vertical_run_chunk

PALETTE=((255,255,255),(0,0,0),(255,0,0))
def entry(color,point,phase='fill'):
    return {'color_index':color,'path':(point,),'phase':phase}

class ReviewRegressionTests(unittest.TestCase):
    def test_input_is_disarmed_even_if_release_raises(self):
        mouse=WindowsMouse.__new__(WindowsMouse);mouse.held=True;mouse._input_armed=True
        def fail(flags):raise OSError('release failed')
        mouse._send=fail
        with self.assertRaises(OSError):mouse.disarm_input()
        self.assertFalse(mouse.input_armed)
        # Failed LEFTUP still belongs to this backend. Keep cleanup ownership
        # while denying any further input, so a later release can retry it.
        self.assertTrue(mouse.held)

    def test_marker_pid_prefix_is_not_ownership(self):
        with tempfile.TemporaryDirectory() as folder:
            marker=Path(folder)/'running.marker';marker.write_text('pid=1234 started=other')
            with patch.object(cd,'RUN_MARKER',marker),patch.object(cd,'RUN_MARKER_OWNED',True),patch('CrashDiagnostics.os.getpid',return_value=123):
                cd.clean_exit()
            self.assertTrue(marker.exists())

    def test_outside_strokes_do_not_paint_border_cpu_or_cuda_compiler(self):
        pm=build_pixel_map(Image.new('RGBA',(4,4),'white'),PALETTE,gpu_mode='CPU',skip_white=True)
        seq=[entry(1,(-5,2)),entry(1,(9,2)),entry(1,(2,-5)),entry(1,(2,9))]
        result=simulate_strokes(pm,seq,PALETTE)
        self.assertFalse(result.coverage_map.any())
        self.assertEqual(len(compile_swept_rectangles(seq,1,4,4)),0)

    def test_partially_visible_brush_is_clipped(self):
        rects=compile_swept_rectangles([entry(1,(-1,2))],3,4,4)
        self.assertEqual(tuple(rects[0]),(0,1,0,3,1))

    def test_checkpoint_order_preserves_repeated_phase(self):
        pm=build_pixel_map(Image.new('RGBA',(1,1),'black'),PALETTE,gpu_mode='CPU',skip_white=False)
        seq=[entry(1,(0,0),'fill'),entry(2,(0,0),'detail'),entry(1,(0,0),'fill')]
        checkpoints=progressive_accuracy_checkpoints(pm,seq,PALETTE)
        self.assertEqual([c['phase'] for c in checkpoints],['fill','detail','fill'])
        self.assertEqual(checkpoints[-1]['pixel_accuracy_percent'],simulate_strokes(pm,seq,PALETTE).metrics['pixel_accuracy_percent'])

    def test_budget_never_exceeds_number_of_paths(self):
        budget=progressive_time_budget([entry(1,(0,0))],active=True,seconds=30)
        self.assertEqual(budget['path_budget'],1)
        self.assertEqual(budget['correction_reserve'],0)

    def test_cuda_batch_work_is_bounded_independently_of_vram(self):
        info=SimpleNamespace(vram_budget_mb=16000,free_vram_mb=16000)
        with patch('GpuAcceleration.plan_vram_allocation',return_value={'tile_rows':1080}):
            plan=_plan(info,1920,1080,900000)
        self.assertLessEqual(1920*plan.tile_rows*plan.rectangle_batch_size,8_000_000)

    def test_vertical_scan_can_be_cancelled(self):
        with self.assertRaises(InterruptedError):
            _vertical_run_chunk(np.zeros((5,5),dtype=np.int32),0,5,lambda:True)

    def test_restore_preserves_settings_changed_after_dump_setup(self):
        original={'DumpType':[2,4]};written={'DumpType':[1,4],'DumpCount':[5,4]}
        result=restore_values({'DumpType':[1,4],'DumpCount':[9,4]},written,original)
        self.assertEqual(result,{'DumpType':[2,4],'DumpCount':[9,4]})

    def test_two_diagnostics_created_in_same_second_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(dp,'DIAGNOSTICS_DIR',Path(folder)),patch.object(dp,'data_dir',return_value=Path(folder)),patch.object(dp,'_technical_info',return_value={}):
                a=dp.create_diagnostics_package();before=a.read_bytes();b=dp.create_diagnostics_package()
                self.assertNotEqual(a,b)
                self.assertEqual(a.read_bytes(),before)

    def test_log_tail_keeps_recent_failure_and_bounds_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'large.log';path.write_text('x'*100000+'\nrecent failure')
            text=dp._read_text(path,100)
            self.assertTrue(text.endswith('recent failure'))
            self.assertLess(len(text),150)

    def test_diagnostics_does_not_probe_cuda_driver(self):
        with patch('GpuAcceleration.acceleration_info',side_effect=AssertionError('must not probe')):
            info=dp._technical_info()
            self.assertTrue(info['gpu']['probe_skipped'])

    def test_thread_start_failure_restores_idle_state(self):
        import threading,queue
        from DrawBot import DrawBotApp
        app=SimpleNamespace(activity=None,closing=False,stop=threading.Event(),events=queue.Queue())
        app.set_busy=lambda value:setattr(app,'activity',value)
        with patch('DrawBot.threading.Thread.start',side_effect=RuntimeError('cannot start thread')):
            with self.assertRaises(RuntimeError):DrawBotApp.begin_worker(app,'mouse-test',lambda:None)
        self.assertIsNone(app.activity)
        self.assertIsNone(app.worker)

    def test_unknown_settings_and_credentials_are_not_exported(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'settings.json').write_text(json.dumps({'quality':'High detail','api_key':'secret-key','password':'secret-password'}))
            with patch.object(dp,'data_dir',return_value=Path(folder)):
                summary=dp._settings_summary()['settings.json']
                self.assertEqual(summary,{'quality':'High detail'})
