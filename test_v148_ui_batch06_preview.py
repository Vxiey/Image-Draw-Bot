"""Actual workspace callbacks, exact viewport parity and bounded UI layout."""
import ast
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
import sys
import tkinter as tk
import unittest
from unittest.mock import Mock,patch

import numpy as np
from PIL import Image

import PreviewNavigation as navigation
from PreviewQuality import viewport_image,viewport_geometry
import StudioUI
import ResponsiveRows
from PreviewDeck import PreviewDeck
import test_v148_ui_profiles_batch04 as state_fixtures


class Var:
    def __init__(self,value):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


def canvas(mapped=True,size=(66,66)):
    return SimpleNamespace(winfo_ismapped=lambda:mapped,winfo_exists=lambda:True,
        winfo_width=lambda:size[0],winfo_height=lambda:size[1],delete=Mock(),
        create_image=Mock(),create_oval=Mock(),create_line=Mock(),create_text=Mock())


def preview_callbacks(canvases,zoom=0):
    source=ast.parse(Path('StudioUI.py').read_text(encoding='utf-8'))
    names=('set_zoom','step_zoom','pan_start','pan_move')
    nodes=[next(n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name==name) for name in names]
    app=SimpleNamespace(preview_zoom=Var(zoom),schedule_previews=Mock())
    scope=dict(vars(navigation));scope.update(a=app,canvas=canvases[0],preview_canvases=canvases,zoom_text=Mock())
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'StudioUI.py','exec'),scope)
    for label in ('+','−'):
        node=next(n for n in ast.walk(source) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
                  and n.func.id=='button' and len(n.args)>2 and isinstance(n.args[1],ast.Constant) and n.args[1].value==label)
        scope[label]=eval(compile(ast.Expression(body=node.args[2]),'StudioUI.py','eval'),scope)
    return app,scope


