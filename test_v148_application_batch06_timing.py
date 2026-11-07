"""Reset acts on the context which actually taught the current draw model."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import DrawTimeCalibration as timing
from DrawBot import DrawBotApp
from test_v148_application_batch04_settings import Value


class TimingResetTests(unittest.TestCase):
    def app(self):
        raw={'profile_key':'microsoft-paint','speed':'Balanced','precision':'High',
             'drawing_style':'Auto','render_style':'Auto','brush_px':1}
        actual=dict(raw,drawing_style_resolved='Line art',render_style='Standard / pixel',
                    effective_paint_tool='Pencil')
        app=SimpleNamespace(activity=None,closing=False,options=Mock(return_value=raw),
            plan={'options':actual,'draw_time_estimate':{'projected_seconds':30.}},
            status=Value(''),draw_time_text=Value('old estimate'))
        def invalidate(message):app.plan=None
        app._mark_plan_stale=Mock(side_effect=invalidate)
        return app,raw,actual

    def test_reset_removes_effective_auto_context_and_invalidates_its_old_preview(self):
        app,raw,actual=self.app()
        with TemporaryDirectory() as temporary,patch.object(timing,'_resolved_path',return_value=Path(temporary)/'timing.json'),patch('DrawBot.log_event'):
            self.assertTrue(timing.record_sample(actual,10,20,completed_paths=10)['recorded'])
            self.assertTrue(timing.record_sample(raw,10,12,completed_paths=10)['recorded'])
            self.assertIsNotNone(timing.load_profile(actual))
            self.assertTrue(DrawBotApp.reset_draw_time_calibration(app))
            self.assertIsNone(timing.load_profile(actual))
            self.assertIsNotNone(timing.load_profile(raw),'a different raw context must not be erased')
        self.assertIsNone(app.plan);app._mark_plan_stale.assert_called_once()

    def test_foreign_profile_plan_never_selects_the_reset_context(self):
        app,raw,actual=self.app();actual['profile_key']='another-profile'
        with patch.object(timing,'reset_profile',return_value={}) as reset,patch('DrawBot.log_event'):
            self.assertTrue(DrawBotApp.reset_draw_time_calibration(app))
        reset.assert_called_once_with(raw)

    def test_reset_failure_preserves_the_existing_plan_and_estimate(self):
        app,_,_=self.app();plan=app.plan
        with patch.object(timing,'reset_profile',side_effect=OSError('disk full')):
            self.assertFalse(DrawBotApp.reset_draw_time_calibration(app))
        self.assertIs(app.plan,plan);self.assertEqual(app.draw_time_text.get(),'old estimate')
        app._mark_plan_stale.assert_not_called();self.assertIn('disk full',app.status.get())

    def test_running_or_closing_application_cannot_reset_an_active_learning_writer(self):
        for field,value in (('activity','draw'),('closing',True)):
            app,_,_=self.app();setattr(app,field,value)
            with patch.object(timing,'reset_profile') as reset:
                self.assertFalse(DrawBotApp.reset_draw_time_calibration(app))
            reset.assert_not_called();app.options.assert_not_called()


if __name__=='__main__':unittest.main()
