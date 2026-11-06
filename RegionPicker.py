"""Select a rectangle on a frozen desktop image. No mouse automation."""
import tkinter as tk
from PIL import Image,ImageGrab,ImageTk

from DpiSupport import normalize_uniform_capture_mapping


def select_region(owner,on_selected,on_error):
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
        destroy_overlay();close_captures();restore_windows()

    def capture():
        nonlocal overlay
        try:
            import ctypes
            api=ctypes.windll.user32
            left,top,width,height=[api.GetSystemMetrics(i) for i in (76,77,78,79)]
            if width <= 0 or height <= 0:raise ValueError('Windows could not read the virtual desktop area.')
            captured=ImageGrab.grab(all_screens=True)
            try:
                shot=captured.convert('RGB')
            finally:
                captured.close()
            captures.append(shot)
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
            state={'done':False}

            def down(event):
                if state['done']:return
                state['start']=(event.x,event.y)
                if 'box' in state:canvas.delete(state['box'])
                state['box']=canvas.create_rectangle(event.x,event.y,event.x,event.y,outline='#00e4cf',width=3)

            def move(event):
                if not state['done'] and 'start' in state:canvas.coords(state['box'],*state['start'],event.x,event.y)

            def up(event):
                if state['done'] or 'start' not in state:return
                x,y=state['start'];a,b=max(0,min(x,event.x)),max(0,min(y,event.y));c,d=min(width,max(x,event.x)),min(height,max(y,event.y))
                if c-a<10 or d-b<10:return
                state['done']=True
                # Copy the crop before destroying the overlay/photo. Destroy the
                # overlay completely before any Win32 target-window probing.
                pa,pb,pc,pd=(int(round(a*scale_x)),int(round(b*scale_y)),
                             int(round(c*scale_x)),int(round(d*scale_y)))
                pa=max(0,min(shot.width,pa));pc=max(pa+1,min(shot.width,pc))
                pb=max(0,min(shot.height,pb));pd=max(pb+1,min(shot.height,pd))
                crop=shot.crop((pa,pb,pc,pd))
                box=(int(round(left+pa)),int(round(top+pb)),
                     int(round(left+pc)),int(round(top+pd)))
                destroy_overlay();close_captures()

                def finish():
                    try:on_selected(box,crop)
                    except Exception as error:on_error(str(error))
                    finally:restore_windows()
                try:owner.after(120,finish)
                except (tk.TclError,RuntimeError):
                    crop.close()
                    restore_windows()

            canvas.bind('<ButtonPress-1>',down);canvas.bind('<B1-Motion>',move);canvas.bind('<ButtonRelease-1>',up)

            def cancel(event=None):
                if state.get('done'):return
                state['done']=True;restore();on_error('Selection cancelled.')
            overlay.bind('<Escape>',cancel);overlay.protocol('WM_DELETE_WINDOW',cancel);overlay.focus_force()
        except Exception as error:
            restore();on_error(str(error))
    try:owner.after(250,capture)
    except (tk.TclError,RuntimeError):
        restore()
        on_error('Selection could not start because the main window is closing.')