class PreviewNavigationTests(unittest.TestCase):
    def test_plus_and_minus_step_from_actual_fit_scale_without_reversing_direction(self):
        for size,view in (((400,400),(400,400)),((100,100),(50,50)),((10000,10000),(100,100)),((2,2),(400,400))):
            for key in ('+','−'):
                with self.subTest(size=size,view=view,key=key):
                    c=canvas();navigation.record_viewport(c,size,view)
                    app,scope=preview_callbacks([c]);before=c._preview_scale
                    scope[key]()
                    after=viewport_geometry(size,view,app.preview_zoom.get()).scale
                    if key=='+':self.assertGreaterEqual(after,before)
                    else:self.assertLessEqual(after,before)
        c=canvas();navigation.record_viewport(c,(400,400),(400,400))
        app,scope=preview_callbacks([c]);scope['+']();self.assertEqual(app.preview_zoom.get(),1.25)

    def test_minus_at_minimum_explicit_zoom_does_not_jump_back_to_fit(self):
        c=canvas();navigation.record_viewport(c,(400,400),(400,400),.125)
        app,scope=preview_callbacks([c],.125);scope['−']()
        self.assertEqual(app.preview_zoom.get(),.125);app.schedule_previews.assert_not_called()

    def test_relative_zoom_uses_the_visible_page_instead_of_hidden_stale_scale(self):
        hidden=canvas(False);visible=canvas()
        navigation.record_viewport(hidden,(100,100),(50,50))
        navigation.record_viewport(visible,(400,400),(400,400))
        app,scope=preview_callbacks([hidden,visible]);scope['+']()
        self.assertEqual(app.preview_zoom.get(),1.25)

    def test_overscrolled_drag_reverses_immediately_even_within_same_gesture(self):
        c=canvas();navigation.record_viewport(c,(100,100),(50,50),1)
        app,scope=preview_callbacks([c],1)
        scope['pan_start'](SimpleNamespace(x=0,y=0))
        scope['pan_move'](SimpleNamespace(x=1000,y=1000))
        self.assertEqual(c._preview_pan,(-25.0,-25.0))
        scope['pan_move'](SimpleNamespace(x=980,y=980))
        self.assertEqual(c._preview_pan,(-5.0,-5.0))
        self.assertEqual(app.schedule_previews.call_count,2)

    def test_clamped_drag_does_not_schedule_unchanged_rasters_and_fit_recenters_every_page(self):
        first=canvas();other=canvas(False)
        for c in (first,other):navigation.record_viewport(c,(100,100),(50,50),1,(500,500))
        app,scope=preview_callbacks([first,other],1)
        scope['pan_start'](SimpleNamespace(x=0,y=0));scope['pan_move'](SimpleNamespace(x=-1000,y=-1000))
        app.schedule_previews.assert_not_called()
        scope['set_zoom'](0)
        for c in (first,other):self.assertEqual(c._preview_pan,(0.0,0.0));self.assertFalse(hasattr(c,'_drag'))

    def test_drawbot_renderer_records_effective_pan_and_releases_temporary_raster(self):
        from DrawBot import DrawBotApp
        source=Image.new('RGB',(100,100),'red');self.addCleanup(source.close)
        c=canvas();c._preview_pan=(-1000,0)
        app=SimpleNamespace(closing=False,original=source,plan=None,original_canvas=c,
            result_canvas=SimpleNamespace(winfo_exists=lambda:False),preview_zoom=Var(1))
        presented=[]
        with patch('PIL.ImageTk.PhotoImage',side_effect=lambda image:presented.append(image) or object()):
            DrawBotApp.show_previews(app)
        self.assertEqual(c._preview_pan,(-25.0,0.0));self.assertEqual(c._preview_image_size,(100,100))
        self.assertEqual(c._preview_viewport_size,(50,50));self.assertEqual(c._preview_scale,1)
        with self.assertRaises(ValueError):presented[0].getpixel((0,0))
        self.assertEqual(source.getpixel((0,0)),(255,0,0))
        app.original=None;DrawBotApp.show_previews(app)
        self.assertFalse(hasattr(c,'_preview_image_size'));self.assertFalse(hasattr(c,'_preview_scale'))
        self.assertEqual(c._preview_pan,(0.0,0.0))

    def test_geometry_refactor_preserves_the_baseline_raster_for_valid_views(self):
        # Independent scalar baseline formula; this checks the pixels as well
        # as rounding at narrow fractional source-box boundaries.
        rng=np.random.default_rng(19)
        source=Image.fromarray(rng.integers(0,256,(37,59,4),dtype=np.uint8),'RGBA')
        self.addCleanup(source.close)
        for view in ((31,23),(80,11),(1,1),(1,79)):
            for zoom in (0,.125,.375,1,2.25,8):
                for pan in ((0,0),(1000,-1000),(3.25,-2.75)):
                    w,h=view;iw,ih=source.size;scale=min(w/iw,h/ih) if zoom<=0 else max(.125,min(8,zoom))
                    sw,sh=min(iw,w/scale),min(ih,h/scale)
                    cx=min(iw-sw/2,max(sw/2,iw/2+pan[0]));cy=min(ih-sh/2,max(sh/2,ih/2+pan[1]))
                    target=(max(1,min(w,round(sw*scale))),max(1,min(h,round(sh*scale))))
                    with closing(source.resize(target,Image.Resampling.NEAREST if scale>=1 else Image.Resampling.LANCZOS,
                                               box=(cx-sw/2,cy-sh/2,cx+sw/2,cy+sh/2))) as part,\
                         closing(Image.new('RGBA',target,'white')) as background:
                        background.alpha_composite(part)
                        with closing(background.convert('RGB')) as expected:
                            actual,actual_scale=viewport_image(source,view,zoom,pan)
                            with closing(actual):
                                self.assertEqual(actual_scale,scale);self.assertEqual(actual.size,expected.size)
                                self.assertEqual(actual.tobytes(),expected.tobytes())


