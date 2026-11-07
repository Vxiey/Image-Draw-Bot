"""Regression coverage for import, calibration and visible UI lifecycle behavior."""
from contextlib import ExitStack
from types import SimpleNamespace
import threading
import queue
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from AutoDrawing import _image_statistics
from BeginnerSetupWizard import (WizardStep,build_setup_wizard,format_setup_status,
                                missing_start_requirements,next_action)
from DrawBot import DrawBotApp,_validated_setup_payload,preview_area_for
from StudioUI import ToolTip
from UICompactLayout import CompactGroup


def ui_app():
    app=SimpleNamespace(closing=False,activity=None,pending_clear_drawing=None,
        stop=threading.Event(),preview_generation=5,original=Image.new('RGBA',(3,2),'red'),
        corners=[(10,10),(90,90)],saved_area=[(10,10),(90,90)],
        target_window=(1,(0,0,100,100)),target_client_rect=(0,0,100,100),
        canvas_anchor_detection=object(),color_session_cache={},browser_auto_calibration_success=True)
    for name in ('status','area_text','browser_auto_text','browser_one_click_text','root',
                 'refresh_palette','save_settings','_mark_plan_stale','_invalidate_target_lock',
                 'file_label','show_previews','_schedule_recovery_checkpoint','_maybe_auto_preview'):
        setattr(app,name,Mock())
    app.game=Mock();app.game.get.return_value='Gartic Phone'
    return app


def paste_and_deliver_bitmap(app):
    """Drive the deferred clipboard worker before the original pixel assertions."""
    app.events=queue.Queue()
    if not hasattr(app,'stop'):app.stop=threading.Event()
    tasks=[]
    def enqueue(activity,task):
        if activity!='load':raise AssertionError('Unexpected clipboard activity')
        app.activity=activity;tasks.append(task);return True
    app.begin_worker=enqueue
    if DrawBotApp.paste_image(app) is not True or len(tasks)!=1:
        raise AssertionError('Clipboard bitmap was not queued')
    tasks[0]()
    while not app.events.empty():
        DrawBotApp._handle_event(app,*app.events.get_nowait())


