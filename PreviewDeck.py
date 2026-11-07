"""Preview pages selected by one compact, keyboard-accessible native menu."""
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

class PreviewDeck(ctk.CTkFrame):
    def __init__(self,parent,command=None,**kwargs):
        super().__init__(parent,**kwargs)
        self._on_change=command
        self.pages={};self.current=tk.StringVar(value='Original');self._visible_name=None
        toolbar=ctk.CTkFrame(self,fg_color='transparent')
        toolbar.pack(fill='x',padx=8,pady=(6,4))
        ctk.CTkLabel(toolbar,text='Preview view',width=88,anchor='w').pack(side='left',padx=(0,8))
        self.selector=ttk.Combobox(toolbar,textvariable=self.current,values=['Original'],
            state='readonly',width=24,style='ImageDrawBot.TCombobox',takefocus=True)
        self.selector.pack(side='left',fill='x',expand=True)
        self.selector.bind('<<ComboboxSelected>>',lambda _event:self.set(self.current.get()))
        self.host=ctk.CTkFrame(self,fg_color='transparent')
        self.host.pack(fill='both',expand=True)
    def add(self,name):
        if not isinstance(name,str) or not name.strip() or name in self.pages:
            raise ValueError('A preview page needs a unique non-empty name.')
        page=ctk.CTkFrame(self.host,fg_color='transparent')
        previous=self._visible_name
        previous_value=self.current.get()
        self.pages[name]=page
        try:
            self.selector.configure(values=list(self.pages))
            if len(self.pages)==1:self.set(name)
        except Exception:
            self.pages.pop(name,None)
            self._visible_name=previous
            try:self.selector.configure(values=list(self.pages) or ['Original'])
            except Exception:pass
            try:self.current.set(previous_value)
            except Exception:pass
            try:page.destroy()
            except Exception:pass
            raise
        return page
    def set(self,name):
        if name not in self.pages:raise ValueError(name)
        # The native menu updates its StringVar before invoking this callback,
        # so visible-page identity must be tracked separately from that value.
        changed=name!=self._visible_name
        initialized=self._visible_name is not None
        if name != self._visible_name:
            previous=self.pages.get(self._visible_name)
            try:
                self.pages[name].pack(fill='both',expand=True)
            except Exception:
                if self._visible_name is not None:
                    try:self.current.set(self._visible_name)
                    except tk.TclError:pass
                raise
            if previous is not None:
                try:previous.pack_forget()
                except tk.TclError:pass
            self._visible_name=name
        self.current.set(name)
        callback=getattr(self,'_on_change',None)
        if changed and initialized and callable(callback):callback()
    def get(self):return self.current.get()
