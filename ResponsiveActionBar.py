"""Keep essential controls visible and mirror overflow through existing buttons."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from ResponsiveRows import bind_widget_event


class ResponsiveActionBar:
    def __init__(self,parent,buttons,*,essential=(),promote_when_enabled=(),menu_text='More actions'):
        self.parent=parent;self.buttons=tuple(buttons);self.essential=tuple(essential)
        self.promoted=tuple(promote_when_enabled);self.visible=();self.overflow=()
        self.job=None;self.closed=False;self.signature=None
        self.menu_button=ttk.Menubutton(parent,text=menu_text,takefocus=True)
        self.menu=tk.Menu(self.menu_button,tearoff=False,postcommand=self.populate)
        self.menu_button.configure(menu=self.menu)
        bind_widget_event(parent,'<Configure>',self.schedule)
        bind_widget_event(parent,'<Destroy>',self.dispose)
        self.schedule()

    def populate(self):
        """Read live permissions at opening; invocation still uses the button gate."""
        self.menu.delete(0,'end')
        for button in self.overflow:
            self.menu.add_command(label=str(button.cget('text')),
                state='disabled' if button.cget('state')=='disabled' else 'normal',command=button.invoke)

    def schedule(self,event=None):
        if self.closed or (event is not None and event.widget is not self.parent):return
        if self.job is None:self.job=self.parent.after_idle(self.apply)

    def apply(self):
        self.job=None
        if self.closed:return
        width=self.parent.winfo_width()
        if width<=1:return
        getter=getattr(self.parent,'_get_widget_scaling',None)
        scale=float(getter()) if callable(getter) else 1.0
        if not math.isfinite(scale) or scale<=0:scale=1.0
        # Native ttk padding is already physical; CTk buttons scale grid kwargs.
        gap=math.ceil(6*scale)
        widths={id(button):button.winfo_reqwidth() for button in self.buttons}
        if sum(widths.values())+gap*len(self.buttons)<=width:
            visible=self.buttons;overflow=();items=visible;columns=len(items)
        else:
            visible=tuple(button for button in self.buttons if button in self.essential or
                          (button in self.promoted and button.cget('state')!='disabled'))
            overflow=tuple(button for button in self.buttons if button not in visible)
            items=(*visible,self.menu_button)
            item_widths=[widths.get(id(button),self.menu_button.winfo_reqwidth()) for button in items]
            columns=len(items) if sum(item_widths)+gap*len(items)<=width else max(1,int(width//(max(item_widths)+gap)))
        signature=(tuple(map(id,visible)),columns,tuple(widths.values()),scale)
        if signature==self.signature:return
        try:focus=self.parent.focus_get()
        except (tk.TclError,KeyError):focus=None
        hidden_focus=False;cursor=focus
        while cursor is not None:
            if cursor in overflow:hidden_focus=True;break
            cursor=getattr(cursor,'master',None)
        for button in (*self.buttons,self.menu_button):button.pack_forget();button.grid_forget()
        for column in range(len(self.buttons)+1):self.parent.grid_columnconfigure(column,weight=0,minsize=0)
        for index,button in enumerate(items):
            padding=3 if button is not self.menu_button else math.ceil(3*scale)
            button.grid(row=index//columns,column=index%columns,sticky='ew',padx=padding,pady=padding)
        self.visible=visible;self.overflow=overflow;self.signature=signature
        if hidden_focus:self.menu_button.focus_set()

    def dispose(self,event=None):
        if event is not None and event.widget is not self.parent:return
        if self.closed:return
        self.closed=True;job=self.job;self.job=None
        if job is not None:
            try:self.parent.after_cancel(job)
            except (tk.TclError,RuntimeError,ValueError):pass
