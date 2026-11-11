"""Widget and scheduler fakes for sidebar installation and local wheel routing."""
from contextlib import ExitStack
from types import SimpleNamespace
import sys
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

import customtkinter as ctk
import ProfileIsolation
import UICompactLayout as compact
from SmoothScroll import install_scrolling


class Widget:
    def __init__(self,master=None,**options):
        self.master=master;self.children=[];self.order=[];self.manager=''
        self.options=dict(options);self.pack_options={};self.destroyed=False
        self.bindings={}
        self.fail_pack=0;self.text_reads=0;self.children_reads=0
        if master is not None:master.children.append(self)
    def winfo_children(self):self.children_reads+=1;return list(self.children)
    def winfo_manager(self):
        if self.destroyed:raise tk.TclError('widget is destroyed')
        return self.manager
    def pack_slaves(self):return list(self.order)
    def pack_info(self):
        if self.manager!='pack':raise tk.TclError('widget is not packed')
        return dict(self.pack_options)
    def pack(self,**options):
        if self.fail_pack:
            self.fail_pack-=1;raise tk.TclError('shell layout failed')
        self.pack_forget()
        order=self.master.order
        if options.get('before') in order:order.insert(order.index(options['before']),self)
        elif options.get('after') in order:order.insert(order.index(options['after'])+1,self)
        else:order.append(self)
        self.manager='pack';self.pack_options=dict(options)
    def pack_forget(self):
        if self.destroyed:raise tk.TclError('widget is destroyed')
        if self.master is not None and self in self.master.order:self.master.order.remove(self)
        self.manager=''
    def cget(self,key):self.text_reads+=1;return self.options.get(key,'')
    def configure(self,**options):self.options.update(options)
    def bind(self,sequence,callback,add=None):
        if add not in ('+',True):self.bindings[sequence]=[]
        self.bindings.setdefault(sequence,[]).append(callback)
    def destroy(self):
        for child in list(self.children):child.destroy()
        self.bindings.clear()
        self.pack_forget();self.destroyed=True
        if self.master is not None:self.master.children.remove(self)


class SidebarTests(unittest.TestCase):
    def test_real_customtkinter_controls_without_text_are_not_invalid_widgets(self):
        for kind in (ctk.CTkFrame,ctk.CTkOptionMenu,ctk.CTkEntry,ctk.CTkSlider):
            widget=object.__new__(kind)
            with self.subTest(kind=kind):self.assertEqual(compact._widget_text(widget),'')

    def test_ctk_padding_snapshot_uses_logical_values_before_the_widget_rescales(self):
        widget=object.__new__(ctk.CTkButton)
        widget._last_geometry_manager_call={'function':tk.Pack.pack,
            'kwargs':{'fill':'x','padx':(12,6),'pady':8}}
        widget.winfo_manager=lambda:'pack'
        widget.pack_info=lambda:{'fill':'x','padx':(18,9),'pady':12}
        expected={'fill':'x','padx':(12,6),'pady':8}
        self.assertEqual(compact._pack_options(widget),expected)
        app=SimpleNamespace()
        ProfileIsolation.register_controls(app,iter(((widget,'paint'),)))
        self.assertEqual(app._scoped_profile_controls[0][2],expected)

    def test_shell_pack_failure_restores_control_order_and_keeps_hidden_controls_hidden(self):
        parent=Widget()
        controls=[Widget(parent,text=f'control {index}') for index in range(4)]
        for index,widget in enumerate(controls):widget.pack(fill='x',padx=index+1)
        hidden=Widget(parent,text='hidden')
        original_order=list(parent.order)
        def frame(*args,**kwargs):
            widget=Widget(*args,**kwargs);widget.fail_pack=1;return widget
        with patch.object(compact.ctk,'CTkFrame',side_effect=frame),patch.object(compact,'KeyboardButton',Widget),patch.object(compact.ctk,'CTkLabel',Widget):
            with self.assertRaisesRegex(tk.TclError,'shell layout failed'):
                compact.CompactGroup(SimpleNamespace(),parent,'Controls','Help',[controls[1],controls[3],hidden])
        self.assertEqual(parent.order,original_order)
        self.assertEqual(parent.children,[*controls,hidden])
        self.assertEqual(hidden.manager,'')
        for index,widget in enumerate(controls):
            self.assertFalse(widget.destroyed)
            self.assertEqual(widget.pack_options['padx'],index+1)

    def test_later_group_failure_rolls_back_prior_groups_before_falling_back(self):
        root=Widget();controls=[Widget(root,text=f'control {index}') for index in range(4)]
        for widget in controls:widget.pack(fill='x')
        app=SimpleNamespace(root=root);layout=compact.CompactLayout(app)
        shells=[]
        def frame(*args,**kwargs):
            widget=Widget(*args,**kwargs);shells.append(widget)
            if len(shells)==2:widget.fail_pack=1
            return widget
        with ExitStack() as stack:
            stack.enter_context(patch.object(compact.ctk,'CTkFrame',side_effect=frame))
            stack.enter_context(patch.object(compact,'KeyboardButton',Widget))
            stack.enter_context(patch.object(compact.ctk,'CTkLabel',Widget))
            stack.enter_context(patch.object(layout,'_install_profile_group',side_effect=lambda:layout.add(root,'One','Help',[controls[0]])))
            stack.enter_context(patch.object(layout,'_install_image_group',side_effect=lambda:layout.add(root,'Two','Help',[controls[2]])))
            stack.enter_context(patch.object(ProfileIsolation,'install_compact_layout',side_effect=lambda *args:layout.install()))
            ProfileIsolation.register_controls(app,[(controls[0],'paint')])
        self.assertIsNone(app._compact_ui_layout)
        self.assertIn('shell layout failed',app._compact_ui_layout_error)
        self.assertEqual(root.order,controls)
        self.assertEqual(root.children,controls)
        self.assertTrue(all(shell.destroyed for shell in shells))
        self.assertEqual(layout.groups,[])
        self.assertIsNone(layout._lookup)

    def test_tree_lookup_preserves_preorder_and_scoped_matches_with_one_tk_read(self):
        root=Widget();left=Widget(root,text='section');right=Widget(root,text='section')
        a=Widget(left,text='Brush settings');nested=Widget(left);b=Widget(nested,text='Brush settings')
        c=Widget(right,text='Brush settings')
        index=compact._WidgetLookup(root)
        before={id(w):(w.text_reads,w.children_reads) for w in (root,left,right,a,nested,b,c)}
        for _ in range(20):
            self.assertIs(index.find(root,'Brush'),a)
            self.assertIs(index.find(left,'Brush'),a)
            self.assertIs(index.find(nested,'Brush'),b)
            self.assertIs(index.find(right,'Brush'),c)
            self.assertIsNone(index.find(left,'missing'))
        after={id(w):(w.text_reads,w.children_reads) for w in (root,left,right,a,nested,b,c)}
        self.assertEqual(before,after)
        for widget in (left,right,a,nested,b,c):self.assertEqual(widget.text_reads,1)
        for widget in (root,left,right,a,nested,b,c):self.assertEqual(widget.children_reads,1)

    def test_destroyed_profile_control_does_not_block_other_visibility_updates(self):
        root=Widget();paint=Widget(root);gartic=Widget(root);stale=Widget(root)
        for widget in (paint,gartic,stale):widget.pack(fill='x')
        app=SimpleNamespace()
        ProfileIsolation.register_controls(app,[(paint,'paint'),(gartic,'gartic'),(stale,'paint')])
        stale.destroy()
        ProfileIsolation.update_visibility(app,'gartic-phone')
        self.assertEqual(paint.manager,'')
        self.assertEqual(gartic.manager,'pack')
        self.assertEqual(app._profile_visibility_key,'gartic-phone')


