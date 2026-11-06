"""Image-only rectangle selector; never sends operating-system mouse input."""
def select_subject(parent, image, callback):
    import tkinter as tk
    import customtkinter as ctk
    from PIL import ImageTk, ImageOps
    preview = ImageOps.exif_transpose(image).convert('RGB')
    preview.thumbnail((max(1,min(900,parent.winfo_screenwidth()-100)), max(1,min(600,parent.winfo_screenheight()-220))))
    width, height = preview.size
    dialog = ctk.CTkToplevel(parent)
    dialog.title('Mark subject')
    dialog.transient(parent)
    ctk.CTkLabel(dialog, text='Drag a rectangle around the people or objects to keep.\nEverything inside the rectangle is included.', wraplength=500).pack(padx=16,pady=12)
    canvas = tk.Canvas(dialog, width=width, height=height, highlightthickness=0, cursor='crosshair')
    canvas.pack(padx=16)
    photo = ImageTk.PhotoImage(preview)
    canvas.create_image(0,0,image=photo,anchor='nw')
    canvas.image = photo
    state = {'start':None, 'box':None, 'region':None}
    def point(event): return max(0,min(width,event.x)),max(0,min(height,event.y))
    def start(event):
        state['start'] = point(event)
        state['region'] = None
        if state['box'] is not None: canvas.delete(state['box'])
        x,y=state['start']
        state['box']=canvas.create_rectangle(x,y,x,y,outline='#4de0ae',width=3)
    def drag(event):
        if state['start'] is None: return
        x,y=point(event); sx,sy=state['start']
        canvas.coords(state['box'],sx,sy,x,y)
        x0,x1=sorted((x,sx)); y0,y1=sorted((y,sy))
        state['region']=(x0/width,y0/height,x1/width,y1/height) if x1-x0>=3 and y1-y0>=3 else None
    def apply():
        if state['region'] is None: return
        region=state['region']
        dialog.destroy()
        callback(region)
    canvas.bind('<Button-1>',start)
    canvas.bind('<B1-Motion>',drag)
    canvas.bind('<ButtonRelease-1>',drag)
    ctk.CTkButton(dialog,text='Use selection',command=apply,fg_color='#23664f').pack(pady=12)
    dialog.bind('<Escape>',lambda event:dialog.destroy())
    dialog.wait_visibility()
    dialog.grab_set()


def show_mask(parent, image, region=None):
    import customtkinter as ctk
    from tkinter import messagebox
    from PIL import Image, ImageOps
    from SubjectFocus import subject_mask
    preview = ImageOps.exif_transpose(image).convert('RGBA')
    preview.thumbnail((720,480))
    try:
        mask, method = subject_mask(preview,region)
    except ValueError as error:
        messagebox.showinfo('Subject selection',str(error),parent=parent)
        return
    original=preview.convert('RGB')
    dimmed=Image.blend(original,Image.new('RGB',original.size,'#161c26'),.8)
    overlay=Image.composite(original,dimmed,Image.fromarray(mask.astype('uint8')*255))
    dialog=ctk.CTkToplevel(parent)
    dialog.title('Subject mask preview')
    dialog.transient(parent)
    ctk.CTkLabel(dialog,text='Bright area = subject. Dim area = background.\n'+method,wraplength=600).pack(padx=16,pady=12)
    photo=ctk.CTkImage(light_image=overlay,dark_image=overlay,size=overlay.size)
    widget=ctk.CTkLabel(dialog,text='',image=photo)
    widget.pack(padx=16,pady=(0,16))
    widget.image=photo
    dialog.bind('<Escape>',lambda event:dialog.destroy())
