"""Progressive-disclosure layout for the crowded StudioUI sidebar.

This module changes presentation only. Existing widgets, Tk variables, profile
scopes and controller callbacks remain authoritative; controls are merely packed
behind compact disclosure buttons and restored without recreating them.
"""
from __future__ import annotations

import tkinter as tk
import customtkinter as ctk
from UiKeyboardNavigation import KeyboardButton
from ResponsiveWorkspace import fit_label

from GameProfiles import PROFILES

FIELD = '#202c3d'
FIELD_HOVER = '#2b3a50'
TEXT = '#f4f7fb'
MUTED = '#94a3b8'
LINE = '#2a384b'
PANEL_ALT = '#1b2635'


def _widget_text(widget):
    try:
        return str(widget.cget('text') or '')
    except (tk.TclError, AttributeError, TypeError, ValueError):
        return ''


def _walk(parent):
    for child in tuple(parent.winfo_children()):
        yield child
        yield from _walk(child)


def _find_text(parent, needle):
    needle = str(needle)
    for widget in _walk(parent):
        if needle in _widget_text(widget):
            return widget
    return None


class _WidgetLookup:
    """Read the original widget tree once while installing sidebar groups."""

    def __init__(self, root):
        self.rows=[]
        self.ranges={}
        stack=[(root,False,False)]
        while stack:
            widget,finished,include=stack.pop()
            if finished:
                start,_=self.ranges[id(widget)]
                self.ranges[id(widget)]=(start,len(self.rows))
                continue
            if include:self.rows.append((widget,_widget_text(widget)))
            self.ranges[id(widget)]=(len(self.rows),None)
            stack.append((widget,True,include))
            try:children=tuple(widget.winfo_children())
            except tk.TclError:children=()
            stack.extend((child,False,True) for child in reversed(children))

    def find(self,parent,needle):
        bounds=self.ranges.get(id(parent))
        if bounds is None:return None
        needle=str(needle)
        for index in range(*bounds):
            widget,text=self.rows[index]
            if needle in text:return widget
        return None


def _direct_child(widget, parent):
    current = widget
    while current is not None and getattr(current, 'master', None) is not parent:
        current = getattr(current, 'master', None)
    return current if current is not None and getattr(current, 'master', None) is parent else None


def _direct_containing(parent, needle):
    widget = _find_text(parent, needle)
    return _direct_child(widget, parent) if widget is not None else None


def _unique(items):
    out = []
    seen = set()
    for item in items:
        if item is None or id(item) in seen:
            continue
        seen.add(id(item)); out.append(item)
    return out


def _pack_options(widget):
    try:
        # CTk's pack_info contains physical padding, whereas its pack() expects
        # logical padding and scales it. Reusing pack_info would scale twice.
        previous=(getattr(widget,'_last_geometry_manager_call',None)
                  if isinstance(widget,ctk.CTkBaseClass) else None)
        if (isinstance(previous,dict) and isinstance(previous.get('kwargs'),dict) and
                getattr(previous.get('function'),'__name__','') in ('pack','pack_configure') and
                widget.winfo_manager()=='pack'):
            options=dict(previous['kwargs'])
        else:
            options = dict(widget.pack_info())
    except (tk.TclError, AttributeError):
        return {}
    # Tk returns the containing widget and ordering helpers too; those are stale
    # after progressive-disclosure moves the control below its section header.
    for key in ('in', 'in_', 'before', 'after'):
        options.pop(key, None)
    return options


def pack_in_order(widget, **options):
    """Apply sibling ordering once, without retaining it for CTk DPI replay.

    ``before``/``after`` identify a currently packed sibling. Once Tk has
    positioned the widget, an ordinary pack reconfiguration preserves that
    position. CTk replays its last pack call when scaling changes, potentially
    after that sibling has been hidden by a profile or disclosure group.
    Keep the logical sizing/padding options, but discard these transient
    ordering dependencies only after the initial pack succeeds.
    """
    result = widget.pack(**options)
    if isinstance(widget, ctk.CTkBaseClass):
        previous = getattr(widget, '_last_geometry_manager_call', None)
        if (isinstance(previous, dict) and isinstance(previous.get('kwargs'), dict)
                and getattr(previous.get('function'), '__name__', '') in ('pack', 'pack_configure')):
            previous['kwargs'] = {key: value for key, value in previous['kwargs'].items()
                                  if key not in ('before', 'after')}
    return result


def _slice_children(parent, first, stop):
    children = list(parent.winfo_children())
    if first not in children or stop not in children:
        return []
    a, b = children.index(first), children.index(stop)
    return children[a:b] if a < b else []