class ScrollHarness:
    def __init__(self,widget,system='win32'):
        self.widget=widget;self.jobs={};self.bindings={};self.local={};self.serial=0;self.cancelled=[]
        self.root=SimpleNamespace(tk=SimpleNamespace(call=lambda *args:system),
            winfo_containing=lambda *args:self.widget,after=self.after,after_cancel=self.cancel,
            bind_all=lambda key,fn:self.bindings.__setitem__(key,fn),
            bind=lambda key,fn,**kwargs:self.local.__setitem__(key,fn))
        self.state=install_scrolling(self.root)
    def after(self,delay,callback):
        self.serial+=1;self.jobs[self.serial]=callback;return self.serial
    def cancel(self,token):self.cancelled.append(token);self.jobs.pop(token,None)
    def flush(self):
        jobs=list(self.jobs.values());self.jobs.clear()
        for callback in jobs:callback()
    def wheel(self,delta=-120):
        return self.bindings['<MouseWheel>'](SimpleNamespace(state=0,num=None,delta=delta,x_root=2,y_root=3))


def panel(increment='0'):
    canvas=Mock();canvas.yview.return_value=(0,.5);canvas.winfo_exists.return_value=True;canvas.cget.return_value=increment
    widget=SimpleNamespace(winfo_class=lambda:'Frame',_parent_canvas=canvas,master=None)
    return widget,canvas


