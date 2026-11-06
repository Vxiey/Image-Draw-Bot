"""Profile and workspace regressions; no Tk window or desktop input is created."""
import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from BeginnerSetupWizard import build_setup_wizard, format_setup_status, format_wizard_dialog, next_action
from GameProfiles import PROFILES, profile_defaults, profile_ui
from ProfileEngine import PIXEL_ACCURATE_SETTINGS, policy_summary, resolve_profile_policy
from ProfileIsolation import capture_defaults, reset_settings, restore_extra
from ProfilePolish import apply_profile_polish, format_profile_polish
from UIState import classify_error, compute_workspace_state
from WordGuesser import find_candidates, load_words, normalize


class Var:
    def __init__(self,value):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


class ProfilePolicyTests(unittest.TestCase):
    def compose(self,profile,request,mode='Auto'):
        requested=dict(request,profile_engine=mode)
        policy,meta=resolve_profile_policy(profile,requested,mode=mode)
        final,polish=apply_profile_polish(profile,policy)
        self.assertEqual(requested,dict(request,profile_engine=mode))
        return policy,final,polish

    def test_pixel_accurate_lock_survives_the_production_policy_chain(self):
        for profile in ('Microsoft Paint','Gartic Phone','Skribbl.io','Skribbl.io Fast'):
            with self.subTest(profile=profile):
                policy,final,meta=self.compose(profile,{'draw_quality':'Pixel Accurate','time_budget_mode':'Manual'})
                for key in PIXEL_ACCURATE_SETTINGS:self.assertEqual(final.get(key),policy.get(key),key)
                self.assertEqual(final['draw_quality'],'Pixel Accurate')
                self.assertEqual(final['planning_resolution'],'Extreme')
                self.assertEqual(final['max_stroke_cap'],'Unlimited')
                self.assertEqual(final['color_fidelity'],'Exact')

    def test_both_unlimited_modes_survive_every_automatic_profile_pass(self):
        for profile in ('Microsoft Paint','Gartic Phone','Skribbl.io','Skribbl.io Fast','Kleki','Other drawing app'):
            for mode in ('Unlimited','Unlimited / Accuracy'):
                with self.subTest(profile=profile,mode=mode):
                    policy,final,meta=self.compose(profile,{'time_budget_mode':mode})
                    self.assertEqual(policy['time_budget_mode'],mode)
                    self.assertEqual(final['time_budget_mode'],mode)
                    self.assertEqual(meta['effective_time_budget'],mode)

    def test_ordinary_auto_defaults_and_manual_choices_keep_their_contract(self):
        _,automatic,_=self.compose('Gartic Phone',{'draw_quality':'Balanced','time_budget_mode':'60 sec'})
        self.assertEqual(automatic['time_budget_mode'],'Gartic Phone Fast')
        request={'draw_quality':'Pixel Accurate','time_budget_mode':'60 sec','quality':'Balanced'}
        _,manual,meta=self.compose('Gartic Phone',request,'Manual settings')
        for key,value in request.items():self.assertEqual(manual[key],value)
        self.assertFalse(meta['applied'])

    def test_profile_summary_reports_the_actual_manual_or_unlimited_budget(self):
        for mode,budget in (('Manual settings','60 sec'),('Auto','Unlimited / Accuracy')):
            _,_,meta=self.compose('Skribbl.io',{'time_budget_mode':budget},mode)
            self.assertEqual(meta['recommended_time_budget'],'Skribbl Default')
            self.assertIn(f' · {budget} · ',format_profile_polish(meta))
            self.assertIn(f'Budget: {budget}\n',format_profile_polish(meta,compact=False))


