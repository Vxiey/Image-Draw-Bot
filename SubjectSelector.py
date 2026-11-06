"""Image-only rectangle selector; never sends operating-system mouse input."""
from contextlib import closing


def _preview_rgba(image,bounds):
    from PIL import Image,ImageOps
    from ImageGeometry import thumbnail_size
    orientation=image.getexif().get(274,1)
    rotated=orientation in (5,6,7,8)
    target=thumbnail_size(image.size,tuple(reversed(bounds)) if rotated else bounds)
    converted=None
    try:
        source=image
        if image.mode not in ('RGB','RGBA','L','LA','RGBa') or 'transparency' in image.info:
            converted=image.convert('RGBA');source=converted
        sampled=source.resize(target,Image.Resampling.LANCZOS)
    finally:
        if converted is not None:converted.close()
    with closing(sampled):
        # An in-memory EXIF object may not have been serialized into info yet.
        sampled.getexif()[274]=orientation
        oriented=ImageOps.exif_transpose(sampled)
    if oriented.mode=='RGBA':return oriented
    try:return oriented.convert('RGBA')
    finally:oriented.close()


def _destroy(window):
    import tkinter as tk
    if window is not None:
        try:window.destroy()
        except (tk.TclError,RuntimeError):pass


def select_subject(parent,image,callback):
    import tkinter as tk
    import customtkinter as ctk
    from PIL import Image,ImageTk
    bounds=(max(1,min(900,parent.winfo_screenwidth()-100)),
            max(1,min(600,parent.winfo_screenheight()-220)))
    dialog=None
    try:
        with closing(_preview_rgba(image,bounds)) as preview, closing(Image.new('RGBA',preview.size,'white')) as flat:
            flat.alpha_composite(preview)
            width,height=flat.size
            dialog=ctk.CTkToplevel(parent)
            dialog.title('Mark subject');dialog.transient(parent)
            ctk.CTkLabel(dialog,text='Drag a rectangle around the people or objects to keep.\nEverything inside the rectangle is included.',wraplength=500).pack(padx=16,pady=12)
            canvas=tk.Canvas(dialog,width=width,height=height,highlightthickness=0,cursor='crosshair')
            canvas.pack(padx=16)
            photo=ImageTk.PhotoImage(flat)
            canvas.create_image(0,0,image=photo,anchor='nw');canvas.image=photo
        state={'start':None,'box':None,'region':None,'closed':False}
        def close(event=None):
            if state['closed']:return
            state['closed']=True;_destroy(dialog)
        def point(event):return max(0,min(width,event.x)),max(0,min(height,event.y))
        def start(event):
            if state['closed']:return
            state['start']=point(event);state['region']=None
            apply_button.configure(state='disabled')
            if state['box'] is not None:canvas.delete(state['box'])
            x,y=state['start'];state['box']=canvas.create_rectangle(x,y,x,y,outline='#4de0ae',width=3)
        def drag(event):
            if state['closed'] or state['start'] is None:return
            x,y=point(event);sx,sy=state['start']
            canvas.coords(state['box'],sx,sy,x,y)
            x0,x1=sorted((x,sx));y0,y1=sorted((y,sy))
            state['region']=(x0/width,y0/height,x1/width,y1/height) if x1-x0>=3 and y1-y0>=3 else None
            apply_button.configure(state='normal' if state['region'] is not None else 'disabled')
        def apply(event=None):
            if state['closed'] or state['region'] is None:return
            region=state['region'];close();callback(region)
        apply_button=ctk.CTkButton(dialog,text='Use selection',command=apply,fg_color='#23664f',state='disabled')
        apply_button.pack(pady=12)
        canvas.bind('<Button-1>',start);canvas.bind('<B1-Motion>',drag);canvas.bind('<ButtonRelease-1>',drag)
        dialog.bind('<Escape>',close);dialog.bind('<Return>',apply);dialog.protocol('WM_DELETE_WINDOW',close)
        try:dialog.wait_visibility();dialog.grab_set()
        except tk.TclError:close()
        return dialog
    except BaseException:
        _destroy(dialog)
        raise


def show_mask(parent,image,region=None):
    import customtkinter as ctk
    from tkinter import messagebox
    from PIL import Image
    from SubjectFocus import subject_mask
    dialog=None;overlay=None
    try:
        with closing(_preview_rgba(image,(720,480))) as preview:
            try:mask,method=subject_mask(preview,region)
            except ValueError as error:
                messagebox.showinfo('Subject selection',str(error),parent=parent)
                return None
            with closing(Image.new('RGBA',preview.size,'white')) as flat:
                flat.alpha_composite(preview)
                with closing(flat.convert('RGB')) as original, closing(Image.new('RGB',preview.size,'#161c26')) as dark:
                    with closing(Image.blend(original,dark,.8)) as dimmed, closing(Image.fromarray(mask.astype('uint8')*255)) as alpha:
                        overlay=Image.composite(original,dimmed,alpha)
        dialog=ctk.CTkToplevel(parent);dialog.title('Subject mask preview');dialog.transient(parent)
        ctk.CTkLabel(dialog,text='Bright area = subject. Dim area = background.\n'+method,wraplength=600).pack(padx=16,pady=12)
        photo=ctk.CTkImage(light_image=overlay,dark_image=overlay,size=overlay.size)
        widget=ctk.CTkLabel(dialog,text='',image=photo);widget.pack(padx=16,pady=(0,16));widget.image=photo
        def release(event=None):
            nonlocal overlay
            if event is not None and event.widget is not dialog:return
            if overlay is not None:overlay.close();overlay=None
        def close(event=None):release();_destroy(dialog)
        dialog.bind('<Destroy>',release,add='+');dialog.bind('<Escape>',close);dialog.protocol('WM_DELETE_WINDOW',close)
        return dialog
    except BaseException:
        if overlay is not None:overlay.close()
        _destroy(dialog)
        raise
