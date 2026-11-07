"""Scrollable ttk calibration forms with persistent actions and local input."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from SmoothScroll import ScrollAccumulator


class CalibrationDialogLayout(ttk.Frame):
    def __init__(self,parent,*,style='TFrame',background='#151d29'):
        super().__init__(parent,style=style)
        self._closed=False;self._focus_job=None;self._focus_target=None;self._bindings=[]
        self._wheel_delta=ScrollAccumulator()
        self.footer=ttk.Frame(self,style=style,padding=(16,8,16,12))
        self.footer.pack(side='bottom',fill='x')
        host=ttk.Frame(self,style=style);host.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(host,highlightthickness=0,borderwidth=0,background=background,yscrollincrement=20,takefocus=True)
        scrollbar=ttk.Scrollbar(host,orient='vertical',command=self.canvas.yview)
        scrollbar.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.body=ttk.Frame(self.canvas,style=style,padding=16)
        self._body_window=self.canvas.create_window((0,0),window=self.body,anchor='nw')
        self.body.bind('<Configure>',self._content_changed)
        self.canvas.bind('<Configure>',self._viewport_changed)
        self.canvas.bind('<Next>',lambda _event:self._scroll_page(1))
        self.canvas.bind('<Prior>',lambda _event:self._scroll_page(-1))
        self.canvas.bind('<Home>',lambda _event:self._scroll_to(0))
        self.canvas.bind('<End>',lambda _event:self._scroll_to(1))
        self._owner=self.winfo_toplevel()
        for sequence,callback in (('<MouseWheel>',self._wheel),('<Button-4>',self._wheel),
                                  ('<Button-5>',self._wheel),('<FocusIn>',self._focus_changed)):
            token=self._owner.bind(sequence,callback,add='+')
            self._bindings.append((sequence,token))
        self.bind('<Destroy>',self._dispose,add='+')

    def label(self,parent=None,**kwargs):
        widget=ttk.Label(self.body if parent is None else parent,**kwargs)
        limit=kwargs.get('wraplength')
        if limit:
            previous=[None]
            def resized(event):
                width=min(int(limit),max(1,event.width))
                if width!=previous[0]:
                    widget.configure(wraplength=width);previous[0]=width
            widget.bind('<Configure>',resized)
        return widget

    def _content_changed(self,_event=None):
        if not self._closed:self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def _viewport_changed(self,event):
        if not self._closed:self.canvas.itemconfigure(self._body_window,width=max(1,event.width))

    def _widget(self,widget):
        if isinstance(widget,str):
            try:widget=self._owner.nametowidget(widget)
            except (KeyError,tk.TclError):return None
        return widget

    def _inside(self,widget):
        widget=self._widget(widget)
        while widget is not None:
            if widget is self.body or widget is self.canvas:return True
            widget=getattr(widget,'master',None)
        return False

    def _wheel(self,event):
        widget=self._widget(event.widget)
        if self._closed or not self._inside(widget) or (getattr(event,'state',0) or 0)&5:return None
        try:
            if widget.winfo_class() in ('Treeview','TCombobox','Text','Listbox','Spinbox','TSpinbox','TScrollbar'):return None
            number=getattr(event,'num',None)
            if number in (4,5):steps=-1 if number==4 else 1
            else:
                delta=float(getattr(event,'delta',0) or 0)
                if not delta:return None
                divisor=1 if self.tk.call('tk','windowingsystem')=='aqua' else 120
                steps=-delta/divisor
            if not self._wheel_delta.add(steps):return None
            units=self._wheel_delta.take()
            if units:self.canvas.yview_scroll(units,'units')
            return 'break'
        except (tk.TclError,AttributeError,ValueError,TypeError,OverflowError):return None

    def _scroll_page(self,direction):
        if not self._closed:self.canvas.yview_scroll(direction,'pages')
        return 'break'

    def _scroll_to(self,fraction):
        if not self._closed:self.canvas.yview_moveto(fraction)
        return 'break'

    def _focus_changed(self,event):
        if self._closed or not self._inside(event.widget) or event.widget is self.canvas:return
        self._focus_target=self._widget(event.widget)
        if self._focus_job is None:self._focus_job=self.after_idle(self._reveal_focus)

    def _reveal_focus(self):
        self._focus_job=None;widget=self._focus_target;self._focus_target=None
        if self._closed:return
        try:
            top=widget.winfo_rooty()-self.body.winfo_rooty();bottom=top+widget.winfo_height()
            visible_top=self.canvas.canvasy(0);height=self.canvas.winfo_height()
            if top<visible_top:self.canvas.yview_moveto(max(0,top)/max(1,self.body.winfo_height()))
            elif bottom>visible_top+height:self.canvas.yview_moveto(max(0,bottom-height)/max(1,self.body.winfo_height()))
        except (tk.TclError,AttributeError):pass

    def _dispose(self,event=None):
        if event is not None and event.widget is not self:return
        if self._closed:return
        self._closed=True;self._focus_target=None
        job=self._focus_job;self._focus_job=None
        if job is not None:
            try:self.after_cancel(job)
            except (tk.TclError,RuntimeError,ValueError):pass
        for sequence,token in self._bindings:
            if token is not None:
                try:self._owner.unbind(sequence,token)
                except (tk.TclError,RuntimeError):pass
        self._bindings=[]
