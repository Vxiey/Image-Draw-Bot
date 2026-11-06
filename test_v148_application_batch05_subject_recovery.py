"""Image-specific subject work survives recovery only with its own raster."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from DrawBot import DrawBotApp
import SessionRecovery as recovery
from SubjectFocus import subject_mask
from test_v148_application_batch04_settings import Value


def application(image=None):
    return SimpleNamespace(
        closing=False, shutdown_complete=False, original=image, saved_area=None,
        corners=[], game=Value('Other drawing app'), subject_focus=Value('Subject only'),
        subject_region=(.15, .2, .55, .8), subject_hint=Value('marked'),
        preview_mode=Value('Automatic'), file_label=Mock(), mouse=Mock(), area_text=Mock(),
        status=Mock(), _mark_plan_stale=Mock(), show_previews=Mock(), set_busy=Mock(),
    )


class SubjectRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for name,path in {'RECOVERY_DIR':root,'STATE_FILE':root/'state.json',
                          'IMAGE_FILE':root/'last-image.png','RENDER_FILE':root/'render.json'}.items():
            self.stack.enter_context(patch.object(recovery,name,path))
        self.stack.enter_context(patch('DrawBot.log_event'))

    def restore(self,app,state,**kwargs):
        with patch.object(DrawBotApp,'_disarm_full_draw'),patch.object(DrawBotApp,'_refresh_target_lock_text'):
            DrawBotApp._apply_recovery_snapshot(app,state,**kwargs)

    def test_marked_subject_roundtrip_preserves_exact_mask_without_input_authorization(self):
        with Image.new('RGBA',(37,29),'blue') as source:
            before=application(source)
            DrawBotApp._save_recovery_checkpoint(before,include_image=True)
            state=recovery.load_snapshot()
            self.assertEqual(state['subject_selection']['mode'],'Subject only')
            self.assertEqual(state['subject_selection']['image_sha256'],state['image_sha256'])
            restored=application()
            self.restore(restored,state)
            self.addCleanup(restored.original.close)
            self.assertEqual(restored.subject_region,before.subject_region)
            self.assertEqual(restored.subject_focus.get(),'Subject only')
            np.testing.assert_array_equal(subject_mask(source,before.subject_region)[0],
                                          subject_mask(restored.original,restored.subject_region)[0])
            self.assertEqual(restored.preview_mode.get(),'Manual')
            self.assertFalse(restored.target_lock_passed)
            self.assertFalse(restored.safety_preflight_passed)
            restored.mouse.disarm_input.assert_called_once()

    def test_changed_source_is_cached_before_attaching_its_new_selection(self):
        with Image.new('RGBA',(5,5),'red') as old,Image.new('RGBA',(7,6),'green') as new:
            app=application(old)
            DrawBotApp._save_recovery_checkpoint(app,include_image=True)
            old_state=recovery.load_snapshot()
            app.original=new;app.subject_region=(.6,.1,.9,.9)
            with patch.object(recovery,'_store_image',side_effect=OSError('disk full')):
                DrawBotApp._save_recovery_checkpoint(app)
            self.assertEqual(recovery.load_snapshot()['subject_selection'],old_state['subject_selection'])
            self.assertIs(app._recovery_source_ref(),old)
            DrawBotApp._save_recovery_checkpoint(app)
            state=recovery.load_snapshot()
            self.assertNotEqual(state['image_sha256'],old_state['image_sha256'])
            self.assertEqual(state['subject_selection']['region'],list(app.subject_region))
            with recovery.load_cached_image(expected_sha256=state['image_sha256']) as cached:
                self.assertEqual(cached.size,new.size)
                self.assertEqual(cached.getpixel((0,0)),new.getpixel((0,0)))

    def test_selection_only_checkpoint_reuses_cached_image_without_reencoding(self):
        with Image.new('RGBA',(5,5),'blue') as source:
            app=application(source);DrawBotApp._save_recovery_checkpoint(app,include_image=True)
            app.subject_region=None;app.subject_focus.set('Subject first')
            with patch.object(recovery,'_store_image',side_effect=AssertionError('unnecessary encoding')):
                DrawBotApp._save_recovery_checkpoint(app)
            selected=recovery.load_snapshot()['subject_selection']
            self.assertIsNone(selected['region']);self.assertEqual(selected['mode'],'Subject first')

    def test_invalid_or_cross_image_selection_is_not_applied(self):
        with Image.new('RGBA',(5,5),'blue') as source:
            DrawBotApp._save_recovery_checkpoint(application(source),include_image=True)
            state=recovery.load_snapshot();raw=json.loads(recovery.STATE_FILE.read_text())
            for selection in (
                dict(state['subject_selection'],image_sha256='a'*64),
                dict(state['subject_selection'],region=[0,0,1,True]),
                dict(state['subject_selection'],region=[0,.9,1,.2]),
                dict(state['subject_selection'],region=[0,0,10**400,1]),
                dict(state['subject_selection'],mode='unsupported'),
            ):
                with self.subTest(selection=selection):
                    raw['subject_selection']=selection
                    recovery.STATE_FILE.write_text(json.dumps(raw))
                    cleaned=recovery.load_snapshot()
                    self.assertIsNone(cleaned['subject_selection'])
                    restored=application()
                    self.restore(restored,cleaned,recovered_image=source)
                    self.assertIsNone(restored.subject_region)
                    self.assertEqual(restored.subject_focus.get(),'Off')

    def test_missing_or_failed_image_does_not_restore_a_selection(self):
        with Image.new('RGBA',(5,5),'blue') as source:
            DrawBotApp._save_recovery_checkpoint(application(source),include_image=True)
            state=recovery.load_snapshot()
            app=application()
            self.restore(app,state,recovered_image=None)
            self.assertIsNone(app.subject_region);self.assertEqual(app.subject_focus.get(),'Off')

    def test_snapshot_without_selection_keeps_legacy_default(self):
        with Image.new('RGBA',(5,5),'blue') as source:
            recovery.save_snapshot(profile='Other drawing app',options={},image=source)
            state=recovery.load_snapshot();self.assertIsNone(state['subject_selection'])
            app=application();self.restore(app,state,recovered_image=source)
            self.assertEqual(app.subject_focus.get(),'Off');self.assertIsNone(app.subject_region)


if __name__=='__main__':unittest.main()
