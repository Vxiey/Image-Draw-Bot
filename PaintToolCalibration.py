"""Calibration window for Microsoft Paint tools and 100% opacity."""
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

from StudioUI import button, BG, PANEL, FIELD, TEXT
from PaintTools import TOOL_FILE, load_tool_calibration, save_tool_calibration
from CalibrationAnchors import make_anchor, ensure_same_layout
from CalibrationValidation import screen_point, point_in_rect


class PaintToolCalibrationApp:
    def __init__(self, root, on_close=None, path=TOOL_FILE):
        from WindowsMouse import WindowsMouse
        self.root,self.on_close,self.path=root,on_close,path
        self.mouse=WindowsMouse()  # DISARMED; get_position() only
        self.positions={};self.brush_menu=None;self.brush_preset=None;self.opacity_100=None
        self.anchor=None;self.anchor_handle=None;self.job=None;self.closed=False
        try:
            data=load_tool_calibration(path)
            if data.get('version') in (2,3):
                self.positions={name:tuple(pos) for name,pos in data.get('tools',{}).items()}
                self.brush_menu=tuple(data['brush_menu']) if data.get('brush_menu') else None
                self.brush_preset=tuple(data['brush_preset']) if data.get('brush_preset') else None
                self.opacity_100=tuple(data['opacity_100']) if data.get('opacity_100') else None
                self.anchor=data.get('anchor')
        except (OSError,ValueError):pass

        root.title('Image Draw Bot · Calibrate Paint tools');root.geometry('680x760');root.minsize(590,620)
        try:root.configure(fg_color=BG)
        except Exception:root.configure(bg=BG)
        from UiCompatibility import scoped_scrollable_frame
        body=scoped_scrollable_frame(root,fg_color=PANEL,corner_radius=18);body.pack(fill='both',expand=True,padx=16,pady=16)
        ttk.Label(body,text='Calibrate Microsoft Paint tools',font=('Segoe UI',18,'bold')).pack(anchor='w')
        ttk.Label(body,text='No clicks are generated while calibrating. During each countdown, switch to Paint and hover over the requested control.',wraplength=560).pack(anchor='w',pady=(6,12))
        self.status=tk.StringVar(value='Recommended setup: capture Pencil. Pencil is opaque and does not use the Brush opacity control. Capture 100% opacity only if you want Auto/Brush to use a brush preset. Keep Paint at the same window size while calibrating and drawing.')
        self.labels={};self.remove_buttons={}
        rows=[('Pencil','Pencil button'),('Eraser','Eraser button'),('Fill','Fill bucket button'),('brush_menu','Brushes menu button'),('brush_preset','one concrete Brush preset')]
        for key,title in rows:
            row=ctk.CTkFrame(body,fg_color=FIELD,corner_radius=12);row.pack(fill='x',pady=6)
            ctk.CTkLabel(row,text=title,text_color=TEXT,font=('Segoe UI',13,'bold')).pack(side='left',padx=14,pady=14)
            label=ctk.CTkLabel(row,text='',text_color='#a6b2c5');label.pack(side='left',padx=8);self.labels[key]=label
            button(row,text='Capture position',command=lambda n=key:self.capture(n,3),width=145,height=38).pack(side='right',padx=12,pady=10)
            remove=button(row,text='Remove',command=lambda n=key:self.remove_control(n),width=76,height=38)
            remove.pack(side='right',pady=10);self.remove_buttons[key]=remove
        ttk.Label(body,text='Brush is two-step: capture the Brushes dropdown button, then during the Brush preset countdown open that menu in Paint and hover over the exact solid brush preset you want Image Draw Bot to use.',wraplength=560).pack(anchor='w',pady=(4,10))
        row=ctk.CTkFrame(body,fg_color=FIELD,corner_radius=12);row.pack(fill='x',pady=(12,6))
        ctk.CTkLabel(row,text='100% opacity point',text_color=TEXT,font=('Segoe UI',13,'bold')).pack(side='left',padx=14,pady=14)
        self.opacity_label=ctk.CTkLabel(row,text='',text_color='#a6b2c5');self.opacity_label.pack(side='left',padx=8)
        button(row,text='Capture position',command=lambda:self.capture('opacity_100',3),width=145,height=38).pack(side='right',padx=12,pady=10)
        remove=button(row,text='Remove',command=lambda:self.remove_control('opacity_100'),width=76,height=38)
        remove.pack(side='right',pady=10);self.remove_buttons['opacity_100']=remove
        ttk.Label(body,text='For Brush only: select the brush preset in Paint, then hover over the 100% end of the opacity control. Pencil does not use this calibration because it is already opaque. Auto prefers Pencil when available.',wraplength=560).pack(anchor='w',pady=(6,10))
        ttk.Label(body,textvariable=self.status,wraplength=560).pack(anchor='w',pady=10)
        actions=ctk.CTkFrame(body,fg_color='transparent');actions.pack(fill='x',pady=(8,0))
        button(actions,text='Save calibration',command=self.save,primary=True).pack(side='left')
        button(actions,text='Start new calibration',command=self.reset_controls).pack(side='left',padx=8)
        button(actions,text='Close',command=self.close).pack(side='right')
        root.protocol('WM_DELETE_WINDOW',self.close);self.refresh()

    def refresh(self):
        values={'Pencil':self.positions.get('Pencil'),'Eraser':self.positions.get('Eraser'),'Fill':self.positions.get('Fill'),
                'brush_menu':self.brush_menu,'brush_preset':self.brush_preset}
        for name,label in self.labels.items():label.configure(text=f'✓ {values[name]}' if values[name] else 'Not captured')
        self.opacity_label.configure(text=f'✓ {self.opacity_100}' if self.opacity_100 else 'Required for Brush only')
        values['opacity_100']=self.opacity_100
        for name,control in getattr(self,'remove_buttons',{}).items():
            control.configure(state='normal' if values[name] is not None and self.job is None else 'disabled')

    def remove_control(self,name):
        if getattr(self,'closed',False) or self.job is not None:return False
        if name in ('Pencil','Eraser','Fill'):
            if name not in self.positions:return False
            del self.positions[name]
        elif name in ('brush_menu','brush_preset','opacity_100'):
            if getattr(self,name) is None:return False
            setattr(self,name,None)
        else:raise ValueError('Unknown Paint control.')
        self.status.set(f'Removed {name.replace("_"," ")}. Save calibration to keep this change.')
        self.refresh();return True

    def reset_controls(self):
        if getattr(self,'closed',False) or self.job is not None:return False
        self.positions={};self.brush_menu=None;self.brush_preset=None;self.opacity_100=None
        self.anchor=None;self.anchor_handle=None
        self.status.set('New calibration: capture the Paint tools you want to use, then save. Pencil is the recommended starting point.')
        self.refresh();return True

    def capture(self,name,seconds):
        if getattr(self,'closed',False) or self.job is not None:return
        if getattr(self,'capture_visibility',None) is None:
            from ScreenTaskWindow import ScreenTaskWindow
            self.capture_visibility=ScreenTaskWindow(self.root)
            self.capture_visibility.hide()
        if seconds:
            friendly={'brush_menu':'Brushes menu button','brush_preset':'Brush preset','opacity_100':'100% opacity point'}.get(name,f'{name} button')
            self.status.set(f'Switch to Paint and hover over the {friendly}. Capturing in {seconds}… Do not click.')
            self.job=self.root.after(1000,lambda:self._capture_tick(name,seconds-1));return
        self._capture_now(name)

    def _capture_tick(self,name,seconds):
        self.job=None
        if getattr(self,'closed',False):return
        if seconds:self.capture(name,seconds)
        else:self._capture_now(name)

    def _capture_now(self,name):
        if getattr(self,'closed',False):return
        try:
            if name not in ('Pencil','Eraser','Fill','opacity_100','brush_menu','brush_preset'):raise ValueError('Unknown Paint control.')
            point=screen_point(self.mouse.get_position())
            from TargetCapture import capture_target_metadata_isolated
            x,y=point;meta=capture_target_metadata_isolated((x-5,y-5,10,10))
            if not point_in_rect(point,meta['client_rect']):raise ValueError('The control is outside the Paint client area.')
            if self.anchor_handle is not None and meta['handle']!=self.anchor_handle:
                raise ValueError('All tool positions must be captured from the same Paint window.')
            if self.anchor is None:
                anchor=make_anchor(meta['client_rect']);stored=point
            else:
                anchor=self.anchor
                dx,dy=ensure_same_layout(self.anchor,meta['client_rect'])
                # Store every point in the first capture's coordinate frame, so
                # moving Paint during calibration does not corrupt earlier points.
                stored=screen_point((point[0]-dx,point[1]-dy))
            self.anchor_handle=meta['handle'];self.anchor=anchor
            if name=='opacity_100':self.opacity_100=stored
            elif name=='brush_menu':self.brush_menu=stored
            elif name=='brush_preset':self.brush_preset=stored
            else:self.positions[name]=stored
            self.status.set(f'Captured {name.replace("_"," ")} at {point}.')
        except (OSError,AttributeError,ValueError) as error:self.status.set(str(error))
        finally:
            visibility=getattr(self,'capture_visibility',None)
            if visibility is not None:visibility.restore()
            self.capture_visibility=None
        self.refresh()

    def save(self):
        if getattr(self,'closed',False) or self.job is not None:return
        try:
            if self.anchor is None:raise ValueError('Capture at least one Paint control first.')
            if not self.positions and not (self.brush_menu or self.brush_preset):raise ValueError('Capture at least one Paint tool.')
            save_tool_calibration(self.positions,self.opacity_100,self.path,anchor=self.anchor,
                                  brush_menu=self.brush_menu,brush_preset=self.brush_preset)
            self.status.set('Paint tool calibration saved.')
        except (OSError,ValueError) as error:self.status.set(f'Could not save: {error}')

    def close(self):
        if getattr(self,'closed',False) or getattr(self,'_closing',False):return
        self._closing=True
        try:
            if self.job is not None:
                try:self.root.after_cancel(self.job)
                except tk.TclError:pass
                self.job=None
            # Native teardown can fail or reenter Close. Keep retry available
            # until the window is gone, and deliver completion only once.
            self.closed=True
            try:self.root.destroy()
            except BaseException:
                self.closed=False
                raise
            finally:
                # The cancelled countdown no longer owns restoring this window.
                # A failed destroy must leave its Close action visible for retry.
                visibility=getattr(self,'capture_visibility',None)
                self.capture_visibility=None
                if visibility is not None:visibility.restore()
            if self.on_close:self.on_close()
        finally:self._closing=False
