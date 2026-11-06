"""Keep explicit button-only action rows accessible inside narrow panels."""
import math
import tkinter as tk


def bind_widget_event(widget,sequence,callback):
    # CTkFrame.bind forwards to its decorative Canvas. Layout and destruction
    # belong to the containing native widget, so bypass only that forwarding.
    if isinstance(widget,tk.Misc):return tk.Misc.bind(widget,sequence,callback,add='+')
    return widget.bind(sequence,callback,add='+')


def wrap_action_rows(parent,*,recursive=True,control_types=None):
    """Install a coalesced grid on eligible rows, preserving widget commands.

    The active workspace calls this for its known tools row only. Recursive
    discovery remains available to older callers; mixed-content rows are left
    alone. Native widths already include CTk scaling, while grid padding does
    not, so padding is converted once for the column calculation.
    """
    import customtkinter as ctk
    previous=getattr(parent,'_responsive_action_rows_state',None)
    if isinstance(previous,dict) and not previous.get('closed'):
        return previous
    if recursive:
        for child in parent.winfo_children():
            wrap_action_rows(child)
    children=[w for w in parent.winfo_children() if w is not getattr(parent,'_canvas',None)]
    accepted=(ctk.CTkButton,) if control_types is None else tuple(control_types)
    if len(children)<2 or not all(isinstance(w,accepted) for w in children):return None
    if not all(w.winfo_manager()=='pack' for w in children):return None
    state={'signature':None,'job':None,'closed':False}

    def apply():
        state['job']=None
        if state['closed']:return
        try:
            width=parent.winfo_width()
            if width<=1:return
            getter=getattr(parent,'_get_widget_scaling',None)
            scale=float(getter()) if callable(getter) else 1.0
            if not math.isfinite(scale) or scale<=0:scale=1.0
            widths=tuple(w.winfo_reqwidth() for w in children)
            cell=max(widths)+math.ceil(6*scale)
            columns=max(1,min(len(children),int(width//max(1,cell))))
            signature=(columns,widths,scale)
            if signature==state['signature']:return
            # Shared grid columns take the largest request from any row. The
            # widest-control bound therefore also fits uneven button rows.
            for child in children:
                child.pack_forget();child.grid_forget()
            for index,child in enumerate(children):
                child.grid(row=index//columns,column=index%columns,sticky='ew',padx=3,pady=3)
            state['signature']=signature
        except (tk.TclError,RuntimeError):
            if not state['closed']:raise

    def changed(event=None):
        if state['closed'] or (event is not None and event.widget is not parent):return
        if state['job'] is None:state['job']=parent.after_idle(apply)

    def dispose(event=None):
        if event is not None and event.widget is not parent:return
        state['closed']=True
        job=state['job'];state['job']=None
        if job is not None:
            try:parent.after_cancel(job)
            except (tk.TclError,RuntimeError,ValueError):pass

    bind_widget_event(parent,'<Configure>',changed)
    bind_widget_event(parent,'<Destroy>',dispose)
    parent._responsive_action_rows_state=state
    changed()
    return state
