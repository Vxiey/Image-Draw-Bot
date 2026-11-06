"""Calibration draft edits and subject-selection callbacks without native input."""
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock,patch

from PIL import Image

import AppToolCalibration as generic
import ExactColorCalibration as exact
import GetColorPositions as palette
import PaintToolCalibration as paint
import SubjectSelector as subject
from CalibrationDialogLayout import CalibrationDialogLayout
from SmoothScroll import ScrollAccumulator


class Var:
    def __init__(self,value=None):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


def palette_app():
    app=palette.CalibrationApp.__new__(palette.CalibrationApp)
    app.closed=False;app.job=None;app.root=Mock();app.preview=Mock();app.refresh=Mock()
    app.status=Var();app.detect_mode=Var('Auto detect');app.rows=Var(1);app.columns=Var(2)
    app.preset=None;app.is_paint=False;app.max_colors=64;app.profile_key='generic'
    app.anchor={'version':1,'client_rect':[0,0,600,400]};app.anchor_handle=42
    app.pending=[(10,10)];app.rgbs=[(200,10,10)];app.map_names=['red'];app.map_indices=[5]
    app.photo=object();app.snapshot=((0,0,100,80),Image.new('RGB',(100,80),'red'))
    return app


class PaletteRescanTests(unittest.TestCase):
    def state(self,app):
        return (app.pending,app.rgbs,app.map_names,app.map_indices,app.photo,app.snapshot,app.anchor,app.anchor_handle)

    def test_invalid_grid_keeps_reviewed_palette_and_target(self):
        app=palette_app();self.addCleanup(app.snapshot[1].close)
        app.detect_mode.set('Grid');app.rows.set(0)
        old=self.state(app)
        self.assertFalse(app.read_snapshot())
        self.assertEqual(self.state(app),old)
        self.assertIn('Previous colors and target were kept',app.status.get())
        app.preview.configure.assert_not_called()

    def test_failed_replacement_closes_only_new_crop_and_never_publishes_new_identity(self):
        for phase in ('scan','photo','widget'):
            with self.subTest(phase=phase),ExitStack() as stack:
                app=palette_app();old=self.state(app)
                stack.callback(app.snapshot[1].close)
                new=Image.new('RGB',(100,80),'blue')
                stack.callback(new.close)
                stack.enter_context(patch('TargetCapture.capture_target_metadata_isolated',return_value={
                    'handle':99,'client_rect':(100,100,900,700)}))
                stack.enter_context(patch('RegionPicker.select_region',side_effect=lambda root,selected,error:selected((100,100,200,180),new)))
                scan=stack.enter_context(patch.object(palette,'detect_color_swatches',return_value=(
                    [(120,120)],[(0,0,255)],{'found':1,'duplicates':0})))
                photo=stack.enter_context(patch.object(palette.ImageTk,'PhotoImage',return_value=object()))
                if phase=='scan':scan.side_effect=ValueError('no usable swatches')
                elif phase=='photo':photo.side_effect=MemoryError('photo allocation')
                else:app.preview.configure.side_effect=tk.TclError('photo presentation')
                app.start_scan()
                self.assertEqual(self.state(app),old)
                self.assertEqual(app.snapshot[1].getpixel((0,0)),(255,0,0))
                with self.assertRaises(ValueError):new.getpixel((0,0))
                self.assertIn('Could not scan',app.status.get())

    def test_complete_replacement_commits_palette_photo_crop_and_anchor_together(self):
        app=palette_app();old=app.snapshot[1];new=Image.new('RGB',(100,80),'blue');photo=object()
        self.addCleanup(new.close)
        with patch('TargetCapture.capture_target_metadata_isolated',return_value={'handle':99,'client_rect':(100,100,900,700)}),\
             patch('RegionPicker.select_region',side_effect=lambda root,selected,error:selected((100,100,200,180),new)),\
             patch.object(palette,'detect_color_swatches',return_value=([(120,120)],[(0,0,255)],{'found':1,'duplicates':0})),\
             patch.object(palette.ImageTk,'PhotoImage',return_value=photo):
            app.start_scan()
        self.assertEqual(app.pending,[(120,120)]);self.assertEqual(app.rgbs,[(0,0,255)])
        self.assertIs(app.snapshot[1],new);self.assertIs(app.photo,photo)
        self.assertEqual(app.anchor_handle,99);self.assertEqual(app.anchor['client_rect'],[100,100,900,700])
        self.assertIsNone(app.map_names);self.assertIsNone(app.map_indices)
        with self.assertRaises(ValueError):old.getpixel((0,0))
        self.assertEqual(new.getpixel((0,0)),(0,0,255))

    def test_refresh_of_current_snapshot_keeps_coordinate_frame_and_closes_thumbnail(self):
        app=palette_app();self.addCleanup(app.snapshot[1].close);old=app.snapshot;anchor=app.anchor;thumbnails=[]
        def photo(image,**kwargs):
            thumbnails.append(image)
            self.assertIs(kwargs['master'],app.root)
            return object()
        with patch.object(palette,'detect_color_swatches',return_value=([(20,20)],[(1,2,3)],{'found':1,'duplicates':0})),\
             patch.object(palette.ImageTk,'PhotoImage',side_effect=photo):
            self.assertTrue(app.read_snapshot())
        self.assertIs(app.snapshot,old);self.assertIs(app.anchor,anchor);self.assertEqual(app.anchor_handle,42)
        with self.assertRaises(ValueError):thumbnails[0].getpixel((0,0))
        self.assertEqual(app.snapshot[1].getpixel((0,0)),(255,0,0))

    def test_delete_removes_the_complete_multi_selection_in_stable_palette_order(self):
        app=palette_app();self.addCleanup(app.snapshot[1].close)
        app.pending=[(i,10) for i in range(6)];app.rgbs=[(i,20,30) for i in range(6)];app.table=Mock()
        app.table.selection.return_value=('4','1','3')
        self.assertEqual(app.undo(SimpleNamespace()),'break')
        self.assertEqual(app.pending,[(0,10),(2,10),(5,10)])
        self.assertEqual(app.rgbs,[(0,20,30),(2,20,30),(5,20,30)])
        app.table.selection_set.assert_called_once_with('1');app.table.focus.assert_called_once_with('1')

    def test_remove_with_no_selection_retains_last_colour_undo_and_cannot_run_after_close(self):
        app=palette_app();self.addCleanup(app.snapshot[1].close)
        app.table=Mock();app.table.selection.return_value=()
        app.undo();self.assertEqual(app.pending,[]);self.assertEqual(app.rgbs,[])
        app.pending=[(5,5)];app.rgbs=[(1,2,3)];app.closed=True
        app.undo();self.assertEqual(app.pending,[(5,5)])


