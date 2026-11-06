"""Local read-only onboarding and practical setting help."""
PAGES = [
  [
    "Your first drawing",
    [
      [
        "What Image Draw Bot does",
        "It turns a picture into mouse strokes, fills and color changes inside another drawing app. It controls your mouse while drawing. Esc stops immediately; F6 pauses or resumes."
      ],
      [
        "Start simple",
        "Try a small icon with clear outlines and a few flat colors on an empty canvas. Keep the default quality and hardware settings for your first result. Shaded photos are harder to reproduce."
      ],
      [
        "Learn alongside the app",
        "This guide does not change settings or start drawing. Keep it open beside the main window, use Back / Next, or jump to a topic. Reopen it later with Get started."
      ]
    ]
  ],
  [
    "Choose your target",
    [
      [
        "Choose the matching profile",
        "Select Microsoft Paint, Gartic Phone, Skribbl.io or the profile for your target before setup. Profiles keep settings and calibration separate."
      ],
      [
        "First browser attempt",
        "Open a drawable canvas. Turn Browser One-Click Mode off and leave Drop-In Start unarmed before importing: these automation features can start drawing after an image is added when enabled."
      ],
      [
        "Keep the layout stable",
        "Keep the canvas and toolbar visible. Changes to browser zoom, display scaling, canvas size or toolbar layout may require setup/calibration again."
      ]
    ]
  ],
  [
    "Add an image and prepare",
    [
      [
        "Select image / Paste / Load URL",
        "Select image opens a local file. Paste uses an image from your clipboard. Load URL needs a direct image address, not a search-results page. A local file is the simplest starting point."
      ],
      [
        "Setup and drawing area",
        "Browser profiles: use One-click Setup + Verify or Auto setup browser. If detection fails, Select drawing area should cover only the drawable canvas, excluding toolbars. Paint includes preparation in Prepare Paint & draw."
      ],
      [
        "Palette and custom colors",
        "Calibration tells the app where tools, colors and canvas are. Read colors calibrates the target palette. In Paint, Custom color palette for picture analyzes this image and enters RGB colors: this operates Paint controls, so keep Paint visible and leave the mouse alone."
      ]
    ]
  ],
  [
    "Preview and drawing modes",
    [
      [
        "Build preview",
        "This prepares a simulation without drawing on the target. Compare the original, reduced-color target and simulated final result. Rebuild after changing the image, canvas or settings; manual preview does not automatically refresh every change."
      ],
      [
        "Choose a starting mode",
        "Balanced or Auto is a good first choice. Extra Fast prioritizes recognizable shapes and speed with outlines and safe fills where supported. Pixel Accurate preserves more detail and can take longer. Filling needs suitable tools and closed regions; strokes are used when filling is unsuitable."
      ],
      [
        "Read the result",
        "If shapes disappear, allow more detail/time or use a simpler image. If colors look wrong, check the profile and palette. A preview is an estimate: target brush behavior and timing still affect the real drawing."
      ],
      [
        "CPU and GPU",
        "Leave hardware settings on Auto initially. The GPU accelerates supported image preparation; it does not remove mouse timing or target-app limits. Increasing every speed setting can cause missed actions."
      ]
    ]
  ],
  [
    "Start, pause and stop",
    [
      [
        "Browser and manual start",
        "Complete setup, then use Unlock full drawing and Start drawing when available. Read missing-setup messages. Keep the target visible and follow the countdown. Browser One-Click and armed drop modes can use an automatic start path."
      ],
      [
        "Optional checks",
        "Small test draws a small real sample and changes the canvas. Test mouse can move the pointer. Safety preflight checks setup; Fast Dry run simulates representative pointer routes without drawing clicks. Use these to investigate setup before a full attempt."
      ],
      [
        "During drawing",
        "Leave the mouse and target layout alone. Esc stops; F6 pauses/resumes. If strokes land in the wrong place or the wrong tool is selected, stop and check calibration before retrying."
      ],
      [
        "Auto clear",
        "Auto clear target canvas before full drawing can erase existing artwork. Keep it off unless the canvas is disposable and you explicitly want it cleared."
      ]
    ]
  ],
  [
    "Troubleshooting and terms",
    [
      [
        "Start is unavailable",
        "Open Setup wizard for the current profile requirements and next action. Check that an image is loaded and no other operation is running. Browser/manual starts may need Unlock full drawing."
      ],
      [
        "Wrong place or colors",
        "Stop with Esc. Check the selected profile, canvas bounds, zoom and toolbar positions. Re-run setup/calibration, then try a small sample."
      ],
      [
        "Slow or unclear result",
        "Use a smaller/simpler image, reduce detail or try Extra Fast. Allow more time for shaded photos. Change one setting at a time and compare a fresh preview."
      ],
      [
        "Common terms",
        "Canvas: the drawable area. Palette: available colors. Calibration: saved positions of controls and canvas. Stroke: one mouse-drawn line or mark. Fill: coloring a closed area. Time budget: the time available for drawing. VRAM: graphics-card memory."
      ],
      [
        "Find help later",
        "Hover over controls for short explanations. Click ? next to a setting for help that stays open while you read. Get started reopens this guide; Setup wizard checks your current setup. Runtime safety reports stay local unless you choose to share them."
      ]
    ]
  ]
]
HELP = {
  "Quality preset": "Start with Balanced or the default. Extra Fast suits short rounds and simple shapes. Pixel Accurate emphasizes detail and can take longer. Build a new preview after changing the preset.",
  "Brush width (px)": "This is the Auto Brush baseline. On supported targets, Image Draw Bot verifies available brush sizes and automatically uses broader brushes for large flat regions and smaller brushes for contours, protected details and corrections. Low-confidence layouts keep the fixed baseline and never guess brush-control clicks.",
  "Rendering style": "Start with Auto. Portrait / shaded suits faces and gradients; Standard / pixel suits flat artwork. Quick Sketch prioritizes recognizable outlines when time is short.",
  "Drawing mode": "Smart paths connects nearby pixels to reduce mouse actions. Lines draws runs; Dots places individual marks and can be much slower. Start with Smart paths.",
  "GPU acceleration": "Auto uses a supported backend when available and falls back to CPU. GPU acceleration helps supported image-processing work; it does not make the target accept unlimited mouse input.",
  "VRAM budget": "Leave Auto initially. A larger budget can help large images but leaves less graphics memory for other apps. More allocated memory is not always faster.",
  "Draw quality": "Higher quality can preserve small features but adds planning work and strokes. Begin with the default; increase quality when a fresh preview loses important details.",
  "Precision": "Higher precision can retain fine edges but usually adds work and strokes. Start with the default and compare a fresh preview.",
  "Speed": "Higher speed only helps when the target app keeps up. If lines have gaps, colors are skipped or controls miss clicks, lower speed and repeat a small test.",
  "Time target": "Choose a budget shorter than the remaining round so setup and finishing have time. A tight budget may omit small details. Check the preview and estimate.",
  "Manual time limit (seconds)": "Leave time for setup and finishing before the round ends. Short budgets can omit small details. Compare estimated time and preview after changes.",
  "Edge behavior": "Controls strokes near the selected canvas boundary. Keep the default at first. If edges are missing, check the real canvas bounds before changing this setting.",
  "Color rendering": "The target may offer fewer colors than the source. Perceptual matching chooses visually similar available colors. Paint custom RGB colors can improve the match, but color switching adds time.",
  "Preview mode": "Build preview calculates a plan without drawing. Rebuild after changing the image, area or settings. The simulation estimates the result; calibration, brush behavior and timing still matter.",
  "CPU workers": "Auto is a good starting point. More workers can help preparation but compete with the target app. A larger number is not always faster.",
  "RAM budget": "Auto balances available memory. Large pictures and detailed plans need more RAM. If preparation struggles, reduce planning resolution rather than allocating all memory.",
  "Planning resolution": "Higher resolution can retain detail but increases memory use, planning time and possible stroke count. Lower it for quicker results or large-image problems.",
  "Fill aggressiveness": "Fill can color closed areas quickly, but an open outline can leak into the background. Start conservatively; verify the target tools and preview before increasing this."
}


