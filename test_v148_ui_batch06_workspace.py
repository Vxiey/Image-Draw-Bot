"""Responsive full-workspace layout, with native Windows controls and no input."""
from contextlib import ExitStack
from types import SimpleNamespace
import sys
import time
import tkinter as tk
import unittest
from unittest.mock import Mock,patch

from ResponsiveWorkspace import ResponsiveWorkspace,fit_label
from ResponsiveActionBar import ResponsiveActionBar
from ResponsiveRows import bind_widget_event


class Value:
    def __init__(self,*args,value=None,**kwargs):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


class Widget:
    def __init__(self,master=None,**kwargs):
        self.master=master;self.options=kwargs;self.width=900;self.request=200;self.scale=1
        self.children=[];self.layout=None;self.layouts=[];self.bindings={};self.columns={};self.rows={}
        self.jobs={};self.serial=0;self.focus=None
        if master is not None:master.children.append(self)
    def pack(self,**kwargs):self.layout=('pack',kwargs)
    def pack_forget(self):self.layout=None
    def grid(self,**kwargs):self.layout=('grid',kwargs);self.layouts.append(kwargs)
    def grid_forget(self):self.layout=None
    def grid_columnconfigure(self,column,**kwargs):self.columns.setdefault(column,{}).update(kwargs)
    def grid_rowconfigure(self,row,**kwargs):self.rows.setdefault(row,{}).update(kwargs)
    def winfo_width(self):return self.width
    def winfo_reqwidth(self):return self.request
    def _get_widget_scaling(self):return self.scale
    def focus_get(self):return self.focus
    def focus_set(self):self.focus=self
    def configure(self,**kwargs):self.options.update(kwargs)
    def cget(self,name):return self.options[name]
    def bind(self,name,callback,**kwargs):self.bindings[name]=callback
    def after_idle(self,callback):self.serial+=1;self.jobs[self.serial]=callback;return self.serial
    def after_cancel(self,job):self.jobs.pop(job,None)
    def flush(self):
        jobs=list(self.jobs.values());self.jobs.clear()
        for callback in jobs:callback()


