"""Settings selectors accept local keyboard input through the actual UI factory."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import tkinter as tk

import customtkinter as ctk

import StudioUI
from UiKeyboardNavigation import KeyboardOptionMenu


def event(symbol, state=0):
    return SimpleNamespace(keysym=symbol, state=state)


def selector_without_window():
    item=object.__new__(KeyboardOptionMenu)
    item._state='normal';item._values=['Safe','Balanced','Aggressive']
    item._current_value='Balanced';item._keyboard_closed=False
    item._close_on_next_click=False;item._text_label=Mock()
    item._variable=Mock();item._variable_callback_blocked=False;item._command=Mock()
    item._dropdown_menu=Mock();item._dropdown_menu.grab_current.return_value=None
    item.winfo_exists=Mock(return_value=True);item.winfo_ismapped=Mock(return_value=True)
    item.winfo_rootx=Mock(return_value=120);item.winfo_rooty=Mock(return_value=230)
    item.winfo_height=Mock(return_value=39);item.focus_get=Mock(return_value=item)
    item._keyboard_in_view=Mock(return_value=True)
    return item


def actual_menu_factory(app, replacement=None):
    # Execute the actual nested factory without constructing the unrelated app.
    tree=ast.parse(Path(StudioUI.__file__).read_text(encoding='utf-8'))
    build=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build_ui')
    functions=[n for n in build.body if isinstance(n,ast.FunctionDef) and n.name in ('control','menu')]
    namespace=dict(vars(StudioUI),a=app)
    if replacement is not None:namespace['KeyboardOptionMenu']=replacement
    exec(compile(ast.Module(body=functions,type_ignores=[]),StudioUI.__file__,'exec'),namespace)
    return namespace['menu']


class SelectorKeyboardTests(unittest.TestCase):
    def test_existing_setting_help_follows_logical_focus_and_cancels_on_blur(self):
        from test_v148_ui_batch07_keyboard import Scheduler
        item=selector_without_window();item._canvas=Mock()
        schedule=Scheduler()
        item.after=Mock(side_effect=lambda _delay,callback:schedule.after_idle(callback))
        item.after_cancel=schedule.after_cancel
        bound={}
        def bind(widget,sequence,callback,**kwargs):
            self.assertIs(widget,item);self.assertEqual(kwargs,{'add':'+'})
            bound[sequence]=callback
        with patch.object(tk.Misc,'bind',side_effect=bind):
            tip=StudioUI.ToolTip(item,'Choose the amount of fill.')
        self.assertEqual(set(bound),{'<FocusIn>','<FocusOut>'})
        bound['<FocusIn>']()
        item.after.assert_called_once_with(450,tip._show)
        self.assertEqual(len(schedule.pending),1)
        window=Mock();tip.window=window
        bound['<FocusOut>']()
        self.assertFalse(schedule.pending);window.destroy.assert_called_once_with()
        self.assertIsNone(tip.window)

    def test_arrows_home_end_update_variable_and_command_once_per_changed_value(self):
        item=selector_without_window()
        for key,value in (('Up','Safe'),('Up','Safe'),('End','Aggressive'),('Right','Aggressive'),
                          ('Left','Balanced'),('Home','Safe'),('Down','Balanced')):
            item._keyboard_key_press(event(key))
            self.assertEqual(item.get(),value)
        self.assertEqual([call.args[0] for call in item._command.call_args_list],
                         ['Safe','Aggressive','Balanced','Safe','Balanced'])
        self.assertEqual(item._variable.set.call_args_list,item._command.call_args_list)
        self.assertFalse(item._variable_callback_blocked)
        # Current values outside a newly reconfigured list enter at its edge.
        item._values=['CPU','Auto'];item._current_value='obsolete'
        item._keyboard_key_press(event('Down'));self.assertEqual(item.get(),'CPU')
        item._current_value='obsolete'
        item._keyboard_key_press(event('Up'));self.assertEqual(item.get(),'Auto')

    def test_live_state_focus_visibility_and_shortcut_modifiers_guard_selection(self):
        for changed in ('disabled','closed','unmapped','destroyed','unfocused','clipped','empty'):
            with self.subTest(state=changed):
                item=selector_without_window()
                if changed=='disabled':item._state='disabled'
                elif changed=='closed':item._keyboard_closed=True
                elif changed=='unmapped':item.winfo_ismapped.return_value=False
                elif changed=='destroyed':item.winfo_exists.return_value=False
                elif changed=='unfocused':item.focus_get.return_value=None
                elif changed=='clipped':item._keyboard_in_view.return_value=False
                elif changed=='empty':item._values=[]
                for key in ('Down','Home','End','Return','space','F4'):
                    item._keyboard_key_press(event(key))
                item._command.assert_not_called()
                item._dropdown_menu.tk_popup.assert_not_called()
                self.assertEqual(item.get(),'Balanced')
        item=selector_without_window()
        for mask in (4,8,128,0x20000):
            self.assertIsNone(item._keyboard_key_press(event('Right',mask)))
        self.assertIsNone(item._keyboard_key_press(event('Tab')))
        item._command.assert_not_called()

    def test_native_popup_entry_and_escape_leave_selection_unchanged(self):
        item=selector_without_window()
        for symbol,mask in (('Return',0),('KP_Enter',0),('space',0),('F4',0),('Down',8),('Down',0x20000)):
            item._keyboard_key_press(event(symbol,mask))
            item._dropdown_menu.tk_popup.assert_called_with(120,269,1)
            self.assertTrue(item._close_on_next_click)
            item._keyboard_key_press(event('Escape'))
            self.assertFalse(item._close_on_next_click)
        item._dropdown_menu.grab_current.return_value=item._dropdown_menu
        item._keyboard_close_popup()
        item._dropdown_menu.grab_release.assert_called_once()
        item._command.assert_not_called()
        self.assertEqual(item.get(),'Balanced')

    def test_pending_native_selection_rechecks_disabled_values_and_destroyed_state(self):
        for state in ('disabled','empty','changed','closed'):
            item=selector_without_window()
            if state=='disabled':item._state='disabled'
            elif state=='empty':item._values=[]
            elif state=='changed':item._values=['CPU','Auto']
            else:item._keyboard_closed=True
            item._dropdown_callback('Safe')
            item._command.assert_not_called()
            self.assertEqual(item.get(),'Balanced')
        item=selector_without_window()
        item._command=None
        item._dropdown_callback('Safe')
        item._variable.set.assert_called_once_with('Safe')

    def test_real_factory_registers_keyboard_selector_and_existing_command(self):
        app=SimpleNamespace(controls=[],options_changed=Mock())
        constructor=Mock(return_value=object())
        factory=actual_menu_factory(app,constructor)
        variable=object()
        widget=factory('parent',variable,('CPU','Auto'))
        self.assertEqual(app.controls,[(widget,'normal')])
        self.assertIs(constructor.call_args.kwargs['variable'],variable)
        self.assertEqual(constructor.call_args.kwargs['values'],['CPU','Auto'])
        constructor.call_args.kwargs['command']('Auto')
        app.options_changed.assert_called_once_with()
        command=Mock()
        factory('parent',variable,['Safe'],command=command)
        constructor.call_args.kwargs['command']('Safe')
        command.assert_called_once_with('Safe')


@unittest.skipUnless(sys.platform=='win32','Actual Windows Tk settings selector delivery')
class WindowsSelectorKeyboardTests(unittest.TestCase):
    def setUp(self):
        self.root=ctk.CTk();self.root.geometry('600x500+50+50')
        self.errors=[]
        self.root.report_callback_exception=lambda *error:self.errors.append(error)

    def tearDown(self):
        self.root.destroy()
        self.assertFalse(self.errors,self.errors)

    def press(self,item,symbol):
        item.event_generate('<KeyPress-'+symbol+'>',when='now')
        self.root.update()

    def test_actual_factory_tab_focus_variable_callback_and_live_configuration(self):
        app=SimpleNamespace(controls=[],options_changed=Mock())
        menu=actual_menu_factory(app)
        entry=ctk.CTkEntry(self.root);entry.pack()
        variable=ctk.StringVar(value='Balanced')
        first=menu(self.root,variable,['Safe','Balanced','Aggressive']);first.pack()
        StudioUI.tooltip(first,'Choose the amount of fill.')
        tip=first._image_draw_bot_tooltip;tip.delay=0
        disabled=menu(self.root,ctk.StringVar(value='Safe'),['Safe']);disabled.pack()
        disabled.configure(state='disabled')
        last=menu(self.root,ctk.StringVar(value='CPU'),['CPU','Auto']);last.pack()
        before=self.root.bind_all('<KeyPress>')
        self.root.update()
        # CTkEntry is a frame around its actual native text Entry. Start Tab
        # from the focused input, not from that decorative outer container.
        entry.focus_force();self.root.update()
        focused=self.root.focus_get()
        self.assertIs(focused,entry._entry)
        focused.event_generate('<Tab>',when='now');self.root.update()
        self.assertIs(self.root.focus_get(),first)
        self.assertIs(first.tk_focusNext(),last)
        self.assertIs(last.tk_focusPrev(),first)
        first.focus_force();self.root.update()
        self.assertEqual(len(first._canvas.find_withtag(first._focus_tag)),1)
        self.assertIsNotNone(tip.window)
        last.focus_force();self.root.update();self.assertIsNone(tip.window)
        first.focus_force();self.root.update()
        self.press(first,'Home');self.assertEqual(variable.get(),'Safe')
        self.press(first,'End');self.assertEqual(variable.get(),'Aggressive')
        self.press(first,'End');self.assertEqual(app.options_changed.call_count,2)
        first.configure(values=['CPU','Auto']);self.press(first,'Down')
        self.assertEqual(variable.get(),'CPU')
        with patch.object(first._dropdown_menu,'tk_popup') as popup:
            self.press(first,'Return');popup.assert_called_once()
            self.press(first,'Escape')
        first.configure(state='disabled');self.press(first,'End')
        self.assertEqual(variable.get(),'CPU')
        tokens=tuple(first._tclCommands or ())
        first.destroy();self.root.update()
        for token in tokens:self.assertFalse(self.root.tk.call('info','commands',token))
        self.assertEqual(self.root.bind_all('<KeyPress>'),before)

    def test_tab_reveals_a_selector_below_the_scroll_view(self):
        panel=ctk.CTkScrollableFrame(self.root,width=400,height=130);panel.pack()
        first=KeyboardOptionMenu(panel,values=['one','two']);first.pack()
        ctk.CTkFrame(panel,width=10,height=900).pack()
        variable=ctk.StringVar(value='one')
        last=KeyboardOptionMenu(panel,values=['one','two'],variable=variable);last.pack()
        self.root.update()
        self.assertFalse(last._keyboard_in_view())
        first.focus_force();self.root.update()
        first.event_generate('<Tab>',when='now');self.root.update()
        self.assertIs(self.root.focus_get(),last)
        self.assertTrue(last._keyboard_in_view())
        self.press(last,'Down');self.assertEqual(variable.get(),'two')


if __name__=='__main__':unittest.main()