class WheelRoutingTests(unittest.TestCase):
    def test_customtkinter_slider_keeps_its_wheel_without_also_scrolling_the_panel(self):
        parent,canvas=panel('1')
        for kind in (ctk.CTkSlider,ctk.CTkScrollbar,ctk.CTkTextbox):
            control=object.__new__(kind);control.master=parent;control.winfo_class=lambda:'Frame'
            leaf=SimpleNamespace(winfo_class=lambda:'Canvas',master=control)
            harness=ScrollHarness(leaf)
            self.assertIsNone(harness.wheel());self.assertEqual(harness.jobs,{})
        canvas.yview_scroll.assert_not_called()

    def test_windows_pixel_increment_preserves_twenty_pixels_per_wheel_notch(self):
        widget,canvas=panel('1');harness=ScrollHarness(widget)
        harness.wheel(-60);harness.flush();canvas.yview_scroll.assert_not_called()
        harness.wheel(-60);harness.flush();canvas.yview_scroll.assert_called_once_with(20,'units')
        canvas.yview_scroll.reset_mock()
        for _ in range(1000):harness.wheel()
        self.assertEqual(len(harness.jobs),1);harness.flush()
        canvas.yview_scroll.assert_called_once_with(240,'units')

    def test_generic_and_nonwindows_canvases_keep_their_original_scroll_units(self):
        for system,increment,delta in (('win32','0',-120),('x11','30',-120),('aqua','8',-1)):
            widget,canvas=panel(increment);harness=ScrollHarness(widget,system)
            harness.wheel(delta);harness.flush();canvas.yview_scroll.assert_called_once_with(1,'units')

    def test_switching_panels_within_one_frame_does_not_discard_the_first_wheel(self):
        first,a=panel();second,b=panel();harness=ScrollHarness(first)
        harness.wheel();harness.widget=second;harness.wheel()
        a.yview_scroll.assert_called_once_with(1,'units')
        b.yview_scroll.assert_not_called()
        harness.flush();b.yview_scroll.assert_called_once_with(1,'units')

    def test_reinstall_is_idempotent_and_root_close_cancels_pending_motion(self):
        widget,canvas=panel();harness=ScrollHarness(widget)
        self.assertIs(install_scrolling(harness.root),harness.state)
        harness.wheel();pending=list(harness.jobs.values())
        harness.local['<Destroy>'](SimpleNamespace(widget=widget))
        self.assertFalse(harness.state['closed'])
        harness.local['<Destroy>'](SimpleNamespace(widget=harness.root))
        self.assertTrue(harness.state['closed']);self.assertEqual(harness.cancelled,[1])
        for callback in pending:callback()
        self.assertIsNone(harness.wheel());canvas.yview_scroll.assert_not_called()

    def test_destroyed_widget_path_and_invalid_pixel_increment_do_not_escape_callback(self):
        dead=SimpleNamespace(winfo_class=Mock(side_effect=tk.TclError('destroyed')))
        self.assertIsNone(ScrollHarness(dead).wheel())
        self.assertIsNone(ScrollHarness('.old.widget').wheel())
        for increment in ('nan','inf','-1','1e-320','bad'):
            widget,canvas=panel(increment);harness=ScrollHarness(widget)
            harness.wheel();harness.flush();canvas.yview_scroll.assert_called_once_with(1,'units')


@unittest.skipUnless(sys.platform=='win32','Real CustomTkinter layout runs on Windows CI.')
class WindowsSidebarTests(unittest.TestCase):
    def test_real_profile_group_can_be_installed_opened_and_scoped(self):
        original_scale=ctk.ScalingTracker.widget_scaling
        ctk.set_widget_scaling(1.5)
        root=ctk.CTk();root.withdraw()
        try:
            parent=ctk.CTkFrame(root);parent.pack()
            game=tk.StringVar(root,value='Microsoft Paint')
            selector=ttk.Combobox(parent,textvariable=game);selector.pack()
            custom=ctk.CTkButton(parent,text='Custom app profile');custom.pack(padx=(12,6),pady=8)
            original_padding={key:custom.pack_info()[key] for key in ('padx','pady')}
            guide=ctk.CTkFrame(parent);guide.pack()
            ctk.CTkLabel(guide,text='Profile guide').pack()
            check=ctk.CTkSwitch(parent,text='Single-color sketch');check.pack()
            menu=ctk.CTkOptionMenu(parent,values=['Pencil','Brush']);menu.pack()
            label=ctk.CTkLabel(parent,text='Paint controls');label.pack()
            app=SimpleNamespace(root=root,game=game,profile_selector=selector,paint_check=check,
                                paint_tool_menu=menu,paint_tool_label=label)
            ProfileIsolation.register_controls(app,[(menu,'paint'),(label,'paint')])
            self.assertIsNone(app._compact_ui_layout_error)
            group=app._compact_ui_layout.groups[0]
            self.assertEqual(group.title,'Profile & ink options')
            self.assertEqual(custom.winfo_manager(),'')
            group.set_open(True)
            self.assertEqual(custom.winfo_manager(),'pack')
            self.assertEqual({key:custom.pack_info()[key] for key in ('padx','pady')},original_padding)
            self.assertEqual(menu.winfo_manager(),'pack')
            for _ in range(3):group.set_open(False);group.set_open(True)
            self.assertEqual({key:custom.pack_info()[key] for key in ('padx','pady')},original_padding)
            game.set('Gartic Phone');ProfileIsolation.update_visibility(app,'gartic-phone')
            self.assertEqual(menu.winfo_manager(),'')
            self.assertEqual(custom.winfo_manager(),'pack')
        finally:
            for token in root.tk.splitlist(root.tk.call('after','info')):root.after_cancel(token)
            root.destroy()
            ctk.set_widget_scaling(original_scale)


if __name__=='__main__':unittest.main()