class ProfileIsolationTests(unittest.TestCase):
    def test_fill_controls_cannot_leak_into_a_profile_without_saved_settings(self):
        app=SimpleNamespace(use_region_fill_engine=Var(True),fill_aggressiveness=Var('Balanced'),
                            detail_zoom=Var('Auto'),quick_sketch_style=Var('Balanced'),
                            quick_sketch_fill_preference=Var('Safe Fill First'))
        capture_defaults(app)
        app.use_region_fill_engine.set(False);app.fill_aggressiveness.set('Aggressive')
        app.detail_zoom.set('4x');app.quick_sketch_style.set('Contour');app.quick_sketch_fill_preference.set('Off')
        reset_settings(app)
        self.assertIs(app.use_region_fill_engine.get(),True)
        self.assertEqual(app.fill_aggressiveness.get(),'Balanced')
        self.assertEqual(app.detail_zoom.get(),'Auto')
        self.assertEqual(app.quick_sketch_style.get(),'Balanced')
        self.assertEqual(app.quick_sketch_fill_preference.get(),'Safe Fill First')

    def test_detail_zoom_viewport_resets_with_the_other_preview_pages(self):
        app=SimpleNamespace(detail_zoom_canvas=SimpleNamespace(_preview_pan=(19,-42)),
                            result_canvas=SimpleNamespace(_preview_pan=(12,9)))
        reset_settings(app)
        self.assertEqual(app.detail_zoom_canvas._preview_pan,(0,0))
        self.assertEqual(app.result_canvas._preview_pan,(0,0))

    def test_missing_profile_extras_preserve_the_selected_profile_defaults(self):
        app=SimpleNamespace(ui_mode=Var('Advanced'),subject_focus=Var('Subject first'),
                            preview_show_background=Var(False))
        restore_extra(app,{})
        self.assertEqual(app.ui_mode.get(),'Advanced')
        self.assertEqual(app.subject_focus.get(),'Subject first')
        self.assertFalse(app.preview_show_background.get())
        restore_extra(app,{'profile_extras':{'ui_mode':'Simple','subject_focus':True}})
        self.assertEqual(app.ui_mode.get(),'Simple')
        self.assertEqual(app.subject_focus.get(),'Subject first')


class WizardTests(unittest.TestCase):
    def test_manual_targets_are_given_available_calibration_actions(self):
        for profile in ('Kleki','Magma','Drawize','Gartic.io','Other drawing app','My custom app'):
            steps=build_setup_wizard(profile_name=profile,image_loaded=True)
            calibration=next(step for step in steps if step.key=='calibration')
            setup=next(step for step in steps if step.key=='auto_setup')
            self.assertIn('Read colors',calibration.action)
            self.assertNotIn('Auto setup',calibration.action)
            self.assertEqual(setup.title,'Manual target setup')
        steps=build_setup_wizard(profile_name='Gartic Phone',image_loaded=True)
        self.assertIn('Auto setup browser',next(step for step in steps if step.key=='calibration').action)

    def test_armed_wizard_points_to_start_instead_of_requesting_another_unlock(self):
        args=dict(profile_name='Skribbl.io',image_loaded=True,tools_ready=True,palette_ready=True,area_ready=True)
        ready=build_setup_wizard(**args,full_draw_unlocked=True)
        self.assertIn('Start drawing',next_action(ready))
        self.assertNotIn('Unlock',format_setup_status(ready))
        unlock=next(step for step in ready if step.key=='unlock')
        self.assertIn('Start is unlocked',unlock.detail)
        expired=build_setup_wizard(**args,full_draw_unlocked=False)
        self.assertIn('Unlock',next_action(expired))

    def test_busy_paint_guidance_does_not_suggest_starting_another_operation(self):
        for image_loaded in (True,False):
            steps=build_setup_wizard(profile_name='Microsoft Paint',image_loaded=image_loaded,activity='preview')
            self.assertEqual(next_action(steps),'Wait for the current operation or press Stop.')

    def test_single_warning_is_not_split_into_letters(self):
        text=format_wizard_dialog((),profile_warnings='Keep the target visible.')
        self.assertIn('- Keep the target visible.',text)
        self.assertNotIn('- K\n',text)


def workspace_arguments(**changes):
    values=dict(image_loaded=True,target_name='Microsoft Paint',paint_tools_ready=False,
                area_ready=False,palette_ready=False,test_passed=False,target_locked=False,
                preflight_passed=False,dry_run_passed=False,prepare_on_start=True)
    values.update(changes)
    return values