class WorkspaceLayoutTests(unittest.TestCase):
    def create(self,stack,width=900,scale=1):
        stack.enter_context(patch('ResponsiveWorkspace.tk.StringVar',Value))
        for name in ('Frame','Label','Combobox'):stack.enter_context(patch('ResponsiveWorkspace.ttk.'+name,Widget))
        main=Widget();main.width=width;main.scale=scale
        panels={name:Widget(main) for name in ('Setup','Workspace','Readiness')}
        changed=Mock();layout=ResponsiveWorkspace(main,panels,on_change=changed);main.flush()
        return main,panels,layout,changed

    def test_compact_and_wide_layouts_reuse_every_panel_without_changing_control_state(self):
        with ExitStack() as stack:
            main,panels,layout,changed=self.create(stack)
            self.assertTrue(layout.compact)
            self.assertEqual([name for name,panel in panels.items() if panel.layout],['Setup'])
            self.assertTrue(all(value['minsize']==0 for value in main.columns.values()))
            layout.select('Readiness')
            self.assertEqual([name for name,panel in panels.items() if panel.layout],['Readiness'])
            main.width=1500;layout.schedule();main.flush()
            self.assertFalse(layout.compact);self.assertIsNone(layout.navigation.layout)
            self.assertEqual([panel.layout[1]['column'] for panel in panels.values()],[0,1,2])
            self.assertEqual([main.columns[n]['minsize'] for n in range(3)],[330,480,286])
            self.assertEqual(layout.selected,'Readiness')

    def test_shrink_preserves_the_panel_containing_focus_and_accounts_for_scaling(self):
        with ExitStack() as stack:
            main,panels,layout,_=self.create(stack,1800,1.5)
            self.assertFalse(layout.compact)
            main.focus=Widget(panels['Workspace']);main.width=1500;layout.schedule();main.flush()
            self.assertTrue(layout.compact);self.assertEqual(layout.selected,'Workspace')
            self.assertEqual([name for name,panel in panels.items() if panel.layout],['Workspace'])
            layout.select('Setup');self.assertIs(layout.selector.focus,layout.selector)

    def test_resize_burst_is_coalesced_and_disposal_cancels_pending_work(self):
        with ExitStack() as stack:
            main,panels,layout,changed=self.create(stack)
            previous=[len(panel.layouts) for panel in panels.values()]
            for _ in range(100):layout.schedule(SimpleNamespace(widget=main))
            self.assertEqual(len(main.jobs),1);main.flush()
            self.assertEqual([len(panel.layouts) for panel in panels.values()],previous)
            layout.schedule();self.assertEqual(len(main.jobs),1)
            layout.dispose(SimpleNamespace(widget=main));self.assertFalse(main.jobs)
            layout.schedule();self.assertFalse(main.jobs)

    def test_header_groups_reflow_without_sharing_a_wide_fixed_row(self):
        with ExitStack() as stack:
            _,_,layout,_=self.create(stack)
            header=Widget();header.width=800
            brand,info,actions=(Widget(header) for _ in range(3))
            brand.request=300;info.request=280
            buttons=[Widget(actions) for _ in range(4)]
            for button in buttons:button.request=120
            layout.header=header;layout.header_groups=(brand,info,actions);layout.header_actions=tuple(buttons)
            layout._layout_header(1)
            self.assertEqual(actions.layout[1]['row'],1)
            header.width=500;layout._layout_header(1)
            self.assertEqual(brand.layout[1]['row'],0);self.assertEqual(actions.layout[1]['row'],1)
            self.assertIsNone(info.layout)
            header.width=1300;layout._layout_header(1)
            self.assertEqual([group.layout[1]['row'] for group in layout.header_groups],[0,0,0])

    def test_wrapped_text_uses_logical_width_and_avoids_duplicate_configurations(self):
        label=Widget();label.scale=1.5;label.configure=Mock()
        fit_label(label,560)
        for _ in range(3):label.bindings['<Configure>'](SimpleNamespace(width=450))
        label.configure.assert_called_once_with(wraplength=300)

    def test_layout_binds_the_native_frame_instead_of_ctk_decorative_canvas(self):
        import customtkinter as ctk
        import tkinter as tk
        frame=object.__new__(ctk.CTkFrame);callback=Mock()
        with patch.object(ctk.CTkFrame,'bind',side_effect=AssertionError('decorative binding')),\
             patch.object(tk.Misc,'bind',return_value='token') as native:
            self.assertEqual(bind_widget_event(frame,'<Configure>',callback),'token')
        native.assert_called_once_with(frame,'<Configure>',callback,add='+')


class ActionButton(Widget):
    def __init__(self,parent,text,state='normal'):
        super().__init__(parent,text=text,state=state);self.request=150;self.command=Mock()
    def invoke(self):
        if self.options['state']!='disabled':return self.command()


class Menu:
    def __init__(self,*args,**kwargs):self.entries=[];self.postcommand=kwargs['postcommand']
    def delete(self,*args):self.entries.clear()
    def add_command(self,**kwargs):self.entries.append(kwargs)


