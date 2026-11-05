import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image
from PaintPreparation import (_INVOKE_ACTION, rgb_controls, prepare_controls, ensure_paint,
                              find_control, find_custom_color_opener, close_edit_colors,
                              edit_colors_dialog_open, prepare_tool_controls)
from DrawBot import DrawBotApp


def node(name,kind='Button',rect=(10,10,30,30),value='',label=''):
    return dict(name=name,kind='ControlType.'+kind,rect=list(rect),value=value,label=label)


def dialog(language='sv'):
    names=('Röd','Grön','Blå') if language=='sv' else ('Red','Green','Blue')
    nodes=[]
    for i,name in enumerate(names):
        y=100+i*40
        nodes += [node('', 'Edit',(100,y,220,y+30),str(i*100)),node(name,'Text',(230,y,260,y+30))]
    return nodes+[node('OK',rect=(100,260,220,290)),node('Avbryt' if language=='sv' else 'Cancel',rect=(240,260,360,290))]


class PaintPreparationTests(unittest.TestCase):
    def test_retry_reuses_open_rgb_dialog_without_invoking_opener(self):
        from PaintPreparation import calibrate_rgb_controls
        main=[node('Edit colors',rect=(80,10,120,40))]
        state={'open':True}; actions=[]
        def backend(handle,**kw):
            if kw.get('action'):
                actions.append(kw['element']['name'])
                if actions[-1]=='Cancel':state['open']=False
            return dialog('en') if state['open'] else main
        controls=calibrate_rgb_controls(42,backend=backend)
        self.assertEqual(controls['OpenCustomColor'],(100,25))
        self.assertEqual(actions,['Cancel'])
        self.assertFalse(state['open'])

    def test_add_custom_color_resolves_named_and_scoped_plus(self):
        from PaintPreparation import find_add_custom_color
        for name in ('Add to custom colors','Lägg till anpassad färg','+'):
            add=node(name,rect=(280,220,310,250))
            self.assertEqual(find_add_custom_color(dialog()+[add]),add)
        with self.assertRaises(ValueError):
            find_add_custom_color(dialog()+[node('+',rect=(10,10,30,30))])
        with self.assertRaises(ValueError):
            find_add_custom_color(dialog())

    def test_rgb_swedish_and_english_label_geometry(self):
        for language in ('sv','en'):
            self.assertEqual(rgb_controls(dialog(language))['BlueField'],(160,195))

    def test_named_fields_and_negative_monitor_coordinates(self):
        nodes=dialog()
        for n in nodes:n['rect']=[v-1000 for v in n['rect']]
        self.assertEqual(rgb_controls(nodes)['RedField'],(-840,-885))

    def test_ambiguous_or_invalid_fields_rejected(self):
        nodes=dialog();nodes.append(dict(nodes[0]))
        with self.assertRaises(ValueError):rgb_controls(nodes)
        nodes=dialog();nodes[0]['value']='999'
        with self.assertRaises(ValueError):rgb_controls(nodes)

    def test_keyboard_shortcut_suffix(self):
        self.assertEqual(find_control([node('Redigera färger (Ctrl+E)')],('redigera färger',))['name'],'Redigera färger (Ctrl+E)')

    def test_modern_paint_custom_color_aliases_and_control_types(self):
        for name,kind in (('Edit colors','Button'),('Edit color','Button'),('More colors','MenuItem'),('Custom color','Custom'),('Redigera färger','Button')):
            chosen=find_custom_color_opener([node(name,kind,rect=(80,10,120,40))])
            self.assertEqual(chosen['name'],name)

    def test_custom_color_opener_rejects_text_only_or_ambiguous_matches(self):
        with self.assertRaises(ValueError):find_custom_color_opener([node('Edit colors','Text')])
        with self.assertRaises(ValueError):find_custom_color_opener([node('Edit colors'),node('More colors')])

    def test_invoke_fallback_never_blindly_requests_selection_pattern(self):
        self.assertIn('TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern',_INVOKE_ACTION)
        self.assertIn('TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern',_INVOKE_ACTION)
        self.assertIn('LegacyIAccessiblePattern',_INVOKE_ACTION)
        self.assertIn("SendWait('{ENTER}')",_INVOKE_ACTION)
        self.assertNotIn('catch [System.InvalidOperationException] {$e.GetCurrentPattern',_INVOKE_ACTION)

    def test_dialog_open_detection_is_based_on_rgb_controls(self):
        self.assertTrue(edit_colors_dialog_open(dialog('en')))
        self.assertFalse(edit_colors_dialog_open([node('Pencil'),node('Size','Slider')]))

    def test_tool_only_preparation_never_opens_edit_colors(self):
        main=[node('Pencil'),node('Size','Slider',(40,40,60,200)),node('Edit colors',rect=(80,10,120,40))]
        actions=[]
        def backend(handle,**kw):
            if kw.get('action'):
                actions.append((kw['action'],kw['element']['name']))
            return main
        self.assertTrue(prepare_tool_controls(42,backend=backend))
        self.assertIn(('invoke','Pencil'),actions)
        self.assertIn(('size','Size'),actions)
        self.assertFalse(any(name=='Edit colors' for _action,name in actions))

    def test_prepare_captures_controls_then_cancels_dialog(self):
        main=[node('Penna'),node('Storlek','Slider',(40,40,60,200)),node('Redigera färger',rect=(80,10,100,30))]
        state={'dialog':False};actions=[]
        def backend(handle,**kw):
            if kw.get('action'):
                name=kw['element']['name'];actions.append((kw['action'],name))
                if name=='Redigera färger':state['dialog']=True
                if name=='Avbryt':state['dialog']=False
            return dialog() if state['dialog'] else main
        out=prepare_controls(42,backend=backend)
        self.assertEqual(out['OpenCustomColor'],(90,20))
        self.assertEqual(out['GreenField'],(160,155))
        self.assertEqual(actions,[('invoke','Penna'),('size','Storlek'),('invoke','Redigera färger'),('invoke','Avbryt')])
        self.assertFalse(state['dialog'])

    def test_prepare_waits_until_edit_colors_actually_closes(self):
        main=[node('Pencil'),node('Size','Slider',(40,40,60,200)),node('Edit colors',rect=(80,10,120,40))]
        state={'dialog':False,'cancel_calls':0};actions=[]
        def backend(handle,**kw):
            if kw.get('action'):
                name=kw['element']['name'];actions.append((kw['action'],name))
                if name=='Edit colors':state['dialog']=True
                if name=='Cancel':
                    state['cancel_calls']+=1
                    # Simulate current Paint returning from the first UIA invoke
                    # while the XAML modal is still present for another cycle.
                    if state['cancel_calls']>=2:state['dialog']=False
            return dialog('en') if state['dialog'] else main
        out=prepare_controls(42,backend=backend)
        self.assertEqual(out['OpenCustomColor'],(100,25))
        self.assertEqual(state['cancel_calls'],2)
        self.assertFalse(state['dialog'])
        self.assertEqual(actions.count(('invoke','Cancel')),2)

    def test_close_edit_colors_refuses_to_claim_success_while_modal_remains(self):
        def backend(handle,**kw):
            return dialog('en')
        with self.assertRaisesRegex(ValueError,'did not close'):
            close_edit_colors(42,backend=backend,wait=lambda _s:None,max_attempts=2)

    def test_close_edit_colors_can_confirm_pending_rgb_dialog(self):
        state={'dialog':True};actions=[]
        def backend(handle,**kw):
            if kw.get('action'):
                name=kw['element']['name'];actions.append((kw['action'],name))
                if name=='OK':state['dialog']=False
            return dialog('en') if state['dialog'] else [node('Pencil')]
        self.assertTrue(close_edit_colors(42,accept=True,backend=backend,wait=lambda _s:None))
        self.assertEqual(actions,[('invoke','OK')])
        self.assertFalse(state['dialog'])

    def test_prepare_accepts_current_english_edit_colors_button(self):
        main=[node('Pencil'),node('Size','Slider',(40,40,60,200)),node('Edit colors',rect=(80,10,120,40))]
        state={'dialog':False};actions=[]
        def backend(handle,**kw):
            if kw.get('action'):
                name=kw['element']['name'];actions.append((kw['action'],name))
                if name=='Edit colors':state['dialog']=True
                if name=='Cancel':state['dialog']=False
            return dialog('en') if state['dialog'] else main
        out=prepare_controls(42,backend=backend)
        self.assertEqual(out['OpenCustomColor'],(100,25))
        self.assertEqual(out['RedField'],(160,115))
        self.assertIn(('invoke','Edit colors'),actions)
        self.assertFalse(state['dialog'])

    def test_existing_window_does_not_launch_or_clear(self):
        paint={'title':'Namnlös - Paint','handle':4}
        self.assertEqual(ensure_paint(lambda:[paint],launch=lambda:self.fail('must not launch')),paint)

    def test_missing_window_launches_once(self):
        paint={'title':'Untitled - Paint','handle':4};calls=[];windows=iter([[],[],[paint]])
        self.assertEqual(ensure_paint(lambda:next(windows),launch=lambda:calls.append('launch'),wait=lambda _:None),paint)
        self.assertEqual(calls,['launch'])

    def test_multiple_windows_and_cancel_never_launch(self):
        paint={'title':'Untitled - Paint','handle':4}
        with self.assertRaises(ValueError):ensure_paint(lambda:[paint,paint],launch=lambda:self.fail())
        with self.assertRaises(InterruptedError):ensure_paint(lambda:[],cancelled=lambda:True,launch=lambda:self.fail())

    def app(self):
        value=lambda x:SimpleNamespace(get=lambda:x)
        image=object();request={'image':image}
        return SimpleNamespace(game=value('Microsoft Paint'),original=image,paint_start_request=request,
                               activity=None,closing=False,stop=threading.Event()),request

    def test_resume_only_the_explicit_current_request(self):
        app,request=self.app()
        with patch.object(DrawBotApp,'draw',return_value=True) as draw:
            self.assertTrue(DrawBotApp._resume_prepared_paint(app,request))
            draw.assert_called_once_with(app,user_initiated=True,paint_prepared=True)
            DrawBotApp._resume_prepared_paint(app,request)
            self.assertEqual(draw.call_count,1)

    def test_cancel_image_change_profile_change_do_not_draw(self):
        for change in ('cancel','image','profile','request'):
            app,request=self.app()
            if change=='cancel':app.stop.set()
            elif change=='image':app.original=object()
            elif change=='profile':app.game=SimpleNamespace(get=lambda:'Gartic Phone')
            else:app.paint_start_request=None
            with patch.object(DrawBotApp,'draw') as draw:
                self.assertFalse(DrawBotApp._resume_prepared_paint(app,request));draw.assert_not_called()

    def test_paint_start_prepares_before_prerequisite_checks(self):
        app,_=self.app();app.auto_calibrate_paint_tools=lambda **kw:kw
        self.assertEqual(DrawBotApp.start_full_drawing(app),{'start_after':True})
        self.assertFalse(DrawBotApp._strict_safety_required(app))

    def test_auto_prepare_reuses_matching_selected_canvas(self):
        value=lambda x:SimpleNamespace(get=lambda:x)
        class Stop:
            def is_set(self):return False
            def wait(self,seconds):return False
        events=[];captured={}
        app=SimpleNamespace(
            activity=None,closing=False,game=value('Microsoft Paint'),original=object(),
            calibration_path='paint-colors.json',paint_start_request=None,stop=Stop(),
            corners=[(100,300),(800,700)],target_window=(7,(0,0,1000,800)),
            target_client_rect=(0,0,1000,800),status=SimpleNamespace(set=lambda text:None),
            events=SimpleNamespace(put=lambda item:events.append(item)),
        )
        def begin_worker(name,work):
            self.assertEqual(name,'paint-auto-calibration');work();return True
        app.begin_worker=begin_worker
        candidate={'handle':7,'rect':(20,30,1020,830),'title':'Untitled - Paint'}
        meta={'handle':7,'rect':(20,30,1020,830),'client_rect':(20,30,1020,830),'dpi':96}
        exact={'OpenCustomColor':(1,1),'ConfirmColor':(2,2),'RedField':(3,3),'GreenField':(4,4),'BlueField':(5,5)}
        def detect(shot,**kwargs):
            captured.update(kwargs)
            return {'canvas_box':kwargs.get('canvas_box_override'),'tools':{},'positions':[],'rgbs':[],
                    'method':'test','confidence':.96,'palette_count':0}
        activate=Mock(return_value=True)
        with patch('PaintPreparation.ensure_paint',return_value=candidate), \
             patch('BrowserOneClick._enumerate_windows',return_value=[candidate]), \
             patch('ScreenGuard.WindowMonitor',return_value=SimpleNamespace(activate=activate)), \
             patch('TargetCapture.probe_handle_isolated',return_value=meta), \
             patch('PaintPreparation.prepare_tool_controls',return_value=True), \
             patch('PaintPreparation.calibrate_rgb_controls',return_value=exact), \
             patch('ExactColorTools.numeric_rgb_available',return_value=False), \
             patch('ExactColorTools.save'),patch('CalibrationAnchors.make_anchor',return_value={}), \
             patch('PIL.ImageGrab.grab',return_value=Image.new('RGB',(1000,800),'white')), \
             patch('PaintFullCalibration.detect_setup',side_effect=detect), \
             patch('PaintFullCalibration.save_setup',side_effect=lambda result,meta,path:result):
            self.assertTrue(DrawBotApp.auto_calibrate_paint_tools(app))
        self.assertEqual(captured['canvas_box_override'],(120,330,820,730))
        self.assertGreaterEqual(activate.call_count,2)
        self.assertTrue(events)
        self.assertEqual(events[-1][0],'paint_auto_calibration_complete')
        self.assertTrue(events[-1][1]['manual_canvas_reused'])


