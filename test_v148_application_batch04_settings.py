"""Settings persistence must reflect the active profile and real save result."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

from DrawBot import DrawBotApp
from ProfileIsolation import SETTING_NAMES
from SettingsValidation import ADDITIONAL_VARIABLES,validated_settings


class Value:
    def __init__(self,value):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


class LocalSettingsTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.path=Path(directory.name)/'settings.json'
        self.app=SimpleNamespace(**{name:Value('') for name in (*SETTING_NAMES,*ADDITIONAL_VARIABLES)})
        self.app.settings_path=self.path;self.app.closing=False;self.app.status=Mock()
        self.app.profile_change_in_progress=False;self.app.saved_area=None;self.app.corners=[]
        self.app.canvas_anchor_detection=None
        for name,value in {'quality':'Balanced','speed':'Safe','mode':'Dots','contrast':1.,
                           'brush_px':'2','max_seconds':'180','outline':False,'skip_white':True,
                           'preview_show_background':True,'preview_show_fill':True,
                           'preview_show_strokes':True,'ui_mode':'Simple','subject_focus':'Off'}.items():
            getattr(self.app,name).set(value)

    def load(self,data):
        self.path.write_text(json.dumps(data),encoding='utf-8')
        with patch('DrawBot.log_event'):return DrawBotApp.read_settings(self.app)

    def test_corrupt_fields_do_not_abort_unrelated_valid_settings(self):
        self.assertTrue(self.load({'quality':[],'contrast':10**400,'speed':'Fast',
                                   'outline':True,'corners':[[1,1],[1,20]]}))
        self.assertEqual(self.app.quality.get(),'Balanced');self.assertEqual(self.app.contrast.get(),1.)
        self.assertEqual(self.app.speed.get(),'Fast');self.assertTrue(self.app.outline.get())
        self.assertIsNone(self.app.saved_area)

    def test_partial_file_preserves_selected_profile_defaults_for_absent_fields(self):
        self.app.brush_px.set('4');self.app.render_style.set('Portrait / shaded')
        self.app.quality.set('Maximum detail');self.app.contrast.set(1.4)
        self.assertTrue(self.load({'speed':'Fast','contrast':True}))
        self.assertEqual(self.app.speed.get(),'Fast');self.assertEqual(self.app.quality.get(),'Maximum detail')
        self.assertEqual(self.app.brush_px.get(),'4');self.assertEqual(self.app.render_style.get(),'Portrait / shaded')
        self.assertEqual(self.app.contrast.get(),1.4)

    def test_apply_error_rolls_back_values_geometry_and_transition_guard(self):
        old=SimpleNamespace(get=self.app.mode.get)
        def fail(value):raise RuntimeError('Tk setter failure')
        old.set=fail;self.app.mode=old
        self.assertFalse(self.load({'quality':'Maximum detail','speed':'Fast','mode':'Shape paths'}))
        self.assertEqual(self.app.quality.get(),'Balanced');self.assertEqual(self.app.speed.get(),'Safe')
        self.assertEqual(self.app.mode.get(),'Dots');self.assertFalse(self.app.profile_change_in_progress)

    def test_settings_application_suppresses_intermediate_profile_callbacks(self):
        observed=[];var=self.app.speed;set_value=var.set
        def setter(value):observed.append(self.app.profile_change_in_progress);set_value(value)
        var.set=setter
        self.assertTrue(self.load({'speed':'Fast'}));self.assertEqual(observed,[True])
        self.assertFalse(self.app.profile_change_in_progress)

    def test_unsupported_schema_is_preserved_through_later_save(self):
        for schema in (3,True,2.0,-1):
            with self.subTest(schema=schema):
                self.assertFalse(self.load({'settings_schema':schema,'quality':'High detail'}))
                before=self.path.read_bytes()
                self.assertFalse(DrawBotApp.save_settings(self.app))
                self.assertEqual(self.path.read_bytes(),before)
        self.path.unlink()
        with patch('DrawBot.log_event'):self.assertFalse(DrawBotApp.read_settings(self.app))
        self.assertIsNone(self.app._settings_protected_path)

    def test_gartic_opacity_round_trips_with_profile_settings(self):
        self.app.gartic_opacity.set('40%')
        self.assertTrue(DrawBotApp.save_settings(self.app))
        self.app.gartic_opacity.set('Auto')
        self.assertTrue(DrawBotApp.read_settings(self.app));self.assertEqual(self.app.gartic_opacity.get(),'40%')

    def test_failed_reread_does_not_revoke_future_schema_protection(self):
        self.assertFalse(self.load({'settings_schema':3,'quality':'future preference'}))
        previous=self.path.read_bytes()
        for error in (PermissionError('temporary lock'),ValueError('temporary read failure')):
            with self.subTest(error=type(error).__name__),patch('RuntimePaths.read_json',side_effect=error),patch('DrawBot.log_event'):
                self.assertFalse(DrawBotApp.read_settings(self.app))
                self.assertEqual(self.app._settings_protected_path,self.path)
                self.assertFalse(DrawBotApp.save_settings(self.app))
                self.assertEqual(self.path.read_bytes(),previous)
        self.assertTrue(self.load({'settings_schema':2,'speed':'Fast'}))
        self.assertIsNone(self.app._settings_protected_path)
        self.assertTrue(DrawBotApp.save_settings(self.app))

    def test_save_result_exposes_disk_failure_and_preserves_old_document(self):
        self.path.write_text('previous')
        with patch('DrawBot.atomic_write_text',side_effect=OSError('disk full')),patch('DrawBot.log_event'):
            self.assertFalse(DrawBotApp.save_settings(self.app))
        self.assertEqual(self.path.read_text(),'previous')

    def test_nonfinite_ui_value_cannot_replace_valid_settings(self):
        self.path.write_text('previous');self.app.contrast.set(float('nan'))
        with patch('DrawBot.log_event'):self.assertFalse(DrawBotApp.save_settings(self.app))
        self.assertEqual(self.path.read_text(),'previous')

    def test_failed_profile_save_retains_selected_active_profile_and_resume(self):
        self.app.game=Value('Microsoft Paint');self.app._active_profile_name='Other drawing app'
        self.app.activity=None;self.app.root=Mock();self.app.profile_change_after='queued'
        self.app.save_settings=Mock(return_value=False)
        with patch.object(DrawBotApp,'_clear_render_resume') as clear,patch.object(DrawBotApp,'_disarm_manual_drop_in'):
            DrawBotApp.change_profile(self.app)
        clear.assert_not_called();self.assertEqual(self.app.game.get(),'Other drawing app')
        self.app.root.after_cancel.assert_called_once_with('queued');self.app.root.after_idle.assert_not_called()

    def test_bounded_reader_rejects_duplicate_keys_before_any_application(self):
        self.path.write_text('{"quality":"High detail","quality":"Maximum detail"}')
        with patch('DrawBot.log_event'):self.assertFalse(DrawBotApp.read_settings(self.app))
        self.assertEqual(self.app.quality.get(),'Balanced')


class ProfileBoundaryTests(unittest.TestCase):
    def test_legacy_aliases_migrate_without_unknown_setting_failures(self):
        from ProfilePortability import sanitize_settings
        out=sanitize_settings({'brush_width':'7','max_time':90,'drawing_mode':'Dots'})
        self.assertEqual(out['brush_px'],'7');self.assertEqual(out['max_seconds'],90);self.assertEqual(out['mode'],'Dots')
        self.assertTrue({'brush_width','max_time','drawing_mode'}.isdisjoint(out))
        self.assertEqual(sanitize_settings({'brush_width':'7','brush_px':'3'})['brush_px'],'3')

    def test_profile_import_rejects_malformed_scalar_settings_before_write(self):
        from ProfilePortability import sanitize_settings,ProfilePortabilityError
        for key,value in (('quality',[]),('outline','true'),('contrast',True),('contrast',3),
                          ('brush_px',False),('profile_extras',{'ui_mode':'Unknown'})):
            with self.subTest(key=key,value=value),self.assertRaises(ProfilePortabilityError):sanitize_settings({key:value})

    def test_canvas_data_cannot_appear_twice_or_as_empty_nonobject(self):
        from ProfilePortability import flatten_settings,ProfilePortabilityError
        corners=[[0,0],[100,100]]
        with self.assertRaises(ProfilePortabilityError):flatten_settings({'renderer':{'corners':corners}},{'corners':corners})
        with self.assertRaises(ProfilePortabilityError):flatten_settings({},[])

    def test_failed_save_cannot_export_stale_settings_or_start_import(self):
        import ProfilePortability as profiles
        app=SimpleNamespace(activity=None,closing=False,game=Value('Other drawing app'),save_settings=Mock(return_value=False))
        package=profiles.build_package('Other drawing app',{'quality':'Balanced'})
        with patch.object(profiles,'_read_json') as read,patch.object(profiles,'_replace_profile_files') as write:
            with self.assertRaises(profiles.ProfilePortabilityError):profiles.package_from_app(app)
            with self.assertRaises(profiles.ProfilePortabilityError):profiles.import_package_into_app(app,package)
        read.assert_not_called();write.assert_not_called()

    def test_pending_profile_change_or_shutdown_blocks_profile_management(self):
        import ProfilePortability as profiles
        package=profiles.build_package('Other drawing app',{})
        for state in ({'closing':True},{'profile_change_in_progress':True},{'profile_change_after':'pending'}):
            app=SimpleNamespace(activity=None,game=Value('Other drawing app'),save_settings=Mock(),**state)
            with self.subTest(state=state),patch.object(profiles,'_replace_profile_files') as write:
                for action in (lambda:profiles.package_from_app(app),lambda:profiles.import_package_into_app(app,package),lambda:profiles.reset_profile(app)):
                    with self.assertRaises(profiles.ProfilePortabilityError):action()
                app.save_settings.assert_not_called();write.assert_not_called()


if __name__=='__main__':unittest.main()
