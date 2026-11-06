"""Coalesced pointer-local scrolling for CustomTkinter panels."""
import math

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
    state={'canvas':None,'job':None,'delta':ScrollAccumulator()}
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
    def flush():
        state['job']=None
        canvas=state['canvas'];units=state['delta'].take()
        try:
            if canvas is not None and canvas.winfo_exists() and units:
                canvas.yview_scroll(units,'units')
        except Exception:
            state['canvas']=None;state['delta']=ScrollAccumulator()
    def wheel(event):
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
            # Native text/list widgets already implement their own class binding.
            if widget.winfo_class() in ('Text','Listbox','Menu','Treeview','TCombobox','Spinbox','TSpinbox','Scale','TScale'):return None
            candidate=getattr(widget,'_parent_canvas',None)
            if candidate is not None and can_scroll(candidate,steps):
                canvas=candidate;break
            widget=getattr(widget,'master',None)
        if canvas is None:return None
        if state['canvas'] is not canvas:
            state['canvas']=canvas;state['delta']=ScrollAccumulator()
        state['delta'].add(steps)
        if state['job'] is None:state['job']=root.after(16,flush)
        return 'break'
    # Replace CTk's per-scrollframe bind_all handlers with one dispatcher.
    # This is installed once after the complete workspace is constructed.
    for sequence in ('<MouseWheel>','<Button-4>','<Button-5>'):
        root.bind_all(sequence,wheel)
    return state