class ActionBarTests(unittest.TestCase):
    def create(self,stack):
        stack.enter_context(patch('ResponsiveActionBar.ttk.Menubutton',Widget))
        stack.enter_context(patch('ResponsiveActionBar.tk.Menu',Menu))
        row=Widget();row.width=550
        buttons=tuple(ActionButton(row,name,'disabled' if name in ('Start','Unlock','Pause') else 'normal')
                      for name in ('Start','Unlock','Dry run','Stop','Pause'))
        bar=ResponsiveActionBar(row,buttons,essential=(buttons[0],buttons[3]),promote_when_enabled=(buttons[4],))
        row.flush()
        return row,buttons,bar

    def test_compact_actions_preserve_current_permissions_and_invoke_existing_button(self):
        with ExitStack() as stack:
            row,buttons,bar=self.create(stack)
            self.assertEqual(bar.visible,(buttons[0],buttons[3]))
            bar.populate();self.assertEqual([entry['label'] for entry in bar.menu.entries],['Unlock','Dry run','Pause'])
            self.assertEqual([entry['state'] for entry in bar.menu.entries],['disabled','normal','disabled'])
            buttons[1].configure(text='Unlock now',state='normal');bar.populate()
            self.assertEqual(bar.menu.entries[0]['label'],'Unlock now')
            self.assertEqual(bar.menu.entries[0]['state'],'normal')
            bar.menu.entries[0]['command']();buttons[1].command.assert_called_once()
            buttons[1].configure(state='disabled');bar.menu.entries[0]['command']()
            buttons[1].command.assert_called_once()
            buttons[0].command.assert_not_called();buttons[3].command.assert_not_called()

    def test_enabled_pause_is_promoted_and_hidden_button_focus_moves_to_menu(self):
        with ExitStack() as stack:
            row,buttons,bar=self.create(stack)
            row.width=1000;bar.schedule();row.flush();self.assertEqual(bar.visible,buttons)
            row.focus=Widget(buttons[1]);row.width=550;bar.schedule();row.flush()
            self.assertIs(bar.menu_button.focus,bar.menu_button)
            buttons[4].configure(state='normal',text='Resume · F6');bar.schedule();row.flush()
            self.assertEqual(bar.visible,(buttons[0],buttons[3],buttons[4]))
            self.assertEqual([button.cget('text') for button in bar.overflow],['Unlock','Dry run'])

    def test_action_bar_teardown_cancels_queued_layout_without_invoking_actions(self):
        with ExitStack() as stack:
            row,buttons,bar=self.create(stack)
            bar.schedule();self.assertEqual(len(row.jobs),1)
            bar.dispose(SimpleNamespace(widget=row));self.assertFalse(row.jobs)
            bar.schedule();self.assertFalse(row.jobs)
            self.assertTrue(all(button.command.call_count==0 for button in buttons))


