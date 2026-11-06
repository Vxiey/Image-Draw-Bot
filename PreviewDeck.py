"""Preview pages selected by a compact menu instead of nine wide tabs."""
import tkinter as tk
import customtkinter as ctk

class PreviewDeck(ctk.CTkFrame):
    def __init__(self,parent,**kwargs):
        super().__init__(parent,**kwargs)
        self.pages={};self.current=tk.StringVar(value='Original');self._visible_name=None
        self.selector=ctk.CTkOptionMenu(self,variable=self.current,values=['Original'],
            command=self.set,dynamic_resizing=False,width=210,height=32,fg_color='#283548',button_color='#354966')
        self.selector.pack(anchor='w',padx=8,pady=(6,4))
        self.host=ctk.CTkFrame(self,fg_color='transparent')
        self.host.pack(fill='both',expand=True)
    def add(self,name):
        if not isinstance(name,str) or not name.strip() or name in self.pages:
            raise ValueError('A preview page needs a unique non-empty name.')
        page=ctk.CTkFrame(self.host,fg_color='transparent')
        self.pages[name]=page;self.selector.configure(values=list(self.pages))
        if len(self.pages)==1:self.set(name)
        return page
    def set(self,name):
        if name not in self.pages:raise ValueError(name)
        # The option menu updates its StringVar before invoking this callback,
        # so visible-page identity must be tracked separately from that value.
        if name != self._visible_name:
            previous=self.pages.get(self._visible_name)
            if previous is not None:previous.pack_forget()
            self.pages[name].pack(fill='both',expand=True)
            self._visible_name=name
        self.current.set(name)
    def get(self):return self.current.get()