class IncomingStateTests(unittest.TestCase):
    def payload(self,**extra):
        payload={'profile_name':'Gartic Phone','palette_count':18,'confidence':.9,
                 'canvas_confidence':.9,'canvas_box':(120,50,300,180),
                 'target_meta':{'handle':2,'rect':(100,0,400,220),'client_rect':(110,30,390,210)}}
        payload.update(extra)
        return payload

    def test_invalid_setup_never_partly_changes_window_or_canvas(self):
        for event in ('browser_auto_calibration_complete','browser_one_click_setup_complete'):
            with self.subTest(event=event):
                app=ui_app();before=(list(app.corners),app.target_window)
                payload=self.payload(canvas_box=(0,0,300,180))
                if event=='browser_one_click_setup_complete':
                    request=DrawBotApp._new_browser_one_click_request(app,force=True)
                    request['phase']='setup'
                    payload['_browser_request']=request
                with self.assertRaises(ValueError):
                    DrawBotApp._handle_event(app,event,payload)
                self.assertEqual((app.corners,app.target_window),before)
                self.assertFalse(app.browser_auto_calibration_success)
                app.refresh_palette.assert_not_called()

    def test_palette_only_setup_clears_the_old_window_canvas(self):
        app=ui_app()
        DrawBotApp._handle_event(app,'browser_auto_calibration_complete',self.payload(canvas_box=None))
        self.assertEqual(app.corners,[]);self.assertEqual(app.saved_area,[])
        self.assertEqual(app.target_window[0],2)
        self.assertFalse(app.browser_auto_calibration_success)
        self.assertIn('Select the drawing area',app.status.set.call_args.args[0])

    def test_nonfinite_confidence_never_authorizes_one_click(self):
        for value in (float('nan'),float('inf'),True,'0.9'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                _validated_setup_payload(self.payload(canvas_confidence=value),require_canvas=True)

    def test_cancelled_worker_results_cannot_replace_current_state(self):
        for event in ('loaded','planned','background_removed','screen','paint_auto_calibration_complete',
                      'browser_auto_calibration_complete','browser_one_click_setup_complete',
                      'one_click_setup_verification_complete'):
            app=ui_app();app.stop.set();original=app.original
            DrawBotApp._handle_event(app,event,object())
            self.assertIs(app.original,original)
            self.assertEqual(app.target_window[0],1)
            app.refresh_palette.assert_not_called()

    def test_queued_preview_does_not_invalidate_the_busy_worker_generation(self):
        for activity,closing in (('preview',False),('draw',False),(None,True)):
            app=ui_app();app.activity=activity;app.closing=closing
            DrawBotApp.update_plan(app)
            self.assertEqual(app.preview_generation,5)

    def test_background_remove_and_undo_update_labels_and_preview(self):
        app=ui_app();old=app.original.copy();app.background_removal_original=old
        removed=Image.new('RGBA',(3,2),(0,0,0,0))
        with patch.object(DrawBotApp,'_clear_render_resume'):
            DrawBotApp._handle_event(app,'background_removed',SimpleNamespace(image=removed,metadata={}))
            self.assertEqual(app.original.getpixel((0,0)),(0,0,0,0))
            self.assertIn('Background removed',app.file_label.set.call_args.args[0])
            self.assertTrue(DrawBotApp.undo_background_removal(app))
        self.assertEqual(app.original.tobytes(),old.tobytes())
        self.assertIsNone(app.background_removal_original)
        self.assertEqual(app.show_previews.call_count,2)

    def test_bitmap_import_discards_old_undo_and_schedules_its_authorized_start(self):
        for armed in (False,True):
            with self.subTest(armed=armed),ExitStack() as stack:
                app=ui_app();app.background_removal_original=Image.new('RGB',(1,1),'blue')
                app.background_removal_meta={'stale':True}
                stack.enter_context(patch('PIL.ImageGrab.grabclipboard',return_value=Image.new('RGB',(5,4),'green')))
                stack.enter_context(patch.object(DrawBotApp,'_manual_drop_in_armed',return_value=armed))
                stack.enter_context(patch.object(DrawBotApp,'_clear_render_resume'))
                stack.enter_context(patch.object(DrawBotApp,'_queue_drop_in_start',return_value=armed))
                pending=stack.enter_context(patch.object(DrawBotApp,'_schedule_pending_drop_in_start'))
                one_click=stack.enter_context(patch.object(DrawBotApp,'_queue_browser_one_click_after_import'))
                paste_and_deliver_bitmap(app)
                self.assertIsNone(app.background_removal_original)
                self.assertIsNone(app.background_removal_meta)
                # The tracked loader's done event owns deferred start scheduling.
                self.assertEqual(pending.call_count,0)
                self.assertEqual(one_click.call_count,int(not armed))


class PresentationTests(unittest.TestCase):
    def test_missing_palette_blocks_browser_and_generic_start(self):
        for name in ('Gartic Phone','Other drawing app'):
            steps=build_setup_wizard(profile_name=name,image_loaded=True,tools_ready=True,
                palette_ready=False,area_ready=True,full_draw_unlocked=True)
            self.assertIn('calibration',[s.key for s in missing_start_requirements(steps)])

    def test_running_operation_overrides_an_unlocked_wizard(self):
        steps=build_setup_wizard(image_loaded=True,tools_ready=True,palette_ready=True,
            area_ready=True,full_draw_unlocked=True,activity='draw')
        self.assertEqual([s.key for s in missing_start_requirements(steps)],['unlock'])
        self.assertIn('Stop',next_action(steps))

    def test_paint_ready_status_uses_the_actual_paint_start_action(self):
        steps=build_setup_wizard(profile_name='Microsoft Paint',image_loaded=True)
        self.assertIn('Prepare Paint & draw',format_setup_status(steps))
        self.assertNotIn('Unlock full drawing',format_setup_status(steps))

    def test_next_action_does_not_consume_a_generator_before_fallback(self):
        steps=(step for step in [WizardStep('extra','Extra setup','next','Select a tool')])
        self.assertEqual(next_action(steps),'Select a tool')

    def test_hidden_widget_does_not_open_a_delayed_tooltip(self):
        widget=Mock();widget.winfo_ismapped.return_value=False
        tip=ToolTip(widget,'help')
        with patch('StudioUI.tk.Toplevel') as top:
            tip._show()
        top.assert_not_called()

    def test_tooltip_creation_failure_destroys_the_partial_window(self):
        widget=Mock();widget.winfo_rootx.return_value=0;widget.winfo_rooty.return_value=0
        widget.winfo_height.return_value=20
        tip=ToolTip(widget,'help')
        with patch('StudioUI.tk.Toplevel') as top,patch('StudioUI.tk.Label',side_effect=tk.TclError('closed')):
            tip._show()
        top.return_value.destroy.assert_called_once()
        self.assertIsNone(tip.window)


class PackedWidget:
    def __init__(self,parent):
        self.master=parent;self.dead=False;self.packs=0;self.unpacks=0
    def winfo_manager(self):
        if self.dead:raise tk.TclError('destroyed')
        return 'pack' if self in self.master.order else ''
    def pack_forget(self):
        self.unpacks+=1;self.master.order.remove(self)
    def pack(self,**kwargs):
        if self.dead:raise tk.TclError('destroyed')
        self.packs+=1
        if self in self.master.order:self.master.order.remove(self)
        self.master.order.insert(self.master.order.index(kwargs['after'])+1,self)


class CompactLayoutTests(unittest.TestCase):
    def group(self):
        parent=SimpleNamespace(order=[])
        parent.pack_slaves=lambda:list(parent.order)
        group=object.__new__(CompactGroup);group.parent=parent;group.open=True
        group.shell=object();group.toggle=Mock();group.title='Options'
        group.items=[PackedWidget(parent) for _ in range(3)]
        group.saved_pack={};group.layout=SimpleNamespace(scope_by_widget={})
        parent.order=[group.shell]+group.items
        return group

    def test_repeated_identical_layout_does_not_repack_widgets(self):
        group=self.group()
        for _ in range(100):group.set_open(True)
        self.assertEqual(sum(w.packs+w.unpacks for w in group.items),0)
        group.toggle.configure.assert_not_called()

    def test_profile_reflow_restores_order_without_unpacking_unaffected_items(self):
        group=self.group();a,b,c=group.items
        group.parent.order=[group.shell,b,c,a]
        group.refresh()
        self.assertEqual(group.parent.order,[group.shell,a,b,c])
        self.assertEqual(a.packs,1);self.assertEqual(b.packs+c.packs,0)
        self.assertEqual(sum(w.unpacks for w in group.items),0)

    def test_destroyed_child_does_not_break_remaining_controls(self):
        group=self.group();dead,alive,last=group.items
        dead.dead=True;group.parent.order=[group.shell,last,alive]
        group.refresh()
        self.assertEqual(group.parent.order,[group.shell,alive,last])


class PreviewBoundsTests(unittest.TestCase):
    def test_direct_full_preview_helper_honors_small_or_invalid_budget(self):
        from PreviewQuality import full_preview_options
        for budget in (32,0,float('nan'),float('inf'),'256',True):
            with self.subTest(budget=budget),self.assertRaises(ValueError):
                full_preview_options({'ram_budget_mb':budget},(100,100))
        self.assertEqual(full_preview_options({'ram_budget_mb':256},(100,100))['ram_budget_mb'],256)

    def test_impossible_memory_budget_does_not_start_a_preview_worker(self):
        app=ui_app();app.options=lambda:{'ram_budget_mb':32}
        app.area=lambda:(0,0,100,100);app.begin_worker=Mock()
        DrawBotApp.update_plan(app,user_initiated=True)
        app.begin_worker.assert_not_called()
        self.assertIn('memory budget',app.status.set.call_args.args[0])

    def test_full_detail_cannot_bypass_the_memory_guard(self):
        app=ui_app();app.options=lambda:{'ram_budget_mb':256}
        app.area=lambda:(0,0,5000,5000);app.begin_worker=Mock()
        DrawBotApp.update_plan(app,user_initiated=True,full_detail=True)
        app.begin_worker.assert_not_called()
        self.assertIn('memory budget',app.status.set.call_args.args[0])

    def test_area_never_exceeds_caps_even_for_nearly_equal_sizes_or_thin_images(self):
        for area,pixels,side in (((761,1),1000,760),((1001,1000),1_000_000,2000),
                                 ((1000000,1),5,10000),((1,1000000),5,10000),((33,33),10,20)):
            with self.subTest(area=area):
                width,height=preview_area_for(area,max_pixels=pixels,max_dimension=side)
                self.assertGreaterEqual(min(width,height),1)
                self.assertLessEqual(width*height,pixels)
                self.assertLessEqual(max(width,height),side)

    def test_invalid_preview_caps_fail_before_allocation(self):
        for invalid in (0,-1,float('nan'),float('inf')):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                preview_area_for((100,100),max_pixels=invalid)

    def test_image_statistics_match_original_compositing_without_mutating_input(self):
        rng=np.random.default_rng(148)
        rgba=Image.fromarray(rng.integers(0,256,(193,251,4),dtype=np.uint8))
        for mode in ('RGBA','RGB','L','LA','P'):
            for transparency in (False,True):
                source=rgba.convert(mode)
                if transparency and mode=='RGB':source.info['transparency']=source.getpixel((0,0))
                elif transparency and mode=='P':source.info['transparency']=0
                before=source.tobytes()
                with source.convert('RGBA') as converted,Image.new('RGBA',source.size,'white') as flat:
                    flat.alpha_composite(converted);flat.thumbnail((128,128))
                    with flat.convert('RGB') as rgb:a=np.asarray(rgb,dtype=np.int16)
                bins=(a//32).astype(np.int32);codes=bins[:,:,0]*64+bins[:,:,1]*8+bins[:,:,2]
                hist=np.bincount(codes.ravel(),minlength=512)
                expected=(float(np.mean(np.min(a,axis=2)>235)),float(np.mean(a.max(axis=2)-a.min(axis=2)>35)),
                          float(np.sort(hist)[-12:].sum()/hist.sum()))
                self.assertEqual(_image_statistics(source),expected,(mode,transparency))
                self.assertEqual(source.tobytes(),before)
                source.close()


if __name__=='__main__':unittest.main()