class PresentationTests(unittest.TestCase):
    def widgets(self,app,scope):
        return [scope[n] for n in ('top_state','profile_pill','profile_guide_icon','profile_guide_badge','profile_guide_tip',
            'profile_guide_recommend','image_info','plan_metrics','error_title','error_message','error_action')]+[
            app.palette_button,app.area_button,app.app_tool_button,*scope['step_headers'][3],*scope['step_dots'].values()]

    def test_progress_text_changes_do_not_rewrite_unchanged_presentation_or_cache_start_permission(self):
        app,scope=state_fixtures.studio_state_renderer(activity='draw')
        widgets=self.widgets(app,scope)
        scope['_apply_ui_state']();counts=[w.configure.call_count for w in widgets]
        for i in range(100):
            app.status.set(f'Drawing: {i}/1000 brush strokes');scope['_apply_ui_state']()
        self.assertEqual([w.configure.call_count for w in widgets],counts)
        self.assertEqual(app._safe_widget_configure.call_count,101)
        self.assertEqual(app._target_lock_valid.call_count,101)

    def test_changed_properties_are_written_and_failed_writes_remain_retryable(self):
        widget=Mock()
        self.assertTrue(StudioUI._configure_presentation(widget,text='A',fg_color='blue'))
        self.assertFalse(StudioUI._configure_presentation(widget,text='A',fg_color='blue'))
        self.assertTrue(StudioUI._configure_presentation(widget,text='B',fg_color='blue'))
        widget.configure.assert_called_with(text='B')
        widget.configure.side_effect=tk.TclError('temporarily unavailable')
        with self.assertRaises(tk.TclError):StudioUI._configure_presentation(widget,text='C')
        self.assertEqual(widget._studio_presentation_values['text'],'B')
        widget.configure.side_effect=None
        self.assertTrue(StudioUI._configure_presentation(widget,text='C'))


class Button:
    def __init__(self,width):
        self.width=width;self.manager='pack';self.positions=[];self.command=Mock()
    def winfo_manager(self):return self.manager
    def winfo_reqwidth(self):return self.width
    def pack_forget(self):self.manager=''
    def grid_forget(self):self.manager=''
    def grid(self,**kwargs):self.manager='grid';self.positions.append(kwargs)


class Row:
    def __init__(self,width,widths,scale=1):
        self.width=width;self.children=[Button(w) for w in widths];self.scale=scale
        self.bindings={};self.jobs={};self.serial=0
    def winfo_width(self):return self.width
    def winfo_children(self):return self.children
    def _get_widget_scaling(self):return self.scale
    def bind(self,name,callback,**kwargs):self.bindings[name]=callback
    def after_idle(self,callback):self.serial+=1;self.jobs[self.serial]=callback;return self.serial
    def after_cancel(self,token):self.jobs.pop(token,None)
    def flush(self):
        jobs=list(self.jobs.values());self.jobs.clear()
        for job in jobs:job()