class DraftEditingTests(unittest.TestCase):
    def app(self,kind):
        cls={'exact':exact.App,'paint':paint.PaintToolCalibrationApp,'generic':generic.AppToolCalibrationApp}[kind]
        app=cls.__new__(cls)
        app.closed=False;app.job=None;app.status=Var();app.refresh=Mock();app.profile_key='generic';app.path='unused'
        app.anchor={'version':1,'client_rect':[0,0,600,400]};app.anchor_handle=42;app.anchor_owner=42;app.anchor_pid=7
        app.positions={'Pencil':(10,10)} if kind=='paint' else {'Brush':(10,10),'Clear':(30,10)}
        app.brush_menu=(20,20);app.brush_preset=(30,30);app.opacity_100=(40,40)
        if kind=='exact':
            app.positions={name:(10+i*10,20) for i,name in enumerate(('OpenCustomColor','ConfirmColor','RedField','GreenField','BlueField','BrightnessTop'))}
        return app

    def test_accidental_brightness_endpoint_can_be_removed_then_valid_numeric_draft_saved(self):
        app=self.app('exact')
        with patch.object(exact,'save') as save:
            app.save();save.assert_not_called()
            self.assertIn('both brightness',app.status.get())
            self.assertTrue(app.remove_control('BrightnessTop'))
            app.save();save.assert_called_once_with('generic',app.positions,anchor=app.anchor)
        self.assertNotIn('BrightnessTop',app.positions)
        self.assertIn('numeric RGB fields',app.status.get())

    def test_removed_paint_brush_and_opacity_are_absent_from_saved_tool_data(self):
        app=self.app('paint')
        for name in ('brush_menu','brush_preset','opacity_100'):self.assertTrue(app.remove_control(name))
        with patch.object(paint,'save_tool_calibration') as save:
            app.save()
        save.assert_called_once_with({'Pencil':(10,10)},None,'unused',anchor=app.anchor,brush_menu=None,brush_preset=None)

    def test_removed_generic_clear_does_not_remove_brush_or_other_draft_state(self):
        app=self.app('generic');anchor=app.anchor
        self.assertTrue(app.remove_control('Clear'))
        with patch.object(generic,'save_calibration') as save:app.save()
        save.assert_called_once_with('generic',{'Brush':(10,10)},anchor=anchor)
        self.assertFalse(app.remove_control('Clear'))

    def test_starting_fresh_discards_only_draft_and_requires_new_capture_before_save(self):
        for kind,module,save_name in (('exact',exact,'save'),('paint',paint,'save_tool_calibration'),('generic',generic,'save_calibration')):
            with self.subTest(kind=kind):
                app=self.app(kind)
                with patch.object(module,save_name) as save:
                    self.assertTrue(app.reset_controls());save.assert_not_called()
                    app.save();save.assert_not_called()
                self.assertEqual(app.positions,{})
                self.assertIsNone(app.anchor);self.assertIsNone(app.anchor_handle)
                if kind=='exact':self.assertIsNone(app.anchor_owner);self.assertIsNone(app.anchor_pid)
                if kind=='paint':self.assertIsNone(app.brush_menu);self.assertIsNone(app.brush_preset);self.assertIsNone(app.opacity_100)

    def test_pending_capture_or_closed_dialog_prevents_draft_mutation(self):
        for kind,name in (('exact','BrightnessTop'),('paint','brush_menu'),('generic','Clear')):
            for state in ('pending','closed'):
                with self.subTest(kind=kind,state=state):
                    app=self.app(kind);before=(dict(app.positions),app.anchor,app.anchor_handle,app.brush_menu)
                    if state=='pending':app.job='capture'
                    else:app.closed=True
                    self.assertFalse(app.remove_control(name));self.assertFalse(app.reset_controls())
                    self.assertEqual((app.positions,app.anchor,app.anchor_handle,app.brush_menu),before)

    def test_generic_capture_rejects_outside_point_without_binding_or_publishing(self):
        app=self.app('generic');app.mouse=SimpleNamespace(get_position=lambda:(900,900));app.capture_visibility=None
        before=dict(app.positions)
        with patch('TargetCapture.capture_target_metadata_isolated',return_value={'handle':42,'client_rect':(0,0,600,400)}):
            app._capture_now('Eraser')
        self.assertEqual(app.positions,before);self.assertIn('outside',app.status.get())


