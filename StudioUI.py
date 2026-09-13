"""Modern Image Draw Bot desktop interface.

The UI is deliberately state-driven: worker threads continue to communicate through
DrawBot's event queue and all widget updates happen on Tk's main loop. Heavy image
planning remains outside this module.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
from GameProfiles import PROFILES, profile_ui, profile_defaults
from ProfileEngine import PROFILE_ENGINE_MODES, policy_summary
from ProfilePortability import export_profile_dialog, import_profile_dialog, reset_profile_dialog
from EdgeBehavior import EDGE_BEHAVIOR_MODES
from Version import APP_VERSION
from PictureCustomPalette import start_picture_custom_palette
from UIState import compute_workspace_state, classify_error
from TimeBudget import TIME_BUDGET_MODES, TARGET_STROKE_COUNTS
from ProgressiveRenderer import PROGRESSIVE_RENDERING_MODES
from PlanningWatchdog import PLANNING_WATCHDOG_MODES
from ShapePaths import SHAPE_MODEL_MODES
from QuickSketchFillContour import QUICK_SKETCH_RENDER_STYLE, QUICK_SKETCH_STYLES, QUICK_SKETCH_FILL_PREFERENCES
from HybridRenderer3 import HYBRID_RENDER_STYLE, HYBRID_MODES
from SketchFillRenderer import SKETCH_FILL_RENDER_STYLE
from DrawingStyleProfiles import DRAWING_STYLES

BG = '#0b0f14'
SIDEBAR = '#101722'
PANEL = '#151d29'
PANEL_ALT = '#1b2635'
FIELD = '#202c3d'
FIELD_HOVER = '#2b3a50'
TEXT = '#f4f7fb'
MUTED = '#94a3b8'
ACCENT = '#72e2bd'
ACCENT_DARK = '#214c40'
PREVIEW = '#0d131d'
LINE = '#2a384b'
SUCCESS = '#54d39f'
WARNING = '#f0c66b'
ERROR = '#ff7d90'
INFO = '#73b8ff'


class ToolTip:
    """Small delayed hover tooltip for CustomTkinter/Tk widgets."""
    def __init__(self, widget, text, delay=450):
        self.widget=widget; self.text=str(text); self.delay=int(delay); self.job=None; self.window=None
        widget.bind('<Enter>', self._enter, add='+'); widget.bind('<Leave>', self._leave, add='+')
        widget.bind('<ButtonPress>', self._leave, add='+')
        widget.bind('<Destroy>', self._leave, add='+')
        widget.bind('<FocusIn>', self._enter, add='+')
        widget.bind('<FocusOut>', self._leave, add='+')
    def _enter(self, _event=None):
        self._cancel()
        try:self.job=self.widget.after(self.delay,self._show)
        except Exception:self.job=None
    def _cancel(self):
        if self.job is not None:
            try:self.widget.after_cancel(self.job)
            except Exception:pass
            self.job=None
    def _leave(self, _event=None):
        self._cancel()
        if self.window is not None:
            try:self.window.destroy()
            except Exception:pass
            self.window=None
    def _show(self):
        self.job=None
        if self.window is not None:return
        try:
            x=self.widget.winfo_rootx()+18; y=self.widget.winfo_rooty()+self.widget.winfo_height()+7
            win=tk.Toplevel(self.widget); win.wm_overrideredirect(True); win.wm_geometry(f'{x:+d}{y:+d}')
            label=tk.Label(win,text=self.text,justify='left',background='#202c3d',foreground='#f4f7fb',
                           relief='solid',borderwidth=1,font=('Segoe UI',9),padx=8,pady=6,wraplength=360)
            label.pack(); self.window=win
            win.update_idletasks()
            left=self.widget.winfo_vrootx(); top=self.widget.winfo_vrooty()
            right=left+self.widget.winfo_vrootwidth(); bottom=top+self.widget.winfo_vrootheight()
            x=max(left,min(x,right-win.winfo_reqwidth()-8))
            y=max(top,min(y,bottom-win.winfo_reqheight()-8))
            win.wm_geometry(f'{x:+d}{y:+d}')
        except Exception:self.window=None


def tooltip(widget, text):
    widget._image_draw_bot_tooltip = ToolTip(widget,text); return widget


def button(parent, text, command, primary=False, danger=False, **kwargs):
    defaults = dict(
        height=42, corner_radius=11, border_width=1,
        border_color=ACCENT if primary else (ERROR if danger else LINE),
        fg_color=ACCENT if primary else ('#40242e' if danger else FIELD),
        hover_color='#a3efd8' if primary else ('#5b2e3a' if danger else FIELD_HOVER),
        text_color='#102d25' if primary else ('#ffd2da' if danger else TEXT),
        text_color_disabled='#64748b', font=('Segoe UI', 12, 'bold'))
    defaults.update(kwargs)
    return ctk.CTkButton(parent, text=text, command=command, **defaults)


def build_ui(a, quality, speed):
    root = a.root
    ctk.set_appearance_mode('dark')
    root.configure(bg=BG)
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    width = min(1560, max(1120, screen_w - 70))
    height = min(960, max(720, screen_h - 90))
    root.geometry(f'{width}x{height}')
    root.minsize(1080, 700)

    style = ttk.Style(root)
    for name in ('TFrame', 'TLabel', 'TLabelframe', 'TLabelframe.Label'):
        style.configure(name, background=PANEL, foreground=TEXT)
    style.configure('Treeview', background=FIELD, fieldbackground=FIELD,
                    foreground=TEXT, rowheight=30, borderwidth=0)
    style.configure('Treeview.Heading', background=PANEL, foreground=TEXT, padding=8)
    style.map('Treeview', background=[('selected', ACCENT_DARK)])
    style.configure('Horizontal.TProgressbar', background=ACCENT,
                    troughcolor=FIELD, borderwidth=0, thickness=5)
    style.configure('ImageDrawBot.TCombobox', fieldbackground=FIELD, background=FIELD,
                    foreground=TEXT, arrowcolor=TEXT, padding=8)
    style.map('ImageDrawBot.TCombobox', fieldbackground=[('readonly', FIELD)],
              foreground=[('readonly', TEXT)], selectbackground=[('readonly', FIELD)],
              selectforeground=[('readonly', TEXT)])

    def frame(parent, color='transparent', radius=16, **kw):
        return ctk.CTkFrame(parent, fg_color=color, corner_radius=radius, **kw)

    def label(parent, text='', var=None, size=12, bold=False, muted=False, **kw):
        opts = dict(font=('Segoe UI', size, 'bold' if bold else 'normal'),
                    text_color=MUTED if muted else TEXT, anchor='w', justify='left')
        opts.update(kw)
        return ctk.CTkLabel(parent, text=text, textvariable=var, **opts)

    def control(widget, normal_state='normal'):
        a.controls.append((widget, normal_state))
        return widget

    def btn(parent, text, command, primary=False, **kw):
        return control(button(parent, text, command, primary=primary, **kw))

    def entry(parent, var, width=180):
        return control(ctk.CTkEntry(parent, textvariable=var, width=width, height=39,
                                    corner_radius=9, fg_color=FIELD, border_color=LINE,
                                    text_color=TEXT, font=('Segoe UI', 12)))

    def menu(parent, var, values, command=None, width=190):
        return control(ctk.CTkOptionMenu(
            parent, variable=var, values=list(values),
            command=command or (lambda _value: a.options_changed()), width=width,
            height=39, corner_radius=9, fg_color=FIELD, button_color=FIELD,
            button_hover_color=FIELD_HOVER, dropdown_fg_color=PANEL,
            dropdown_hover_color=FIELD_HOVER, text_color=TEXT,
            font=('Segoe UI', 11)))

    def separator(parent, pady=10):
        item = frame(parent, LINE, radius=0, height=1)
        item.pack(fill='x', pady=pady)
        return item

    def setting_row(parent, title, var, values, help_text='', width=178):
        row = frame(parent)
        row.pack(fill='x', pady=5)
        text = frame(row)
        text.pack(side='left', fill='x', expand=True)
        from GettingStarted import explain
        from tkinter import messagebox
        explanation = explain(title, help_text)
        heading = frame(text)
        heading.pack(fill='x')
        title_label = label(heading, title, bold=True, size=11, wraplength=145)
        title_label.pack(side='left')
        tooltip(title_label, explanation)
        help_button = ctk.CTkButton(heading, text='?', width=24, height=24,
            fg_color=FIELD, hover_color=LINE,
            command=lambda: messagebox.showinfo(title, explanation, parent=root))
        help_button.pack(side='left', padx=5)
        tooltip(help_button, 'Click for an explanation and practical advice.')
        if help_text:
            label(text, help_text, muted=True, size=10, wraplength=185).pack(anchor='w', pady=(2, 0))
        widget = menu(row, var, values, width=width)
        widget.pack(side='right', padx=(8, 0))
        tooltip(widget, explanation)
        widget._setting_row = row
        return widget

    def numeric_row(parent, title, var, help_text='', width=82):
        row = frame(parent)
        row.pack(fill='x', pady=5)
        text = frame(row)
        text.pack(side='left', fill='x', expand=True)
        from GettingStarted import explain
        from tkinter import messagebox
        explanation = explain(title, help_text)
        heading = frame(text)
        heading.pack(fill='x')
        title_label = label(heading, title, bold=True, size=11, wraplength=145)
        title_label.pack(side='left')
        tooltip(title_label, explanation)
        help_button = ctk.CTkButton(heading, text='?', width=24, height=24,
            fg_color=FIELD, hover_color=LINE,
            command=lambda: messagebox.showinfo(title, explanation, parent=root))
        help_button.pack(side='left', padx=5)
        tooltip(help_button, 'Click for an explanation and practical advice.')
        if help_text:
            label(text, help_text, muted=True, size=10, wraplength=190).pack(anchor='w', pady=(2, 0))
        field = entry(row, var, width)
        field.pack(side='right', padx=(8, 0))
        field.bind('<FocusOut>', a.options_changed)
        field.bind('<Return>', a.options_changed)
        tooltip(field, explanation)
        return field

    # ---- Top bar ---------------------------------------------------------
    header = frame(root)
    header.pack(fill='x', padx=22, pady=(18, 10))
    from AppBranding import header_image
    a.brand_icon = header_image(42)
    logo = label(header, '', image=a.brand_icon, width=42, height=42, anchor='center')
    logo.pack(side='left', padx=(0, 11))
    title = frame(header)
    title.pack(side='left')
    label(title, 'Image Draw Bot', size=23, bold=True).pack(side='left')
    label(title, APP_VERSION, size=9, bold=True, fg_color=FIELD, corner_radius=8,
          width=96, height=24, anchor='center').pack(side='left', padx=(9, 0))

    top_state = label(header, 'Not ready', size=11, bold=True, fg_color=FIELD,
                      corner_radius=10, width=112, height=32, anchor='center')
    top_state.pack(side='left', padx=(16, 0))
    profile_pill = label(header, 'Other drawing app', size=10, muted=True,
                         fg_color=SIDEBAR, corner_radius=9, width=150, height=30,
                         anchor='center')
    profile_pill.pack(side='left', padx=(8, 0))

    btn(header, 'ℹ  About', a.show_about, width=76, height=34).pack(side='right')
    guide_btn=btn(header, '❔  Get started', a.show_welcome, width=112, height=34); guide_btn.pack(side='right', padx=(0, 8)); tooltip(guide_btn,'Learn target setup, drawing modes, previews and troubleshooting.')
    wizard_btn=btn(header, '🧭  Setup wizard', a.show_beginner_setup_wizard, width=126, height=34); wizard_btn.pack(side='right', padx=(0, 8)); tooltip(wizard_btn,'Step 20: show exactly what is missing before Start. No mouse input is used.')
    tools_button = button(header, '🧰  Tools', lambda: None, width=78, height=34)
    tools_button.pack(side='right', padx=(0, 8))

    # ---- Fixed action/status bar ----------------------------------------
    footer = frame(root, PANEL, border_width=1, border_color=LINE, radius=14)
    footer.pack(side='bottom', fill='x', padx=22, pady=(10, 16))
    footer_row = frame(footer)
    footer_row.pack(fill='x', padx=15, pady=(11, 7))
    a.start = btn(footer_row, '🔒  Start locked', a.start_full_drawing, True,
                  width=152, height=45, state='disabled')
    a.start.pack(side='right', padx=(9, 0))
    a.start_unlock = btn(footer_row, '🔓  Unlock full drawing', a.unlock_full_drawing, False,
                         width=164, height=39, state='disabled')
    a.start_unlock.pack(side='right', padx=(8, 0))
    a.dry_run_button = btn(footer_row, '🖱️  Fast Dry run · ≤12s', a.run_dry_run, False,
                           width=148, height=39, state='disabled')
    a.dry_run_button.pack(side='right', padx=(8, 0))
    a.safety_preflight_button = btn(footer_row, '🛡️  Safety preflight', a.run_safety_preflight, False,
                                    width=142, height=39, state='disabled')
    a.safety_preflight_button.pack(side='right', padx=(8, 0))
    a.target_lock_button = btn(footer_row, '🔒  Lock setup', a.lock_setup, False,
                               width=118, height=39, state='disabled')
    a.target_lock_button.pack(side='right', padx=(8, 0))
    tooltip(a.target_lock_button,'Lock target window/canvas geometry after the small drawing test. Any important setup change invalidates this lock.')
    tooltip(a.safety_preflight_button,'Read-only target verification. No clicks are sent.')
    tooltip(a.dry_run_button,'Simulates representative cursor paths without clicking. Required before full drawing.')
    tooltip(a.start_unlock,'Temporary second confirmation. It does not disable CanvasGuard.')
    tooltip(a.start,'Starts real mouse drawing only after all safety gates are valid. Esc stops immediately.')
    button(footer_row, '⛔  Stop · Esc', a.cancel, danger=True, width=108, height=39).pack(side='right')
    a.pause_button = button(footer_row, '⏸  Pause · F6', a.toggle_pause,
                            width=108, height=39, state='disabled')
    a.pause_button.pack(side='right', padx=8)
    footer_status = label(footer_row, var=a.status, muted=True, wraplength=720, size=11)
    footer_status.pack(side='left', fill='x', expand=True)
    a.progress = ttk.Progressbar(footer, maximum=100)
    a.progress.pack(fill='x', padx=15, pady=(0, 10))

    # ---- Three-column workspace ----------------------------------------
    main = frame(root)
    main.pack(fill='both', expand=True, padx=22)
    main.grid_columnconfigure(0, weight=0, minsize=330)
    main.grid_columnconfigure(1, weight=1, minsize=480)
    main.grid_columnconfigure(2, weight=0, minsize=286)
    main.grid_rowconfigure(0, weight=1)

    # LEFT: step-by-step workflow.
    sidebar_shell = frame(main, SIDEBAR, border_width=1, border_color=LINE, radius=15)
    sidebar_shell.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
    sidebar = ctk.CTkScrollableFrame(sidebar_shell, fg_color=SIDEBAR, corner_radius=13,
                                     width=306, scrollbar_button_color=FIELD,
                                     scrollbar_button_hover_color=FIELD_HOVER)
    sidebar.pack(fill='both', expand=True, padx=5, pady=6)

    step_dots = {}
    step_headers = {}
    def step_card(number, title_text, subtitle='', icon='•'):
        card = frame(sidebar, PANEL, border_width=1, border_color=LINE, radius=13)
        card.pack(fill='x', padx=6, pady=6)
        head = frame(card)
        head.pack(fill='x', padx=12, pady=(11, 7))
        dot = label(head, icon, size=15, bold=True, fg_color=FIELD,
                    width=34, height=34, corner_radius=10, anchor='center')
        dot.pack(side='left', padx=(0, 8)); step_dots[number] = dot
        text = frame(head); text.pack(side='left', fill='x', expand=True)
        title_label=label(text, f'{number}. {title_text}', bold=True, size=13)
        title_label.pack(anchor='w')
        subtitle_label=label(text, subtitle, muted=True, size=9, wraplength=235)
        if subtitle: subtitle_label.pack(anchor='w', pady=(1, 0))
        step_headers[number]=(title_label,subtitle_label)
        body = frame(card)
        body.pack(fill='x', padx=12, pady=(0, 12))
        return body

    step1 = step_card(1, 'Choose target app', 'Pick the app/game you want Image Draw Bot to draw into.', '🎯')
    a.profile_selector = ttk.Combobox(step1, textvariable=a.game, values=list(PROFILES),
                                      state='readonly', style='ImageDrawBot.TCombobox',
                                      font=('Segoe UI', 11), height=10)
    a.profile_selector.pack(fill='x', ipady=5)
    a.profile_selector.bind('<<ComboboxSelected>>', lambda _event: a.change_profile())
    a.controls.append((a.profile_selector, 'readonly'))
    btn(step1, '➕  Custom app profile', a.add_profile, height=32).pack(fill='x', pady=(7, 5))
    profile_io = frame(step1)
    profile_io.pack(fill='x', pady=(0, 5))
    export_btn = btn(profile_io, '⇧  Export', lambda: export_profile_dialog(a), height=31, width=125)
    export_btn.pack(side='left', fill='x', expand=True, padx=(0, 4))
    import_btn = btn(profile_io, '⇩  Import', lambda: import_profile_dialog(a), height=31, width=125)
    import_btn.pack(side='left', fill='x', expand=True, padx=(4, 0))
    reset_profile_btn = btn(step1, '↺  Reset profile to defaults', lambda: reset_profile_dialog(a), height=31)
    reset_profile_btn.pack(fill='x', pady=(0, 5))
    tooltip(export_btn, 'Step 27: export only this profile to a portable .drawprofile/JSON file. Hardware/timing state and input authorization are excluded.')
    tooltip(import_btn, 'Step 27: validate and import a .drawprofile. Existing names can be replaced or imported as an isolated copy.')
    tooltip(reset_profile_btn, 'Delete only this profile’s saved settings/calibration/cache files and restore Image Draw Bot defaults. Other profiles are untouched.')
    label(step1, var=a.profile_hint, muted=True, wraplength=270, size=9).pack(anchor='w')
    profile_guide = frame(step1, PANEL_ALT, border_width=1, border_color=LINE, radius=10)
    profile_guide.pack(fill='x', pady=(7, 2))
    profile_guide_head=frame(profile_guide);profile_guide_head.pack(fill='x', padx=9, pady=(8, 2))
    profile_guide_icon=label(profile_guide_head, '🧩', size=16, width=26, anchor='center');profile_guide_icon.pack(side='left')
    profile_guide_badge=label(profile_guide_head, 'Profile guide', size=9, bold=True, text_color=ACCENT);profile_guide_badge.pack(side='left', padx=(5,0))
    profile_guide_tip=label(profile_guide, '', muted=True, wraplength=245, size=9)
    profile_guide_tip.pack(anchor='w', padx=10, pady=(2, 4))
    profile_guide_recommend=label(profile_guide, '', size=9, text_color=ACCENT, wraplength=245)
    profile_guide_recommend.pack(anchor='w', padx=10, pady=(0, 9))
    a.paint_check = control(ctk.CTkSwitch(step1, text='Single-color sketch (current ink)',
                                         variable=a.paint_simple, command=a.paint_mode_changed,
                                         progress_color=ACCENT_DARK, text_color=TEXT,
                                         font=('Segoe UI', 10)))
    a.paint_check.pack(fill='x', pady=(8, 2))
    tooltip(a.paint_check,'Works in Paint and drawing games, including Gartic. Select black in the target app first. Uses current ink without palette clicks or palette calibration; game profiles use simple contours.')
    a.paint_tool_menu = menu(step1, a.paint_tool,
                             ['Auto (recommended)', 'Use current tool', 'Brush', 'Pencil', 'Eraser'],
                             lambda _value: a.paint_tool_changed(), width=272)
    a.paint_tool_menu.pack(fill='x', pady=(3, 0)); a.paint_tool_menu.configure(state='disabled')
    a.paint_tool_label=label(step1, var=a.paint_tool_text, muted=True, wraplength=270, size=9)
    a.paint_tool_label.pack(anchor='w', pady=(5, 0))

    step2 = step_card(2, 'Add image', 'Choose, paste, drop or load a direct image URL.', '🖼️')
    row = frame(step2); row.pack(fill='x')
    select_image_btn=btn(row, '🖼️  Select image', a.open_file, True, height=37); select_image_btn.pack(side='left', fill='x', expand=True)
    tooltip(select_image_btn,'Choose the source image. It starts drawing only when one-shot Drop-In Start is explicitly armed.')
    btn(row, '📋  Paste', a.paste_image, width=70, height=37).pack(side='left', padx=(6, 0))
    image_tools = frame(step2); image_tools.pack(fill='x', pady=(7, 0))
    bg_btn=btn(image_tools, '✂  Remove BG', a.remove_image_background, width=104, height=34);bg_btn.pack(side='left',fill='x',expand=True)
    tooltip(bg_btn,'Auto-remove only border-connected background and convert it to transparency. Transparent pixels generate no drawing strokes.')
    undo_bg=btn(image_tools, '↶  Undo', a.undo_background_removal, width=70, height=34);undo_bg.pack(side='left',padx=(6,0))
    tooltip(undo_bg,'Restore the image from before background removal.')
    png_btn=btn(image_tools, 'PNG', a.save_png_copy, width=58, height=34);png_btn.pack(side='left',padx=(6,0))
    tooltip(png_btn,'Export the current image as a lossless RGBA PNG, preserving transparency.')
    url_row = frame(step2)
    url_row.pack(fill='x', pady=(7, 0))
    url_field = entry(url_row, a.url, 165); url_field.pack(side='left', fill='x', expand=True)
    btn(url_row, '🌐  Load URL', a.fetch_url, width=82, height=37).pack(side='left', padx=(6, 0))
    url_field.bind('<Return>', lambda _e: a.fetch_url() if not a.activity else None)
    label(step2, var=a.file_label, muted=True, wraplength=270, size=9).pack(anchor='w', pady=(7, 0))
    clear_row=frame(step2);clear_row.pack(fill='x',pady=(6,0))
    button(clear_row,'Clear image',a.clear_image,height=32,width=95).pack(side='left',fill='x',expand=True)
    button(clear_row,'Clear cached drawing',a.clear_cached_drawing,height=32,width=150).pack(side='left',fill='x',expand=True,padx=(5,0))
    upscale_row=frame(step2); upscale_row.pack(fill='x',pady=(7,0))
    btn(upscale_row,'Upscale image…',a.upscale_dialog,height=34).pack(side='left',fill='x',expand=True)
    btn(upscale_row,'Undo',a.undo_upscale,width=65,height=34).pack(side='right',padx=(6,0))
    one_click=control(ctk.CTkSwitch(step2, text='Browser One-Click Mode', variable=a.browser_one_click_enabled, command=a.options_changed, fg_color=ACCENT, progress_color=ACCENT, button_color='#e8fff7', button_hover_color='#ffffff', text_color=TEXT)); one_click.pack(anchor='w', pady=(7,0))
    tooltip(one_click,'Supported browser games only: add an image and Image Draw Bot automatically finds/reuses the game window, detects canvas/palette, checks brush controls and runs visual preflight before drawing. Paint is never auto-started.')
    a.browser_one_click_label=label(step2, var=a.browser_one_click_text, muted=True, wraplength=270, size=9)
    a.browser_one_click_label.pack(anchor='w', pady=(3,0))
    a.drop_in_button=btn(step2, '⚡  Arm Drop-In Start', a.arm_manual_drop_in, height=34)
    a.drop_in_button.pack(fill='x', pady=(7, 0))
    tooltip(a.drop_in_button,'One-shot browser/game mode. On Gartic Phone this also arms a temporary drop listener over the detected game canvas, so a Google/Chrome image can be released directly on Gartic and start when setup is safe. Paint keeps its normal guarded flow.')
    label(step2, var=a.drop_in_text, muted=True, wraplength=270, size=9).pack(anchor='w', pady=(4, 0))
    a.smart_drop_button=btn(step2, '🎯  Arm game canvas image drop', a.arm_smart_canvas_drop, height=34)
    a.smart_drop_button.pack(fill='x', pady=(7, 0))
    tooltip(a.smart_drop_button,'Supported browser games: places a temporary 60-second drop target exactly over the detected drawable canvas. Drag an image from Google Images/Chrome/Edge or File Explorer onto the canvas; Image Draw Bot imports it, re-verifies canvas/palette and starts drawing automatically. CanvasGuard/preflight still apply.')
    label(step2, var=a.smart_drop_in_text, muted=True, wraplength=270, size=9).pack(anchor='w', pady=(4, 0))
    a.auto_clear_switch=control(ctk.CTkSwitch(step2, text='Auto clear target canvas before full drawing', variable=a.auto_clear_canvas, command=a.canvas_clear_changed, fg_color=ACCENT, progress_color=ACCENT, button_color='#e8fff7', button_hover_color='#ffffff', text_color=TEXT))
    a.auto_clear_switch.pack(anchor='w', pady=(9,0))
    tooltip(a.auto_clear_switch,'Opt-in destructive prelude. Paint uses Select All/Delete. Drawing games use a calibrated Clear canvas control, or a CanvasGuard-bounded Eraser sweep when Brush + Eraser are calibrated. Never erases during Small Test, never clicks in Dry Run, and never clears a compatible resume.')
    label(step2, var=a.canvas_clear_text, muted=True, wraplength=270, size=9).pack(anchor='w', pady=(3,0))
    image_info = label(step2, 'No image information yet.', muted=True, size=9, wraplength=270)
    image_info.pack(anchor='w', pady=(2, 0))

    step3 = step_card(3, 'Prepare target app', 'One-click Setup detects and independently verifies canvas/palette; manual calibration remains fallback.', '🧰')
    a.one_click_setup_button=btn(step3,'⚡  One-click Setup + Verify',a.run_one_click_setup_verify,True,height=39)
    a.one_click_setup_button.pack(fill='x',pady=(0,5))
    tooltip(a.one_click_setup_button,'Step 27.5: Microsoft Paint and supported browser games. Detect/reuse the target, calibrate canvas/palette, then run a second independent live verification pass. Setup never starts drawing or unlocks mouse input.')
    a.one_click_setup_label=label(step3,var=a.one_click_setup_text,muted=True,wraplength=270,size=9)
    a.one_click_setup_label.pack(anchor='w',pady=(0,7))
    a.gartic_setup_button=btn(step3,'Auto setup Gartic — full canvas',a.auto_setup_gartic_full,height=35)
    a.gartic_setup_button.pack(fill='x',pady=(0,6))
    a.paint_auto_button = btn(step3, '✨  Prepare Paint automatically', a.auto_calibrate_paint_tools, height=35)
    a.paint_auto_button.pack(fill='x'); a.paint_auto_button.configure(state='disabled')
    a.paint_tool_button = btn(step3, '🖌  Manual Paint calibration', a.calibrate_paint_tools, height=34)
    a.paint_tool_button.pack(fill='x', pady=(6,0)); a.paint_tool_button.configure(state='disabled')
    a.browser_auto_button = btn(step3, '✨  Auto setup browser', a.auto_calibrate_browser_profile, height=36)
    a.browser_auto_button.pack(fill='x', pady=(6, 0)); a.browser_auto_button.configure(state='disabled')
    tooltip(a.browser_auto_button,'Gartic Phone, Skribbl.io/Fast and SketchHeads: automatically detect/verify palette and safe canvas. Before drawing, Image Draw Bot read-only re-scans after Chrome zoom, resize, window movement or DPI changes. No calibration clicks are generated.')
    a.browser_auto_label=label(step3, var=a.browser_auto_text, muted=True, wraplength=270, size=9)
    a.browser_auto_label.pack(anchor='w', pady=(4, 2))
    a.app_tool_button = btn(step3, '🧰  Calibrate Brush / Fill / Eraser / Clear', a.calibrate_app_tools, height=34)
    a.app_tool_button.pack(fill='x', pady=(6, 0)); a.app_tool_button.configure(state='disabled')
    a.app_tool_label=label(step3, var=a.app_tool_text, muted=True, wraplength=270, size=9)
    a.app_tool_label.pack(anchor='w', pady=(4, 4))
    a.palette_button = btn(step3, '🎨  Read colors / palette', a.calibrate, height=35)
    a.palette_button.pack(fill='x', pady=(2, 0))
    tooltip(a.palette_button,'Read/calibrate the target app palette. Re-run after palette/layout changes.')
    label(step3, var=a.palette_text, muted=True, wraplength=270, size=9).pack(anchor='w', pady=(4, 4))
    a.picture_palette_button = btn(step3, '🖼  Custom color palette for picture', lambda: start_picture_custom_palette(a), height=34)
    a.picture_palette_button.pack(fill='x', pady=(2, 0))
    tooltip(a.picture_palette_button, 'Microsoft Paint: calibrate RGB automatically, save image colors with + and a pause between colors, then Build preview. The preview and drawing use this same picture palette.')
    a.area_button = btn(step3, '▣  Select drawing area', a.set_boundary, height=37)
    a.area_button.pack(fill='x', pady=(2, 0))
    tooltip(a.area_button,'Select ONLY the drawable canvas. CanvasGuard treats this as a hard boundary for every drawing path and Fill action.')
    label(step3, var=a.area_text, muted=True, wraplength=270, size=9).pack(anchor='w', pady=(4, 3))
    a.reuse = btn(step3, '↩  Use saved drawing area', a.reuse_area, height=32)
    a.reuse.pack(fill='x', pady=(0, 6))
    row = frame(step3); row.pack(fill='x')
    btn(row, '🖱️  Test mouse', a.test_mouse, height=34).pack(side='left', fill='x', expand=True)
    btn(row, '🧪  Small test', lambda: a.draw(test=True, user_initiated=True), height=34).pack(side='left', fill='x', expand=True, padx=(6, 0))
    label(step3, var=a.target_lock_text, muted=True, wraplength=270, size=9).pack(anchor='w', pady=(7, 0))

    step4 = step_card(4, 'Configure drawing', 'Simple shows essentials; Advanced/Developer reveal tuning and diagnostics.', '⚙️')
    a.ui_mode = tk.StringVar(value='Simple')
    mode_switch = ctk.CTkSegmentedButton(step4, values=['Simple', 'Advanced', 'Developer'],
                                         variable=a.ui_mode, selected_color=ACCENT_DARK,
                                         selected_hover_color='#2d6756', unselected_color=FIELD,
                                         unselected_hover_color=FIELD_HOVER, text_color=TEXT,
                                         font=('Segoe UI', 10, 'bold'), height=34)
    mode_switch.pack(fill='x', pady=(0, 7))
    preset_menu=setting_row(step4,'Drawing preset',a.render_preset,['Auto','Manual','Masterpiece','Extra fast'],'Extra fast draws closed contours, fills safe areas, then draws remaining detail. Calibrate Brush and Fill to enable buckets. Auto selects an engine; Masterpiece uses unlimited time.',width=160)
    preset_menu.configure(command=a.render_preset_changed)
    style_profile_menu=setting_row(step4,'Drawing style profile',a.drawing_style,DRAWING_STYLES,
        'Auto classifies the source. Pixel Art protects exact pixels; Logo prioritizes Fill + clean regions; Portrait protects faces/details; Photo/Shaded preserves tonal structure; Line Art protects thin contours; Cartoon/Illustration uses flat regions + outlines.',width=178)
    sketch_switch=control(ctk.CTkSwitch(step4,text='Black contour sketch',variable=a.outline,
        command=a.sketch_mode_changed,progress_color=ACCENT_DARK,text_color=TEXT))
    sketch_switch.pack(anchor='w',pady=(0,8))
    tooltip(sketch_switch,'Simple black outlines, no shading or colour fills. Uses a calibrated black swatch. For Single-color sketch, select black in the app/game yourself first. Turn off to return to colour drawing.')
    setting_row(step4, 'Sketch detail', a.sketch_detail, ['Auto','Simple','Balanced','Detailed'],
                'Auto fits detail to the available time. Gartic timer reading runs at Start when enabled; preview before Start uses the manual budget.', width=160)
    timer_switch=control(ctk.CTkSwitch(step4,text='Read Gartic timer at Start',variable=a.read_gartic_timer,command=a.options_changed,progress_color=ACCENT_DARK,text_color=TEXT))
    timer_switch.pack(anchor='w',pady=(0,8))
    tooltip(timer_switch,'Gartic Phone only: watch the round pie timer for about 6 seconds at Start to estimate remaining time. Keep it visible. Uncertain readings stop Start; turn this off to use a manual time budget.')
    setting_row(step4, 'Quality preset', a.quality, list(quality), width=160)
    numeric_row(step4, 'Brush width', a.brush_px, 'Auto chooses from Gartic levels 1–5. Other profiles keep their normal pixel-width range.', width=84)
    a.gartic_opacity_menu = setting_row(step4, 'Gartic opacity', a.gartic_opacity,
        ['Auto','10%','20%','30%','40%','50%','60%','70%','80%','90%','100%'],
        'Auto analyzes edges, color complexity and smooth shading. Low opacity is used only when it can improve tonal likeness.', width=118)
    a.gartic_opacity_row = getattr(a.gartic_opacity_menu, '_setting_row', a.gartic_opacity_menu)
    focus_menu = setting_row(step4, 'Subject focus', a.subject_focus,
                             ['Off', 'Subject first', 'Subject only'],
                             'Pixel Accurate · 1 px pencil. No AI detection.', width=160)
    focus_menu.configure(command=a.subject_focus_changed)
    focus_buttons = frame(step4); focus_buttons.pack(fill='x', pady=4)
    btn(focus_buttons, 'Mark subject…', a.mark_subject, height=32).pack(side='left', fill='x', expand=True)
    btn(focus_buttons, 'Auto', a.reset_subject, height=32, width=65).pack(side='right', padx=(6,0))
    btn(step4, 'Check subject mask', a.preview_subject, height=32).pack(fill='x', pady=4)
    label(step4, var=a.subject_hint, muted=True, wraplength=270, size=10).pack(anchor='w')


    advanced_host = frame(step4)
    developer_host = frame(step4)

    def collapsible(parent, title_text, hint, expanded=False):
        shell = frame(parent, PANEL_ALT, border_width=1, border_color=LINE, radius=11)
        shell.pack(fill='x', pady=5)
        body = frame(shell)
        state = {'open': expanded, 'job': None}
        toggle = button(shell, ('▾  ' if expanded else '›  ') + title_text, lambda: None,
                        width=270, height=35, anchor='w', fg_color='transparent',
                        hover_color=FIELD, border_width=0, font=('Segoe UI', 11, 'bold'))
        toggle.pack(fill='x', padx=5, pady=(4, 0))
        label(shell, hint, muted=True, size=9, wraplength=250).pack(anchor='w', padx=12, pady=(0, 4))
        if expanded: body.pack(fill='x', padx=10, pady=(2, 10))
        def apply_toggle():
            state['job'] = None
            if state['open']:
                body.pack_forget(); state['open'] = False; toggle.configure(text='›  ' + title_text)
            else:
                body.pack(fill='x', padx=10, pady=(2, 10)); state['open'] = True; toggle.configure(text='▾  ' + title_text)
        def request_toggle():
            if state['job'] is None:
                try: state['job'] = root.after_idle(apply_toggle)
                except tk.TclError: state['job'] = None
        toggle.configure(command=request_toggle)
        return body

    quality_card = collapsible(advanced_host, '🎨  Quality', 'Rendering, detail and advanced color.', True)
    setting_row(quality_card, 'Profile policy', a.profile_engine, list(PROFILE_ENGINE_MODES), 'Auto applies the selected app renderer policy. Manual settings keeps your renderer choices unchanged; safety gates are unaffected.')
    setting_row(quality_card, 'Edge behavior', a.edge_behavior, list(EDGE_BEHAVIOR_MODES), 'Hard Clip skips unsafe edge strokes. Adaptive follows the safe inset when possible. Preserve Outline keeps near-edge contours without leaving Canvas Guard.')
    setting_row(quality_card, 'Rendering style', a.render_style, ['Auto', 'Portrait / shaded', 'Standard / pixel', QUICK_SKETCH_RENDER_STYLE, SKETCH_FILL_RENDER_STYLE, HYBRID_RENDER_STYLE], 'Quick Sketch uses verified closed-region Fill plus simplified visible contours for recognition-first 60–150s drawing. Unsafe regions stay connected scanlines.')
    setting_row(quality_card, 'Hybrid mode', a.hybrid_mode, list(HYBRID_MODES), 'Step 29: Auto Hybrid or a specialised deterministic mode for Pixel Art, Icon / Logo, Line Art, Portrait, Shaded Object or Deadline Silhouette. No AI/OCR; safety and calibration are unchanged.')
    setting_row(quality_card, 'Quick Sketch style', a.quick_sketch_style, list(QUICK_SKETCH_STYLES), 'Simple trims micro texture hardest; Detailed keeps more secondary structure. Used only by Quick Sketch or Auto Tuner when it selects Quick Sketch.')
    setting_row(quality_card, 'Quick Sketch fill', a.quick_sketch_fill_preference, list(QUICK_SKETCH_FILL_PREFERENCES), 'Safe Fill First searches more closed regions but still requires Region Fill safety + Safe Fill Mask. Scanline Preferred uses Fill only for the strongest candidates.')
    setting_row(quality_card, 'Draw quality', a.draw_quality, ['Balanced', 'High likeness', 'Maximum likeness', 'GPU enhanced', 'Pixel Accurate'])
    setting_row(quality_card, 'Detail level', a.quality, list(quality))
    setting_row(quality_card, 'Adaptive detail', a.adaptive_detail, ['Auto', 'Off', 'Preserve detail', 'Balanced', 'Strong simplify'], 'Protects high-contrast edges while simplifying flat texture. Auto adapts to image complexity.')
    setting_row(quality_card, 'Detail zoom', a.detail_zoom, ['Auto', 'Off', '2x', '4x'], 'Internally re-analyzes small source regions at 2x/4x and adds high-value micro-details. It never changes Paint/browser page zoom or canvas calibration.')
    setting_row(quality_card, 'Visual verification', a.visual_verification, ['Auto', 'Off', 'Fast', 'Balanced', 'Strict'], 'After each color batch, read the canvas and detect wrong color, missed regions, fill leaks or misplaced strokes. Auto = Balanced for Paint.')
    setting_row(quality_card, 'Color rendering', a.color_rendering, ['RGB nearest', 'Perceptual match', 'Layered color mix'])
    setting_row(quality_card, 'Color fidelity', a.color_fidelity, ['Fast', 'Balanced', 'Faithful', 'Exact'], 'Faithful preserves source lightness/saturation and avoids dark palette bias. Exact disables tone preference and keeps pure nearest-color behavior.')
    setting_row(quality_card, 'Color layers', a.color_layers, ['Off', 'Light shading', 'Dual-color mix', 'Full color mix'])
    setting_row(quality_card, 'Custom color workflow', a.custom_color_workflow, ['Adaptive exact (recommended)', 'Exact custom + palette fallback', 'Calibrated palette', 'Custom colors first', 'Custom colors only'])
    setting_row(quality_card, 'Exact color count', a.exact_color_limit, ['Auto', '8', '16', '24', '32'])
    setting_row(quality_card, 'Drawing mode', a.mode, ['Smart paths (recommended)', 'Shape paths', 'Lines (fastest)', 'Dots'], 'Shape paths is fastest for skribbl-style drawings; Smart paths stays more exact.')
    setting_row(quality_card, 'Shape order', a.shape_order, ['Fill first', 'Contour first'], 'Fill first makes images recognizable quickly; contour first keeps outlines clearer.')
    setting_row(quality_card, 'Shape model', a.shape_model, list(SHAPE_MODEL_MODES), 'Better shapes v2 uses smoother silhouettes and wider form fills. Fast raster keeps the older simple hatcher.')
    setting_row(quality_card, 'Max stroke cap', a.max_stroke_cap, ['Auto', '1000', '2500', '5000', '10000', 'Unlimited'], 'Hard cap for Shape paths before the global target count is applied.')
    setting_row(quality_card, 'Progressive renderer', a.progressive_rendering, list(PROGRESSIVE_RENDERING_MODES), 'Large forms first, important contours second, tiny details last.')
    setting_row(quality_card, 'Planning watchdog', a.planning_watchdog, list(PLANNING_WATCHDOG_MODES), 'Stops heavy final planning before mouse input and retries with safer fallback settings.')
    setting_row(quality_card, 'Preview mode', a.preview_mode, ['Manual', 'Auto light', 'Auto full'], 'Manual is recommended for stability.')
    setting_row(quality_card, 'Preview detail', a.preview_detail_level, ['Fast', 'Balanced', 'Detailed', 'Micro detail'], 'Detailed preserves eyes, pupils, thin contours and other small high-contrast features. Micro detail uses a heavier recovery pass.')

    precision_card = collapsible(advanced_host, 'Precision & Speed', 'Coordinate accuracy, cadence and time.', False)
    setting_row(precision_card, 'Precision', a.precision, ['Normal', 'High', 'Ultra'])
    setting_row(precision_card, 'Speed', a.speed, list(speed))
    setting_row(precision_card, 'Stroke optimizer', a.stroke_optimizer, ['Auto', 'Off', 'Travel only', 'Smart merge'], 'Smart merge reorders paths and joins only exact shared endpoints. It never draws a shortcut through empty canvas.')
    setting_row(precision_card, 'Time target', a.time_budget_mode, list(TIME_BUDGET_MODES), 'Game presets keep a safety reserve and fit the final execution plan to the usable deadline.')
    deadline_switch=control(ctk.CTkSwitch(precision_card,text='Adaptive deadline renderer',variable=a.adaptive_deadline_renderer,
        command=a.options_changed,progress_color=ACCENT_DARK,text_color=TEXT,font=('Segoe UI',10)))
    deadline_switch.pack(anchor='w',pady=(4,5))
    tooltip(deadline_switch,'Chooses the highest-value set of fills/strokes that fits the real render budget. It drops low-value detail before important silhouettes and can enter Panic Mode at runtime.')
    setting_row(precision_card, 'Safety reserve', a.deadline_safety_reserve, ['Auto','Off','3','5','7','8','10','12','15','20','25'], 'Seconds held back before the game deadline. Auto is recommended and scales with round time; Off is advanced/unsafe.')
    setting_row(precision_card, 'Target stroke count', a.target_stroke_count, list(TARGET_STROKE_COUNTS), 'Optional secondary cap. Auto follows the selected time target.')
    numeric_row(precision_card, 'Custom target strokes', a.target_stroke_custom, '50–50000, only used in Custom.', width=82)
    numeric_row(precision_card, 'Manual time limit (seconds)', a.max_seconds, 'Used by Manual or Custom time target.', width=74)
    btn(precision_card, 'Reset learned draw timing', a.reset_draw_time_calibration, height=32).pack(fill='x', pady=(5,2))

    smart_card = collapsible(advanced_host, 'Smart tools', 'Fill, background and color scheduling.', False)
    region_switch=control(ctk.CTkSwitch(
        smart_card, text='Use Region Fill Engine', variable=a.use_region_fill_engine,
        command=a.options_changed, progress_color=ACCENT_DARK, text_color=TEXT, font=('Segoe UI',10)))
    region_switch.pack(anchor='w', pady=(3,5))
    tooltip(region_switch,'Outline-first + fill-heavy planner. Closed connected regions are filled only when leak-risk and measured wall-clock cost are both safe; otherwise normal strokes/runs are kept.')
    setting_row(smart_card, 'Fill aggressiveness', a.fill_aggressiveness, ['Safe', 'Balanced', 'Aggressive'], 'Changes the safety/cost threshold only. Open contours, invalid seeds and hard leak risks can never be forced through.')
    setting_row(smart_card, 'Auto Fill', a.background_fill, ['Off', 'Conservative', 'Balanced', 'Aggressive'], 'Legacy/background fill policy. Region Fill Engine can still accelerate safe interior regions when this is Off.')
    setting_row(smart_card, 'Fill engine', a.fill_engine, ['Auto', 'Safe rectangles', 'Closed regions v2'])
    setting_row(smart_card, 'Background simplification', a.background_simplification, ['Off', 'Conservative', 'Balanced', 'Strong'])
    setting_row(smart_card, 'Color grouping', a.color_grouping, ['Accurate', 'Smart', 'Reduced palette'])
    setting_row(smart_card, 'Color workflow', a.color_workflow, ['Finish color first', 'Progressive passes'])
    label(smart_card, 'Finish color first paints every path of one color before selecting the next color.', muted=True, wraplength=510, size=9).pack(anchor='w', pady=(0, 4))
    setting_row(smart_card, 'Tool strategy', a.tool_strategy, ['Auto', 'Precision first', 'Speed first', 'Respect selected'])
    for text, var in (('Skip white', a.skip_white), ('Emphasize centered subject', a.portrait_focus)):
        control(ctk.CTkSwitch(smart_card, text=text, variable=var, command=a.options_changed,
                             progress_color=ACCENT_DARK, text_color=TEXT,
                             font=('Segoe UI', 10))).pack(anchor='w', pady=5)
    label(smart_card, 'Contrast', bold=True, size=10).pack(anchor='w', pady=(6, 1))
    control(ctk.CTkSlider(smart_card, from_=.5, to=2, variable=a.contrast,
                         command=a.options_changed, progress_color=ACCENT,
                         button_color=ACCENT, width=235)).pack(fill='x', pady=(2, 8))

    gpu_card = collapsible(advanced_host, 'GPU', 'Universal CUDA/OpenCL workload routing with safe CPU fallback.', False)
    setting_row(gpu_card, 'GPU acceleration', a.gpu_mode, ['Auto', 'CPU', 'NVIDIA CUDA'])
    setting_row(gpu_card, 'GPU performance', a.gpu_performance, ['Balanced', 'High throughput', 'Maximum'])
    setting_row(gpu_card, 'VRAM budget', a.gpu_vram, ['Auto', '25%', '50%', '75%', '90%', '2 GB', '4 GB', '6 GB', '8 GB', '12 GB', '16 GB', '24 GB'])
    label(gpu_card, 'Step 23: Auto uses the Step 22 benchmark to route OKLab, palette, ΔE, quantization, edge and pixel workloads independently to CUDA, OpenCL (AMD/Intel/NVIDIA) or CPU. NVIDIA CUDA still force-selects the legacy CUDA path where supported. Mouse drawing remains single-stream.', muted=True, size=9, wraplength=245).pack(anchor='w', pady=(2, 5))
    btn(gpu_card, '⚡  Benchmark NVIDIA / AMD / Intel', lambda: a.run_performance_auto_tuner(apply=False), height=33).pack(fill='x', pady=(5, 0))
    btn(gpu_card, 'Test selected compute backend', a.test_gpu_acceleration, height=33).pack(fill='x', pady=(5, 0))
    btn(gpu_card, 'Clear GPU cache', a.clear_gpu_cache, height=33).pack(fill='x', pady=(5, 0))

    resource_card = collapsible(advanced_host, 'CPU / RAM allocation', 'Controls planning workers, process strategy and memory budget.', False)
    setting_row(resource_card, 'CPU workers', a.cpu_workers, ['Auto', '1', '2', '4', '6', '8', '12', '16', '24', '32', 'All logical'], 'Auto uses most logical threads and leaves the UI responsive.')
    setting_row(resource_card, 'CPU engine', a.cpu_engine, ['Auto', 'Threads', 'Processes'], 'Processes can use more cores on large final plans but starts slower.')
    setting_row(resource_card, 'RAM budget', a.ram_budget, ['Auto', '512 MB', '1 GB', '2 GB', '4 GB', '8 GB', '12 GB', '16 GB', 'Custom'], 'Caps chunk/cache size for planning.')
    numeric_row(resource_card, 'Custom RAM (MB)', a.ram_custom_mb, 'Used only when RAM budget is Custom.', width=82)
    setting_row(resource_card, 'Planning resolution', a.planning_resolution, ['Auto', 'Standard', 'High', 'Ultra', 'Extreme'], 'Higher values make bigger source plans so CPU/GPU/RAM have real work to process.')
    setting_row(resource_card, 'Resource scheduler', a.resource_scheduler, ['Auto', 'Off', 'Benchmark recommendations'], 'Adaptive phase scheduler: CPU/SIMD for colors, GPU for matrix work when useful, capped CPU chunks for shapes/paths.')
    btn(resource_card, '🧠  Test CPU / RAM allocation', a.test_resource_allocation, height=33).pack(fill='x', pady=(5, 0))
    btn(resource_card, '📊  Run performance benchmark', a.run_performance_benchmark, height=33).pack(fill='x', pady=(5, 0))
    btn(resource_card, '🧪  Run Step 10 benchmark suite', a.run_benchmark_suite, height=33).pack(fill='x', pady=(5, 0))
    label(resource_card, var=a.benchmark_suite_text, muted=True, size=9, wraplength=245).pack(anchor='w', pady=(4,2))
    auto_tune_btn=btn(resource_card, '⚙  Universal Hardware Auto Benchmark', lambda: a.run_performance_auto_tuner(apply=True), height=35); auto_tune_btn.pack(fill='x', pady=(5, 0))
    tooltip(auto_tune_btn, 'Benchmarks CPU/RAM and usable NVIDIA/AMD/Intel CUDA/OpenCL backends locally, then applies a safe per-machine recommendation. Never arms mouse input.')

    dev_card = collapsible(developer_host, '🛠  Developer tools', 'Logs, reports, probes and diagnostics.', True)
    label(dev_card, 'Privacy: local diagnostics only. No telemetry or report-upload backend is included.', muted=True, size=9, wraplength=260).pack(anchor='w', pady=(0, 5))
    for text, command in (('Open logs / app data', a.open_app_data_folder),
                          ('Benchmark all hardware', lambda: a.run_performance_auto_tuner(apply=False)),
                          ('Test selected GPU backend', a.test_gpu_acceleration),
                          ('Test CPU / RAM allocation', a.test_resource_allocation),
                          ('Run performance benchmark', a.run_performance_benchmark),
                          ('Run Step 10 benchmark suite', a.run_benchmark_suite),
                          ('Run self-test', a.run_self_test),
                          ('Create diagnostics ZIP', a.collect_diagnostics),
                          ('Enable Windows .dmp', a.enable_crash_dumps)):
        btn(dev_card, text, command, height=32).pack(fill='x', pady=3)

    def apply_ui_mode(*_):
        mode = a.ui_mode.get()
        advanced_host.pack_forget(); developer_host.pack_forget()
        if mode in ('Advanced', 'Developer'):
            advanced_host.pack(fill='x', pady=(5, 0))
        if mode == 'Developer':
            developer_host.pack(fill='x', pady=(5, 0))
    a.ui_mode.trace_add('write', lambda *_: root.after_idle(apply_ui_mode))
    apply_ui_mode()

    step5 = step_card(5, 'Safety & draw', 'Build preview when wanted, then pass each safety gate before full drawing.', '▶️')
    wizard_status=label(step5, var=a.setup_wizard_text, fg_color=FIELD, corner_radius=8, text_color=ACCENT, size=9, wraplength=260)
    wizard_status.pack(fill='x', pady=(0, 6), ipady=5)
    wizard_open_btn=btn(step5, '🧭  Open setup wizard', a.show_beginner_setup_wizard, height=34)
    wizard_open_btn.pack(fill='x', pady=(0, 7)); tooltip(wizard_open_btn,'Shows target-specific missing requirements, warnings and the next safe action before Start.')
    plan_metrics = label(step5, 'No plan yet.', muted=True, size=9, wraplength=270)
    plan_metrics.pack(anchor='w', pady=(0, 4))
    color_plan = label(step5, a.color_plan_text, muted=True, size=9, wraplength=270)
    color_plan.pack(anchor='w', pady=(0, 3))
    draw_time_side = label(step5, a.draw_time_text, muted=True, size=9, wraplength=270)
    draw_time_side.pack(anchor='w', pady=(0, 3))
    draw_live_side = label(step5, a.draw_live_time_text, muted=True, size=9, wraplength=270)
    draw_live_side.pack(anchor='w', pady=(0, 2))
    total_draw_side = label(step5, a.total_draw_time_text, size=10, bold=True, wraplength=270)
    total_draw_side.pack(anchor='w', pady=(0, 6))
    review_card = frame(step5, PANEL_ALT, border_width=1, border_color=LINE, radius=10)
    review_card.pack(fill='x', pady=(0, 7))
    label(review_card, 'Correction Review', size=10, bold=True, text_color=ACCENT).pack(anchor='w', padx=9, pady=(8, 1))
    label(review_card, var=a.correction_review_text, muted=True, size=9, wraplength=248).pack(anchor='w', padx=9, pady=(0, 6))
    review_actions = frame(review_card)
    review_actions.pack(fill='x', padx=8, pady=(0, 8))
    a.correction_review_button = btn(review_actions, 'Review', a.show_correction_review, width=74, height=30)
    a.correction_review_button.pack(side='left')
    a.correction_retry_button = btn(review_actions, 'Correction only', a.retry_post_draw_correction, width=112, height=30)
    a.correction_retry_button.pack(side='left', padx=5)
    a.correction_full_retry_button = btn(review_actions, 'Full retry', a.retry_full_after_review, width=82, height=30)
    a.correction_full_retry_button.pack(side='left')
    tooltip(a.correction_retry_button, 'Runs only a bounded post-draw correction pass from a fresh read-only canvas snapshot. It still requires the normal target lock, safety preflight and unlock chain before native input.')
    tooltip(a.correction_full_retry_button, 'Retries the full drawing with the current image/settings. It never bypasses preflight, dry run, unlock or CanvasGuard.')
    history_actions = frame(review_card)
    history_actions.pack(fill='x', padx=8, pady=(0, 8))
    a.correction_history_button = btn(history_actions, 'History / before-after', a.show_correction_history, width=186, height=28)
    a.correction_history_button.pack(side='left')
    tooltip(a.correction_history_button, 'Shows compact per-profile before/after metrics for recent correction passes. It does not store screenshots, crops, hashes or pixels.')
    setting_row(step5, 'Preview mode', a.preview_mode, ['Manual', 'Auto light', 'Auto full'], 'Manual prevents lag while configuring and after profile switches.', width=126)
    setting_row(step5, 'Preview detail', a.preview_detail_level, ['Fast', 'Balanced', 'Detailed', 'Micro detail'], 'Detailed is recommended. Micro detail can take longer on large images.', width=126)
    build_preview_btn=btn(step5, '👁️  Build preview', a.request_preview, height=36); build_preview_btn.pack(fill='x', pady=(2, 6))
    tooltip(build_preview_btn,'Manual / Auto full uses the final planner for preview parity. Auto light keeps the bounded fast preview. CanvasGuard/Edge Behavior matches execution.')
    a.target_lock_secondary = btn(step5, '🔒  Lock setup', a.lock_setup, False, height=38, state='disabled')
    a.target_lock_secondary.pack(fill='x', pady=(0, 6))
    a.safety_preflight_secondary = btn(step5, '🛡️  Safety preflight', a.run_safety_preflight, False, height=38, state='disabled')
    a.safety_preflight_secondary.pack(fill='x', pady=(0, 6))
    a.dry_run_secondary = btn(step5, '🖱️  Fast Dry run · ≤12s', a.run_dry_run, False, height=38, state='disabled')
    a.dry_run_secondary.pack(fill='x', pady=(0, 6))
    a.start_unlock_secondary = btn(step5, '🔓  Unlock full drawing', a.unlock_full_drawing, False, height=38, state='disabled')
    a.start_unlock_secondary.pack(fill='x', pady=(0, 6))
    tooltip(a.target_lock_secondary,'Freeze the current target/canvas setup. Important changes invalidate the lock.')
    tooltip(a.safety_preflight_secondary,'Read-only verification before mouse input can be armed.')
    tooltip(a.dry_run_secondary,'Fast no-click simulation of representative routes. Required before full drawing.')
    tooltip(a.start_unlock_secondary,'Temporary confirmation step. CanvasGuard remains mandatory.')
    a.start_secondary = btn(step5, '🔒  Start locked', a.start_full_drawing, True, height=42, state='disabled')
    a.start_secondary.pack(fill='x')
    label(step5, 'Paint: load an image, then Prepare Paint & draw. Canvas, pencil size and RGB colors are prepared automatically. Tests and previews are optional. Browser/game profiles use Unlock → Start.', muted=True,
          size=9, wraplength=270).pack(anchor='w', pady=(6, 0))

    # CENTER: preview workspace and Tools alternate view.
    center_host = frame(main)
    center_host.grid(row=0, column=1, sticky='nsew', padx=(0, 12))
    workspace_center = frame(center_host, PANEL, border_width=1, border_color=LINE, radius=15)
    tools_center = frame(center_host, PANEL, border_width=1, border_color=LINE, radius=15)

    preview_head = frame(workspace_center)
    preview_head.pack(fill='x', padx=16, pady=(15, 8))
    text = frame(preview_head); text.pack(side='left', fill='x', expand=True)
    label(text, '👁️  Preview workspace', size=18, bold=True).pack(anchor='w')
    label(text, 'Manual preview prevents lag while configuring/profile switching. Build only when you want to refresh it.', muted=True, size=10).pack(anchor='w', pady=(2, 0))
    label(text, var=a.draw_time_text, size=11, bold=True, fg_color=FIELD, corner_radius=8, wraplength=560).pack(anchor='w', pady=(7, 0))
    label(text, var=a.draw_live_time_text, size=10, fg_color=FIELD, corner_radius=8, wraplength=560).pack(anchor='w', pady=(5, 0))
    label(text, var=a.total_draw_time_text, size=11, bold=True, fg_color=FIELD, corner_radius=8, wraplength=560).pack(anchor='w', pady=(5, 0))
    a.preview_zoom = tk.DoubleVar(value=0.0)
    a.preview_show_background = tk.BooleanVar(value=True)
    a.preview_show_fill = tk.BooleanVar(value=True)
    a.preview_show_strokes = tk.BooleanVar(value=True)
    zoom_text = label(preview_head, 'Fit', muted=True, size=10, width=50, anchor='center')
    zoom_text.pack(side='right', padx=3)
    def set_zoom(value):
        value = max(0.0, min(8.0, float(value)))
        a.preview_zoom.set(value); zoom_text.configure(text='Fit' if value==0 else f'{round(value*100):.0f}%'); a.schedule_previews(delay=15)
    button(preview_head, '+', lambda: set_zoom(a.preview_zoom.get()+.25), width=34, height=32).pack(side='right', padx=2)
    button(preview_head, '−', lambda: set_zoom(a.preview_zoom.get()-.25), width=34, height=32).pack(side='right', padx=2)
    button(preview_head, '1:1', lambda: set_zoom(1.0), width=42, height=32).pack(side='right', padx=2)
    button(preview_head, 'Fit', lambda: set_zoom(0.0), width=46, height=32).pack(side='right', padx=2)

    full_preview_row=frame(workspace_center);full_preview_row.pack(fill='x',padx=16,pady=(0,5))
    btn(full_preview_row,'Full detail preview',a.request_full_preview,height=32).pack(side='left')
    label(full_preview_row,'Native target pixels · 1:1 to inspect · drag to pan',muted=True,size=10).pack(side='left',padx=8)
    a.preview_tabs = ctk.CTkTabview(workspace_center, fg_color=PREVIEW, corner_radius=13,
                                    segmented_button_fg_color=FIELD,
                                    segmented_button_selected_color=ACCENT_DARK,
                                    segmented_button_selected_hover_color='#2d6756',
                                    segmented_button_unselected_color=FIELD,
                                    segmented_button_unselected_hover_color=FIELD_HOVER,
                                    text_color=TEXT,command=lambda:a.schedule_previews(delay=20))
    a.preview_tabs.pack(fill='both', expand=True, padx=14, pady=(0, 9))
    # Legacy tab source marker retained for older UI compatibility tests: ('Drawing preview', 'result_canvas')
    preview_specs = (
        ('Original', 'original_canvas'), ('Quantized target', 'quantized_target_canvas'),
        ('Simulated final', 'result_canvas'), ('ΔE heatmap', 'delta_e_canvas'),
        ('Accuracy error', 'accuracy_error_canvas'), ('Coverage map', 'coverage_canvas'),
        ('Detail zoom', 'detail_zoom_canvas'),
        ('Safety map', 'safety_canvas'), ('Debug overlay', 'safety_debug_canvas'),
        ('Stroke plan', 'stroke_canvas'), ('Fill regions', 'fill_canvas'),
        ('Color map', 'color_canvas'))
    for tab_name, attr in preview_specs:
        tab = a.preview_tabs.add(tab_name)
        canvas = tk.Canvas(tab, bg=PREVIEW, height=260, highlightthickness=0)
        canvas.pack(fill='both', expand=True, padx=4, pady=4)
        setattr(a, attr, canvas)
        canvas.bind('<Configure>', a.schedule_previews)
        def pan_start(event,c=canvas):c._drag=(event.x,event.y,getattr(c,'_preview_pan',(0,0)))
        def pan_move(event,c=canvas):
            if not hasattr(c,'_drag') or a.preview_zoom.get()==0:return
            x,y,old=c._drag;scale=max(.125,getattr(c,'_preview_scale',1))
            c._preview_pan=(old[0]-(event.x-x)/scale,old[1]-(event.y-y)/scale)
            a.schedule_previews(delay=30)
        canvas.bind('<ButtonPress-1>',pan_start)
        canvas.bind('<B1-Motion>',pan_move)
    a.original_canvas.bind('<Button-1>', lambda _e: a.open_file() if a.original is None and not a.activity else None,add='+')

    preview_options = frame(workspace_center)
    preview_options.pack(fill='x', padx=16, pady=(0, 7))
    for text, var in (('Show background', a.preview_show_background),
                      ('Show fill regions', a.preview_show_fill),
                      ('Show stroke paths', a.preview_show_strokes)):
        ctk.CTkSwitch(preview_options, text=text, variable=var,
                      command=lambda: a.schedule_previews(delay=15), progress_color=ACCENT_DARK,
                      text_color=MUTED, font=('Segoe UI', 9)).pack(side='left', padx=(0, 15))
    mobile_btn=btn(preview_options, '📱 Mobile Preview', a.show_mobile_preview, width=132, height=31)
    mobile_btn.pack(side='right')
    tooltip(mobile_btn, 'Starts an opt-in local-network preview page for your phone. No cloud or telemetry. Same Wi-Fi/LAN required.')
    label(workspace_center, var=a.preview_diagnostics_text, fg_color=FIELD, corner_radius=8, wraplength=760, size=9).pack(fill='x', padx=16, pady=(0, 5), ipady=5)
    label(workspace_center, var=a.mobile_preview_status, muted=True, wraplength=760, size=9).pack(fill='x', padx=16, pady=(0, 4))
    label(workspace_center, var=a.summary, muted=True, wraplength=760, size=10).pack(fill='x', padx=16, pady=(0, 13))

    # Tools alternate center page.
    tools_scroll = ctk.CTkScrollableFrame(tools_center, fg_color=PANEL, corner_radius=14)
    tools_scroll.pack(fill='both', expand=True, padx=6, pady=6)
    label(tools_scroll, 'Tools & diagnostics', size=21, bold=True).pack(anchor='w', padx=16, pady=(14, 2))
    label(tools_scroll, 'Run isolated tests, inspect the canvas, export previews and collect sanitized diagnostics. Full drawing requires Preflight + Unlock + Start.', muted=True, size=10, wraplength=720).pack(anchor='w', padx=16, pady=(0, 12))
    release_card = frame(tools_scroll, PANEL_ALT)
    release_card.pack(fill='x', padx=16, pady=6)
    label(release_card, f'Image Draw Bot {APP_VERSION}', size=14, bold=True).pack(anchor='w', padx=14, pady=(12, 3))
    row = frame(release_card); row.pack(fill='x', padx=14, pady=(4, 12))
    btn(row, 'Quick guide', a.show_welcome, width=105, height=33).pack(side='left')
    btn(row, 'Setup wizard', a.show_beginner_setup_wizard, width=112, height=33).pack(side='left', padx=6)
    btn(row, 'Open app data', a.open_app_data_folder, width=115, height=33).pack(side='left', padx=6)
    btn(row, 'Hardware bench', lambda: a.run_performance_auto_tuner(apply=False), width=112, height=33).pack(side='left')
    btn(row, 'Test resources', a.test_resource_allocation, width=112, height=33).pack(side='left', padx=6)
    btn(row, 'Benchmark', a.run_performance_benchmark, width=96, height=33).pack(side='left')
    btn(row, 'Golden tests', a.run_golden_image_regression, width=112, height=33).pack(side='left', padx=6)
    btn(row, 'Clear GPU cache', a.clear_gpu_cache, width=118, height=33).pack(side='left')
    btn(row, 'Run self-test', a.run_self_test, width=105, height=33).pack(side='left', padx=6)

    update_card = frame(tools_scroll, PANEL_ALT)
    update_card.pack(fill='x', padx=16, pady=6)
    label(update_card, 'Update center', size=14, bold=True).pack(anchor='w', padx=14, pady=(12, 2))
    label(update_card, var=a.update_summary, size=10, wraplength=690).pack(anchor='w', padx=14, pady=(2, 2))
    label(update_card, var=a.update_detail, muted=True, size=9, wraplength=690).pack(anchor='w', padx=14, pady=(0, 8))
    update_actions=frame(update_card); update_actions.pack(fill='x', padx=14, pady=(0, 12))
    check_update_btn=btn(update_actions, 'Check updates / install', a.check_for_updates, width=138, height=32); check_update_btn.pack(side='left')
    release_page_btn=btn(update_actions, 'Open GitHub Releases', a.open_latest_release_page, width=156, height=32); release_page_btn.pack(side='left', padx=6)
    a.update_download_button=release_page_btn
    tooltip(check_update_btn,'Contacts only the public Image Draw Bot GitHub Releases API after this explicit click. Downloads and verifies a newer Windows installer, then starts the update. Save your work first.')
    tooltip(release_page_btn,'Opens the official Image Draw Bot GitHub Releases page in your browser.')

    tuner_card = frame(tools_scroll, PANEL_ALT)
    tuner_card.pack(fill='x', padx=16, pady=6)
    label(tuner_card, 'Universal Hardware Auto Benchmark', size=14, bold=True).pack(anchor='w', padx=14, pady=(12, 2))
    label(tuner_card, var=a.auto_tune_summary, size=10, wraplength=690).pack(anchor='w', padx=14, pady=(2, 2))
    label(tuner_card, var=a.auto_tune_detail, muted=True, size=9, wraplength=690).pack(anchor='w', padx=14, pady=(0, 8))
    tuner_actions=frame(tuner_card); tuner_actions.pack(fill='x', padx=14, pady=(0, 12))
    tune_only_btn=btn(tuner_actions, 'Benchmark only', lambda: a.run_performance_auto_tuner(apply=False), width=128, height=32); tune_only_btn.pack(side='left')
    tune_apply_btn=btn(tuner_actions, 'Benchmark & apply', lambda: a.run_performance_auto_tuner(apply=True), width=142, height=32); tune_apply_btn.pack(side='left', padx=6)
    apply_saved_btn=btn(tuner_actions, 'Apply saved recommendation', a.apply_performance_tune, width=180, height=32); apply_saved_btn.pack(side='left')
    tooltip(tune_only_btn, 'Runs a local planning-resource benchmark only. It never clicks or moves the mouse.')
    tooltip(tune_apply_btn, 'Benchmarks CPU/RAM plus NVIDIA/AMD/Intel compute backends, then applies the safe settings supported by the current renderer. Safety settings are untouched.')
    tooltip(apply_saved_btn, 'Re-applies the last local tuner result without running another benchmark.')

    safety_report_card = frame(tools_scroll, PANEL_ALT)
    safety_report_card.pack(fill='x', padx=16, pady=6)
    label(safety_report_card, 'Runtime safety report', size=14, bold=True).pack(anchor='w', padx=14, pady=(12, 2))
    label(safety_report_card, var=a.runtime_safety_summary, size=10, wraplength=690).pack(anchor='w', padx=14, pady=(2, 2))
    label(safety_report_card, var=a.runtime_safety_detail, muted=True, size=9, wraplength=690).pack(anchor='w', padx=14, pady=(0, 8))
    safety_actions=frame(safety_report_card); safety_actions.pack(fill='x', padx=14, pady=(0, 12))
    latest_btn=btn(safety_actions, 'Open latest report', a.open_latest_safety_report, width=138, height=32); latest_btn.pack(side='left')
    folder_btn=btn(safety_actions, 'Open report folder', a.open_safety_reports_folder, width=138, height=32); folder_btn.pack(side='left', padx=6)
    refresh_btn=btn(safety_actions, 'Refresh', a.refresh_runtime_safety_ui, width=86, height=32); refresh_btn.pack(side='left')
    tooltip(latest_btn,'Opens the newest local .txt runtime safety report.')
    tooltip(folder_btn,'Opens the local safety-reports folder. Nothing is uploaded automatically.')

    for title_text, description, action, command in (
        ('Mouse control', 'Runs the no-click mouse probe in an isolated process.', 'Test mouse', a.test_mouse),
        ('Small drawing', 'Draws a tiny test so Paint/tool/color problems are caught early.', 'Draw test', lambda: a.draw(test=True, user_initiated=True)),
        ('Inspect drawing area', 'Captures the selected canvas so you can verify its bounds.', 'Show screenshot', a.capture_screen),
        ('Record drawing area', 'Records up to 30 seconds as a GIF for debugging.', 'Record GIF', a.record_screen),
        ('Export preview', 'Exports the current drawing preview as PNG.', 'Export PNG', a.export_preview),
        ('Mobile Preview', 'Serves Original, Drawing Preview and Safety Map to a phone on the same Wi-Fi/LAN. Opt-in and local-only.', 'Open Mobile', a.show_mobile_preview),
        ('Diagnostics', 'Creates a sanitized ZIP with logs, system/GPU/resource information, settings summaries and calibration hashes. Source/recovery images are excluded.', 'Create diagnostics', a.collect_diagnostics),
        ('Safe recovery', 'Clears the local crash-recovery checkpoint. Recovery never restores Start authorization, target lock, preflight or dry-run passes.', 'Clear recovery', a.clear_recovery_snapshot),
        ('Windows crash dumps', 'Enables per-user .dmp capture for hard Python/Win32 crashes.', 'Enable .dmp', a.enable_crash_dumps)):
        card = frame(tools_scroll, PANEL_ALT)
        card.pack(fill='x', padx=16, pady=5)
        btn(card, action, command, width=148, height=34).pack(side='right', padx=12, pady=12)
        label(card, title_text, size=13, bold=True).pack(anchor='w', padx=14, pady=(11, 1))
        label(card, description, muted=True, size=9, wraplength=470).pack(anchor='w', padx=14, pady=(0, 11))

    # Preserve Word helper as an existing feature inside Tools.
    word_card = frame(tools_scroll, PANEL_ALT)
    word_card.pack(fill='x', padx=16, pady=(12, 16))
    label(word_card, 'Word helper', size=15, bold=True).pack(anchor='w', padx=14, pady=(12, 2))
    label(word_card, 'Filter a word list by length and known letters. No AI.', muted=True, size=9).pack(anchor='w', padx=14, pady=(0, 9))
    row = frame(word_card); row.pack(fill='x', padx=14)
    for text, var in (('Letter count', a.guess_length), ('Pattern, e.g. c__t', a.guess_pattern)):
        box = frame(row); box.pack(side='left', padx=(0, 10))
        label(box, text, muted=True, size=9).pack(anchor='w')
        entry(box, var, 155).pack(anchor='w', pady=(3, 0))
        var.trace_add('write', lambda *_: a.update_guesses())
    btn(row, 'Import word list', a.import_words, width=140, height=34).pack(side='right', anchor='s')
    label(word_card, var=a.word_source, muted=True, size=9).pack(anchor='w', padx=14, pady=(8, 3))
    a.guess_list = tk.Listbox(word_card, height=5, exportselection=False, bg=FIELD, fg=TEXT,
                              selectbackground=ACCENT_DARK, selectforeground=TEXT,
                              borderwidth=0, highlightthickness=0, font=('Segoe UI', 11),
                              activestyle='none')
    a.guess_list.pack(fill='x', padx=14, pady=5)
    label(word_card, var=a.guess_result, muted=True, size=9).pack(anchor='w', padx=14)
    btn(word_card, 'Copy selected word', a.copy_guess, height=32).pack(anchor='w', padx=14, pady=(7, 12))

    center_mode = {'name': 'workspace'}
    def show_center(name='workspace'):
        workspace_center.pack_forget(); tools_center.pack_forget()
        center_mode['name'] = name
        if name == 'tools':
            tools_center.pack(fill='both', expand=True)
            tools_button.configure(text='↩  Workspace', fg_color=ACCENT_DARK)
        else:
            workspace_center.pack(fill='both', expand=True)
            tools_button.configure(text='🧰  Tools', fg_color=FIELD)
    def toggle_tools(): show_center('workspace' if center_mode['name'] == 'tools' else 'tools')
    tools_button.configure(command=toggle_tools)
    a.show_tools=lambda:show_center('tools')
    show_center('workspace')

    # RIGHT: readiness + contextual help + error card.
    right = frame(main, SIDEBAR, border_width=1, border_color=LINE, radius=15, width=286)
    right.grid(row=0, column=2, sticky='nsew')
    right.pack_propagate(False)
    label(right, '🛡️  Readiness', size=16, bold=True).pack(anchor='w', padx=15, pady=(15, 2))
    label(right, 'Complete the blocking items before a full drawing.', muted=True, size=9, wraplength=250).pack(anchor='w', padx=15, pady=(0, 9))
    checklist_host = frame(right)
    checklist_host.pack(fill='x', padx=12)
    checklist_rows = {}
    for key, text in (('image', 'Image loaded'), ('target', 'Target profile selected'),
                      ('tools', 'Drawing controls ready'), ('area', 'Drawing area selected'),
                      ('palette', 'Palette ready'), ('test', 'First stroke test passed'),
                      ('lock', 'Setup locked'), ('preflight', 'Safety preflight passed'),
                      ('dryrun', 'Dry run passed'), ('gpu', 'GPU ready / CPU fallback active')):
        row = frame(checklist_host, PANEL, radius=10)
        row.pack(fill='x', pady=3)
        dot = label(row, '•', size=18, bold=True, width=20, anchor='center', text_color=MUTED)
        dot.pack(side='left', padx=(7, 2), pady=6)
        text_label = label(row, text, size=9, wraplength=205)
        text_label.pack(side='left', fill='x', expand=True, padx=(1, 7), pady=7)
        checklist_rows[key] = (row, dot, text_label)

    context_card = frame(right, PANEL, radius=12)
    context_card.pack(fill='x', padx=12, pady=(11, 5))
    label(context_card, '➡  NEXT STEP', size=8, bold=True, text_color=ACCENT).pack(anchor='w', padx=12, pady=(10, 0))
    label(context_card, var=a.next_step, size=10, wraplength=240).pack(anchor='w', padx=12, pady=(4, 11))

    error_card = frame(right, '#2d1e27', border_width=1, border_color='#70404d', radius=12)
    error_title = label(error_card, '⚠️  Error', size=12, bold=True, text_color='#ffd2da')
    error_title.pack(anchor='w', padx=12, pady=(10, 2))
    error_message = label(error_card, '', size=9, text_color='#f4ced6', wraplength=240)
    error_message.pack(anchor='w', padx=12)
    error_action = label(error_card, '', size=9, muted=True, wraplength=240)
    error_action.pack(anchor='w', padx=12, pady=(5, 8))
    erow = frame(error_card)
    erow.pack(fill='x', padx=10, pady=(0, 10))
    button(erow, '📂 Logs', a.open_app_data_folder, width=76, height=30).pack(side='left')
    button(erow, '📦 Diagnostics', a.collect_diagnostics, width=104, height=30).pack(side='left', padx=5)
    button(erow, '🧪 Retry', lambda: a.draw(test=True, user_initiated=True), width=78, height=30).pack(side='left')

    # ---- Safe state renderer --------------------------------------------
    ui_state_job = {'id': None}
    ui_state_running = {'value': False}

    def gpu_summary():
        if a.plan:
            stats = (a.plan.get('options', {}).get('portrait_stats') or {})
            if stats.get('gpu_accelerated'):
                return f"{stats.get('acceleration_backend', 'CUDA')}: {stats.get('acceleration_device', 'GPU')}"
        mode = a.gpu_mode.get()
        return 'CPU selected' if mode == 'CPU' else ('CUDA requested · CPU fallback available' if mode == 'NVIDIA CUDA' else 'Auto · NVIDIA/AMD/Intel per-workload routing · CPU fallback')

    def palette_ready_now():
        paint_bypass = a.paint_simple.get() or (a.game.get() == 'Microsoft Paint' and a.paint_tool.get() == 'Eraser')
        return bool(a.palette_ready or paint_bypass)

    def _apply_ui_state():
        ui_state_job['id'] = None
        if a.closing or ui_state_running['value']:
            return
        ui_state_running['value'] = True
        try:
            tool_ready = bool(a._paint_tool_preflight_ready())
            state = compute_workspace_state(
                image_loaded=a.original is not None,
                target_name=a.game.get(),
                paint_tools_ready=tool_ready,
                area_ready=len(a.corners) == 2,
                palette_ready=palette_ready_now(),
                test_passed=bool(getattr(a, 'small_test_passed', False)),
                target_locked=bool(a._target_lock_valid()),
                preflight_passed=bool(a._safety_preflight_valid()),
                dry_run_passed=bool(a._dry_run_valid()),
                gpu_text=gpu_summary(), strict_safety=(a.game.get() == 'Microsoft Paint'), activity=a.activity, status=a.status.get())
            try:
                from BeginnerSetupWizard import build_setup_wizard, format_setup_status
                steps_for_wizard = build_setup_wizard(profile_name=a.game.get(), image_loaded=a.original is not None,
                    tools_ready=tool_ready, palette_ready=palette_ready_now(), area_ready=len(a.corners) == 2,
                    small_test_passed=bool(getattr(a, 'small_test_passed', False)),
                    target_locked=bool(a._target_lock_valid()), preflight_passed=bool(a._safety_preflight_valid()),
                    dry_run_passed=bool(a._dry_run_valid()), full_draw_unlocked=bool(a._full_draw_unlocked()), activity=a.activity)
                a.setup_wizard_text.set(format_setup_status(steps_for_wizard))
            except Exception:
                pass
            tone_colors = {
                'ready': (ACCENT_DARK, SUCCESS), 'attention': ('#40371f', WARNING),
                'blocked': (FIELD, MUTED), 'working': ('#183958', INFO), 'error': ('#48232e', ERROR)}
            bg, fg = tone_colors.get(state.tone, (FIELD, TEXT))
            state_icons={'ready':'✓','attention':'!','blocked':'×','working':'↻','error':'⚠'}
            top_state.configure(text=f"{state_icons.get(state.tone,'•')}  {state.label}", fg_color=bg, text_color=fg)
            meta=profile_ui(a.game.get())
            profile_pill.configure(text=f"{meta.get('icon','🧩')}  {a.game.get()}")
            profile_guide_icon.configure(text=meta.get('icon','🧩'))
            profile_guide_badge.configure(text=meta.get('badge','Profile guide'))
            profile_guide_tip.configure(text=meta.get('tip',''))
            recommended=profile_defaults(a.game.get())
            policy_mode=getattr(getattr(a,'profile_engine',None),'get',lambda:'Auto')()
            try:
                from ProfilePolish import profile_release_preset
                preset=profile_release_preset(a.game.get())
                polish=f" · {preset.recommended_time_budget} · {preset.color_policy}"
            except Exception:
                polish=''
            profile_guide_recommend.configure(text=(
                f"Profile Engine v2: {policy_summary(a.game.get())} · {policy_mode}{polish}"))
            title_widget,subtitle_widget=step_headers[3]
            title_widget.configure(text=f"3. {meta.get('prepare_title','Prepare target app')}")
            subtitle_widget.configure(text=meta.get('prepare_subtitle','Calibrate the target app and select its canvas.'))
            a.palette_button.configure(text=meta.get('palette_button','🎨  Read colors / palette'))
            a.area_button.configure(text=meta.get('area_button','▣  Select drawing area'))
            a.app_tool_button.configure(text=meta.get('tool_button','🧰  Calibrate Brush / Fill'))

            item_map = {item.key: item for item in state.items}
            item_colors = {'ready': SUCCESS, 'attention': WARNING, 'blocked': ERROR, 'optional': MUTED}
            item_glyphs = {'ready': '✓', 'attention': '!', 'blocked': '×', 'optional': '•'}
            for key, (_row, dot, text_widget) in checklist_rows.items():
                item = item_map[key]
                dot.configure(text=item_glyphs.get(item.state,'•'), text_color=item_colors.get(item.state, MUTED))
                text_widget.configure(text=item.label)

            for number, good in ((1, a.game.get() in PROFILES), (2, a.original is not None),
                                 (3, len(a.corners) == 2 and tool_ready),
                                 (4, a.plan is not None), (5, state.ready)):
                step_dots[number].configure(fg_color=ACCENT_DARK if good else FIELD,
                                            text_color=SUCCESS if good else MUTED)

            if a.original is None:
                image_info.configure(text='No image information yet.')
            else:
                w, h = a.original.size
                aspect = w / max(1, h)
                image_info.configure(text=f'{w:,} × {h:,} px · {a.original.mode} · aspect {aspect:.2f}:1')

            plan = a.plan or {}
            if plan:
                estimate = float(plan.get('estimate', 0)); unit = f'{estimate/60:.1f} min' if estimate >= 60 else f'{estimate:.0f} s'
                time_meta = plan.get('draw_time_estimate') or {}
                shown_unit = time_meta.get('projected_label') or unit
                range_text = time_meta.get('range_label') or shown_unit
                opts = plan.get('options', {}); fill = opts.get('background_fill_plan') or {}
                fills = (1 if fill.get('enabled') else 0) + len(opts.get('fill_regions', []) or [])
                colors = sum(bool(g) for g in plan.get('groups', []))
                tool = opts.get('effective_paint_tool') or opts.get('paint_tool') or 'Brush'
                path_stats = plan.get('path_stats') or {}
                progressive = ''
                if path_stats.get('progressive_enabled'):
                    progressive = f"\nProgressive: {int(path_stats.get('progressive_foundation_paths', 0)):,} forms → {int(path_stats.get('progressive_contour_paths', 0)):,} contours → {int(path_stats.get('progressive_detail_paths', 0)):,} details"
                if time_meta.get('is_projection'):
                    time_line=f"final ≈ {shown_unit} · range {range_text}"
                else:
                    time_line=f"estimate ≈ {shown_unit}"
                deadline=opts.get('adaptive_deadline_meta') or {}
                deadline_line=''
                if deadline.get('enabled'):
                    game_time=float(deadline.get('total_seconds',0) or 0)
                    budget=float(deadline.get('render_budget_seconds',0) or 0)
                    reserve=float(deadline.get('reserve_seconds',0) or 0)
                    hard_stop=float(deadline.get('hard_stop_seconds',game_time) or game_time)
                    status=deadline.get('budget_status','?')
                    dropped=int(deadline.get('dropped_paths',0) or 0)
                    effective=float(deadline.get('effective_estimated_seconds',deadline.get('estimated_after_seconds',0)) or 0)
                    deadline_line=f"\nDeadline: {status} · game {game_time:.0f}s · render {budget:.0f}s · reserve {reserve:.0f}s · hard stop {hard_stop:.0f}s · estimate {effective:.1f}s · dropped {dropped:,}"
                acc=opts.get('adaptive_accuracy_meta') or {}
                accuracy_line=''
                if acc:
                    _parts=[
                        f"Visual {float(acc.get('visual_accuracy_percent',0) or 0):.1f}%",
                        f"Source Pixel {float(acc.get('source_pixel_accuracy_percent',acc.get('raw_pixel_accuracy_percent',0)) or 0):.1f}%",
                        f"Perceptual {float(acc.get('perceptual_color_accuracy_percent',0) or 0):.1f}%",
                        f"Luminance {float(acc.get('luminance_accuracy_percent',0) or 0):.1f}%",
                        f"Hue {float(acc.get('hue_accuracy_percent',0) or 0):.1f}%",
                        f"Edge {float(acc.get('edge_accuracy_percent',0) or 0):.1f}%",
                    ]
                    if acc.get('coverage_percent') is not None:
                        _parts.append(f"Coverage {float(acc.get('coverage_percent') or 0):.1f}%")
                    if acc.get('plan_execution_accuracy_percent') is not None:
                        _parts.append(f"Plan execution {float(acc.get('plan_execution_accuracy_percent') or 0):.1f}%")
                    accuracy_line='\n'+' · '.join(_parts)
                    if acc.get('plan_source_divergence_note'):
                        accuracy_line+='\n'+str(acc.get('plan_source_divergence_note'))
                plan_metrics.configure(text=f"{int(plan.get('count', 0)):,} strokes · {time_line}\n{tool} · {fills} Fill action(s) · {colors} color phase(s){progressive}{deadline_line}{accuracy_line}")
            else:
                plan_metrics.configure(text='No plan yet. Load an image and finish setup.')

            err = classify_error(a.status.get())
            if err:
                error_title.configure(text=err['title']); error_message.configure(text=err['message']); error_action.configure(text=err['action'])
                if not error_card.winfo_manager(): error_card.pack(fill='x', padx=12, pady=(7, 5))
            elif error_card.winfo_manager():
                error_card.pack_forget()

            # The sidebar start button mirrors the controller-owned footer button.
            ready = state.ready and not a.activity and bool(a._full_draw_unlocked())
            a._safe_widget_configure(a.start_secondary, state='normal' if ready else 'disabled')
        finally:
            ui_state_running['value'] = False

    def refresh_ui_state(*_args):
        if a.closing or ui_state_job['id'] is not None:
            return
        try: ui_state_job['id'] = root.after_idle(_apply_ui_state)
        except (tk.TclError, RuntimeError): ui_state_job['id'] = None

    a.status.trace_add('write', refresh_ui_state)
    a.file_label.trace_add('write', refresh_ui_state)
    a.area_text.trace_add('write', refresh_ui_state)
    a.palette_text.trace_add('write', refresh_ui_state)
    a.paint_tool_text.trace_add('write', refresh_ui_state)
    a.summary.trace_add('write', refresh_ui_state)
    from ProfileIsolation import register_controls
    register_controls(a,[(a.paint_tool_menu,'paint'),(a.paint_tool_label,'paint'),
        (a.paint_auto_button,'paint'),(a.paint_tool_button,'paint'),(a.picture_palette_button,'paint'),
        (a.one_click_setup_button,'oneclick'),(a.one_click_setup_label,'oneclick'),
        (one_click,'browser-auto'),(a.browser_one_click_label,'browser-auto'),
        (a.browser_auto_button,'browser-auto'),(a.browser_auto_label,'browser-auto'),
        (a.app_tool_button,'nonpaint'),(a.app_tool_label,'nonpaint'),
        (a.gartic_setup_button,'gartic'),(timer_switch,'gartic'),(a.gartic_opacity_row,'gartic')])
    a.refresh_ui_state = refresh_ui_state
    refresh_ui_state()

    root.bind('<Control-o>', lambda _e: a.open_file() if not a.activity else None)
    root.bind('<F1>', lambda _e: a.show_welcome())

    from SmoothScroll import install_scrolling
    a.scroll_dispatcher=install_scrolling(root)
