"""Keyboard behavior for the application's own CustomTkinter buttons.

Bindings belong to each button and end with its lifetime. A button is one Tab
stop; Return, keypad Enter and Space use its existing state-checked invoke().
"""
from __future__ import annotations

import tkinter as tk
from weakref import WeakSet

import customtkinter as ctk


class KeyboardButton(ctk.CTkButton):
    _focus_tag = 'imagedrawbot_keyboard_focus'

    def __init__(self, *args, focus_color='#72e2bd', **kwargs):
        self._keyboard_ready = False
        self._keyboard_closed = False
        self._keyboard_pressed = None
        self._keyboard_job = None
        self._keyboard_focus_active = False
        self._keyboard_focus_displayed = False
        self._keyboard_nodes = WeakSet()
        self._keyboard_focus_color = focus_color
        super().__init__(*args, **kwargs)
        self._keyboard_ready = True
        # CTk forwards configure()/bind()/focus_set() to decorative children.
        # Native Frame operations give the logical button one traversal stop.
        tk.Frame.configure(self, takefocus=self._keyboard_focusable)
        for sequence, callback in (
                ('<FocusIn>', self._keyboard_focus_in),
                ('<FocusOut>', self._keyboard_focus_out),
                ('<KeyPress-Return>', self._keyboard_key_press),
                ('<KeyRelease-Return>', self._keyboard_key_release),
                ('<KeyPress-KP_Enter>', self._keyboard_key_press),
                ('<KeyRelease-KP_Enter>', self._keyboard_key_release),
                ('<KeyPress-space>', self._keyboard_key_press),
                ('<KeyRelease-space>', self._keyboard_key_release)):
            tk.Misc.bind(self, sequence, callback, add='+')
        self._keyboard_sync_children()

    def _keyboard_focusable(self, _path=None):
        try:
            return bool(not self._keyboard_closed and self.winfo_exists()
                        and self.winfo_ismapped() and self.cget('state') != 'disabled'
                        and callable(self.cget('command')))
        except (tk.TclError, RuntimeError):
            return False

    def _keyboard_has_focus(self):
        try:
            widget = self.focus_get()
        except (tk.TclError, KeyError):
            return False
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, 'master', None)
        return False

    def _keyboard_scroll_frames(self):
        parent = getattr(self, 'master', None)
        while parent is not None:
            if isinstance(parent, ctk.CTkScrollableFrame):
                yield parent
            parent = getattr(parent, 'master', None)

    def _keyboard_reveal_focus(self):
        """Reveal a Tab target inside owned CTk scroll frames, inside out."""
        frames = tuple(self._keyboard_scroll_frames())
        if not frames:
            return
        try:
            position = [self.winfo_rootx(), self.winfo_rooty()]
            size = (self.winfo_width(), self.winfo_height())
            for frame in frames:
                canvas = frame._parent_canvas
                axis = 0 if frame._orientation == 'horizontal' else 1
                viewport_start = canvas.winfo_rootx() if axis == 0 else canvas.winfo_rooty()
                viewport_size = canvas.winfo_width() if axis == 0 else canvas.winfo_height()
                if viewport_size <= 1:
                    continue
                if (position[axis] >= viewport_start and
                        position[axis] + size[axis] <= viewport_start + viewport_size):
                    continue
                bounds = canvas.bbox(frame._create_window_id)
                if not bounds:
                    continue
                extent = bounds[axis + 2] - bounds[axis]
                if extent <= 0:
                    continue
                coordinate = canvas.canvasx if axis == 0 else canvas.canvasy
                origin = coordinate(0)
                # Centre the target so platform scroll increments have room
                # to round without leaving its label outside the viewport.
                desired = origin + position[axis] - viewport_start + (size[axis] - viewport_size) / 2
                fraction = max(0.0, min(1.0, (desired - bounds[axis]) / extent))
                (canvas.xview_moveto if axis == 0 else canvas.yview_moveto)(fraction)
                # Native child coordinates may update at idle. Project this
                # scroll now when revealing the target in an outer viewport.
                position[axis] -= coordinate(0) - origin
        except (tk.TclError, RuntimeError, AttributeError):
            return  # The activation guard still rejects a clipped/gone target.

    def _keyboard_in_view(self):
        """A mapped canvas child may still be completely scrolled out of view."""
        frames = tuple(self._keyboard_scroll_frames())
        if not frames:
            return True
        try:
            x = self.winfo_rootx() + self.winfo_width() / 2
            y = self.winfo_rooty() + self.winfo_height() / 2
            for frame in frames:
                canvas = frame._parent_canvas
                left, top = canvas.winfo_rootx(), canvas.winfo_rooty()
                if not (left <= x < left + canvas.winfo_width() and
                        top <= y < top + canvas.winfo_height()):
                    return False
            return True
        except (tk.TclError, RuntimeError, AttributeError):
            return False

    def focus_set(self):
        return tk.Misc.focus_set(self)

    focus = focus_set

    def focus_force(self):
        return tk.Misc.focus_force(self)

    def _keyboard_sync_children(self):
        # CTk can replace text/image labels during configure(). Its persistent
        # canvas and each new label remain decorative rather than extra stops.
        for child in (self._canvas, self._text_label, self._image_label):
            if child is not None and child not in self._keyboard_nodes:
                child.configure(takefocus=0)
                child.bind('<ButtonPress-1>', self._keyboard_pointer_focus, add='+')
                self._keyboard_nodes.add(child)

    def _draw(self, *args, **kwargs):
        super()._draw(*args, **kwargs)
        if getattr(self, '_keyboard_ready', False) and not self._keyboard_closed:
            self._keyboard_sync_children()
            self._keyboard_draw_focus()

    def _keyboard_draw_focus(self):
        try:
            if not self._keyboard_focus_active or not self._keyboard_focusable():
                if self._keyboard_focus_displayed:
                    self._canvas.delete(self._focus_tag)
                    self._keyboard_focus_displayed = False
                return
            self._canvas.delete(self._focus_tag)
            self._keyboard_focus_displayed = False
            width, height = self._canvas.winfo_width(), self._canvas.winfo_height()
            inset = max(2, round(2 * self._get_widget_scaling()))
            if width > 2 * inset and height > 2 * inset:
                self._canvas.create_rectangle(inset, inset, width - inset, height - inset,
                    outline=self._keyboard_focus_color, width=inset, tags=(self._focus_tag,))
                self._canvas.tag_raise(self._focus_tag)
                self._keyboard_focus_displayed = True
        except (tk.TclError, RuntimeError):
            pass  # Destruction can occur between a focus event and its repaint.

    def _keyboard_focus_in(self, _event=None):
        self._keyboard_focus_active = True
        self._keyboard_reveal_focus()
        self._keyboard_draw_focus()

    def _keyboard_focus_out(self, _event=None):
        self._keyboard_focus_active = False
        self._keyboard_cancel()
        self._keyboard_draw_focus()

    def _keyboard_pointer_focus(self, _event=None):
        self._keyboard_cancel()
        if self._keyboard_focusable():
            self.focus_set()

    @staticmethod
    def _keyboard_key(event):
        symbol = getattr(event, 'keysym', '')
        if symbol in ('Return', 'KP_Enter'):
            return 'Return'
        return 'space' if symbol == 'space' else None

    def _keyboard_key_press(self, event):
        key = self._keyboard_key(event)
        # Preserve modified shortcuts instead of treating them as activation.
        if key is None or (getattr(event, 'state', 0) or 0) & (4 | 8 | 128 | 0x20000):
            return None
        if not self._keyboard_has_focus() or not self._keyboard_focusable():
            return 'break'
        if self._keyboard_pressed == key:
            # X11 may deliver a release/press pair for autorepeat. Defer the
            # release to idle so that pair cannot repeatedly invoke the action.
            if self._keyboard_job is not None:
                self.after_cancel(self._keyboard_job)
                self._keyboard_job = None
        elif self._keyboard_pressed is None:
            self._keyboard_pressed = key
        return 'break'

    def _keyboard_key_release(self, event):
        key = self._keyboard_key(event)
        if key is None:
            return None
        if key == self._keyboard_pressed and self._keyboard_job is None:
            self._keyboard_job = self.after_idle(self._keyboard_activate)
        return 'break'

    def _keyboard_activate(self):
        self._keyboard_job = None
        pressed = self._keyboard_pressed
        self._keyboard_pressed = None
        if (pressed is not None and self._keyboard_has_focus() and
                self._keyboard_focusable() and self._keyboard_in_view()):
            # invoke() rechecks CTk's live state too; callbacks and Start/Stop
            # permissions stay with the existing controller.
            return self.invoke()
        return None

    def _keyboard_cancel(self):
        self._keyboard_pressed = None
        job, self._keyboard_job = self._keyboard_job, None
        if job is not None:
            try:
                self.after_cancel(job)
            except (tk.TclError, RuntimeError, ValueError):
                pass

    def destroy(self):
        self._keyboard_closed = True
        self._keyboard_cancel()
        super().destroy()
