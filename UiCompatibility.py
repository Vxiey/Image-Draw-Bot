"""Small runtime compatibility guards for third-party UI widgets.

No telemetry/networking. The patch is deliberately narrow and idempotent.
"""
from __future__ import annotations
import tkinter as tk

_PATCHED = False
_MISSING = object()


def _leave_paint_to_tk():
    pass


def draw_without_idle_flush(canvas, draw, *args, **kwargs):
    """Run the CTk painter without dispatching unrelated pending application callbacks."""
    # CTk 6 explicitly calls update_idletasks on its private decoration canvas.
    # Its drawing operations already enqueue real Tk paints. Let the outer
    # event loop deliver them after the widget has finished its state change.
    previous = vars(canvas).get('update_idletasks', _MISSING)
    canvas.update_idletasks = _leave_paint_to_tk
    try:
        return draw(*args, **kwargs)
    finally:
        if previous is _MISSING:
            del canvas.update_idletasks
        else:
            canvas.update_idletasks = previous


def scoped_window_class(base):
    """Use a local root/window subclass without changing third-party classes."""
    from UiWindowLifetime import scoped_window_class as owned_class
    return owned_class(base)


def scoped_toplevel(parent, **kwargs):
    """Create an application CTk dialog with owned callbacks and shared polls."""
    import customtkinter as ctk
    return scoped_window_class(ctk.CTkToplevel)(parent, **kwargs)


def _scoped_scrollable_class(base):
    class ScopedScrollableFrame(base):
        """Own the global callbacks CTk installs for this particular frame."""

        def __init__(self, *args, **kwargs):
            self._owned_scroll_bindings = []
            self._scroll_destroyed = False
            try:
                super().__init__(*args, **kwargs)
            except BaseException:
                self._release_scroll_bindings()
                try:
                    super().destroy()
                except Exception:
                    pass
                raise

        def bind_all(self, sequence=None, func=None, add=None):
            token = super().bind_all(sequence, func, add)
            if token is not None and func is not None:
                self._owned_scroll_bindings.append((self._root(), sequence, token))
            return token

        def _release_scroll_bindings(self):
            bindings = self._owned_scroll_bindings
            self._owned_scroll_bindings = []
            for root, sequence, token in bindings:
                try:
                    # Tkinter's targeted remover keeps every other bind_all
                    # callback and deletes only this frame's Tcl command.
                    root._unbind(('bind', 'all', sequence), token)
                except (tk.TclError, RuntimeError):
                    pass

        def destroy(self):
            if self._scroll_destroyed:
                return
            self._scroll_destroyed = True
            self._release_scroll_bindings()
            super().destroy()

    return ScopedScrollableFrame


class _ScrollbarPaint:
    """Coalesce the app's scrollbar draws outside CTk's nested idle flush."""

    def __init__(self, frame):
        self.bar = frame._scrollbar
        self.draw = self.bar._draw
        self.job = None
        self.dirty = False
        self.recolor = False
        self.painting = False
        self.bar._draw = self.request
        # Tk's Canvas invokes the viewport command even for unchanged bounds
        # while rearranging children. CTk 6 calls _draw on every set.
        command = 'xscrollcommand' if frame._orientation == 'horizontal' else 'yscrollcommand'
        frame._parent_canvas.configure(**{command: self.viewport})
        tk.Misc.bind(self.bar, '<Destroy>', self.dispose, add='+')

    def viewport(self, first, last):
        if self.bar is not None and self.bar.get() != (float(first), float(last)):
            self.bar.set(first, last)

    def request(self, no_color_updates=False):
        if self.bar is None:
            return
        self.dirty = True
        self.recolor |= not no_color_updates
        if self.job is None and not self.painting:
            self.job = self.bar.after_idle(self._after_layout)

    def _after_layout(self):
        # update_idletasks() inside another CTk scrollbar may call this idle
        # hook. A timer runs in the outer event loop, never in that idle flush.
        self.job = self.bar.after(0, self._paint)

    def _paint(self):
        self.job = None
        recolor = self.recolor
        self.dirty = self.recolor = False
        self.painting = True
        try:
            draw_without_idle_flush(self.bar._canvas, self.draw, no_color_updates=not recolor)
        finally:
            self.painting = False
            if self.dirty:
                self.request(no_color_updates=True)

    def dispose(self, event):
        if event.widget is not self.bar:
            return
        if self.job is not None:
            self.bar.after_cancel(self.job)
        self.job = self.draw = self.bar = None


def scoped_scrollable_frame(parent, **kwargs):
    """Create an app-owned scroll frame and retire its callbacks on destruction."""
    import customtkinter as ctk
    frame = _scoped_scrollable_class(ctk.CTkScrollableFrame)(parent, **kwargs)
    _ScrollbarPaint(frame)
    return frame


def patch_customtkinter_scroll_guard() -> bool:
    """Prevent CTkScrollableFrame from dereferencing non-widget event targets.

    Some Tk/CustomTkinter combinations deliver ``event.widget`` as a Tcl path
    string after a widget has been destroyed/reparented. CustomTkinter 5.x then
    assumes ``.master`` exists and raises inside the global mouse-wheel binding.
    Returning False for non-widget targets is equivalent to 'not scrollable'.
    """
    global _PATCHED
    if _PATCHED:
        return True
    try:
        from customtkinter.windows.widgets.ctk_scrollable_frame import CTkScrollableFrame
    except Exception:
        return False
    original = getattr(CTkScrollableFrame, '_check_if_valid_scroll', None)
    if not callable(original):
        return False
    if getattr(original, '_imagedrawbot_safe_scroll_guard', False):
        _PATCHED = True
        return True

    def guarded(self, widget):
        if widget is None or isinstance(widget, str) or not hasattr(widget, 'master'):
            return False
        try:
            return original(self, widget)
        except (AttributeError, RuntimeError, tk.TclError):
            return False

    guarded._imagedrawbot_safe_scroll_guard = True
    guarded._imagedrawbot_original = original
    CTkScrollableFrame._check_if_valid_scroll = guarded
    _PATCHED = True
    return True