class TinySubjectTests(unittest.TestCase):
    def harness(self,stack,size):
        image=Image.new('RGB',size,'red');stack.callback(image.close)
        bindings={};window_bindings={};buttons=[];callback=Mock()
        top=stack.enter_context(patch('customtkinter.CTkToplevel'))
        stack.enter_context(patch('customtkinter.CTkLabel'))
        stack.enter_context(patch('customtkinter.CTkButton',side_effect=lambda *a,**k:buttons.append(k) or Mock()))
        canvas=stack.enter_context(patch('tkinter.Canvas'))
        stack.enter_context(patch('PIL.ImageTk.PhotoImage'))
        canvas.return_value.bind.side_effect=lambda name,fn:bindings.__setitem__(name,fn)
        top.return_value.bind.side_effect=lambda name,fn,**kwargs:window_bindings.__setitem__(name,fn)
        parent=Mock();parent.winfo_screenwidth.return_value=1200;parent.winfo_screenheight.return_value=800
        subject.select_subject(parent,image,callback)
        return SimpleNamespace(canvas=canvas.return_value,bindings=bindings,window_bindings=window_bindings,
                               buttons=buttons,callback=callback,top=top.return_value)

    def test_full_extent_of_tiny_and_thin_images_can_be_applied(self):
        for size in ((1,1),(2,2),(1,10),(10,2),(3,3)):
            with self.subTest(size=size),ExitStack() as stack:
                h=self.harness(stack,size)
                h.bindings['<Button-1>'](SimpleNamespace(x=0,y=0))
                h.bindings['<ButtonRelease-1>'](SimpleNamespace(x=size[0],y=size[1]))
                h.buttons[0]['command']()
                h.callback.assert_called_once_with((0.0,0.0,1.0,1.0))

    def test_tiny_drags_on_normal_images_still_need_a_meaningful_rectangle(self):
        with ExitStack() as stack:
            h=self.harness(stack,(100,80))
            h.bindings['<Button-1>'](SimpleNamespace(x=5,y=5))
            h.bindings['<ButtonRelease-1>'](SimpleNamespace(x=7,y=7))
            h.buttons[0]['command']();h.callback.assert_not_called()

    def test_select_whole_image_is_explicit_and_keyboard_apply_remains_once_only(self):
        with ExitStack() as stack:
            h=self.harness(stack,(1,1))
            self.assertEqual(h.window_bindings['<Control-a>'](), 'break')
            h.callback.assert_not_called()
            h.window_bindings['<Return>']();h.window_bindings['<Return>']()
            h.callback.assert_called_once_with((0.0,0.0,1.0,1.0))
            h.top.destroy.assert_called_once()