def explain(title, fallback=''):
    body = HELP.get(title)
    if body:
        return title + '\n\n' + body + ('\n\nSetting details: ' + fallback if fallback else '')
    return title + '\n\n' + (fallback or 'Leave the default for your first drawing. Change one setting at a time and rebuild the preview to compare.')


def guide_pages(profile):
    pages = [(title, list(cards)) for title, cards in PAGES]
    if profile == 'Microsoft Paint':
        pages[1][1][1] = ('Prepare Paint', 'Open Paint with an empty canvas and keep its toolbar visible. Choose the Microsoft Paint profile. Prepare Paint & draw prepares the canvas, pencil size and RGB controls before drawing.')
        pages[4][1][0] = ('Start in Paint', 'Load an image, then press Prepare Paint & draw. This performs setup and then draws; it is not just a calibration button. Preview and small tests are optional but useful for a first attempt.')
    else:
        from GameProfiles import PROFILES
        from TargetCapabilities import requires_manual_setup
        key = PROFILES.get(profile, ('generic',))[0]
        if requires_manual_setup(key):
            pages[1][1][1] = ('Manual target setup', 'This profile uses manual setup. Keep the normal brush and palette visible, read the colors and select only the drawable canvas. Leave Drop-In Start unarmed while learning the setup.')
            pages[2][1][1] = ('Setup and drawing area', 'Use Read colors to calibrate the visible palette, then Select drawing area around only the canvas. Calibrate Brush / Fill when you want those optional tools. This profile has no verified automatic browser detector.')
    return pages