class WindowsScriptSyntaxTests(unittest.TestCase):
    @unittest.skipUnless(__import__('os').name=='nt','Windows modal invocation regression')
    def test_modal_helper_bounds_wait_and_propagates_completed_errors(self):
        import base64, os, subprocess
        from PaintPreparation import _INVOKE_HELPER
        helper=_INVOKE_HELPER.replace('    public static void Invoke',
            '    public static bool Probe() { return Run(() => Thread.Sleep(5000), 100); }\n'
            '    public static void ErrorProbe() { Run(() => { throw new Exception("probe"); }, 1000); }\n'
            '    public static void Invoke',1)
        script="Add-Type -AssemblyName UIAutomationClient; Add-Type -AssemblyName UIAutomationTypes; $ErrorActionPreference='Stop';\n"+helper
        script+="\n$watch=[Diagnostics.Stopwatch]::StartNew(); if([PaintModalAction]::Probe()){throw 'Blocking action unexpectedly completed'}; if($watch.ElapsedMilliseconds -gt 3000){throw 'Modal action blocked caller'}; $failed=$false; try{[PaintModalAction]::ErrorProbe()}catch{$failed=$true}; if(!$failed){throw 'Provider exception was swallowed'}"
        path=os.path.join(os.environ['SystemRoot'],'System32','WindowsPowerShell','v1.0','powershell.exe')
        result=subprocess.run([path,'-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(script.encode('utf-16-le')).decode()],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))

    @unittest.skipUnless(__import__('os').name=='nt','Windows PowerShell parser')
    def test_embedded_script_parses_without_running_paint(self):
        import base64,os,subprocess
        from PaintPreparation import _SCRIPT
        source=_SCRIPT.replace('HANDLE','42').replace('ACTION',_INVOKE_ACTION)
        payload=base64.b64encode(source.encode('utf-8')).decode()
        script="$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+payload+"'));$tokens=$null;$errors=$null;[void][System.Management.Automation.Language.Parser]::ParseInput($s,[ref]$tokens,[ref]$errors);if($errors.Count){throw ($errors | Out-String)}"
        path=os.path.join(os.environ['SystemRoot'],'System32','WindowsPowerShell','v1.0','powershell.exe')
        result=subprocess.run([path,'-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(script.encode('utf-16-le')).decode()],capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