class CalibrationLayoutTests(unittest.TestCase):
    def layout(self):
        form=object.__new__(CalibrationDialogLayout)
        form._closed=False;form._focus_job=None;form._focus_target=None;form._bindings=[]
        form._wheel_delta=ScrollAccumulator();form.tk=SimpleNamespace(call=lambda *args:'win32')
        form.body=SimpleNamespace(master=None,winfo_rooty=lambda:100,winfo_height=lambda:1000)
        form.canvas=SimpleNamespace(yview_scroll=Mock(),yview_moveto=Mock(),canvasy=lambda y:0,winfo_height=lambda:200)
        form._owner=SimpleNamespace(nametowidget=Mock())
        form.after_idle=Mock(return_value='focus-job');form.after_cancel=Mock()
        return form

    def test_wheel_is_local_preserves_fractional_motion_and_respects_nested_inputs(self):
        form=self.layout();label=SimpleNamespace(master=form.body,winfo_class=lambda:'TLabel')
        def event(widget,delta=-60):return SimpleNamespace(widget=widget,delta=delta,num=None,state=0)
        self.assertEqual(form._wheel(event(label)),'break');form.canvas.yview_scroll.assert_not_called()
        self.assertEqual(form._wheel(event(label)),'break');form.canvas.yview_scroll.assert_called_once_with(1,'units')
        form.canvas.yview_scroll.reset_mock()
        outside=SimpleNamespace(master=None,winfo_class=lambda:'TLabel')
        table=SimpleNamespace(master=form.body,winfo_class=lambda:'Treeview')
        self.assertIsNone(form._wheel(event(outside)));self.assertIsNone(form._wheel(event(table)))
        form.canvas.yview_scroll.assert_not_called()
        form._owner.nametowidget.return_value=label
        self.assertEqual(form._wheel(event('.body.label',-120)),'break')
        form.canvas.yview_scroll.assert_called_once_with(1,'units')

    def test_focus_below_fold_is_revealed_and_pending_job_is_cancelled_on_disposal(self):
        form=self.layout()
        field=SimpleNamespace(master=form.body,winfo_rooty=lambda:800,winfo_height=lambda:30)
        form._focus_changed(SimpleNamespace(widget=field));form._focus_changed(SimpleNamespace(widget=field))
        form.after_idle.assert_called_once()
        form._reveal_focus();form.canvas.yview_moveto.assert_called_once_with(.53)
        form._focus_changed(SimpleNamespace(widget=field));form._dispose()
        form.after_cancel.assert_called_once_with('focus-job');self.assertIsNone(form._focus_target)


@unittest.skipUnless(sys.platform=='win32','Actual Windows ttk calibration layout')
class WindowsCalibrationLayoutTests(unittest.TestCase):
    def assert_inside(self,widget,container):
        self.assertTrue(widget.winfo_ismapped())
        self.assertGreaterEqual(widget.winfo_rootx(),container.winfo_rootx())
        self.assertGreaterEqual(widget.winfo_rooty(),container.winfo_rooty())
        self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),container.winfo_rootx()+container.winfo_width())
        self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),container.winfo_rooty()+container.winfo_height())

    def test_exact_and_palette_dialogs_keep_actions_visible_at_650_by_500(self):
        for kind in ('exact','palette'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temporary,ExitStack() as stack:
                root=tk.Tk();stack.callback(root.destroy)
                stack.enter_context(patch('WindowsMouse.WindowsMouse',return_value=Mock()))
                if kind=='exact':
                    stack.enter_context(patch.object(exact,'load',side_effect=FileNotFoundError))
                    app=exact.App(root,'generic')
                else:app=palette.CalibrationApp(root,path=Path(temporary)/'colours.json')
                root.geometry('650x500');root.update_idletasks()
                self.assert_inside(app.save_button,root);self.assert_inside(app.close_button,root)
                self.assertLess(app.layout.canvas.yview()[1],1.0)
                app.layout.canvas.yview_moveto(1);root.update_idletasks()
                self.assert_inside(app.save_button,root);self.assert_inside(app.close_button,root)
                if kind=='exact':
                    last=app.remove_buttons['Eyedropper'];self.assert_inside(last,app.layout.canvas)
                    app.positions['Eyedropper']=(2,3);app.refresh();last.invoke();self.assertNotIn('Eyedropper',app.positions)
                else:self.assert_inside(app.add_code,app.layout.canvas)

    def test_repeated_form_teardown_removes_only_its_window_callbacks(self):
        root=tk.Tk();root.geometry('650x500')
        observed=[];unrelated=root.bind('<MouseWheel>',lambda event:observed.append(event.delta),add='+')
        sequences=('<MouseWheel>','<Button-4>','<Button-5>','<FocusIn>')
        before={name:tuple(line for line in root.bind(name).splitlines() if line.strip()) for name in sequences}
        try:
            for _ in range(3):
                form=CalibrationDialogLayout(root);form.pack(fill='both',expand=True)
                tokens=[token for _,token in form._bindings]
                root.update_idletasks();form.destroy();root.update_idletasks()
                self.assertEqual({name:tuple(line for line in root.bind(name).splitlines() if line.strip()) for name in sequences},before)
                for token in tokens:self.assertFalse(root.tk.call('info','commands',token))
                self.assertTrue(root.tk.call('info','commands',unrelated))
            root.update();root.event_generate('<MouseWheel>',delta=120,when='now')
            self.assertEqual(observed,[120])
        finally:root.destroy()


if __name__=='__main__':unittest.main()