class CompactGroup:
    """Hide/show already-created sibling widgets while retaining widget state."""

    def __init__(self, layout, parent, title, hint, items, *, before=None, after=None):
        self.layout = layout
        self.parent = parent
        self.title = str(title)
        self.hint = str(hint)
        self.items = [w for w in _unique(items) if getattr(w, 'master', None) is parent]
        self.saved_pack = {id(w): _pack_options(w) for w in self.items}
        self.original_order=tuple(parent.pack_slaves())
        self.shell=None
        self._rolled_back=False
        self.open = False

        try:
            self.shell = ctk.CTkFrame(parent, fg_color=PANEL_ALT, corner_radius=10,
                                      border_width=1, border_color=LINE)
            self.toggle = KeyboardButton(
                self.shell, text='›  ' + self.title, command=self.toggle_open,
                height=34, anchor='w', corner_radius=8, border_width=0,
                fg_color='transparent', hover_color=FIELD,
                text_color=TEXT, font=('Segoe UI', 12, 'bold'))
            self.toggle.pack(fill='x', padx=6, pady=(6, 0))
            self.caption = ctk.CTkLabel(
                self.shell, text=self.hint, anchor='w', justify='left',
                text_color=MUTED, font=('Segoe UI', 11), wraplength=248)
            self.caption.pack(fill='x', padx=12, pady=(0, 8))
            fit_label(self.caption, 248)

            for widget in self.items:
                if widget.winfo_manager() == 'pack':
                    widget.pack_forget()

            pack = dict(fill='x', pady=5)
            if before is not None and before.winfo_manager() == 'pack':
                pack['before'] = before
            elif after is not None and after.winfo_manager() == 'pack':
                pack['after'] = after
            pack_in_order(self.shell, **pack)
        except BaseException as error:
            problems=self.rollback()
            if problems:error.add_note('Sidebar rollback: '+'; '.join(problems))
            raise

    def rollback(self):
        """Restore original controls/order and destroy only our disclosure shell."""
        if self._rolled_back:return ()
        self._rolled_back=True
        wanted={id(widget) for widget in self.items}
        originally_packed={id(widget) for widget in self.original_order}
        problems=[];following=None
        for widget in reversed(self.original_order):
            try:
                if id(widget) in wanted:
                    options=dict(self.saved_pack[id(widget)])
                    if following is not None:options['before']=following
                    pack_in_order(widget, **options)
                if widget.winfo_manager()=='pack':following=widget
            except Exception as error:problems.append(str(error))
        for widget in self.items:
            if id(widget) not in originally_packed:
                try:widget.pack_forget()
                except Exception as error:problems.append(str(error))
        if self.shell is not None:
            try:self.shell.destroy()
            except Exception as error:problems.append(str(error))
        return tuple(problems)

    def _scope_allowed(self, widget):
        scope = self.layout.scope_by_widget.get(id(widget))
        if not scope:
            return True
        try:
            from ProfileIsolation import scope_visible
            name = self.layout.app.game.get()
            key = PROFILES.get(name, ('generic',))[0]
            return bool(scope_visible(scope, key))
        except (AttributeError, KeyError, tk.TclError):
            return True

    def refresh(self):
        # ProfileIsolation may have restored a child; hide only disallowed items
        # and preserve controls that are already in the requested sibling order.
        desired=[]
        for widget in self.items:
            try:
                allowed=self.open and self._scope_allowed(widget)
                if not allowed:
                    if widget.winfo_manager() == 'pack':widget.pack_forget()
                else:
                    widget.winfo_manager()  # Detect a destroyed Tcl widget before packing.
                    desired.append(widget)
            except tk.TclError:
                continue
        if not desired:return
        try:order=list(self.parent.pack_slaves())
        except tk.TclError:return
        previous = self.shell
        for widget in desired:
            if previous in order:
                index=order.index(previous)+1
                if index<len(order) and order[index] is widget:
                    previous=widget
                    continue
            options = dict(self.saved_pack.get(id(widget), {}))
            options['after'] = previous
            try:
                pack_in_order(widget, **options)
                if widget in order:order.remove(widget)
                if previous in order:order.insert(order.index(previous)+1,widget)
                else:order.append(widget)
                previous = widget
            except tk.TclError:
                # A widget may have been destroyed during shutdown/profile reset.
                continue

    def set_open(self, value):
        changed=self.open!=bool(value)
        self.open = bool(value)
        if changed:
            try:self.toggle.configure(text=('▾  ' if self.open else '›  ') + self.title)
            except tk.TclError:return
        self.refresh()

    def toggle_open(self):
        self.set_open(not self.open)