def _guide_wrap_length(body):
    """Convert the actual Tk width to the logical pixels CTkLabel expects."""
    import math
    width = body.winfo_width()
    if width <= 1:
        return None
    scale = 1.0
    getter = getattr(body, '_get_widget_scaling', None)
    if callable(getter):
        try:
            candidate = float(getter())
            if math.isfinite(candidate) and candidate > 0:
                scale = candidate
        except (TypeError, ValueError, OverflowError):
            pass
    return max(1, int(width / scale) - 56)


def show_guide(app):
    import customtkinter as ctk
    import logging
    import tkinter as tk
    from ReleaseState import mark_welcome_seen
    existing = getattr(app, '_getting_started_window', None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                return existing
        except tk.TclError:
            pass
    window = None
    state = {'page': 0, 'closed': False, 'resize_job': None,
             'profile_job': None, 'trace': None, 'last_wrap': None}
    labels = []

    def cleanup(event=None):
        if event is not None and event.widget is not window:
            return
        state['closed'] = True
        for name in ('resize_job', 'profile_job'):
            job = state[name]
            state[name] = None
            if job is not None and window is not None:
                try:
                    window.after_cancel(job)
                except (tk.TclError, RuntimeError):
                    pass
        trace = state['trace']
        state['trace'] = None
        if trace is not None:
            try:
                app.game.trace_remove('write', trace)
            except (tk.TclError, RuntimeError):
                pass
        if getattr(app, '_getting_started_window', None) is window:
            app._getting_started_window = None

    def resize_now():
        state['resize_job'] = None
        if state['closed']:
            return
        wrap = _guide_wrap_length(body)
        if wrap is None or wrap == state['last_wrap']:
            return
        for label in labels:
            label.configure(wraplength=wrap)
        state['last_wrap'] = wrap

    def resize(event=None):
        if state['closed'] or state['resize_job'] is not None:
            return
        if event is not None and event.widget is not body:
            return
        state['resize_job'] = window.after_idle(resize_now)

    def render(index):
        if state['closed']:
            return
        profile = app.game.get()
        title, cards = guide_pages(profile)[index]
        old_children = body.winfo_children()
        page = ctk.CTkFrame(body, fg_color='transparent')
        new_labels = []
        try:
            for heading, text in cards:
                card = ctk.CTkFrame(page, fg_color='#252e3e', corner_radius=12)
                card.pack(fill='x', padx=6, pady=6)
                for content, font, color in ((heading, ('Segoe UI', 15, 'bold'), '#f0f4fb'), (text, ('Segoe UI', 13), '#c3cedf')):
                    label = ctk.CTkLabel(card, text=content, font=font, text_color=color, justify='left', anchor='w', wraplength=max(1, width - 100))
                    label.pack(fill='x', padx=16, pady=(10, 8))
                    new_labels.append(label)
            page.pack(fill='both', expand=True)
        except BaseException:
            page.destroy()
            raise
        for child in old_children:
            child.destroy()
        labels[:] = new_labels
        state['page'] = index
        state['last_wrap'] = None
        nav.set(title)
        progress.configure(text=f'{index + 1} / {len(PAGES)} - Profile: {profile}')
        back.configure(state='normal' if index else 'disabled')
        next_button.configure(text='Done' if index == len(PAGES)-1 else 'Next')
        body._parent_canvas.yview_moveto(0)
        resize()

    def done(event=None):
        if state['closed']:
            return
        cleanup()
        try:
            mark_welcome_seen()
        except OSError:
            logging.getLogger(__name__).exception('Could not save welcome state')
        finally:
            window.destroy()

    def next_page(event=None):
        if state['closed']:
            return
        if state['page'] == len(PAGES)-1:
            done()
        else:
            render(state['page']+1)

    def previous_page(event=None):
        if not state['closed'] and state['page']:
            render(state['page']-1)

    def refresh_profile():
        state['profile_job'] = None
        if not state['closed']:
            render(state['page'])

    def profile_changed(*_):
        if not state['closed'] and state['profile_job'] is None:
            state['profile_job'] = window.after_idle(refresh_profile)

    try:
        window = ctk.CTkToplevel(app.root)
        app._getting_started_window = window
        window.title('Get started - Image Draw Bot')
        from WorkspaceLayout import fit_window
        width, height = fit_window(window, preferred=(840, 760), minimum=(480, 420), margin=(80, 100))
        window.configure(fg_color='#101319')
        window.transient(app.root)
        # Non-modal so instructions can be followed in the main app.
        ctk.CTkLabel(window, text='Get started', font=('Segoe UI', 26, 'bold')).pack(anchor='w', padx=24, pady=(20, 4))
        progress = ctk.CTkLabel(window, text='', text_color='#a6b2c5')
        progress.pack(anchor='w', padx=24, pady=(0, 8))
        titles = [title for title, cards in PAGES]
        nav = ctk.CTkOptionMenu(window, values=titles, command=lambda title: render(titles.index(title)))
        nav.pack(fill='x', padx=24, pady=(0, 12))
        from UiCompatibility import scoped_scrollable_frame
        body = scoped_scrollable_frame(window, fg_color='#1a202b')
        body.pack(fill='both', expand=True, padx=20)
        footer = ctk.CTkFrame(window, fg_color='transparent')
        footer.pack(fill='x', padx=24, pady=16)
        back = ctk.CTkButton(footer, text='Back', width=90, command=previous_page)
        back.pack(side='left')
        ctk.CTkButton(footer, text='Close guide · Esc', width=130, command=done).pack(side='left', padx=8)
        next_button = ctk.CTkButton(footer, text='Next', width=100, command=next_page)
        next_button.pack(side='right')
        ctk.CTkLabel(window, text='Alt+Left / Alt+Right: previous / next topic', text_color='#a6b2c5').pack(pady=(0, 8))
        body.bind('<Configure>', resize, add='+')
        window.bind('<Alt-Left>', previous_page)
        window.bind('<Alt-Right>', next_page)
        window.bind('<Escape>', done)
        window.bind('<Destroy>', cleanup, add='+')
        window.protocol('WM_DELETE_WINDOW', done)
        state['trace'] = app.game.trace_add('write', profile_changed)
        render(0)
        return window
    except BaseException:
        cleanup()
        if window is not None:
            try:
                window.destroy()
            except (tk.TclError, RuntimeError):
                pass
        raise
