"""Responsive presentation of the same workspace controls and native pages."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from ResponsiveRows import bind_widget_event


def fit_label(widget,maximum):
    """Keep a wrapped CTk label inside its allocated physical width."""
    last=[None]
    def resized(event):
        getter=getattr(widget,'_get_widget_scaling',None)
        scale=float(getter()) if callable(getter) else 1.0
        if not math.isfinite(scale) or scale<=0:scale=1.0
        width=max(1,min(maximum,int(event.width/scale)))
        if width!=last[0]:widget.configure(wraplength=width);last[0]=width
    bind_widget_event(widget,'<Configure>',resized)
    return widget


class ResponsiveWorkspace:
    def __init__(self,main,panels,*,header=None,header_groups=(),header_actions=(),on_change=None):
        self.main=main;self.panels=dict(panels);self.header=header
        self.header_groups=tuple(header_groups);self.header_actions=tuple(header_actions)
        self.on_change=on_change;self.closed=False;self.job=None
        self.compact=None;self._signature=None;self._header_signature=None
        self.selected=next(iter(self.panels));self.variable=tk.StringVar(master=main,value=self.selected)
        self.navigation=ttk.Frame(main,style='TFrame')
        ttk.Label(self.navigation,text='Workspace panel').pack(side='left',padx=(0,8))
        self.selector=ttk.Combobox(self.navigation,textvariable=self.variable,values=tuple(self.panels),
            state='readonly',takefocus=True,style='ImageDrawBot.TCombobox',width=24)
        self.selector.pack(side='left',fill='x',expand=True)
        self.selector.bind('<<ComboboxSelected>>',lambda _event:self.select(self.variable.get()))
        bind_widget_event(main,'<Configure>',self.schedule)
        bind_widget_event(main,'<Destroy>',self.dispose)
        if header is not None:bind_widget_event(header,'<Configure>',self.schedule)
        self.schedule()

    def _scale(self):
        getter=getattr(self.main,'_get_widget_scaling',None)
        value=float(getter()) if callable(getter) else 1.0
        return value if math.isfinite(value) and value>0 else 1.0

    def _focused_panel(self):
        try:widget=self.main.focus_get()
        except (tk.TclError,KeyError):return None
        while widget is not None:
            for name,panel in self.panels.items():
                if widget is panel:return name
            widget=getattr(widget,'master',None)
        return None

    def select(self,name):
        if name not in self.panels:raise ValueError('Unknown workspace panel.')
        if self.closed:return
        changed=name!=self.selected
        focus=self._focused_panel()
        self.selected=name
        if self.variable.get()!=name:self.variable.set(name)
        if self.compact and changed:
            for panel in self.panels.values():panel.grid_forget()
            self.panels[name].grid(row=1,column=0,columnspan=3,sticky='nsew')
            if focus is not None and focus!=name:self.selector.focus_set()
            if callable(self.on_change):self.on_change()

    def schedule(self,event=None):
        if self.closed or (event is not None and event.widget not in (self.main,self.header)):return
        if self.job is None:self.job=self.main.after_idle(self.apply)

    def _layout_header(self,scale):
        if self.header is None or len(self.header_groups)!=3:return
        width=self.header.winfo_width()
        if width<=1:return
        brand,info,actions=self.header_groups
        brand_width=brand.winfo_reqwidth();info_width=info.winfo_reqwidth()
        actions_width=sum(widget.winfo_reqwidth()+math.ceil(6*scale) for widget in self.header_actions)
        mode=0 if width>=brand_width+info_width+actions_width+math.ceil(24*scale) else (
            1 if width>=brand_width+info_width+math.ceil(12*scale) else 2)
        signature=(mode,scale)
        if signature==self._header_signature:return
        for group in self.header_groups:group.pack_forget();group.grid_forget()
        for column in range(3):self.header.grid_columnconfigure(column,weight=0,minsize=0)
        if mode==0:
            self.header.grid_columnconfigure(2,weight=1)
            brand.grid(row=0,column=0,sticky='w')
            info.grid(row=0,column=1,sticky='w',padx=8)
            actions.grid(row=0,column=2,sticky='ew',padx=(8,0))
        elif mode==1:
            self.header.grid_columnconfigure(1,weight=1)
            brand.grid(row=0,column=0,sticky='w')
            info.grid(row=0,column=1,sticky='e')
            actions.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(4,0))
        else:
            self.header.grid_columnconfigure(0,weight=1)
            # These badges repeat the profile selector, readiness panel and
            # footer status. Keep the actionable header reachable on low/narrow
            # screens instead of spending another row on duplicate summaries.
            for row,group in enumerate((brand,actions)):
                group.grid(row=row,column=0,sticky='ew',pady=(0,4) if row<2 else 0)
        self._header_signature=signature

    def apply(self):
        self.job=None
        if self.closed:return
        width=self.main.winfo_width()
        if width<=1:return
        scale=self._scale();self._layout_header(scale)
        compact=width<math.ceil(1120*scale)
        signature=(compact,scale)
        if signature==self._signature:return
        focus=self._focused_panel()
        if compact and focus is not None:
            self.selected=focus;self.variable.set(focus)
        for panel in self.panels.values():panel.grid_forget()
        for column in range(3):self.main.grid_columnconfigure(column,weight=0,minsize=0)
        self.main.grid_rowconfigure(0,weight=0,minsize=0)
        self.main.grid_rowconfigure(1,weight=1,minsize=0)
        if compact:
            self.main.grid_columnconfigure(0,weight=1)
            self.navigation.grid(row=0,column=0,columnspan=3,sticky='ew',pady=(0,8))
            self.panels[self.selected].grid(row=1,column=0,columnspan=3,sticky='nsew')
        else:
            self.navigation.grid_forget()
            for column,(panel,minimum) in enumerate(zip(self.panels.values(),(330,480,286))):
                self.main.grid_columnconfigure(column,weight=1 if column==1 else 0,minsize=math.ceil(minimum*scale))
                panel.grid(row=1,column=column,sticky='nsew',padx=(0,12) if column<2 else 0)
        self.compact=compact;self._signature=signature
        if callable(self.on_change):self.on_change()

    def dispose(self,event=None):
        if event is not None and event.widget is not self.main:return
        if self.closed:return
        self.closed=True;job=self.job;self.job=None
        if job is not None:
            try:self.main.after_cancel(job)
            except (tk.TclError,RuntimeError,ValueError):pass
