"""Coalesced pointer-local scrolling for CustomTkinter panels."""
import math
import tkinter as tk

class ScrollAccumulator:
    def __init__(self):self.pending=0.0
    def add(self,steps):
        try:steps=float(steps)
        except (ValueError,TypeError,OverflowError):return False
        if not math.isfinite(steps):return False
        self.pending=max(-12.0,min(12.0,self.pending+steps))
        return True
    def take(self):
        units=math.trunc(self.pending)
        self.pending-=units
        return units

def install_scrolling(root):
    previous=getattr(root,'_image_draw_scroll_dispatcher',None)
    if isinstance(previous,dict) and not previous.get('closed',True):return previous
    from customtkinter import CTkScrollbar,CTkSlider,CTkTextbox
    from UiKeyboardNavigation import KeyboardSlider
    wheel_owners=(CTkScrollbar,CTkSlider,CTkTextbox)
    state={'canvas':None,'job':None,'delta':ScrollAccumulator(),'closed':False}
    try:window_system=root.tk.call('tk','windowingsystem')
    except Exception:window_system=''
    def can_scroll(canvas,steps):
        try:
            first,last=map(float,canvas.yview())
            if not (math.isfinite(first) and math.isfinite(last)):return False
        except Exception:
            # Retain compatibility with canvases that cannot report a view
            # until their first layout pass.
            return True
        return first>1e-6 if steps<0 else last<1-1e-6
    def units_per_notch(canvas):
        # CTk's Windows canvas uses a one-pixel increment. Its normal handler
        # scrolls 120/6 = 20 such units per wheel notch. Keep that distance after
        # coalescing; a generic canvas with its default increment needs no scale.
        if window_system!='win32':return 1
        try:increment=float(canvas.cget('yscrollincrement'))
        except (AttributeError,TypeError,ValueError,OverflowError,tk.TclError):return 1
        return max(1,round(20/increment)) if math.isfinite(increment) and increment>=1 else 1
    def flush_pending():
        if state['closed']:return
        canvas=state['canvas'];units=state['delta'].take()
        try:
            if canvas is not None and canvas.winfo_exists() and units:
                canvas.yview_scroll(units*units_per_notch(canvas),'units')
        except Exception:
            state['canvas']=None;state['delta']=ScrollAccumulator()
    def flush():
        state['job']=None
        flush_pending()
    def dispose(event=None):
        if event is not None and event.widget is not root:return
        if state['closed']:return
        state['closed']=True
        job=state['job'];state['job']=None
        cancel=getattr(root,'after_cancel',None)
        if job is not None and callable(cancel):
            try:cancel(job)
            except (RuntimeError,ValueError,tk.TclError):pass
        state['canvas']=None;state['delta']=ScrollAccumulator()
    def wheel(event):
        if state['closed']:return None
        # Ctrl zoom and Shift horizontal scrolling belong to their own bindings.
        if (getattr(event,'state',0) or 0)&5:return None
        number=getattr(event,'num',None)
        try:
            delta=float(getattr(event,'delta',0) or 0)
            steps=-1 if number==4 else 1 if number==5 else -delta/(1 if window_system=='aqua' else 120)
        except (TypeError,ValueError,OverflowError):return None
        if not math.isfinite(steps) or not steps:return None
        try:widget=root.winfo_containing(event.x_root,event.y_root)
        except Exception:return None
        canvas=None
        while widget is not None:
            # CTk sliders and scrollbars wrap a Canvas/Frame, so native class
            # names alone do not identify controls that already own the wheel.
            if isinstance(widget,KeyboardSlider):
                # The contrast control only owns wheel input after deliberate
                # focus. Otherwise scrolling through its row still moves the panel.
                if widget._keyboard_owns_wheel():return None
            elif isinstance(widget,wheel_owners):return None
            try:kind=widget.winfo_class()
            except (AttributeError,RuntimeError,tk.TclError):return None
            if kind in ('Text','Listbox','Menu','Treeview','TCombobox','Spinbox','TSpinbox','Scale','TScale'):return None
            candidate=getattr(widget,'_parent_canvas',None)
            if candidate is not None and can_scroll(candidate,steps):
                canvas=candidate;break
            widget=getattr(widget,'master',None)
        if canvas is None:return None
        if state['canvas'] is not canvas:
            # The pointer can cross panels within the 16 ms batch. Deliver the
            # old panel's complete motion before changing its destination.
            flush_pending()
            state['canvas']=canvas;state['delta']=ScrollAccumulator()
        state['delta'].add(steps)
        if state['job'] is None:
            try:state['job']=root.after(16,flush)
            except (RuntimeError,tk.TclError):dispose();return None
        return 'break'
    # Replace CTk's per-scrollframe bind_all handlers with one dispatcher.
    # This is installed once after the complete workspace is constructed.
    for sequence in ('<MouseWheel>','<Button-4>','<Button-5>'):
        root.bind_all(sequence,wheel)
    bind=getattr(root,'bind',None)
    if callable(bind):bind('<Destroy>',dispose,add='+')
    state['dispose']=dispose
    root._image_draw_scroll_dispatcher=state
    return state
