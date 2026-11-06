"""A background checkpoint must not cancel work or restore an unrelated image."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from PIL import Image
from DrawBot import DrawBotApp


class RecoveryUiTests(unittest.TestCase):
    def test_checkpoint_reschedules_only_its_own_timer_and_coalesces_image_request(self):
        callbacks=[]
        root=Mock()
        root.after.side_effect=lambda delay,fn:callbacks.append(fn) or 'new-recovery'
        unrelated=('browser_one_click_after','pending_drop_in_after','manual_drop_in_after',
                   'draw_arm_after','preview_after','preview_render_after','profile_change_after',
                   'paint_config_after','capture_job')
        app=SimpleNamespace(closing=False,shutdown_complete=False,root=root,
                            recovery_image_pending=True,recovery_checkpoint_after='old-recovery',
                            **{name:name+'-job' for name in unrelated})
        DrawBotApp._schedule_recovery_checkpoint(app,include_image=False,delay=100)
        root.after_cancel.assert_called_once_with('old-recovery')
        for name in unrelated:self.assertEqual(getattr(app,name),name+'-job')
        with patch.object(DrawBotApp,'_save_recovery_checkpoint') as save:
            callbacks[0]()
        save.assert_called_once_with(app,include_image=True)
        self.assertFalse(app.recovery_image_pending)

    def app(self):
        return SimpleNamespace(game=SimpleNamespace(get=lambda:'Other drawing app'),
                               preview_mode=Mock(),file_label=Mock(),mouse=Mock(),area_text=Mock(),
                               status=Mock(),_mark_plan_stale=Mock(),show_previews=Mock(),set_busy=Mock(),
                               original=None)

    def restore(self,app,state,loader):
        with patch('SessionRecovery.load_cached_image',loader), \
             patch.object(DrawBotApp,'_disarm_full_draw') as disarm, \
             patch.object(DrawBotApp,'_refresh_target_lock_text'),patch('DrawBot.log_event'):
            DrawBotApp._apply_recovery_snapshot(app,state)
        disarm.assert_called_once()
        self.assertFalse(app.small_test_passed)
        self.assertFalse(app.target_lock_passed)
        self.assertFalse(app.safety_preflight_passed)
        self.assertFalse(app.dry_run_passed)
        app.preview_mode.set.assert_called_once_with('Manual')

    def test_snapshot_without_image_never_uses_an_unrelated_cached_file(self):
        for has_image in (False,None,1):
            with self.subTest(has_image=has_image):
                app=self.app();loader=Mock()
                self.restore(app,{'profile':'Other drawing app','options':{},'has_image':has_image},loader)
                loader.assert_not_called();self.assertIsNone(app.original)

    def test_recovery_passes_exact_snapshot_digest_and_keeps_input_disarmed(self):
        app=self.app();image=Image.new('RGBA',(6,4),'red');loader=Mock(return_value=image)
        self.restore(app,{'profile':'Other drawing app','options':{},'has_image':True,'image_sha256':'a'*64},loader)
        loader.assert_called_once_with(expected_sha256='a'*64)
        self.assertIs(app.original,image)

    def test_legacy_snapshot_can_load_its_legacy_image(self):
        app=self.app();loader=Mock(return_value=Image.new('RGB',(2,2)))
        self.restore(app,{'profile':'Other drawing app','options':{},'has_image':True},loader)
        loader.assert_called_once_with(expected_sha256=None)

    def test_declined_recovery_reports_cleanup_failure_without_restoring_or_escaping(self):
        app=SimpleNamespace(closing=False,activity=None,root=Mock(),status=Mock())
        with patch('SessionRecovery.load_snapshot',return_value={'has_image':True}), \
             patch('SessionRecovery.clear_snapshot',side_effect=OSError('cache is locked')), \
             patch('DrawBot.messagebox.askyesno',return_value=False), \
             patch('DrawBot.messagebox.showwarning') as warning, \
             patch.object(DrawBotApp,'_apply_recovery_snapshot') as restore, \
             patch('DrawBot.log_event') as log:
            DrawBotApp.offer_safe_session_recovery(app)
        restore.assert_not_called()
        warning.assert_called_once()
        self.assertIn('cache is locked',warning.call_args.args[1])
        self.assertIn('could not be fully cleared',app.status.set.call_args.args[0])
        self.assertFalse(any('checkpoint cleared.' in str(call) for call in log.call_args_list))


if __name__=='__main__':unittest.main()