def studio_state_renderer(primary_state='normal',**changes):
    """Execute the production nested renderer with plain variable/widget fakes."""
    import StudioUI
    source=ast.parse(Path('StudioUI.py').read_text(encoding='utf-8'))
    node=next(n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='_apply_ui_state')
    module=ast.Module(body=[node],type_ignores=[]);ast.fix_missing_locations(module)
    app=SimpleNamespace(closing=False,original=SimpleNamespace(size=(10,10),mode='RGB'),corners=[],activity=None,
        plan=None,game=Var('Microsoft Paint'),status=Var('Image loaded.'),
        _paint_tool_preflight_ready=Mock(return_value=False),_target_lock_valid=Mock(return_value=False),
        _safety_preflight_valid=Mock(return_value=False),_dry_run_valid=Mock(return_value=False),
        _full_draw_unlocked=Mock(return_value=False),setup_wizard_text=Var(''),palette_button=Mock(),
        area_button=Mock(),app_tool_button=Mock(),_safe_widget_configure=Mock(),start_secondary=Mock(),
        start=SimpleNamespace(cget=lambda key:primary_state),full_draw_armed_until=0.0)
    for key,value in changes.items():setattr(app,key,value)
    scope=dict(vars(StudioUI));scope.update(a=app,ui_state_job={'id':1},ui_state_running={'value':False},
        compute_workspace_state=compute_workspace_state,classify_error=classify_error,
        palette_ready_now=lambda:False,gpu_summary=lambda:'CPU',PROFILES=PROFILES,profile_ui=profile_ui,
        profile_defaults=profile_defaults,policy_summary=policy_summary,
        step_headers={3:(Mock(),Mock())},step_dots={n:Mock() for n in range(1,6)},checklist_rows={})
    for name in ('top_state','profile_pill','profile_guide_icon','profile_guide_badge','profile_guide_tip',
                 'profile_guide_recommend','image_info','plan_metrics','error_title','error_message','error_action','error_card'):
        scope[name]=Mock()
    scope['error_card'].winfo_manager.return_value=''
    exec(compile(module,'StudioUI.py','exec'),scope)
    return app,scope


class WorkspaceTests(unittest.TestCase):
    def test_paint_can_prepare_without_claiming_calibration_or_test_readiness(self):
        state=compute_workspace_state(**workspace_arguments())
        self.assertTrue(state.ready);self.assertFalse(state.can_test)
        self.assertEqual(state.label,'Ready to prepare Paint')
        items={item.key:item for item in state.items}
        for key in ('tools','area','palette','test','lock','preflight','dryrun'):
            self.assertEqual(items[key].state,'optional')
        for changes in ({'image_loaded':False},{'activity':'draw'},{'status':'Error: preparation failed'}):
            self.assertFalse(compute_workspace_state(**workspace_arguments(**changes)).ready)
        self.assertFalse(compute_workspace_state(**workspace_arguments(target_name='Skribbl.io')).ready)

    def test_paint_sidebar_mirrors_the_controller_start_and_uses_one_readiness_snapshot(self):
        app,scope=studio_state_renderer()
        scope['_apply_ui_state']()
        app._safe_widget_configure.assert_called_once_with(app.start_secondary,state='normal')
        self.assertIn('ready. Prepare Paint & draw',app.setup_wizard_text.get())
        for method in ('_target_lock_valid','_safety_preflight_valid','_dry_run_valid','_full_draw_unlocked'):
            getattr(app,method).assert_called_once_with()
        self.assertEqual(app.full_draw_armed_until,0.0)

    def test_sidebar_never_overrides_a_disabled_primary_start_or_busy_state(self):
        for primary,activity in (('disabled',None),('normal','draw')):
            app,scope=studio_state_renderer(primary,activity=activity)
            scope['_apply_ui_state']()
            app._safe_widget_configure.assert_called_once_with(app.start_secondary,state='disabled')

    def test_help_shortcut_no_longer_claims_global_quick_start_f1(self):
        source=ast.parse(Path('StudioUI.py').read_text(encoding='utf-8'))
        bindings=[]
        for node in ast.walk(source):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='bind' and len(node.args)>1:
                if isinstance(node.args[1],ast.Lambda) and any(isinstance(n,ast.Attribute) and n.attr=='show_welcome' for n in ast.walk(node.args[1])):
                    bindings.append(node)
        self.assertEqual([n.args[0].value for n in bindings],['<Shift-F1>'])
        root=Mock();app=SimpleNamespace(show_welcome=Mock())
        module=ast.fix_missing_locations(ast.Module(body=[ast.Expr(bindings[0])],type_ignores=[]))
        exec(compile(module,'StudioUI.py','exec'),{'root':root,'a':app})
        root.bind.call_args.args[1](SimpleNamespace())
        app.show_welcome.assert_called_once_with()


class WordUnicodeTests(unittest.TestCase):
    def test_casefolded_letters_are_recomposed_before_validation_and_matching(self):
        words=('ǰ','ΐ')
        for word in words:self.assertEqual(normalize(word),word)
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'words.txt';path.write_text('\n'.join(words),encoding='utf-8')
            loaded=load_words(path)
        self.assertEqual(loaded,words)
        self.assertEqual(find_candidates(loaded,'?',1),list(words))
        self.assertEqual(find_candidates(loaded,'j\u030c',1),['ǰ'])


if __name__=='__main__':unittest.main()
