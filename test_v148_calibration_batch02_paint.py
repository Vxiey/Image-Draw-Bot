"""Paint verification, persistence and modal contracts without desktop input."""
import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from PIL import Image

import OneClickSetupVerification as verification
import PaintAutoCalibration as paint_auto
import PaintColorVerifier as color
import PaintFullCalibration as full
import PaintPreparation as preparation
import PaintTools as tools
import RuntimePaths
from Colors import save_calibration
from test_paint_preparation import dialog,node


class SavedPaintVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.palette=Path(self.tmp.name)/'palette.json';self.toolfile=Path(self.tmp.name)/'tools.json'
        self.client=(0,0,1200,800);self.anchor={'version':1,'client_rect':list(self.client)}
        self.points=[(20+i*20,50+(i//10)*20) for i in range(20)]
        self.colors=[(i*10%256,i*20%256,i*30%256) for i in range(20)]
        self.tools={'version':3,'tools':{'Pencil':[10,10],'Fill':[20,20]},'anchor':self.anchor}
        self.detected={'canvas_box':(100,100,900,600),'palette_count':20,'confidence':.9,'positions':self.points,'rgbs':self.colors,'tools':self.tools['tools']}
        self.image=Image.new('RGB',(1200,800),'white')

    def save_palette(self,**kwargs):
        save_calibration(kwargs.pop('points',self.points),kwargs.pop('colors',self.colors),self.palette,profile_key='microsoft-paint',state='verified',verification={'confidence':kwargs.pop('confidence',.9)},anchor=kwargs.pop('anchor',self.anchor),**kwargs)

    def verify(self,detected=None,tooldata=None,client=None):
        with patch.object(full,'detect_setup',return_value=detected or self.detected),patch.object(tools,'load_tool_calibration',return_value=tooldata or self.tools):
            return verification.verify_paint_live({'client_rect':client or self.client},(100,100,900,600) if client is None else (200,200,1000,700),self.palette,screenshot=self.image)

    def test_live_verifier_rejects_off_client_saved_points(self):
        self.save_palette(points=[(5000+i,5000) for i in range(20)])
        with self.assertRaises(ValueError):self.verify()

    def test_matching_count_cannot_hide_wrong_palette_coordinates(self):
        self.save_palette(points=[(x+10,y) for x,y in self.points])
        result=self.verify()
        self.assertFalse(result.passed);self.assertFalse(result.palette_ok)

    def test_matching_coordinates_cannot_hide_wrong_saved_rgb(self):
        wrong=list(self.colors);wrong[0]=(255,255,255)
        self.save_palette(colors=wrong)
        result=self.verify()
        self.assertFalse(result.passed);self.assertEqual(result.palette_verified,19)

    def test_legacy_or_wrong_live_tools_cannot_pass_independent_verification(self):
        self.save_palette()
        legacy={'version':1,'tools':self.tools['tools']}
        self.assertFalse(self.verify(tooldata=legacy).tool_ok)
        wrong=copy.deepcopy(self.tools);wrong['tools']['Pencil']=[70,10]
        self.assertFalse(self.verify(tooldata=wrong).tool_ok)

    def test_translated_anchor_is_resolved_before_live_comparison(self):
        self.save_palette();detected=copy.deepcopy(self.detected)
        detected['positions']=[(x+100,y+100) for x,y in self.points]
        detected['tools']={name:(x+100,y+100) for name,(x,y) in self.tools['tools'].items()}
        detected['canvas_box']=(200,200,1000,700)
        self.assertTrue(self.verify(detected=detected,client=(100,100,1300,900)).passed)

    def test_zero_saved_confidence_cannot_be_replaced_by_live_confidence(self):
        self.save_palette(confidence=0)
        result=self.verify();self.assertFalse(result.passed);self.assertEqual(result.confidence,0)

    def test_verified_palette_requires_explicit_profile_owner(self):
        self.save_palette();raw=json.loads(self.palette.read_text());raw.pop('profile');self.palette.write_text(json.dumps(raw))
        with self.assertRaises(ValueError):verification.load_verified_palette(self.palette,'microsoft-paint')

    def test_browser_palette_translation_uses_current_frame(self):
        data={'anchor':self.anchor};rows=[{'position':[30,50],'rgb':[1,2,3]}]
        self.assertEqual(verification._live_palette_rows(data,rows,(100,100,1300,900)),[((130,150),(1,2,3))])

    def result(self):return dict(self.detected,method='test-verified')

    def test_invalid_palette_never_updates_tool_file(self):
        self.palette.write_text('original palette');self.toolfile.write_text('original tools')
        result=self.result();result['positions']=[(20,50)]*20
        with self.assertRaises(ValueError):full.save_setup(result,{'client_rect':self.client},self.palette,self.toolfile)
        self.assertEqual(self.palette.read_text(),'original palette');self.assertEqual(self.toolfile.read_text(),'original tools')

    def test_paired_paint_save_rolls_back_second_publication_failure(self):
        self.palette.write_text('original palette');self.toolfile.write_text('original tools')
        original=RuntimePaths._replace_with_retry
        def publish(source,destination):
            if Path(source).suffix=='.import' and Path(destination)==self.palette:raise PermissionError('blocked palette publication')
            return original(source,destination)
        with patch.object(RuntimePaths,'_replace_with_retry',side_effect=publish),self.assertRaises(OSError):
            full.save_setup(self.result(),{'client_rect':self.client},self.palette,self.toolfile)
        self.assertEqual(self.palette.read_text(),'original palette');self.assertEqual(self.toolfile.read_text(),'original tools')

    def test_tools_and_palette_cannot_alias_one_destination(self):
        with self.assertRaises(ValueError):full.save_setup(self.result(),{'client_rect':self.client},self.palette,self.palette)
        self.assertFalse(self.palette.exists())

    def test_tool_loader_rejects_oversized_optional_data(self):
        self.toolfile.write_text(' '*140000)
        with self.assertRaises(ValueError):tools.load_tool_calibration(self.toolfile)

    def test_invalid_auto_confidence_is_not_promoted_to_one(self):
        data=copy.deepcopy(self.tools);data['auto']={'confidence':float('nan')}
        self.assertEqual(tools.validate_tool_calibration(data)['auto']['confidence'],0)
        data['version']=True
        with self.assertRaises(ValueError):tools.validate_tool_calibration(data)

    def test_tool_resolution_rejects_outside_client(self):
        tools.save_tool_calibration({'Pencil':(9000,9000)},path=self.toolfile,anchor=self.anchor)
        with self.assertRaises(ValueError):tools.build_tool_actions('Pencil',self.toolfile,current_client_rect=self.client)


class PaintBoundaryTests(unittest.TestCase):
    def test_auto_calibration_preserves_detector_confidence(self):
        image=Image.new('RGB',(800,600),'white')
        detected={'tools':{'Pencil':(10,10)},'confidence':.85}
        with patch.object(full,'detect_setup',return_value=detected):
            self.assertEqual(paint_auto.detect_controls(image,(0,0,800,600))['Pencil'].confidence,.85)

    def test_auto_calibration_rejects_screenshot_dimension_mismatch(self):
        with patch.object(full,'detect_setup') as detector,self.assertRaises(ValueError):
            paint_auto.detect_controls(Image.new('RGB',(799,600)),(0,0,800,600))
        detector.assert_not_called()

    def test_auto_calibration_rechecks_cancellation_before_save(self):
        cancelled=[False]
        def detect(*args,**kwargs):cancelled[0]=True;return {'Pencil':paint_auto.Candidate('Pencil',(30,30),.9,.9)}
        with patch.object(paint_auto,'detect_controls',side_effect=detect),patch.object(paint_auto,'save_tool_calibration') as save,self.assertRaises(InterruptedError):
            paint_auto.auto_calibrate({'client_rect':(0,0,800,600)},screenshot=Image.new('RGB',(800,600)),cancelled=lambda:cancelled[0])
        save.assert_not_called()

    def test_rgb_verification_cannot_clamp_bad_input_into_match(self):
        for rgb in ((-1,0,0),(256,0,0),(0.1,0,0),(False,0,0),(0,0),(0,0,0,255)):
            with self.subTest(rgb=rgb),self.assertRaises(ValueError):color.verify_paint_color(rgb,(0,0,0))

    def test_unknown_verification_context_does_not_use_default_tolerance(self):
        with self.assertRaises(ValueError):color.verify_paint_color((0,0,0),(0,0,0),context='typo')

    def test_invalid_numeric_rgb_values_do_not_mean_modal_is_closed(self):
        nodes=dialog('en');nodes[0]['value']='999';calls=[]
        def backend(handle,**kwargs):calls.append(kwargs);return nodes
        with self.assertRaises(ValueError):preparation.close_edit_colors(42,backend=backend,wait=lambda _:None,max_attempts=1)
        self.assertTrue(any(call.get('action')=='invoke' for call in calls))

    def test_empty_automation_tree_does_not_prove_closed(self):
        with self.assertRaises(ValueError):preparation.close_edit_colors(42,backend=lambda *args,**kwargs:[],wait=lambda _:None,max_attempts=1)

    def test_modal_reappearing_after_final_settle_is_not_success(self):
        scans=iter([dialog('en'),[node('Pencil')],dialog('en')])
        def backend(handle,**kwargs):return dialog('en') if kwargs.get('action') else next(scans)
        with self.assertRaises(ValueError):preparation.close_edit_colors(42,backend=backend,wait=lambda _:None,max_attempts=1)

    def test_ambiguous_named_rgb_edits_cannot_fall_back_to_one_label(self):
        nodes=dialog('en')+[node('Red','Edit',(100,100,220,130),'1'),node('Red','Edit',(400,100,520,130),'2')]
        with self.assertRaisesRegex(ValueError,'ambiguous'):preparation.rgb_controls(nodes)

    def test_control_geometry_and_handle_are_validated_before_native_script(self):
        for handle in (0,-1,True,2**64,'42'):
            with self.subTest(handle=handle),self.assertRaises(ValueError):preparation._automation_script(handle)
        for rect in ([0,0,float('nan'),2],[0,0,10**1000,2],[0,0,0,2],[0,0,2,True]):
            with self.subTest(rect=rect),self.assertRaises(ValueError):preparation._automation_script(42,element=node('OK',rect=rect),action='invoke')

    def test_subprocess_cleanup_remains_bounded_when_child_retains_pipe(self):
        process=Mock(returncode=None);process.poll.return_value=None
        process.communicate.side_effect=subprocess.TimeoutExpired('compiler',1)
        with patch.object(preparation,'system_directory',return_value=Path('/trusted')),patch.object(preparation.subprocess,'Popen',return_value=process),self.assertRaises(InterruptedError):
            preparation._run_powershell('0',cancelled=Mock(side_effect=[False,True]))
        process.kill.assert_called_once_with();process.communicate.assert_called_once_with(timeout=1);process.wait.assert_called_once_with(timeout=1)

    def test_cancel_during_completed_scan_does_not_publish_output(self):
        process=Mock(returncode=0);process.poll.return_value=0;process.communicate.return_value=(b'[]',b'')
        with patch.object(preparation,'system_directory',return_value=Path('/trusted')),patch.object(preparation.subprocess,'Popen',return_value=process),self.assertRaises(InterruptedError):
            preparation._run_powershell('0',cancelled=Mock(side_effect=[False,False,True]))

    def test_scan_rejects_nonobject_rows_and_output_over_budget(self):
        with patch.object(preparation.os,'name','nt'),patch.object(preparation,'_run_powershell',return_value=b'[null]'),self.assertRaises(ValueError):preparation.automation(42)
        process=Mock(returncode=0);process.poll.return_value=0;process.communicate.return_value=(b'x'*(8*1024*1024+1),b'')
        with patch.object(preparation,'system_directory',return_value=Path('/trusted')),patch.object(preparation.subprocess,'Popen',return_value=process),self.assertRaises(ValueError):preparation._run_powershell('0')


@unittest.skipUnless(os.name=='nt','Windows PowerShell parser; no Paint controls are accessed')
class WindowsPaintParserRegressionTests(unittest.TestCase):
    def test_complete_focused_fallback_script_parses_without_executing_it(self):
        source=preparation._automation_script(42,element=node("Redigera färger ' test"),action='invoke')
        script='$source=ConvertFrom-Json -InputObject '+preparation._powershell_json_literal(source)+'\n'
        script+="$tokens=$null\n$errors=$null\n$ast=[System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)\nConvertTo-Json -InputObject @{errors=@($errors | ForEach-Object {$_.Message})} -Compress"
        result=json.loads(preparation._run_powershell(script).decode('utf-8-sig'))
        self.assertEqual(result,{'errors':[]})

    def test_generic_list_serializes_all_rows_as_one_json_array(self):
        script="$rows=[System.Collections.Generic.List[object]]::new()\nfor($i=0;$i -lt 1000;$i++){$rows.Add(@{id=$i})}\nConvertTo-Json -InputObject @($rows.ToArray()) -Compress"
        result=json.loads(preparation._run_powershell(script).decode('utf-8-sig'))
        self.assertEqual(result,[{'id':i} for i in range(1000)])


if __name__=='__main__':unittest.main()
