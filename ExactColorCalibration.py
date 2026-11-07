"""Isolated, ttk-only exact/custom color control calibration."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from CalibrationAnchors import make_anchor,ensure_same_layout
from CalibrationValidation import screen_point,point_in_rect
from ExactColorTools import ALL_FIELDS,BASE_FIELDS,RGB_FIELDS,SPECTRUM_FIELDS,load,save
from Colors import enable_dpi_awareness

LABELS={
 'OpenCustomColor':'Open custom color / Edit colors button',
 'SpectrumTopLeft':'Color spectrum: top-left corner',
 'SpectrumBottomRight':'Color spectrum: bottom-right corner',
 'BrightnessTop':'Brightness/value scale: top point (optional)',
 'BrightnessBottom':'Brightness/value scale: bottom point (optional)',
 'SelectedColorPreview':'Selected-color preview swatch inside Edit colors (optional)',
 'ActiveColorPreview':'Active Color 1 / foreground swatch in Paint ribbon (optional)',
 'RedField':'Red (R) input field (fallback)', 'GreenField':'Green (G) input field (fallback)','BlueField':'Blue (B) input field (fallback)',
 'ConfirmColor':'Confirm / OK button','Eyedropper':'Eyedropper tool (optional)'}

ORDER=('OpenCustomColor','SpectrumTopLeft','SpectrumBottomRight','BrightnessTop','BrightnessBottom','SelectedColorPreview','ActiveColorPreview',
       'RedField','GreenField','BlueField','ConfirmColor','Eyedropper')

class App:
    def __init__(self,root,profile_key):
        from WindowsMouse import WindowsMouse
        self.root=root;self.profile_key=profile_key;self.mouse=WindowsMouse();self.positions={};self.anchor=None;self.job=None
        self.anchor_handle=None;self.anchor_owner=None;self.anchor_pid=None;self.closed=False
        try:
            data=load(profile_key);self.positions={k:tuple(v) for k,v in data['controls'].items()};self.anchor=data['anchor']
        except (OSError,ValueError):pass
        root.title('Image Draw Bot · Smart custom palette')
        from WorkspaceLayout import fit_window
        from CalibrationDialogLayout import CalibrationDialogLayout
        fit_window(root,preferred=(760,760),minimum=(500,400))
        self.layout=CalibrationDialogLayout(root);self.layout.pack(fill='both',expand=True);body=self.layout.body
        ttk.Label(body,text='Smart custom palette / exact color',font=('Segoe UI',17,'bold')).pack(anchor='w')
        self.layout.label(text=(
            'Recommended for maximum accuracy: capture Open custom color, the Red/Green/Blue fields, Selected-color preview, Confirm, and the spectrum corners as fallback. '
            "During drawing, Adaptive exact measures RGB from the source image, types that RGB into Paint automatically, checks the selected-color preview when calibrated, and only then confirms it. "
            'The visual spectrum remains a safe fallback when numeric RGB cannot be verified. Calibration itself never clicks.'),wraplength=700).pack(fill='x',pady=(6,12))
        self.status=tk.StringVar(value='Best accuracy: capture Open + R/G/B + Selected preview + Active Color 1 swatch + Confirm. Also capture Spectrum corners for automatic fallback.')
        self.labels={};self.remove_buttons={}
        for name in ORDER:
            row=ttk.Frame(body);row.pack(fill='x',pady=4)
            row.columnconfigure(0,weight=1)
            self.layout.label(row,text=LABELS[name],wraplength=380).grid(row=0,column=0,sticky='ew',padx=(0,8))
            lab=ttk.Label(row,text='Not captured');lab.grid(row=1,column=0,sticky='w');self.labels[name]=lab
            ttk.Button(row,text='Capture',command=lambda n=name:self.capture(n,3)).grid(row=0,column=2,rowspan=2,padx=(4,0))
            if name!='OpenCustomColor':
                remove=ttk.Button(row,text='Remove',command=lambda n=name:self.remove_control(n),width=7)
                remove.grid(row=0,column=1,rowspan=2,padx=4);self.remove_buttons[name]=remove
        ttk.Separator(body).pack(fill='x',pady=10)
        self.layout.label(textvariable=self.status,wraplength=700).pack(fill='x',pady=6)
        actions=self.layout.footer
        self.save_button=ttk.Button(actions,text='Save calibration',command=self.save);self.save_button.pack(side='left')
        ttk.Button(actions,text='Start new calibration',command=self.reset_controls).pack(side='left',padx=8)
        self.close_button=ttk.Button(actions,text='Close',command=self.close);self.close_button.pack(side='right')
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh()
    def refresh(self):
        optional={'Eyedropper','SelectedColorPreview','ActiveColorPreview','BrightnessTop','BrightnessBottom','RedField','GreenField','BlueField'}
        for n,l in self.labels.items():l.configure(text=('✓ '+str(self.positions[n])) if n in self.positions else ('Optional' if n in optional else 'Not captured'))
        for name,button in getattr(self,'remove_buttons',{}).items():
            button.configure(state='normal' if name in self.positions and self.job is None else 'disabled')
    def remove_control(self,name):
        if getattr(self,'closed',False) or self.job is not None:return False
        if name not in ALL_FIELDS:raise ValueError('Unknown exact color control.')
        if name=='OpenCustomColor':return self.reset_controls()
        if name not in self.positions:return False
        del self.positions[name]
        self.status.set(f'Removed {LABELS[name]}. Save calibration to keep this change.')
        self.refresh();return True
    def reset_controls(self):
        if getattr(self,'closed',False) or self.job is not None:return False
        self.positions={};self.anchor=None;self.anchor_handle=None;self.anchor_owner=None;self.anchor_pid=None
        self.status.set('New calibration: capture Open custom color first, then the controls you want to use. Save when ready.')
        self.refresh();return True
    def capture(self,name,seconds):
        if getattr(self,'closed',False) or self.job is not None:return
        if getattr(self,'capture_visibility',None) is None:
            from ScreenTaskWindow import ScreenTaskWindow
            self.capture_visibility=ScreenTaskWindow(self.root)
            self.capture_visibility.hide()
        if seconds:
            self.status.set(f'Switch to the target app and hover over: {LABELS[name]}. Capturing in {seconds}… Do not click.')
            self.job=self.root.after(1000,lambda:self._tick(name,seconds-1));return
        self._now(name)
    def _tick(self,name,seconds):
        self.job=None
        if not getattr(self,'closed',False):self.capture(name,seconds) if seconds else self._now(name)
    def _now(self,name):
        if getattr(self,'closed',False):return
        try:
            if name not in ALL_FIELDS:raise ValueError('Unknown exact color control.')
            if getattr(self,'anchor_handle',None) is None and name!='OpenCustomColor':
                raise ValueError('Capture Open custom color first to identify the current target window.')
            point=screen_point(self.mouse.get_position())
            from TargetCapture import capture_target_metadata_isolated,probe_handle_isolated
            x,y=point;meta=capture_target_metadata_isolated((x-5,y-5,10,10))
            if not point_in_rect(point,meta['client_rect']):raise ValueError('The control is outside the captured client area.')
            handle=getattr(self,'anchor_handle',None)
            if handle is None:
                current=meta
            elif meta['handle']==handle:
                current=meta
            else:
                owner=meta.get('owner_root_handle')
                if (owner is None or owner!=getattr(self,'anchor_owner',None) or
                        not meta.get('target_pid') or meta['target_pid']!=getattr(self,'anchor_pid',None)):
                    raise ValueError('Capture controls only from the same target window or its owned color dialog.')
                # Dialog geometry is independent; rebase against the original
                # target's client area, never against the modal's smaller frame.
                current=probe_handle_isolated(handle)
                if (current.get('owner_root_handle',handle)!=self.anchor_owner or
                        current.get('target_pid')!=self.anchor_pid):
                    raise ValueError('The target window identity changed. Capture Open custom color again.')
            anchor=self.anchor or make_anchor(current['client_rect'])
            reset_controls=False
            try:dx,dy=ensure_same_layout(anchor,current['client_rect'])
            except ValueError:
                if name!='OpenCustomColor':raise
                # An explicit opener capture can start a new layout after a
                # resize. Never mix its new frame with the saved old controls.
                anchor=make_anchor(current['client_rect']);dx=dy=0;reset_controls=True
            stored=screen_point((point[0]-dx,point[1]-dy))
            self.anchor=anchor;self.anchor_handle=current['handle']
            self.anchor_owner=current.get('owner_root_handle',current['handle']);self.anchor_pid=current.get('target_pid')
            if reset_controls:self.positions={}
            self.positions[name]=stored;self.status.set(f'Captured {LABELS[name]} at {point}.')
        except Exception as e:self.status.set(str(e))
        finally:
            visibility=getattr(self,'capture_visibility',None)
            if visibility is not None:visibility.restore()
            self.capture_visibility=None
        self.refresh()
    def save(self):
        if getattr(self,'closed',False) or self.job is not None:return
        try:
            if self.anchor is None:raise ValueError('Capture the Open custom color control first.')
            missing_base=[n for n in BASE_FIELDS if n not in self.positions]
            spectrum=all(n in self.positions for n in SPECTRUM_FIELDS)
            numeric=all(n in self.positions for n in RGB_FIELDS)
            if missing_base:raise ValueError('Missing required controls: '+', '.join(LABELS[n] for n in missing_base))
            if not spectrum and not numeric:
                raise ValueError('Capture both spectrum corners (recommended) or all three R/G/B fields before saving.')
            if ('BrightnessTop' in self.positions) != ('BrightnessBottom' in self.positions):
                raise ValueError('Capture both brightness-scale endpoints or neither.')
            save(self.profile_key,self.positions,anchor=self.anchor)
            mode='numeric RGB fields and visual spectrum' if numeric and spectrum else ('visual spectrum' if spectrum else 'numeric RGB fields')
            self.status.set(f'Exact color controls saved using {mode}. You can close this window.')
        except (OSError,ValueError) as e:self.status.set(f'Could not save: {e}')

    def close(self):
        if getattr(self,'closed',False):return
        self.closed=True
        job=self.job;self.job=None
        if job is not None:
            try:self.root.after_cancel(job)
            except (tk.TclError,RuntimeError,ValueError):pass
        try:self.root.destroy()
        except (tk.TclError,RuntimeError):pass

def main(argv=None):
    import argparse,traceback
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--profile',default='generic');p.add_argument('--log',default='');args,_=p.parse_known_args(argv)
    try:
        from AppBranding import configure_root, set_windows_app_id
        set_windows_app_id()
        enable_dpi_awareness();root=configure_root(tk.Tk());App(root,args.profile);root.mainloop();return 0
    except Exception:
        if args.log:
            try:Path(args.log).write_text(traceback.format_exc(),encoding='utf-8')
            except OSError:pass
        return 1
if __name__=='__main__':raise SystemExit(main())
