"""Generic Brush/Fill/Eraser/Clear calibration for non-Paint drawing apps."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

from AppTools import GENERIC_TOOLS, load_calibration, save_calibration
from CalibrationAnchors import make_anchor, ensure_same_layout
from CalibrationValidation import screen_point, point_in_rect
from StudioUI import button, BG, PANEL, FIELD, TEXT


class AppToolCalibrationApp:
    def __init__(self, root, profile_key: str, profile_name: str, on_close=None):
        from WindowsMouse import WindowsMouse
        self.root, self.profile_key, self.profile_name, self.on_close = root, profile_key, profile_name, on_close
        self.mouse = WindowsMouse()  # DISARMED: get_position only
        self.positions = {}; self.anchor = None; self.anchor_handle = None; self.job = None; self.closed = False
        try:
            data = load_calibration(profile_key)
            self.positions = {name: tuple(pos) for name, pos in data.get("tools", {}).items()}
            self.anchor = data.get("anchor")
        except (OSError, ValueError):
            pass
        root.title(f"Image Draw Bot · Calibrate {profile_name} tools"); root.geometry("680x650"); root.minsize(590, 560)
        try: root.configure(fg_color=BG)
        except Exception: root.configure(bg=BG)
        from UiCompatibility import scoped_scrollable_frame
        body = scoped_scrollable_frame(root, fg_color=PANEL, corner_radius=18); body.pack(fill="both", expand=True, padx=16, pady=16)
        ttk.Label(body, text=f"Calibrate {profile_name} tools", font=("Segoe UI",18,"bold")).pack(anchor="w")
        ttk.Label(body, text="Image Draw Bot never guesses tool coordinates. During each countdown, switch to the target app and hover over the requested control. No clicks are generated while calibrating.", wraplength=560).pack(anchor="w", pady=(6,12))
        self.status = tk.StringVar(value="Capture Clear canvas for one-click automatic clearing. Brush + Eraser can be used as a fallback sweep. Keep the app window at the same size while drawing.")
        self.labels = {}; self.remove_buttons = {}
        for name in GENERIC_TOOLS:
            row = ctk.CTkFrame(body, fg_color=FIELD, corner_radius=12); row.pack(fill="x", pady=6)
            title = "Clear canvas button" if name == "Clear" else f"{name} tool"
            ctk.CTkLabel(row, text=title, text_color=TEXT, font=("Segoe UI",13,"bold")).pack(side="left", padx=14, pady=14)
            label = ctk.CTkLabel(row, text="", text_color="#a6b2c5"); label.pack(side="left", padx=8); self.labels[name] = label
            button(row, text="Capture position", command=lambda n=name:self.capture(n,3), width=145, height=38).pack(side="right", padx=12, pady=10)
            remove=button(row,text='Remove',command=lambda n=name:self.remove_control(n),width=76,height=38)
            remove.pack(side='right',pady=10);self.remove_buttons[name]=remove
        ttk.Label(body, textvariable=self.status, wraplength=560).pack(anchor="w", pady=10)
        actions = ctk.CTkFrame(body, fg_color="transparent"); actions.pack(fill="x", pady=(8,0))
        button(actions, text="Save calibration", command=self.save, primary=True).pack(side="left")
        button(actions,text='Start new calibration',command=self.reset_controls).pack(side='left',padx=8)
        button(actions, text="Close", command=self.close).pack(side="right")
        root.protocol("WM_DELETE_WINDOW", self.close); self.refresh()

    def refresh(self):
        for name, label in self.labels.items():
            value = self.positions.get(name); label.configure(text=f"✓ {value}" if value else "Not captured")
        for name,control in getattr(self,'remove_buttons',{}).items():
            control.configure(state='normal' if name in self.positions and self.job is None else 'disabled')

    def remove_control(self,name):
        if getattr(self,'closed',False) or self.job is not None:return False
        if name not in GENERIC_TOOLS:raise ValueError('Unknown application control.')
        if name not in self.positions:return False
        del self.positions[name]
        self.status.set(f'Removed {name}. Save calibration to keep this change.')
        self.refresh();return True

    def reset_controls(self):
        if getattr(self,'closed',False) or self.job is not None:return False
        self.positions={};self.anchor=None;self.anchor_handle=None
        self.status.set('New calibration: capture the controls you want to use in the target window, then save.')
        self.refresh();return True

    def capture(self, name, seconds):
        if getattr(self,'closed',False) or self.job is not None: return
        if getattr(self,'capture_visibility',None) is None:
            from ScreenTaskWindow import ScreenTaskWindow
            self.capture_visibility=ScreenTaskWindow(self.root)
            self.capture_visibility.hide()
        if seconds:
            self.status.set(f"Switch to {self.profile_name} and hover over the {name} tool. Capturing in {seconds}… Do not click.")
            self.job = self.root.after(1000, lambda:self._capture_tick(name, seconds-1)); return
        self._capture_now(name)

    def _capture_tick(self, name, seconds):
        self.job = None
        if getattr(self,'closed',False):return
        if seconds: self.capture(name, seconds)
        else: self._capture_now(name)

    def _capture_now(self, name):
        if getattr(self,'closed',False):return
        try:
            if name not in GENERIC_TOOLS:raise ValueError('Unknown application control.')
            point = screen_point(self.mouse.get_position())
            from TargetCapture import capture_target_metadata_isolated
            x,y = point; meta = capture_target_metadata_isolated((x-5,y-5,10,10))
            if not point_in_rect(point,meta['client_rect']):raise ValueError('The control is outside the target client area.')
            if self.anchor_handle is not None and meta["handle"] != self.anchor_handle:
                raise ValueError("All tool positions must be captured from the same target window.")
            if self.anchor is None:
                anchor = make_anchor(meta["client_rect"]); stored = point
            else:
                dx,dy = ensure_same_layout(self.anchor, meta["client_rect"])
                stored = screen_point((point[0]-dx, point[1]-dy))
                anchor = self.anchor
            self.anchor_handle = meta["handle"]
            self.anchor = anchor
            self.positions[name] = stored
            self.status.set(f"Captured {name} at {point}.")
        except (OSError, AttributeError, ValueError) as error:
            self.status.set(str(error))
        finally:
            visibility=getattr(self,'capture_visibility',None)
            if visibility is not None:visibility.restore()
            self.capture_visibility=None
        self.refresh()

    def save(self):
        if getattr(self,'closed',False) or self.job is not None:return
        try:
            if self.anchor is None: raise ValueError("Capture at least one tool first.")
            save_calibration(self.profile_key, self.positions, anchor=self.anchor)
            self.status.set("Application tool calibration saved.")
        except (OSError, ValueError) as error:
            self.status.set(f"Could not save: {error}")

    def close(self):
        if getattr(self,'closed',False):return
        self.closed=True
        if self.job is not None:
            try: self.root.after_cancel(self.job)
            except tk.TclError: pass
            self.job = None
        self.root.destroy()
        if self.on_close: self.on_close()