class ResponsiveTests(unittest.TestCase):
    def test_uneven_buttons_and_scaled_padding_fit_common_columns(self):
        for scale in (1,1.5,2):
            row=Row(round(320*scale),[round(w*scale) for w in (100,200,200,100)],scale)
            with patch('customtkinter.CTkButton',Button):ResponsiveRows.wrap_action_rows(row,recursive=False)
            row.flush()
            self.assertEqual([b.positions[-1]['column'] for b in row.children],[0,0,0,0])
            row.width=round(420*scale);row.bindings['<Configure>'](SimpleNamespace(widget=row));row.flush()
            self.assertEqual([b.positions[-1]['column'] for b in row.children],[0,1,0,1])
            self.assertTrue(all(callable(b.command) for b in row.children))

    def test_resize_bursts_keep_one_idle_job_and_teardown_cancels_it(self):
        row=Row(400,[100]*9)
        with patch('customtkinter.CTkButton',Button):
            state=ResponsiveRows.wrap_action_rows(row,recursive=False)
            self.assertIs(ResponsiveRows.wrap_action_rows(row,recursive=False),state)
        for _ in range(100):row.bindings['<Configure>'](SimpleNamespace(widget=row))
        self.assertEqual(len(row.jobs),1);row.flush()
        self.assertEqual([b.positions[-1]['row'] for b in row.children],[0,0,0,1,1,1,2,2,2])
        row.bindings['<Configure>'](SimpleNamespace(widget=row));row.flush()
        self.assertTrue(all(len(b.positions)==1 for b in row.children))
        row.bindings['<Configure>'](SimpleNamespace(widget=row));self.assertEqual(len(row.jobs),1)
        row.bindings['<Destroy>'](SimpleNamespace(widget=row));self.assertFalse(row.jobs)
        row.bindings['<Configure>'](SimpleNamespace(widget=row));self.assertFalse(row.jobs)

    def test_preview_selection_notifies_only_actual_page_changes(self):
        deck=object.__new__(PreviewDeck);deck.pages={'Original':Mock(),'Safety map':Mock()}
        deck.current=Var('Original');deck._visible_name=None;deck._on_change=Mock()
        deck.set('Original');deck._on_change.assert_not_called()
        deck.current.set('Safety map');deck.set('Safety map');deck.set('Safety map')
        deck._on_change.assert_called_once_with()
        self.assertEqual(deck.get(),'Safety map')


@unittest.skipUnless(sys.platform=='win32','Actual Windows Tk/CTk layout')
class WindowsWorkspaceLayoutTests(unittest.TestCase):
    def test_all_preview_pages_remain_selectable_in_a_narrow_native_deck(self):
        import customtkinter as ctk
        root=ctk.CTk();root.geometry('420x340');changed=Mock()
        try:
            deck=PreviewDeck(root,command=changed);deck.pack(fill='both',expand=True)
            source=ast.parse(Path('StudioUI.py').read_text(encoding='utf-8'))
            assignment=next(n for n in ast.walk(source) if isinstance(n,ast.Assign)
                            and any(isinstance(t,ast.Name) and t.id=='preview_specs' for t in n.targets))
            names=[name for name,_ in ast.literal_eval(assignment.value)]
            for name in names:deck.add(name)
            root.update_idletasks()
            self.assertEqual(len(names),12);self.assertEqual(tuple(deck.selector['values']),tuple(names))
            self.assertGreater(deck.selector.winfo_width(),80)
            self.assertLessEqual(deck.selector.winfo_rootx()+deck.selector.winfo_width(),root.winfo_rootx()+root.winfo_width())
            for index,name in enumerate(names):
                deck.selector.current(index);deck.selector.event_generate('<<ComboboxSelected>>');root.update_idletasks()
                self.assertEqual(deck.get(),name)
                self.assertEqual([n for n,p in deck.pages.items() if p.winfo_ismapped()],[name])
            self.assertEqual(changed.call_count,11)
            self.assertTrue(int(deck.selector['takefocus']))
        finally:root.destroy()

    def test_nine_tool_actions_wrap_inside_the_native_row_at_both_scales(self):
        import customtkinter as ctk
        for scale in (1.0,1.5):
            root=ctk.CTk();root.geometry('430x400')
            try:
                ctk.set_widget_scaling(scale)
                row=ctk.CTkFrame(root);row.pack(fill='x',padx=8)
                buttons=[ctk.CTkButton(row,text=f'Tool {i}',width=width) for i,width in enumerate((105,112,115,112,112,96,112,118,105))]
                for button in buttons:button.pack(side='left')
                ResponsiveRows.wrap_action_rows(row,recursive=False);root.update_idletasks()
                self.assertGreater(len({button.grid_info()['row'] for button in buttons}),1)
                right=row.winfo_rootx()+row.winfo_width()
                self.assertTrue(all(button.winfo_ismapped() and button.winfo_rootx()+button.winfo_width()<=right for button in buttons))
            finally:
                root.destroy();ctk.set_widget_scaling(1.0)


if __name__=='__main__':unittest.main()
