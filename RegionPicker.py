"""Select a rectangle on a frozen desktop image. No mouse automation."""
import tkinter as tk
from PIL import Image,ImageGrab,ImageTk

from DpiSupport import normalize_uniform_capture_mapping


def select_region(owner,on_selected,on_error,*,cancelled=None):
    """Select a crop and transfer its ownership to on_selected on delivery.

    The callback may retain the crop (palette calibration does). A consumer
    that only analyses it synchronously must close it in its own finally block.
    Undelivered crops and desktop buffers remain owned by this function.
    """
    if cancelled is not None and not callable(cancelled):
        raise TypeError('Selection cancellation must be a callback.')
    if cancelled is not None and cancelled():
        on_error('Selection cancelled.')
        return
    windows=[owner]
    parent=getattr(owner,'master',None)
    if isinstance(parent,(tk.Tk,tk.Toplevel)):windows.append(parent)
    states=[]
    for w in windows:
        try:states.append(w.state())
        except tk.TclError:states.append('normal')
    for w in windows:
        try:w.withdraw()
        except tk.TclError:pass
    overlay=None
    restored=False
    captures=[]
    pending_crop=None
    closed=False
    jobs={'capture':None,'poll':None,'finish':None}
    state={'done':False}

    def cancel_jobs():
        for name,job in list(jobs.items()):
            jobs[name]=None
            if job is not None:
                try:owner.after_cancel(job)
                except (tk.TclError,RuntimeError):pass

    def close_captures():
        while captures:
            captures.pop().close()

    def restore_windows():
        nonlocal restored
        if restored:return
        restored=True
        for w,state in reversed(list(zip(windows,states))):
            try:
                if state in ('normal','zoomed') and w.winfo_exists():
                    w.deiconify()
                    if state=='zoomed':w.state('zoomed')
                elif state=='iconic' and w.winfo_exists():
                    w.iconify()
            except tk.TclError:pass

    def destroy_overlay():
        nonlocal overlay
        current=overlay;overlay=None
        if current is not None:
            try:
                if current.winfo_exists():current.destroy()
            except tk.TclError:pass

    def restore():
        nonlocal pending_crop
        cancel_jobs();destroy_overlay();close_captures()
        if pending_crop is not None:
            pending_crop.close();pending_crop=None
        restore_windows()

    def abort(message='Selection cancelled.'):
        nonlocal closed
        if closed:return
        closed=True;state['done']=True
        restore();on_error(message)

    def check_cancelled():
        if closed:return True
        try:
            requested=cancelled is not None and cancelled()
        except Exception as error:
            abort(f'Selection could not continue: {error}')
            return True
        if requested:
            abort()
            return True
        return False

    def poll_cancelled():
        jobs['poll']=None
        if check_cancelled():return
        try:jobs['poll']=owner.after(50,poll_cancelled)
        except (tk.TclError,RuntimeError):
            abort('Selection ended because the main window is closing.')

    def capture():
        nonlocal overlay
        jobs['capture']=None
        if check_cancelled():return
        try:
            import ctypes
            from WindowsSystem import load_system_library
            api=load_system_library('user32.dll')
            api.GetSystemMetrics.argtypes=[ctypes.c_int];api.GetSystemMetrics.restype=ctypes.c_int
            left,top,width,height=[api.GetSystemMetrics(i) for i in (76,77,78,79)]
            if width <= 0 or height <= 0:raise ValueError('Windows could not read the virtual desktop area.')
            captured=ImageGrab.grab(all_screens=True)
            try:
                shot=captured.convert('RGB')
            finally:
                captured.close()
            captures.append(shot)
            if check_cancelled():return
            scale_x=scale_y=1.0
            display_shot=shot
            if shot.size!=(width,height):
                # v1.0.116: tolerate the common uniform logical-vs-physical
                # mismatch seen on 4K/high-DPI setups instead of forcing a
                # restart.  Selection remains in overlay coordinates and is
                # mapped back to physical capture pixels on release.
                scale_x,scale_y=normalize_uniform_capture_mapping((width,height),shot.size)
                display_shot=shot.resize((width,height),Image.Resampling.LANCZOS)
                captures.append(display_shot)
            overlay=tk.Toplevel(owner);overlay.overrideredirect(True);overlay.attributes('-topmost',True)
            overlay.geometry(f'{width}x{height}+0+0');overlay.update_idletasks()
            from ctypes import wintypes
            api.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];api.GetAncestor.restype=wintypes.HWND
            api.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
            api.SetWindowPos.restype=wintypes.BOOL
            handle=api.GetAncestor(overlay.winfo_id(),2)
            if not handle:raise OSError('Could not read the selection window handle.')
            if not api.SetWindowPos(handle,None,left,top,width,height,0x0004):raise OSError('Could not display the screen selection overlay.')
            canvas=tk.Canvas(overlay,highlightthickness=0,cursor='crosshair');canvas.pack(fill='both',expand=True)
            photo=ImageTk.PhotoImage(display_shot);canvas.photo=photo;canvas.create_image(0,0,image=photo,anchor='nw')
            canvas.create_rectangle(12,12,650,56,fill='#142b36',outline='')
            canvas.create_text(26,34,anchor='w',text='Drag a rectangle around the area. Release to select. Esc = cancel.',fill='white',font=('Segoe UI',12))

            def down(event):
                if state['done'] or check_cancelled():return
                state['start']=(event.x,event.y)
                if 'box' in state:canvas.delete(state['box'])
                state['box']=canvas.create_rectangle(event.x,event.y,event.x,event.y,outline='#00e4cf',width=3)

            def move(event):
                if not state['done'] and not check_cancelled() and 'start' in state:canvas.coords(state['box'],*state['start'],event.x,event.y)

            def up(event):
                nonlocal pending_crop
                if state['done'] or check_cancelled() or 'start' not in state:return
                x,y=state['start'];a,b=max(0,min(x,event.x)),max(0,min(y,event.y));c,d=min(width,max(x,event.x)),min(height,max(y,event.y))
                if c-a<10 or d-b<10:return
                state['done']=True
                # Copy the crop before destroying the overlay/photo. Destroy the
                # overlay completely before any Win32 target-window probing.
                pa,pb,pc,pd=(int(round(a*scale_x)),int(round(b*scale_y)),
                             int(round(c*scale_x)),int(round(d*scale_y)))
                pa=max(0,min(shot.width,pa));pc=max(pa+1,min(shot.width,pc))
                pb=max(0,min(shot.height,pb));pd=max(pb+1,min(shot.height,pd))
                try:pending_crop=shot.crop((pa,pb,pc,pd))
                except Exception as error:
                    abort(str(error));return
                box=(int(round(left+pa)),int(round(top+pb)),
                     int(round(left+pc)),int(round(top+pd)))
                destroy_overlay();close_captures()

                def finish():
                    nonlocal closed,pending_crop
                    jobs['finish']=None
                    if check_cancelled():return
                    crop=pending_crop;pending_crop=None
                    closed=True;cancel_jobs()
                    try:on_selected(box,crop)
                    except Exception as error:on_error(str(error))
                    finally:restore_windows()
                try:jobs['finish']=owner.after(120,finish)
                except (tk.TclError,RuntimeError):
                    abort('Selection ended because the main window is closing.')

            canvas.bind('<ButtonPress-1>',down);canvas.bind('<B1-Motion>',move);canvas.bind('<ButtonRelease-1>',up)

            def cancel(event=None):
                abort()
            overlay.bind('<Escape>',cancel);overlay.protocol('WM_DELETE_WINDOW',cancel);overlay.focus_force()
            check_cancelled()
        except Exception as error:
            abort(str(error))
    try:
        jobs['capture']=owner.after(250,capture)
        if cancelled is not None:jobs['poll']=owner.after(50,poll_cancelled)
    except (tk.TclError,RuntimeError):
        abort('Selection could not start because the main window is closing.')
