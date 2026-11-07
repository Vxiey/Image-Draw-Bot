"""Capture any visible palette, without a game-specific layout or color order."""
import tkinter as tk
from tkinter import ttk
from contextlib import closing
from RuntimePaths import atomic_write_text
BG="#0b0f14"
PANEL="#151d29"
FIELD="#202c3d"
TEXT="#f4f7fb"
MUTED="#94a3b8"
LINE="#2a384b"
ACCENT="#72e2bd"
ACCENT_DARK="#214c40"
from PIL import ImageGrab,ImageTk,ImageDraw
from PaletteMaps import PRESETS, detect_preset, sample_grid, sample_paint_grid, detect_color_swatches
from Colors import (sample_screen_color,save_calibration,enable_dpi_awareness,
                    CALIBRATION_FILE,normalize_rgb)
from CalibrationAnchors import make_anchor, ensure_same_layout
from CalibrationValidation import screen_point, screen_rect, point_in_rect


class CalibrationApp:
    def __init__(self,root,on_close=None,path=CALIBRATION_FILE,profile="generic"):
        from WindowsMouse import WindowsMouse
        self.mouse,self.root,self.on_close=WindowsMouse(),root,on_close
        self.path=path;self.is_paint=profile=='microsoft-paint';self.profile_key=str(profile);self.preset=PRESETS.get(profile);self.max_colors=96 if str(profile)=='gartic-phone' else 64
        self.map_names=None;self.map_indices=None;self.pending=[];self.rgbs=[];self.job=None;self.snapshot=None
        self.anchor=None;self.anchor_handle=None;self.closed=False
        root.configure(bg=BG);root.title('Image Draw Bot · Read color palette')
        from WorkspaceLayout import fit_window
        from CalibrationDialogLayout import CalibrationDialogLayout
        fit_window(root,preferred=(760,780),minimum=(500,400))
        style=ttk.Style(root)
        try: style.theme_use('clam')
        except tk.TclError: pass
        style.configure('Palette.TFrame',background=PANEL)
        style.configure('TFrame',background=PANEL)
        style.configure('TLabel',background=PANEL,foreground=TEXT,font=('Segoe UI',10))
        style.configure('Palette.TLabel',background=PANEL,foreground=TEXT,font=('Segoe UI',10))
        style.configure('Palette.TButton',font=('Segoe UI',10,'bold'),padding=(10,8))
        style.configure('Palette.Treeview',background=FIELD,fieldbackground=FIELD,foreground=TEXT,rowheight=28)
        style.configure('Palette.Treeview.Heading',background='#1b2635',foreground=TEXT,font=('Segoe UI',9,'bold'))
        self.layout=CalibrationDialogLayout(root,style='Palette.TFrame',background=PANEL)
        self.layout.pack(fill='both',expand=True);body=self.layout.body
        ttk.Label(body,text='🎨  Read colors from your application',font=('Segoe UI',18,'bold'),style='Palette.TLabel').pack(anchor='w')
        self.layout.label(text='1. Select palette area   →   2. Review colors   →   3. Save',wraplength=650,style='Palette.TLabel').pack(fill='x',pady=8)
        self.status=tk.StringVar(value='Select only the area where Image Draw Bot should look for color swatches. No mouse input is generated during detection.')
        self.count=tk.StringVar(value='No palette loaded')
        self.auto=ttk.Button(body,text='▣  Select color sampling area',command=self.start_scan,style='Palette.TButton');self.auto.pack(fill='x',pady=8)
        self.preview=ttk.Label(body,text='The selected sampling area appears here',anchor='center');self.preview.pack(fill='x',pady=8)
        mode_row=ttk.Frame(body);mode_row.pack(fill='x',pady=(4,8))
        ttk.Label(mode_row,text='Detection mode').pack(side='left')
        self.detect_mode=tk.StringVar(value='Auto detect')
        if not self.preset:
            mode_menu=ttk.Combobox(mode_row,textvariable=self.detect_mode,values=['Auto detect','Grid'],state='readonly',width=15)
            mode_menu.pack(side='right');mode_menu.bind('<<ComboboxSelected>>',lambda _event:self.read_snapshot())
        else:
            ttk.Label(mode_row,text='Preset map').pack(side='right')
        grid=ttk.Frame(body);grid.pack(fill='x',pady=8)
        self.rows=tk.IntVar(value=2);self.columns=tk.IntVar(value=9)
        from pathlib import Path
        self.grid_path=Path(path).with_suffix('.grid.json')
        try:
            import json
            counts=json.loads(self.grid_path.read_text(encoding='utf-8'))
            r,c=counts['rows'],counts['columns']
            if type(r) is int and type(c) is int and min(r,c)>0 and r*c<=self.max_colors:self.rows.set(r);self.columns.set(c)
        except (OSError,ValueError,KeyError,TypeError):pass
        if not self.preset:
            ttk.Label(grid,text='Grid rows').pack(side='left')
            ttk.Entry(grid,width=6,textvariable=self.rows).pack(side='left',padx=8)
            ttk.Label(grid,text='Columns').pack(side='left')
            ttk.Entry(grid,width=6,textvariable=self.columns).pack(side='left',padx=8)
        else:
            preset_note='Preset profile: fixed color map'
            if self.profile_key=='gartic-phone': preset_note='Gartic Phone: 6 columns × 12 rows = 72 colors'
            ttk.Label(grid,text=preset_note).pack(side='left')
        self.rescan=ttk.Button(grid,text='↻  Refresh scan',command=self.read_snapshot,style='Palette.TButton');self.rescan.pack(side='right')
        self.layout.label(text='Auto detect finds solid color swatches only inside your selected area. Use Grid mode if the palette is arranged in equal cells and auto detection misses colors.',wraplength=560).pack(fill='x')
        self.swatches=tk.Canvas(body,width=540,height=94,highlightthickness=0,bg=PANEL);self.swatches.pack(fill='x',pady=8)
        ttk.Label(body,textvariable=self.count).pack(anchor='w')
        self.table=ttk.Treeview(body,columns=('rgb','position'),show='headings',height=5,style='Palette.Treeview',selectmode='extended')
        self.table.heading('rgb',text='Color (RGB; ARGB converted)');self.table.heading('position',text='Click position on screen')
        self.table.pack(fill='both',expand=True,pady=8)
        self.table.bind('<Delete>',self.undo)
        actions=ttk.Frame(body);actions.pack(fill='x')
        self.undo_button=ttk.Button(actions,text='−  Remove selected colors',command=self.undo,style='Palette.TButton');self.undo_button.pack(side='left')
        self.add=ttk.Button(actions,text='＋  Capture a color manually…',command=lambda:self.capture(4),style='Palette.TButton');self.add.pack(side='right')
        code_row=ttk.Frame(body);code_row.pack(fill='x',pady=(9,0))
        self.color_code=tk.StringVar()
        code_entry=ttk.Entry(code_row,textvariable=self.color_code,width=28);code_entry.pack(side='left')
        self.add_code=ttk.Button(code_row,text='＋  Add RGB/ARGB at cursor',command=self.capture_code,style='Palette.TButton')
        self.add_code.pack(side='left',padx=8)
        self.layout.label(text='ARGB uses AARRGGBB. Alpha is converted to visible RGB on a white background.',
                  wraplength=560).pack(fill='x',pady=(4,0))
        self.layout.label(textvariable=self.status,wraplength=560).pack(fill='x',pady=12)
        self.save_button=ttk.Button(self.layout.footer,text='✓  Save colors for profile',command=self.save,style='Palette.TButton');self.save_button.pack(side='left',fill='x',expand=True,padx=(0,8))
        self.close_button=ttk.Button(self.layout.footer,text='Cancel',command=self.close,style='Palette.TButton');self.close_button.pack(side='right')
        root.protocol('WM_DELETE_WINDOW',self.close);self.refresh()

    def _capture_anchor_for_area(self, area, *, replace=False, commit=True):
        """Capture target client geometry without generating mouse input."""
        from TargetCapture import capture_target_metadata_isolated
        meta=capture_target_metadata_isolated(area)
        if self.anchor_handle is not None and meta['handle']!=self.anchor_handle and not replace:
            raise ValueError('All calibrated colors must belong to the same target window.')
        if self.anchor is None or replace:
            anchor=make_anchor(meta['client_rect'])
            if commit:self.anchor_handle=meta['handle'];self.anchor=anchor
        else:
            ensure_same_layout(self.anchor,meta['client_rect'])
        return meta

    def _canonical_point(self, point):
        x,y=screen_point(point)
        from TargetCapture import capture_target_metadata_isolated
        meta=capture_target_metadata_isolated((x-5,y-5,10,10))
        if not point_in_rect((x,y),meta['client_rect']):raise ValueError('The color position is outside the target client area.')
        if self.anchor is None:
            anchor=make_anchor(meta['client_rect'])
            self.anchor_handle=meta['handle'];self.anchor=anchor;return (x,y)
        if self.anchor_handle is not None and meta['handle']!=self.anchor_handle:
            raise ValueError('All calibrated colors must belong to the same target window.')
        dx,dy=ensure_same_layout(self.anchor,meta['client_rect'])
        return screen_point((x-dx,y-dy))

    def refresh(self):
        self.swatches.delete('all')
        for i,rgb in enumerate(self.rgbs):
            x=(i%32)*15;y=(i//32)*30
            self.swatches.create_rectangle(x,y,x+13,y+24,fill='#%02x%02x%02x'%tuple(rgb),outline='#777777')
        self.table.delete(*self.table.get_children())
        for i,(p,rgb) in enumerate(zip(self.pending,self.rgbs)):self.table.insert('', 'end',iid=str(i),values=(str(tuple(rgb)),str(tuple(p))))
        self.count.set(f'{len(self.pending)} colors selected · maximum {self.max_colors}')
        self.auto.configure(state='normal');self.rescan.configure(state='normal')
        self.add.configure(state='normal' if len(self.pending)<self.max_colors else 'disabled')
        self.add_code.configure(state='normal' if len(self.pending)<self.max_colors else 'disabled')
        for b in (self.undo_button,self.save_button):b.configure(state='normal' if self.pending else 'disabled')

    def capture(self,seconds):
        if getattr(self,'closed',False) or self.job is not None:return
        if len(self.pending)>=self.max_colors:self.status.set('The palette is full. Remove a color before adding another.');return
        for b in (self.add,self.add_code,self.auto,self.rescan,self.undo_button,self.save_button):b.configure(state='disabled')
        if getattr(self,'capture_visibility',None) is None:
            from ScreenTaskWindow import ScreenTaskWindow
            self.capture_visibility=ScreenTaskWindow(self.root)
            self.capture_visibility.hide()
        if seconds:
            self.status.set(f'Move the mouse to the center of a color swatch.\nCapturing in {seconds} seconds. Do not click.')
            def tick():
                self.job=None
                self.capture(seconds-1)
            self.job=self.root.after(1000,tick);return
        try:
            live_position=screen_point(self.mouse.get_position())
            position=self._canonical_point(live_position)
            if position in self.pending:
                if self.is_paint:
                    self.status.set('This color swatch is already mapped. No duplicate is needed.');self.refresh();return
                raise ValueError('That color swatch is already selected.')
            rgb=sample_screen_color(*live_position)
            if self.is_paint and tuple(rgb) in [tuple(c) for c in self.rgbs]:
                self.status.set('The color is already mapped. The existing position will be kept.');self.refresh();return
            self.map_names=None;self.map_indices=None
            self.pending.append(position);self.rgbs.append(rgb)
            self.status.set('Color added. Capture more colors or press Save colors.')
        except (OSError,AttributeError,ValueError) as error:self.status.set(str(error))
        finally:
            visibility=getattr(self,'capture_visibility',None)
            if visibility is not None:visibility.restore()
            self.capture_visibility=None
        self.refresh()

    def capture_code(self,seconds=3):
        """Associate an explicit RGB/ARGB value with the current cursor point."""
        if getattr(self,'closed',False) or self.job is not None:return
        if len(self.pending)>=self.max_colors:self.status.set('The palette is full. Remove a color before adding another.');return
        if seconds:
            try:normalize_rgb(self.color_code.get())
            except ValueError as error:self.status.set(str(error));return
            from ScreenTaskWindow import ScreenTaskWindow
            self.capture_visibility=ScreenTaskWindow(self.root);self.capture_visibility.hide()
            self.status.set('Hover over the matching colour swatch. Capturing in 3 seconds…')
            def finish_code():
                self.job=None
                self.capture_code(0)
            self.job=self.root.after(3000,finish_code)
            return
        try:
            rgb=normalize_rgb(self.color_code.get())
            position=self._canonical_point(screen_point(self.mouse.get_position()))
            if position in self.pending:raise ValueError('That screen position is already mapped.')
            if rgb in [tuple(c) for c in self.rgbs]:raise ValueError('That RGB color is already mapped.')
            self.pending.append(position);self.rgbs.append(rgb)
            self.map_names=None;self.map_indices=None;self.color_code.set('')
            self.status.set(f'Color added as RGB {rgb}. Add more colors or press Save colors.')
        except (OSError,ValueError,AttributeError) as error:self.status.set(str(error))
        finally:
            visibility=getattr(self,'capture_visibility',None)
            if visibility is not None:visibility.restore()
            self.capture_visibility=None
        self.refresh()

    def start_scan(self):
        if getattr(self,'closed',False) or self.job is not None:return
        from RegionPicker import select_region
        def selected(box,image):
            if getattr(self,'closed',False):image.close();return
            try:
                left,top,right,bottom=screen_rect(box)
                if image.size!=(right-left,bottom-top):raise ValueError('The selected screenshot size changed. Select the palette again.')
                meta=self._capture_anchor_for_area((left,top,right-left,bottom-top),replace=True,commit=False)
                anchor=make_anchor(meta['client_rect'])
            except (OSError,ValueError) as error:
                image.close();self.status.set(str(error));return
            try:
                self.read_snapshot((box,image),anchor=anchor,anchor_handle=meta['handle'])
            finally:
                # The selected crop transfers to the dialog only after a full
                # successful scan. Keep the previous frame/colours on failure.
                if self.snapshot is None or self.snapshot[1] is not image:image.close()
        select_region(self.root,selected,lambda message:self.status.set(message))

    def read_snapshot(self,snapshot=None,*,anchor=None,anchor_handle=None):
        if getattr(self,'closed',False) or self.job is not None:return False
        candidate=self.snapshot if snapshot is None else snapshot
        if candidate is None:self.status.set('Select the palette on screen first.');return False
        try:
            if snapshot is not None and anchor is None:
                raise ValueError('The new palette area needs a target-window anchor.')
            (left,top,right,bottom),screenshot=candidate
            mode=self.detect_mode.get() if not self.preset else 'Preset map'
            rows=columns=None
            if not self.preset and mode=='Grid':
                rows,columns=self.rows.get(),self.columns.get()
                if min(rows,columns)<1 or not 1<=rows*columns<=self.max_colors:
                    raise ValueError('Enter a valid number of color swatches for this profile.')
            note=''
            if self.preset:
                try:
                    positions=detect_preset(screenshot,self.preset,(left,top))
                    # The screen is authoritative: save the RGB actually rendered
                    # at each detected swatch, never blindly copy preset RGB.
                    rgbs=[screenshot.getpixel((int(x-left),int(y-top))) for x,y in positions]
                    names=list(self.preset.names);indices=list(range(len(rgbs)))
                    note='Preset positions matched; actual on-screen RGB values were sampled. '
                except ValueError:
                    # UI themes/game revisions can change RGB values. Fall back to
                    # geometry-based swatch detection instead of failing the profile.
                    positions,rgbs,stats=detect_color_swatches(screenshot,(left,top),max_colors=self.max_colors)
                    names=None;indices=None
                    note=f"Preset RGB changed; auto-detect recovered {stats['found']} visible colors. "
            elif mode=='Auto detect':
                positions,rgbs,stats=detect_color_swatches(screenshot,(left,top),max_colors=self.max_colors)
                names=None;indices=None
                note=f"Auto detect found {stats['found']} colors; {stats['duplicates']} duplicate swatches merged. "
            elif self.is_paint:
                positions,rgbs,stats=sample_paint_grid(screenshot,rows,columns,(left,top));names=None;indices=None
                note=f"Grid mode: {stats['duplicates']} duplicates merged, {stats['skipped']} empty/unclear swatches skipped. "
            else:
                positions,rgbs=sample_grid(screenshot,rows,columns,(left,top));names=None;indices=None
                note='Grid mode completed. '
            with closing(screenshot.copy()) as shown:
                shown.thumbnail((560,150))
                if not self.preset and mode=='Grid':
                    pen=ImageDraw.Draw(shown)
                    for col in range(1,columns):
                        x=round(col*shown.width/columns);pen.line((x,0,x,shown.height),fill='#ff00bf',width=1)
                    for row in range(1,rows):
                        y=round(row*shown.height/rows);pen.line((0,y,shown.width,y),fill='#ff00bf',width=1)
                photo=ImageTk.PhotoImage(shown,master=self.root)
            self.preview.configure(image=photo,text='')
        except (OSError,ValueError,AttributeError,tk.TclError,MemoryError) as error:
            retained=' Previous colors and target were kept.' if self.pending else ''
            self.status.set(f'Could not scan: {error}.{retained}')
            self.refresh()
            return False
        previous=self.snapshot
        self.pending=positions;self.rgbs=rgbs;self.map_names=names;self.map_indices=indices;self.photo=photo
        if snapshot is not None:
            self.snapshot=candidate;self.anchor=anchor;self.anchor_handle=anchor_handle
            if previous is not None and previous[1] is not screenshot:previous[1].close()
        self.status.set(note+'Review the detected colors. Remove incorrect matches, then save.')
        self.refresh()
        return True

    def undo(self,event=None):
        if getattr(self,'closed',False) or self.job is not None or not self.pending:return 'break'
        selected=self.table.selection()
        indices=sorted({int(value) for value in selected} if selected else {len(self.pending)-1},reverse=True)
        if any(index<0 or index>=len(self.pending) for index in indices):return 'break'
        self.map_names=None;self.map_indices=None
        for index in indices:self.pending.pop(index);self.rgbs.pop(index)
        self.refresh()
        if self.pending:
            next_index=str(min(indices[-1],len(self.pending)-1))
            self.table.selection_set(next_index);self.table.focus(next_index)
        return 'break'

    def save(self):
        if self.job is not None:return
        try:
            if self.is_paint and self.anchor is None:
                raise ValueError('Select/capture the Paint palette again so the colors can be anchored to the Paint window.')
            save_calibration(self.pending,self.rgbs,self.path,names=self.map_names,indices=self.map_indices,anchor=self.anchor,profile_key=self.profile_key,state='calibrated',verification={'method':'manual-palette-capture','source':'user-reviewed-capture'})
        except (OSError,ValueError) as error:self.status.set(f'Could not save: {error}');return
        try:
            import json
            atomic_write_text(self.grid_path,json.dumps({'rows':self.rows.get(),'columns':self.columns.get()}))
        except (OSError,ValueError,tk.TclError):pass
        self.close()

    def close(self):
        if getattr(self,'closed',False):return
        self.closed=True
        if self.job is not None:
            job=self.job;self.job=None
            try:self.root.after_cancel(job)
            except (tk.TclError,ValueError,RuntimeError):pass
        if self.snapshot is not None:
            self.snapshot[1].close();self.snapshot=None
        try:self.root.destroy()
        except (tk.TclError,RuntimeError):pass
        if self.on_close:
            try:self.on_close()
            except (tk.TclError,RuntimeError):pass


def main(argv=None):
    """Run palette calibration as an isolated helper process.

    Keeping this window out of the main Image Draw Bot process prevents a Tk/native
    calibration crash from taking down the drawing workspace.
    """
    import argparse
    import traceback
    from pathlib import Path
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--path',default=str(CALIBRATION_FILE))
    parser.add_argument('--profile',default='generic')
    parser.add_argument('--log',default='')
    args,_unknown=parser.parse_known_args(argv)
    log_path=Path(args.log) if args.log else Path(args.path).with_name('ImageDrawBot-palette-calibration.log')
    try:
        enable_dpi_awareness()
        from AppBranding import configure_root, set_windows_app_id
        set_windows_app_id()
        root=tk.Tk()
        configure_root(root)
        CalibrationApp(root,path=Path(args.path),profile=str(args.profile))
        root.mainloop()
        return 0
    except BaseException:
        try:
            log_path.parent.mkdir(parents=True,exist_ok=True)
            log_path.write_text(traceback.format_exc(),encoding='utf-8')
        except OSError:
            pass
        traceback.print_exc()
        return 1


if __name__=='__main__':
    raise SystemExit(main())