@unittest.skipUnless(sys.platform=='win32','Actual complete Windows Tk workspace layout')
class WindowsCompleteWorkspaceTests(unittest.TestCase):
    def wait_for_native_layout(self, root, predicate, description):
        deadline=time.monotonic()+4
        while True:
            root.update()
            if predicate():return
            if time.monotonic()>=deadline:
                self.fail(description+'; actual geometry='+root.geometry()+
                          '; native min/max='+str((tk.Wm.wm_minsize(root),tk.Wm.wm_maxsize(root))))
            time.sleep(.01)

    def resize_native(self, root, app, width, height):
        # CTk._set_scaling temporarily locks the native window min/max to its
        # previous size and restores those limits after 1000 ms. An immediate
        # geometry()+update() can therefore test a different size than claimed.
        factor=root._get_window_scaling()
        expected=(round(width*factor),round(height*factor))
        def limits_allow_resize():
            low,high=tk.Wm.wm_minsize(root),tk.Wm.wm_maxsize(root)
            return all(lower<=value<=upper for lower,value,upper in zip(low,expected,high))
        self.wait_for_native_layout(root,limits_allow_resize,'CTk did not restore resize limits')
        root.geometry(f'{width}x{height}')
        def settled():
            return ((root.winfo_width(),root.winfo_height())==expected and
                    all(bar.job is None for bar in
                        (app.workspace_layout,app.draw_action_bar,app.help_action_bar)))
        self.wait_for_native_layout(root,settled,'The requested physical client size did not settle')
        self.assertEqual((root.winfo_width(),root.winfo_height()),expected)

    def layout_diagnostics(self, root, app, widget):
        def describe(item):
            return (str(item),item.winfo_manager(),item.winfo_ismapped(),
                    item.winfo_geometry(),(item.winfo_reqwidth(),item.winfo_reqheight()))
        ancestors=[];current=widget
        while current is not None:
            ancestors.append(describe(current));current=getattr(current,'master',None)
        return {'selected':app.workspace_layout.selected,'compact':app.workspace_layout.compact,
                'ancestors':ancestors,'root_packed':[describe(item) for item in root.pack_slaves()],
                'actions':[describe(item) for item in (*app.draw_action_bar.visible,app.draw_action_bar.menu_button)]}

    def test_actual_studio_keeps_start_stop_and_all_panels_inside_compact_windows(self):
        import customtkinter as ctk
        from DrawBot import DrawBotApp

        class NoInput:
            def add_hotkey(self,*args,**kwargs):return 1
            def remove_hotkey(self,*args):pass
            def get_position(self):return (0,0)

        errors=[]
        with ExitStack() as stack:
            for name in ('read_settings','refresh_runtime_safety_ui','refresh_auto_tuner_ui','refresh_palette',
                         'refresh_tool_calibration','refresh_app_tool_calibration','maybe_auto_hardware_benchmark',
                         'offer_safe_session_recovery','show_welcome','_schedule_recovery_checkpoint'):
                stack.enter_context(patch.object(DrawBotApp,name))
            stack.enter_context(patch.object(DrawBotApp,'save_settings',return_value=True))
            stack.enter_context(patch.object(DrawBotApp,'report_tk_callback_exception',side_effect=lambda *args:errors.append(args)))
            stack.enter_context(patch('DrawBot.previous_run_unclean',return_value=False))
            stack.enter_context(patch('ReleaseState.should_show_welcome',return_value=False))
            root=ctk.CTk()
            try:
                app=DrawBotApp(root,NoInput(),NoInput());root.minsize(500,400)
                root.update()
                def inside(widget):
                    if not widget.winfo_ismapped():self.fail(str(self.layout_diagnostics(root,app,widget)))
                    self.assertGreaterEqual(widget.winfo_rootx(),root.winfo_rootx())
                    self.assertGreaterEqual(widget.winfo_rooty(),root.winfo_rooty())
                    self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),root.winfo_rootx()+root.winfo_width()+1)
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),root.winfo_rooty()+root.winfo_height()+1)
                for scale,width,height in ((1,1024,700),(1,650,500),(1.5,1024,700),(1.5,650,500),(1,1560,960)):
                    ctk.set_widget_scaling(scale);self.resize_native(root,app,width,height)
                    with self.subTest(scale=scale,width=width,height=height):
                        inside(app.start);inside(app.stop_button)
                        bar=app.draw_action_bar
                        self.assertEqual(set(bar.visible)|set(bar.overflow),set(bar.buttons))
                        if bar.overflow:
                            inside(bar.menu_button);bar.populate()
                            self.assertEqual(bar.menu.index('end')+1,len(bar.overflow))
                            for index,button in enumerate(bar.overflow):
                                self.assertEqual(bar.menu.entrycget(index,'state'),button.cget('state'))
                        for button in bar.visible:inside(button)
                        app.pause_button.configure(state='normal',text='Resume · F6');bar.schedule();root.update()
                        inside(app.pause_button)
                        app.pause_button.configure(state='disabled');bar.schedule();root.update()
                        self.assertEqual(app.start.cget('state'),'disabled')
                        self.assertEqual(app.stop_button.cget('state'),'normal')
                        if app.workspace_layout.compact:
                            inside(app.workspace_layout.selector)
                            for name,panel in app.workspace_layout.panels.items():
                                app.workspace_layout.select(name);root.update()
                                outer=getattr(panel,'_parent_frame',panel)
                                inside(outer)
                                self.assertGreaterEqual(outer.winfo_height(),round(48*scale),
                                    str(self.layout_diagnostics(root,app,outer)))
                            app.show_tools();root.update()
                            self.assertEqual(app.workspace_layout.selected,'Workspace')
                self.assertFalse(errors,errors)
            finally:
                root.destroy();ctk.set_widget_scaling(1.0)


if __name__=='__main__':unittest.main()