class CompactLayout:
    def __init__(self, app, scoped_entries=()):
        self.app = app
        self.scope_by_widget = {id(widget): scope for widget, scope in scoped_entries}
        self.groups = []
        self._lookup=None

    def _find(self,parent,needle):
        return self._lookup.find(parent,needle) if self._lookup is not None else _find_text(parent,needle)

    def _direct(self,parent,needle):
        widget=self._find(parent,needle)
        return _direct_child(widget,parent) if widget is not None else None

    def add(self, parent, title, hint, items, *, before=None, after=None):
        items = _unique(items)
        if parent is None or not items:
            return None
        group = CompactGroup(self, parent, title, hint, items, before=before, after=after)
        self.groups.append(group)
        return group

    def _install_profile_group(self):
        selector = getattr(self.app, 'profile_selector', None)
        if selector is None:
            return
        parent = selector.master
        guide = self._direct(parent, 'Profile guide')
        items = [
            self._direct(parent, 'Custom app profile'),
            self._direct(parent, 'Export'),
            self._direct(parent, 'Reset profile to defaults'),
            _direct_child(getattr(self.app, 'paint_check', None), parent),
            _direct_child(getattr(self.app, 'paint_tool_menu', None), parent),
            _direct_child(getattr(self.app, 'paint_tool_label', None), parent),
        ]
        self.add(parent, 'Profile & ink options',
                 'Custom profiles, import/export and manual ink/tool overrides.',
                 items, after=guide)

    def _install_image_group(self):
        button = getattr(self.app, 'drop_in_button', None)
        if button is None:
            return
        parent = button.master
        first = self._direct(parent, 'Clear image')
        info = self._direct(parent, 'No image information yet.')
        if first is None or info is None:
            return
        self.add(parent, 'Image options & automation',
                 'Cache, upscale, browser One-Click, Drop-In and canvas clearing.',
                 _slice_children(parent, first, info), after=info)

    def _install_target_group(self):
        start = getattr(self.app, 'gartic_setup_button', None)
        area = getattr(self.app, 'area_button', None)
        label = getattr(self.app, 'one_click_setup_label', None)
        if start is None or area is None or label is None:
            return
        parent = area.master
        first = _direct_child(start, parent)
        stop = _direct_child(area, parent)
        anchor = _direct_child(label, parent)
        self.add(parent, 'Manual calibration',
                 'Fallback controls for app-specific tools, palettes and calibration.',
                 _slice_children(parent, first, stop), after=anchor)

    def _install_tuning_group(self):
        # Step 4 has no public frame handle. Resolve it from the stable control
        # labels already used by StudioUI regression tests.
        root = self.app.root
        sketch_detail = self._find(root, 'Sketch detail')
        if sketch_detail is None:
            return
        row = getattr(sketch_detail, 'master', None)
        while row is not None and self._direct(row, 'Black contour sketch') is None:
            row = getattr(row, 'master', None)
        parent = row
        if parent is None:
            return
        first = self._direct(parent, 'Sketch detail')
        stop = self._direct(parent, '🎨  Quality')
        anchor = self._direct(parent, 'Black contour sketch')
        if first is None or stop is None:
            return
        self.add(parent, 'Fine tuning',
                 'Sketch detail, timer, quality, brush width and subject focus.',
                 _slice_children(parent, first, stop), after=anchor)

    def _install_safety_group(self):
        start = getattr(self.app, 'start_secondary', None)
        review_button = getattr(self.app, 'correction_review_button', None)
        if start is None or review_button is None:
            return
        parent = start.master
        preview_mode = self._direct(parent, 'Preview mode')
        build_preview = self._direct(parent, 'Build preview')
        if preview_mode is not None and build_preview is not None:
            preview_items = _slice_children(parent, preview_mode, build_preview)
            self.add(parent, 'Preview options',
                     'Refresh/detail controls. Manual preview remains the safe default.',
                     preview_items, before=build_preview)

        review_card = _direct_child(review_button, parent)
        wizard = self._direct(parent, 'Open setup wizard')
        final_help = self._direct(parent, 'Paint: load an image')
        items = [wizard, review_card,
                 _direct_child(getattr(self.app, 'target_lock_secondary', None), parent),
                 _direct_child(getattr(self.app, 'safety_preflight_secondary', None), parent),
                 _direct_child(getattr(self.app, 'dry_run_secondary', None), parent),
                 _direct_child(getattr(self.app, 'start_unlock_secondary', None), parent),
                 _direct_child(start, parent), final_help]
        self.add(parent, 'Review & safety shortcuts',
                 'Correction review and duplicate shortcuts; the fixed footer is primary.',
                 items, after=build_preview)

    def _collapse_existing_heavy_cards(self):
        # StudioUI's existing collapsibles keep their own state; invoke their
        # button instead of directly hiding the body so the next click opens it.
        for marker in ('🎨  Quality', '🛠  Developer tools'):
            button = self._find(self.app.root, '▾  ' + marker)
            if button is None:
                continue
            invoke = getattr(button, 'invoke', None)
            if callable(invoke):
                try:
                    invoke()
                except tk.TclError:
                    pass

    def install(self):
        try:
            self._lookup=_WidgetLookup(self.app.root)
            self._install_profile_group()
            self._install_image_group()
            self._install_target_group()
            self._install_tuning_group()
            self._install_safety_group()
            self._collapse_existing_heavy_cards()
            return self
        except BaseException as error:
            for group in reversed(self.groups):
                problems=group.rollback()
                if problems:error.add_note('Sidebar rollback: '+'; '.join(problems))
            self.groups.clear()
            raise
        finally:
            self._lookup=None

    def refresh(self):
        for group in self.groups:
            group.refresh()


def install_compact_layout(app, scoped_entries=()):
    """Install compact layout once and return the stateful layout object."""
    current = getattr(app, '_compact_ui_layout', None)
    if current is not None:
        return current
    return CompactLayout(app, scoped_entries).install()
